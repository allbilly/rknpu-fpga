#!/usr/bin/env python3
"""Bounded standalone simulations for the private AXI-Lite diagnostic router."""
from __future__ import annotations
import datetime,hashlib,json,os,pathlib,signal,shutil,subprocess,sys,time
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');PKG=pathlib.Path(__file__).resolve().parent
RTL=ROOT/'build/ddr-capacity-owner-source-v1/rk_axil_diagnostic_router.sv';TB=PKG/'tb_axil_diagnostic_router.sv'
TOOLS={n:shutil.which(n) for n in ('iverilog','vvp','verilator')};TIMEOUT=300
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def version(path,args):
 if not path:return {'path':None,'available':False}
 p=subprocess.run([path,*args],cwd=PKG,capture_output=True,text=True,timeout=10)
 return {'path':path,'returncode':p.returncode,'stdout':p.stdout.strip(),'stderr':p.stderr.strip()}
def host_sample():
 m={}
 for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
  if line.startswith(('MemAvailable:','SwapFree:')):
   f=line.split();m[f[0][:-1]+'_kib']=int(f[1])
 psi={}
 for d in ('memory','cpu'):
  rows={}
  for line in pathlib.Path(f'/proc/pressure/{d}').read_text().splitlines():
   x=line.split();rows[x[0]]={k:float(v) for k,v in (y.split('=') for y in x[1:] if '=' in y)}
  psi[d]=rows
 return {'utc':utc(),**m,'memory_psi_full_avg10':psi['memory']['full']['avg10'],
  'cpu_psi_some_avg10':psi['cpu']['some']['avg10'],'cgroup':pathlib.Path('/proc/self/cgroup').read_text().strip()}
def run(name,argv):
 started=utc();t0=time.monotonic();out=PKG/(name+'.stdout.log');err=PKG/(name+'.stderr.log');timed=False;cleanup=None
 with out.open('wb') as so,err.open('wb') as se:
  p=subprocess.Popen(argv,cwd=PKG,stdout=so,stderr=se,start_new_session=True)
  try:rc=p.wait(timeout=TIMEOUT)
  except subprocess.TimeoutExpired:
   timed=True;os.killpg(p.pid,signal.SIGTERM)
   try:rc=p.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);rc=p.wait()
   cleanup={'pgid':p.pid,'signal':'SIGTERM_then_SIGKILL_if_needed','returncode':rc}
 return {'name':name,'argv':argv,'cwd':str(PKG),'started_utc':started,'finished_utc':utc(),'wall_seconds':round(time.monotonic()-t0,6),
  'timeout_seconds':TIMEOUT,'timed_out':timed,'returncode':rc,'stdout_path':str(out),'stdout_sha256':sha(out),
  'stderr_path':str(err),'stderr_sha256':sha(err),'cleanup':cleanup}
def main():
 out=PKG/'report.json'
 if out.exists():raise SystemExit('fresh validation directory required')
 sources=[RTL,TB,PKG/'run_validation.py'];before={str(p):sha(p) for p in sources}
 host=host_sample()
 if host['MemAvailable_kib']<8*1024*1024 or host['memory_psi_full_avg10']>=1.0 or host['cpu_psi_some_avg10']>=5.0:
  raise SystemExit('host headroom/pressure gate failed')
 versions={'iverilog':version(TOOLS['iverilog'],['-V']),'vvp':version(TOOLS['vvp'],['-V']),
           'verilator':version(TOOLS['verilator'],['--version'])}
 commands=[];status='FAIL';failure=None
 try:
  if not all(TOOLS[x] for x in ('iverilog','vvp','verilator')):raise RuntimeError('required simulator unavailable')
  iv=PKG/'router_iverilog.vvp'
  c=run('iverilog_compile',[TOOLS['iverilog'],'-g2012','-Wall','-s','tb_axil_diagnostic_router','-o',str(iv),str(RTL),str(TB)])
  commands.append(c)
  if c['returncode']:raise RuntimeError('Icarus compile failed')
  c=run('iverilog_sim',[TOOLS['vvp'],str(iv)]);commands.append(c)
  if c['returncode'] or 'PASS_AXIL_DIAGNOSTIC_ROUTER' not in pathlib.Path(c['stdout_path']).read_text():raise RuntimeError('Icarus router simulation failed')
  obj=PKG/'verilator_obj';obj.mkdir()
  c=run('verilator_compile',[TOOLS['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_axil_diagnostic_router',
     '-j','2','--Mdir',str(obj),str(RTL),str(TB)]);commands.append(c)
  if c['returncode']:raise RuntimeError('strict Verilator compile failed')
  c=run('verilator_sim',[str(obj/'Vtb_axil_diagnostic_router')]);commands.append(c)
  if c['returncode'] or 'PASS_AXIL_DIAGNOSTIC_ROUTER' not in pathlib.Path(c['stdout_path']).read_text():raise RuntimeError('Verilator router simulation failed')
  status='PASS_AXIL_DIAGNOSTIC_ROUTER_STANDALONE_ONLY'
 except BaseException as e:failure=repr(e)
 after={str(p):sha(p) for p in sources};unchanged=before==after
 if not unchanged:status='FAIL'
 prior_v1=PKG.parent/'axil-diagnostic-router-validation-v1/report.json'
 prior_v2=PKG.parent/'axil-diagnostic-router-validation-v2/report.json'
 prior_v3=PKG.parent/'axil-diagnostic-router-validation-v3/report.json'
 prior_v4=PKG.parent/'axil-diagnostic-router-validation-v4/report.json'
 prior_v5=PKG.parent/'axil-diagnostic-router-validation-v5/report.json'
 prior_v6=PKG.parent/'axil-diagnostic-router-validation-v6/report.json'
 report={'schema':'axil-diagnostic-router-validation-v1','status':status,'failure':failure,
  'started_utc':commands[0]['started_utc'] if commands else utc(),'finished_utc':utc(),
  'host_admission':host,'host_final':host_sample(),'cgroup':host['cgroup'],
  'cgroup_limits_requested':{'MemoryMax':'4GiB','MemorySwapMax':0,'CPUQuota':'200%','TasksMax':256},
  'sources_before':before,'sources_after':after,'sources_unchanged':unchanged,'tool_versions':versions,'commands':commands,
  'seed':'0x3588b157','max_native_timeout_seconds':TIMEOUT,
  'scope':'Standalone router with tagged independent child stubs; not full parent/register/board integration.',
  'hardware_executed':False,'vivado_executed':False,'physical_capacity_qualified':False,'parent_integration_qualified':False}
 out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'status':status,'failure':failure,'report':str(out),'commands':[(x['name'],x['returncode']) for x in commands]},indent=2))
 return 0 if status.startswith('PASS') else 1
if __name__=='__main__':raise SystemExit(main())
