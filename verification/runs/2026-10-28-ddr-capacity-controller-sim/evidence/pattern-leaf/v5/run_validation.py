#!/usr/bin/env python3
"""Bounded offline validation of the private synthesizable DDR pattern leaf."""
from __future__ import annotations
import datetime,hashlib,json,os,pathlib,re,shutil,signal,subprocess,sys,time

ROOT=pathlib.Path('/home/fedora/rknpu-fpga')
PKG=pathlib.Path(__file__).resolve().parent
RTL=ROOT/'build/ddr-capacity-bist-source-v1/rk_ddr_capacity_pattern.sv'
TB=PKG/'tb_capacity_pattern.sv';VECTORS=PKG/'vectors.txt';VMAN=PKG/'vectors-manifest.json'
GEN=PKG/'make_vectors.py';TOP='rk_ddr_capacity_pattern';BENCH='tb_capacity_pattern'
TIMEOUT=300
TOOLS={n:shutil.which(n) for n in ('iverilog','vvp','verilator','yosys','make','python3')}

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1<<20),b''):h.update(block)
 return h.hexdigest()
def run_cmd(name,argv,timeout=TIMEOUT):
 started=utc();begin=time.monotonic();out=PKG/(name+'.stdout.log');err=PKG/(name+'.stderr.log')
 code=None;timed_out=False;cleanup=None
 with out.open('wb') as stdout,err.open('wb') as stderr:
  child=subprocess.Popen(argv,cwd=PKG,stdout=stdout,stderr=stderr,start_new_session=True)
  try:code=child.wait(timeout=timeout)
  except subprocess.TimeoutExpired:
   timed_out=True;os.killpg(child.pid,signal.SIGTERM)
   try:code=child.wait(timeout=5)
   except subprocess.TimeoutExpired:
    os.killpg(child.pid,signal.SIGKILL);code=child.wait()
   cleanup={'pgid':child.pid,'signal':'SIGTERM_then_SIGKILL_if_needed','leader_returncode':code}
 return {'name':name,'argv':argv,'cwd':str(PKG),'started_utc':started,'finished_utc':utc(),
  'wall_seconds':round(time.monotonic()-begin,6),'timeout_seconds':timeout,'timed_out':timed_out,'returncode':code,
  'stdout_path':str(out),'stdout_sha256':sha(out),'stderr_path':str(err),'stderr_sha256':sha(err),'cleanup':cleanup}
def tool_version(path,args):
 if not path:return {'path':None,'available':False}
 r=subprocess.run([path,*args],cwd=PKG,text=True,capture_output=True,timeout=10)
 return {'path':path,'returncode':r.returncode,'stdout':r.stdout.strip(),'stderr':r.stderr.strip()}
def pressure():
 mem={}
 for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
  if line.startswith(('MemAvailable:','SwapFree:')):
   f=line.split();mem[f[0].rstrip(':')+'_kib']=int(f[1])
 psi={}
 for name in ('memory','cpu'):
  fields={}
  for line in pathlib.Path(f'/proc/pressure/{name}').read_text().splitlines():
   parts=line.split();fields[parts[0]]={k:float(v) for k,v in (item.split('=') for item in parts[1:] if '=' in item)}
  psi[name]=fields
 return {'utc':utc(),**mem,'memory_psi_full_avg10':psi['memory'].get('full',{}).get('avg10'),
         'cpu_psi_some_avg10':psi['cpu'].get('some',{}).get('avg10'),
         'cgroup':pathlib.Path('/proc/self/cgroup').read_text().strip()}
def require(ok,msg):
 if not ok:raise RuntimeError(msg)
def bitvals(bits,value):return [(value>>i)&1 for i in range(len(bits))]
def parse_init(raw):
 if isinstance(raw,int):return raw
 if not isinstance(raw,str):raise ValueError(f'unsupported LUT INIT parameter {raw!r}')
 return int(raw,2) if set(raw)<=set('01') else int(raw,0)
def eval_mapped(module,address,seed,trial):
 values={}
 ports=module['ports']
 for name,value in [('address',address),('seed',seed),('trial',trial)]:
  bits=ports[name]['bits']
  for bit,val in zip(bits,bitvals(bits,value)):
   if isinstance(bit,int):values[bit]=val
 changed=True
 for _ in range(len(module.get('cells',{}))+2):
  if not changed:break
  changed=False
  for cell in module.get('cells',{}).values():
   typ=cell['type'];conn=cell.get('connections',{});outs=[];ins=[]
   if typ.startswith('LUT') and typ[3:].isdigit():
    n=int(typ[3:]);inputs=[conn[f'I{i}'][0] for i in range(n)]
    if not all(isinstance(x,int) and x in values for x in inputs):continue
    index=sum(values[b]<<i for i,b in enumerate(inputs));init=parse_init(cell['parameters']['INIT']);result=(init>>index)&1
    outs=conn['O'];outvals=[result]
   elif typ in ('INV','$_NOT_'):
    pin='I' if 'I' in conn else 'A';b=conn[pin][0]
    if not isinstance(b,int) or b not in values:continue
    outs=conn['O'];outvals=[1-values[b]]
   elif typ in ('BUF','IBUF','OBUF','$_BUF_'):
    pin='I' if 'I' in conn else 'A';b=conn[pin][0]
    if not isinstance(b,int) or b not in values:continue
    outs=conn['O'];outvals=[values[b]]
   elif typ in ('GND','VCC'):
    outs=conn.get('G',conn.get('P',conn.get('Y',[])));outvals=[0 if typ=='GND' else 1]
   else:
    # Unknown blackboxes or unsupported mapped primitives are rejected below.
    continue
   for out,val in zip(outs,outvals):
    if isinstance(out,int) and values.get(out)!=val:values[out]=val;changed=True
 def outbit(name):
  bit=ports[name]['bits'][0]
  if isinstance(bit,int) and bit in values:return values[bit]
  if bit in ('0','1'):return int(bit)
  raise RuntimeError(f'mapped output {name} unresolved: {bit!r}')
 valid=outbit('valid')
 data=[]
 for bit in ports['data']['bits']:
  if isinstance(bit,int) and bit in values:data.append(values[bit])
  elif bit in ('0','1'):data.append(int(bit))
  else:raise RuntimeError(f'mapped data output unresolved: {bit!r}')
 return valid,data

def mapped_proof(json_path):
 design=json.loads(pathlib.Path(json_path).read_text());mods=design['modules'];require(TOP in mods,'mapped top missing')
 m=mods[TOP];ports=m['ports'];require(len(ports['address']['bits'])==31 and len(ports['seed']['bits'])==32 and
     len(ports['trial']['bits'])==1 and len(ports['valid']['bits'])==1 and len(ports['data']['bits'])==512,
     'mapped leaf port shape changed')
 cells=m.get('cells',{});types={c['type'] for c in cells.values()}
 require(not any(re.search(r'(DSP|RAMB|URAM|FIFO)',t,re.I) for t in types),'mapped leaf unexpectedly uses DSP/BRAM/URAM/FIFO')
 allowed=re.compile(r'^(LUT[1-6]|INV|BUF|IBUF|OBUF|GND|VCC)$')
 unsupported=sorted(t for t in types if not allowed.match(t))
 require(not unsupported,'unsupported mapped primitive/blackbox: '+repr(unsupported))
 def get_valid(a):return eval_mapped(m,a,0x3588c350,0)[0]
 checks={f'0x{a:08x}':get_valid(a) for a in (0,64,1,63,0x7fffffc0,0x7fffffff)}
 require(checks=={'0x00000000':1,'0x00000040':1,'0x00000001':0,'0x0000003f':0,
                 '0x7fffffc0':1,'0x7fffffff':0},'mapped valid truth table mismatch: '+repr(checks))
 base_valid,base_data=eval_mapped(m,0,0,0)
 dynamic=[False]*512
 for bit in range(32):
  _,changed=eval_mapped(m,0,1<<bit,0)
  for i,(a,b) in enumerate(zip(base_data,changed)):
   if a!=b:dynamic[i]=True
 require(all(dynamic),'mapped data outputs include constant bits: '+repr([i for i,x in enumerate(dynamic) if not x][:16]))
 return {'top':TOP,'ports':{n:{'direction':p['direction'],'width':len(p['bits'])} for n,p in ports.items()},
  'cell_count':len(cells),'cell_types':{t:sum(1 for c in cells.values() if c['type']==t) for t in sorted(types)},
  'unsupported_primitives':unsupported,'contains_DSP_or_memory':False,'all_512_data_bits_dynamic_by_seed_toggle':all(dynamic),
  'mapped_valid_truth_table':checks,'valid_nonconstant':len(set(checks.values()))==2,
  'valid_depends_on_address_alignment':True,'physical_capacity_qualified':False}

def main():
 report_path=PKG/'report.json';require(not report_path.exists(),'fresh validation output required')
 source_paths=[RTL,TB,GEN,VECTORS,VMAN]
 hashes_before={str(p):sha(p) for p in source_paths}
 vman=json.loads(VMAN.read_text());require(vman['rows']==4162 and sha(VECTORS)==vman['vectors_sha256'],'vector fixture/manifest mismatch')
 require(vman['rtl_source_sha256']==hashes_before[str(RTL)],'RTL differs from vector fixture source binding')
 versions={'iverilog':tool_version(TOOLS['iverilog'],['-V']),'vvp':tool_version(TOOLS['vvp'],['-V']),
  'verilator':tool_version(TOOLS['verilator'],['--version']),'yosys':tool_version(TOOLS['yosys'],['-V'])}
 host=pressure();require(host['MemAvailable_kib']>=8*1024*1024,'host admission requires at least 8 GiB MemAvailable')
 require((host['memory_psi_full_avg10'] or 0)<1.0 and (host['cpu_psi_some_avg10'] or 0)<5.0,
         'host memory/cpu pressure admission gate failed')
 cgroup=pathlib.Path('/proc/self/cgroup').read_text().strip()
 commands=[];status='FAIL';proof=None
 try:
  iverilog=TOOLS['iverilog'];vvp=TOOLS['vvp'];verilator=TOOLS['verilator'];yosys=TOOLS['yosys']
  require(all((iverilog,vvp,verilator,yosys)),'required Icarus/Verilator/Yosys tool unavailable')
  ivobj=PKG/'capacity_iverilog.vvp'
  c=run_cmd('iverilog_compile',[iverilog,'-g2012','-Wall','-s',BENCH,'-o',str(ivobj),str(RTL),str(TB)]);commands.append(c);require(c['returncode']==0,'Icarus compile failed')
  c=run_cmd('iverilog_sim',[vvp,str(ivobj),f'+VECTORS={VECTORS}']);commands.append(c);require(c['returncode']==0,'Icarus simulation failed')
  vlt_mdir=PKG/'verilator_obj';vlt_mdir.mkdir()
  c=run_cmd('verilator_compile',[verilator,'--binary','--timing','--assert','--Wall','--top-module',BENCH,
    '-j','2','--Mdir',str(vlt_mdir),str(RTL),str(TB)]);commands.append(c);require(c['returncode']==0,'strict Verilator compile failed')
  sim=vlt_mdir/('V'+BENCH)
  c=run_cmd('verilator_sim',[str(sim),f'+VECTORS={VECTORS}']);commands.append(c);require(c['returncode']==0,'Verilator simulation failed')
  mapped_json=PKG/'mapped.json';mapped_v=PKG/'mapped.v'
  script=(f'read_verilog -sv -D SYNTHESIS {RTL}; hierarchy -check -top {TOP}; '
          f'synth_xilinx -family xc7 -top {TOP}; check; stat; write_json {mapped_json}; write_verilog -noattr {mapped_v}')
  c=run_cmd('yosys_xc7_synth',[yosys,'-p',script]);commands.append(c);require(c['returncode']==0,'Yosys XC7 synthesis failed')
  proof=mapped_proof(mapped_json)
  marker='PASS_CAPACITY_PATTERN'
  for name in ('iverilog_sim','verilator_sim'):
   log=(PKG/(name+'.stdout.log')).read_text();require(marker in log,name+' PASS marker absent')
  status='PASS_SYNTHESIZABLE_PATTERN_LEAF_ONLY'
 except BaseException as error:
  failure=repr(error)
 else:failure=None
 hashes_after={str(p):sha(p) for p in source_paths}
 no_drift=hashes_before==hashes_after
 if not no_drift:status='FAIL'
 prior_v1=PKG.parent/'ddr-capacity-bist-leaf-validation-v1/report.json'
 prior_v2=PKG.parent/'ddr-capacity-bist-leaf-validation-v2/report.json'
 prior_v3=PKG.parent/'ddr-capacity-bist-leaf-validation-v3/report.json'
 prior_v4=PKG.parent/'ddr-capacity-bist-leaf-validation-v4/report.json'
 report={'schema':'ddr-capacity-pattern-leaf-validation-v1','status':status,'failure':failure,
  'started_utc':commands[0]['started_utc'] if commands else utc(),'finished_utc':utc(),
  'host_admission':host,'host_final':pressure(),'cgroup':cgroup,
  'prior_failures':[{'path':str(p),'sha256':sha(p),'status':json.loads(p.read_text())['status']} for p in (prior_v1,prior_v2,prior_v3,prior_v4)],
  'cgroup_limits_requested':{'MemoryMax':'4GiB','MemorySwapMax':0,'CPUQuota':'200%','TasksMax':256},
  'process_limits_note':'Parent validation runner was launched within systemd-run --user --scope; children inherit the same scope.',
  'source_hashes_before':hashes_before,'source_hashes_after':hashes_after,'source_unchanged':no_drift,
  'vector_manifest':vman,'tool_versions':versions,'commands':commands,'mapped_proof':proof,
  'scope':'Private RTL pattern-leaf equivalence and XC7 mapping only; not memory controller, DDR capacity, physical target or application qualification.',
  'hardware_executed':False,'physical_capacity_qualified':False,'full2gib_physical_claim':False}
 report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'status':status,'failure':failure,'report':str(report_path),'source_unchanged':no_drift,
  'commands':[(x['name'],x['returncode']) for x in commands]},indent=2))
 return 0 if status.startswith('PASS') else 1

if __name__=='__main__':raise SystemExit(main())
