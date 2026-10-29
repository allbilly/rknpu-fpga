#!/usr/bin/env python3
"""Bounded simulation tests for the private DDR sweep AXI adapter and joined wrapper."""
from __future__ import annotations
import datetime,hashlib,json,os,pathlib,re,shutil,signal,subprocess,sys,time
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');PKG=pathlib.Path(__file__).resolve().parent
HDL_SOURCES=[ROOT/'build/ddr-capacity-bist-source-v1/rk_ddr_capacity_pattern.sv',
 ROOT/'build/ddr-capacity-bist-source-v1/rk_ddr_capacity_sweep.sv',
 ROOT/'build/ddr-capacity-bist-source-v1/rk_ddr_capacity_axi.sv',
 ROOT/'build/ddr-capacity-bist-source-v1/rk_ddr_capacity_bist.sv',
 ROOT/'rtl/ddr/rk_mig_write_fence.sv',ROOT/'rtl/ddr/rk_mig_ecc_monitor.sv',
 PKG/'tb_capacity_axi.sv',PKG/'tb_capacity_bist_joined.sv']
PUBLIC_ORACLE=ROOT/'tools/ddr/capacity_pattern.py'
PUBLIC_GOLDEN_SOURCES=[PKG/'make_nonzero_pattern_goldens.py',PKG/'check_nonzero_pattern_goldens.py',
                       PKG/'nonzero-public-goldens.txt',PKG/'nonzero-golden-manifest.json',PUBLIC_ORACLE]
SOURCES=HDL_SOURCES+PUBLIC_GOLDEN_SOURCES+[PKG/'run_validation.py']
TOOLS={n:shutil.which(n) for n in ('iverilog','vvp','verilator','python3')};TIMEOUT=300
CONFIGS=[('small256_base0',0,256,True),('span512_base0',0,512,False),('small256_base1000',0x1000,256,False),('last512_base7ffffe00',0x7ffffe00,512,False)]
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def require(ok,msg):
 if not ok:raise RuntimeError(msg)
def version(path,args):
 if not path:return {'available':False,'path':None}
 p=subprocess.run([path,*args],cwd=PKG,capture_output=True,text=True,timeout=10)
 return {'path':path,'returncode':p.returncode,'stdout':p.stdout.strip(),'stderr':p.stderr.strip()}
def host_sample():
 mem={}
 for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
  if line.startswith(('MemAvailable:','SwapFree:')):
   x=line.split();mem[x[0][:-1]+'_kib']=int(x[1])
 psi={}
 for d in ('memory','cpu'):
  rows={}
  for line in pathlib.Path(f'/proc/pressure/{d}').read_text().splitlines():
   f=line.split();rows[f[0]]={k:float(v) for k,v in (i.split('=') for i in f[1:] if '=' in i)}
  psi[d]=rows
 return {'utc':utc(),**mem,'memory_psi_full_avg10':psi['memory']['full']['avg10'],
  'cpu_psi_some_avg10':psi['cpu']['some']['avg10'],'cgroup':pathlib.Path('/proc/self/cgroup').read_text().strip()}
def run_cmd(name,argv):
 started=utc();t0=time.monotonic();out=PKG/(name+'.stdout.log');err=PKG/(name+'.stderr.log');timed_out=False;cleanup=None
 with out.open('wb') as so,err.open('wb') as se:
  p=subprocess.Popen(argv,cwd=PKG,stdout=so,stderr=se,start_new_session=True)
  try:rc=p.wait(timeout=TIMEOUT)
  except subprocess.TimeoutExpired:
   timed_out=True;os.killpg(p.pid,signal.SIGTERM)
   try:rc=p.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);rc=p.wait()
   cleanup={'pgid':p.pid,'sigterm_then_sigkill_if_needed':True,'returncode':rc}
 return {'name':name,'argv':argv,'cwd':str(PKG),'started_utc':started,'finished_utc':utc(),'wall_seconds':round(time.monotonic()-t0,6),
  'timeout_seconds':TIMEOUT,'timed_out':timed_out,'returncode':rc,'stdout_path':str(out),'stdout_sha256':sha(out),
  'stderr_path':str(err),'stderr_sha256':sha(err),'cleanup':cleanup}
def check_success(command,marker):
 data=pathlib.Path(command['stdout_path']).read_text();require(command['returncode']==0 and marker in data,command['name']+' failed/missing marker')
def main():
 report_path=PKG/'report.json';require(not report_path.exists(),'fresh validation output required')
 before={str(p):sha(p) for p in SOURCES};host=host_sample()
 require(host['MemAvailable_kib']>=8*1024*1024,'prelaunch requires >=8 GiB MemAvailable')
 require(host['memory_psi_full_avg10']<1.0 and host['cpu_psi_some_avg10']<5.0,'prelaunch memory/cpu pressure gate failed')
 versions={'iverilog':version(TOOLS['iverilog'],['-V']),'vvp':version(TOOLS['vvp'],['-V']),'verilator':version(TOOLS['verilator'],['--version'])}
 commands=[];status='FAIL';failure=None
 try:
  require(all(TOOLS[x] for x in ('iverilog','vvp','verilator')),'required simulator unavailable')
  gold_report=PKG/'public-golden-check.json'
  c=run_cmd('public_software_golden_check',[TOOLS['python3'],str(PKG/'check_nonzero_pattern_goldens.py'),'--out',str(gold_report)])
  commands.append(c);require(c['returncode']==0 and 'PASS_PUBLIC_SOFTWARE_NONZERO_PATTERN_GOLDENS' in pathlib.Path(c['stdout_path']).read_text(),
      'public software nonzero pattern golden check failed')
  gold_arg=f'+GOLDENS={PKG/"nonzero-public-goldens.txt"}'
  for label,base,span,faults in CONFIGS:
   ivout=PKG/(label+'-icarus.vvp')
   argv=[TOOLS['iverilog'],'-g2012','-Wall','-s','tb_capacity_axi',f'-Ptb_capacity_axi.BASE_ADDR={base}',
    f'-Ptb_capacity_axi.SPAN_BYTES={span}','-Ptb_capacity_axi.TIMEOUT_CYCLES=32','-o',str(ivout),*[str(x) for x in HDL_SOURCES]]
   c=run_cmd(label+'_icarus_compile',argv);commands.append(c);require(c['returncode']==0,label+' Icarus compile failed')
   argv=[TOOLS['vvp'],str(ivout),gold_arg]+(['+FAULTS'] if faults else [])
   c=run_cmd(label+'_icarus_sim',argv);commands.append(c);check_success(c,f'PASS_AXI_INTEGRATED span={span} base={base:08x}')
   check_success(c,'PASS_PUBLIC_PATTERN_GOLDENS rows=18 base=00001000 software_oracle=tools/ddr/capacity_pattern.py')
   if faults:check_success(c,'PASS_AXI_FAULT_DIRECTED')
   vltdir=PKG/(label+'-verilator-obj');vltdir.mkdir()
   argv=[TOOLS['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_capacity_axi','-j','2','--Mdir',str(vltdir),
    f"-GBASE_ADDR=31'd{base}",f"-GSPAN_BYTES=32'd{span}",'-GTIMEOUT_CYCLES=32',*[str(x) for x in HDL_SOURCES]]
   c=run_cmd(label+'_verilator_compile',argv);commands.append(c);require(c['returncode']==0,label+' strict Verilator compile failed')
   argv=[str(vltdir/'Vtb_capacity_axi'),gold_arg]+(['+FAULTS'] if faults else [])
   c=run_cmd(label+'_verilator_sim',argv);commands.append(c);check_success(c,f'PASS_AXI_INTEGRATED span={span} base={base:08x}')
   check_success(c,'PASS_PUBLIC_PATTERN_GOLDENS rows=18 base=00001000 software_oracle=tools/ddr/capacity_pattern.py')
   if faults:
    check_success(c,'PASS_AXI_FAULT_DIRECTED');check_success(c,'PASS_AXI_UNKNOWN_FIELDS=NOT_APPLICABLE_TWO_STATE')
  # Validate the root-authored joined composition wrapper with the actual fence and ECC monitor.
  ivobj=PKG/'joined-icarus.vvp'
  argv=[TOOLS['iverilog'],'-g2012','-Wall','-s','tb_capacity_bist_joined','-Ptb_capacity_bist_joined.BASE_ADDR=0',
   '-Ptb_capacity_bist_joined.SPAN_BYTES=256','-Ptb_capacity_bist_joined.TIMEOUT_CYCLES=32','-o',str(ivobj),*[str(x) for x in HDL_SOURCES]]
  c=run_cmd('joined_icarus_compile',argv);commands.append(c);require(c['returncode']==0,'joined Icarus compile failed')
  c=run_cmd('joined_icarus_sim',[TOOLS['vvp'],str(ivobj),gold_arg]);commands.append(c);check_success(c,'PASS_JOINED_BIST span=256 base=00000000')
  check_success(c,'PASS_PUBLIC_PATTERN_GOLDENS rows=18 base=00001000 software_oracle=tools/ddr/capacity_pattern.py')
  vlt=PKG/'joined-verilator-obj';vlt.mkdir()
  argv=[TOOLS['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_capacity_bist_joined','-j','2','--Mdir',str(vlt),
   "-GBASE_ADDR=31'd0","-GSPAN_BYTES=32'd256",'-GTIMEOUT_CYCLES=32',*[str(x) for x in HDL_SOURCES]]
  c=run_cmd('joined_verilator_compile',argv);commands.append(c);require(c['returncode']==0,'joined strict Verilator compile failed')
  c=run_cmd('joined_verilator_sim',[str(vlt/'Vtb_capacity_bist_joined'),gold_arg]);commands.append(c);check_success(c,'PASS_JOINED_BIST span=256 base=00000000')
  check_success(c,'PASS_PUBLIC_PATTERN_GOLDENS rows=18 base=00001000 software_oracle=tools/ddr/capacity_pattern.py')
  status='PASS_AXI_ADAPTER_AND_JOINED_BIST_SIMULATION_ONLY'
 except BaseException as error:failure=repr(error)
 after={str(p):sha(p) for p in SOURCES};unchanged=before==after
 if not unchanged:status='FAIL'
 prior=[]
 for v in (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15):
  p=PKG.parent/f'ddr-capacity-axi-validation-v{v}/attempt.json'
  if not p.exists():p=PKG.parent/f'ddr-capacity-axi-validation-v{v}/compile-attempt.json'
  if not p.exists():p=PKG.parent/f'ddr-capacity-axi-validation-v{v}/report.json'
  if not p.exists():p=PKG.parent/f'ddr-capacity-axi-validation-v{v}/icarus-faults.log'
  if p.exists():prior.append({'path':str(p),'sha256':sha(p),'status':'PRESERVED_PRIOR_FAILURE'})
 report={'schema':'ddr-capacity-axi-adapter-validation-v1','status':status,'failure':failure,
  'started_utc':commands[0]['started_utc'] if commands else utc(),'finished_utc':utc(),
  'host_admission':host,'host_final':host_sample(),'cgroup':host['cgroup'],
  'cgroup_limits_requested':{'MemoryMax':'4GiB','MemorySwapMax':0,'CPUQuota':'200%','TasksMax':256},
  'source_hashes_before':before,'source_hashes_after':after,'sources_unchanged':unchanged,
  'public_pattern_reference_check_path':str(PKG/'public-golden-check.json'),
  'public_pattern_reference_check_sha256':sha(PKG/'public-golden-check.json') if (PKG/'public-golden-check.json').is_file() else None,
  'tool_versions':versions,'commands':commands,'prior_failed_attempts':prior,
  'span_configs':[{'base':f'0x{base:08x}','span_bytes':span,'lines':span//64,'fault_matrix':faults} for _,base,span,faults in CONFIGS],
  'timeout_seconds_per_command':TIMEOUT,'unknown_fields_scope':{'icarus_four_state':'expected in FAULTS run','verilator':'NOT_APPLICABLE_TWO_STATE'},
  'hardware_executed':False,'vivado_executed':False,'shared_lease_used':False,'physical_capacity_qualified':False,
  'real_mig_integration_qualified':False,'model_run_executed':False}
 report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'status':status,'failure':failure,'report':str(report_path),'source_unchanged':unchanged,
  'commands':[(x['name'],x['returncode']) for x in commands]},indent=2))
 return 0 if status.startswith('PASS') else 1
if __name__=='__main__':raise SystemExit(main())
