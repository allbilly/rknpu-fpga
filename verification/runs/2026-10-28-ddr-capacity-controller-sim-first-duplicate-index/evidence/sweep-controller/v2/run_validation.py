#!/usr/bin/env python3
"""Bounded private RTL controller behavior tests; no hardware interface exists."""
from __future__ import annotations
import datetime,hashlib,json,os,pathlib,re,shutil,signal,subprocess,sys,time
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');PKG=pathlib.Path(__file__).resolve().parent
SRC=ROOT/'build/ddr-capacity-bist-source-v1';SWEEP=SRC/'rk_ddr_capacity_sweep.sv';LEAF=SRC/'rk_ddr_capacity_pattern.sv'
BENCH=PKG/'tb_capacity_sweep.sv';ELAB=PKG/'tb_capacity_sweep_full_elab.sv';INVALID=PKG/'tb_capacity_sweep_invalid.sv'
TIMEOUT=300;TOOLS={n:shutil.which(n) for n in ('iverilog','vvp','verilator','make','python3')}
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):
 h=hashlib.sha256()
 with pathlib.Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def require(ok,msg):
 if not ok:raise RuntimeError(msg)
def tool_version(path,args):
 if not path:return {'path':None,'available':False}
 r=subprocess.run([path,*args],cwd=PKG,text=True,capture_output=True,timeout=10)
 return {'path':path,'returncode':r.returncode,'stdout':r.stdout.strip(),'stderr':r.stderr.strip()}
def host_sample():
 mem={}
 for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
  if line.startswith(('MemAvailable:','SwapFree:')):
   f=line.split();mem[f[0].rstrip(':')+'_kib']=int(f[1])
 psi={}
 for domain in ('memory','cpu'):
  rows={}
  for line in pathlib.Path(f'/proc/pressure/{domain}').read_text().splitlines():
   p=line.split();rows[p[0]]={k:float(v) for k,v in (x.split('=') for x in p[1:] if '=' in x)}
  psi[domain]=rows
 return {'utc':utc(),**mem,'memory_psi_full_avg10':psi['memory'].get('full',{}).get('avg10'),
  'cpu_psi_some_avg10':psi['cpu'].get('some',{}).get('avg10'),'cgroup':pathlib.Path('/proc/self/cgroup').read_text().strip()}
def run_cmd(name,argv,timeout=TIMEOUT):
 start=utc();begin=time.monotonic();out=PKG/(name+'.stdout.log');err=PKG/(name+'.stderr.log');timed_out=False;cleanup=None
 with out.open('wb') as stdout,err.open('wb') as stderr:
  child=subprocess.Popen(argv,cwd=PKG,stdout=stdout,stderr=stderr,start_new_session=True)
  try:rc=child.wait(timeout=timeout)
  except subprocess.TimeoutExpired:
   timed_out=True;os.killpg(child.pid,signal.SIGTERM)
   try:rc=child.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);rc=child.wait()
   cleanup={'pgid':child.pid,'signals':'SIGTERM_then_SIGKILL_if_needed','returncode':rc}
 return {'name':name,'argv':argv,'cwd':str(PKG),'started_utc':start,'finished_utc':utc(),
  'wall_seconds':round(time.monotonic()-begin,6),'timeout_seconds':timeout,'timed_out':timed_out,'returncode':rc,
  'stdout_path':str(out),'stdout_sha256':sha(out),'stderr_path':str(err),'stderr_sha256':sha(err),'cleanup':cleanup}
def require_marker(command,marker):
 p=pathlib.Path(command['stdout_path']);require(command['returncode']==0 and marker in p.read_text(),command['name']+' required marker missing')

def main():
 report_path=PKG/'report.json';require(not report_path.exists(),'fresh output directory required')
 paths=[SWEEP,LEAF,BENCH,ELAB,INVALID]
 before={str(p):sha(p) for p in paths}
 versions={'iverilog':tool_version(TOOLS['iverilog'],['-V']),'vvp':tool_version(TOOLS['vvp'],['-V']),
  'verilator':tool_version(TOOLS['verilator'],['--version'])}
 host=host_sample();require(host['MemAvailable_kib']>=8*1024*1024,'host admission requires >=8GiB MemAvailable')
 require((host['memory_psi_full_avg10'] or 0)<1.0 and (host['cpu_psi_some_avg10'] or 0)<5.0,'host pressure admission failed')
 commands=[];expected_negative=[];status='FAIL';failure=None
 try:
  require(all(TOOLS[k] for k in ('iverilog','vvp','verilator')),'Icarus, VVP, or Verilator unavailable')
  iv=TOOLS['iverilog'];vvp=TOOLS['vvp'];vl=TOOLS['verilator']
  ivobj=PKG/'sweep_behavior.vvp'
  c=run_cmd('icarus_behavior_compile',[iv,'-g2012','-Wall','-s','tb_capacity_sweep','-o',str(ivobj),str(LEAF),str(SWEEP),str(BENCH)]);commands.append(c);require(c['returncode']==0,'Icarus behavior compile failed')
  c=run_cmd('icarus_behavior_sim',[vvp,str(ivobj)]);commands.append(c);require_marker(c,'PASS_SWEEP_CONTROLLER behavioral_cases=PASS')
  # Default full 2 GiB parameters are checked without starting the 33M-line loop.
  ivfull=PKG/'sweep_full_elab.vvp'
  c=run_cmd('icarus_full_window_elab_compile',[iv,'-g2012','-Wall','-s','tb_capacity_sweep_full_elab','-o',str(ivfull),str(LEAF),str(SWEEP),str(ELAB)]);commands.append(c);require(c['returncode']==0,'Icarus full-window elaboration compile failed')
  c=run_cmd('icarus_full_window_elab_sim',[vvp,str(ivfull)]);commands.append(c);require_marker(c,'PASS_SWEEP_FULL_WINDOW_ELAB_ONLY last=7fffffc0 no_span_iteration=1')
  # Invalid parameters must fatal with the exact constructor guard, not silently elaborate.
  invalid_cases=[('unaligned_base',{'TEST_BASE':1,'TEST_SPAN':256,'TEST_TIMEOUT':20}),
   ('short_span',{'TEST_BASE':0,'TEST_SPAN':32,'TEST_TIMEOUT':20}),
   ('unaligned_span',{'TEST_BASE':0,'TEST_SPAN':65,'TEST_TIMEOUT':20}),
   ('beyond_31bit_window',{'TEST_BASE':0x7fffffc0,'TEST_SPAN':128,'TEST_TIMEOUT':20}),
   ('zero_timeout',{'TEST_BASE':0,'TEST_SPAN':256,'TEST_TIMEOUT':0}),
   ('empty_span',{'TEST_BASE':0,'TEST_SPAN':0,'TEST_TIMEOUT':20})]
  for label,params in invalid_cases:
   obj=PKG/(label+'.vvp')
   argv=[iv,'-g2012','-Wall','-s','tb_capacity_sweep_invalid',
    f'-Ptb_capacity_sweep_invalid.TEST_BASE={params["TEST_BASE"]}',
    f'-Ptb_capacity_sweep_invalid.TEST_SPAN={params["TEST_SPAN"]}',
    f'-Ptb_capacity_sweep_invalid.TEST_TIMEOUT={params["TEST_TIMEOUT"]}',
    '-o',str(obj),str(LEAF),str(SWEEP),str(INVALID)]
   comp=run_cmd(label+'_compile',argv);commands.append(comp);require(comp['returncode']==0,label+' invalid-parameter compile failed')
   sim=run_cmd(label+'_reject',[vvp,str(obj)]);commands.append(sim)
   text=(pathlib.Path(sim['stdout_path']).read_text()+pathlib.Path(sim['stderr_path']).read_text())
   require(sim['returncode']!=0 and 'Capacity sweep needs aligned nonempty31-bit span and positive timeout' in text and
       'FAIL_SWEEP_INVALID_PARAMETER_ACCEPTED' not in text,label+' invalid parameter was not rejected by DUT guard')
   expected_negative.append({'case':label,'parameters':params,'compile_rc':comp['returncode'],'simulation_rc':sim['returncode'],
       'expected_fatal_observed':True,'simulation_stdout_sha256':sim['stdout_sha256'],'simulation_stderr_sha256':sim['stderr_sha256']})
  vlt=PKG/'verilator_obj';vlt.mkdir()
  c=run_cmd('verilator_behavior_compile',[vl,'--binary','--timing','--assert','--Wall','--top-module','tb_capacity_sweep',
      '-j','2','--Mdir',str(vlt),str(LEAF),str(SWEEP),str(BENCH)]);commands.append(c);require(c['returncode']==0,'strict Verilator behavior compile failed')
  c=run_cmd('verilator_behavior_sim',[str(vlt/'Vtb_capacity_sweep')]);commands.append(c);require_marker(c,'PASS_SWEEP_CONTROLLER behavioral_cases=PASS')
  vltfull=PKG/'verilator_full_elab_obj';vltfull.mkdir()
  c=run_cmd('verilator_full_window_elab_compile',[vl,'--binary','--timing','--assert','--Wall','--top-module','tb_capacity_sweep_full_elab',
      '-j','2','--Mdir',str(vltfull),str(LEAF),str(SWEEP),str(ELAB)]);commands.append(c);require(c['returncode']==0,'strict Verilator full-window elaboration compile failed')
  c=run_cmd('verilator_full_window_elab_sim',[str(vltfull/'Vtb_capacity_sweep_full_elab')]);commands.append(c);require_marker(c,'PASS_SWEEP_FULL_WINDOW_ELAB_ONLY last=7fffffc0 no_span_iteration=1')
  status='PASS_CONTROLLER_ADAPTER_CONTRACT_SIMULATION_ONLY'
 except BaseException as e:failure=repr(e)
 after={str(p):sha(p) for p in paths};unchanged=before==after
 if not unchanged:status='FAIL'
 prior_v1=PKG.parent/'ddr-capacity-sweep-validation-v1/report.json'
 report={'schema':'ddr-capacity-sweep-controller-validation-v1','status':status,'failure':failure,
  'started_utc':commands[0]['started_utc'] if commands else utc(),'finished_utc':utc(),
  'host_admission':host,'host_final':host_sample(),'cgroup':host['cgroup'],
  'cgroup_limits_requested':{'MemoryMax':'4GiB','MemorySwapMax':0,'CPUQuota':'200%','TasksMax':256},
  'scope_note':'Test-only adapter/fence contract. No MIG integration or physical controller evidence.',
  'source_hashes_before':before,'source_hashes_after':after,'sources_unchanged':unchanged,
  'tool_versions':versions,'commands':commands,'negative_parameter_cases':expected_negative,
  'prior_failures':[{'path':str(prior_v1),'sha256':sha(prior_v1),'status':json.loads(prior_v1.read_text())['status']}],
  'timeouts_seconds':{'each_native_compile_or_sim_case':TIMEOUT},
  'seeds':['0x00000000','0x3588c350','0xffffffff'],'span_bytes':256,'lines_per_pass':4,
  'full_window_default_proof':'Separate default-parameter elaboration only; no 33,554,432-line iteration.',
  'hardware_executed':False,'full_capacity_qualified':False,'physical_ddr_qualified':False,'model_run_executed':False}
 report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'status':status,'failure':failure,'report':str(report_path),
  'commands':[(c['name'],c['returncode']) for c in commands],'sources_unchanged':unchanged},indent=2))
 return 0 if status.startswith('PASS') else 1
if __name__=='__main__':raise SystemExit(main())
