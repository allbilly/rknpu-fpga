#!/usr/bin/env python3
"""Bounded Icarus/strict Verilator tests for the private DDR ownership observer."""
from __future__ import annotations
import datetime,hashlib,json,os,pathlib,shutil,signal,subprocess,sys,time
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');PKG=pathlib.Path(__file__).resolve().parent
RTL=ROOT/'build/ddr-capacity-owner-source-v1/rk_ddr_capacity_owner.sv'
BENCH=PKG/'tb_capacity_owner.sv';INVALID=PKG/'tb_capacity_owner_invalid.sv'
TIMEOUT=300;TOOLS={n:shutil.which(n) for n in ('iverilog','vvp','verilator','python3')}
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def require(ok,msg):
 if not ok:raise RuntimeError(msg)
def version(path,args):
 if not path:return {'path':None,'available':False}
 p=subprocess.run([path,*args],cwd=PKG,capture_output=True,text=True,timeout=10)
 return {'path':path,'returncode':p.returncode,'stdout':p.stdout.strip(),'stderr':p.stderr.strip()}
def host_sample():
 mem={}
 for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
  if line.startswith(('MemAvailable:','SwapFree:')):
   x=line.split();mem[x[0][:-1]+'_kib']=int(x[1])
 psi={}
 for d in ('memory','cpu'):
  row={}
  for line in pathlib.Path(f'/proc/pressure/{d}').read_text().splitlines():
   x=line.split();row[x[0]]={k:float(v) for k,v in (item.split('=') for item in x[1:] if '=' in item)}
  psi[d]=row
 return {'utc':utc(),**mem,'memory_psi_full_avg10':psi['memory']['full']['avg10'],
  'cpu_psi_some_avg10':psi['cpu']['some']['avg10'],'cgroup':pathlib.Path('/proc/self/cgroup').read_text().strip()}
def run_cmd(name,argv,timeout=TIMEOUT):
 started=utc();t0=time.monotonic();out=PKG/(name+'.stdout.log');err=PKG/(name+'.stderr.log');timed=False;cleanup=None
 with out.open('wb') as so,err.open('wb') as se:
  p=subprocess.Popen(argv,cwd=PKG,stdout=so,stderr=se,start_new_session=True)
  try:rc=p.wait(timeout=timeout)
  except subprocess.TimeoutExpired:
   timed=True;os.killpg(p.pid,signal.SIGTERM)
   try:rc=p.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);rc=p.wait()
   cleanup={'pgid':p.pid,'sigterm_then_sigkill_if_needed':True,'returncode':rc}
 return {'name':name,'argv':argv,'cwd':str(PKG),'started_utc':started,'finished_utc':utc(),
  'wall_seconds':round(time.monotonic()-t0,6),'timeout_seconds':timeout,'timed_out':timed,'returncode':rc,
  'stdout_path':str(out),'stdout_sha256':sha(out),'stderr_path':str(err),'stderr_sha256':sha(err),'cleanup':cleanup}
def logtext(command):return pathlib.Path(command['stdout_path']).read_text(errors='replace')+pathlib.Path(command['stderr_path']).read_text(errors='replace')
def main():
 out=PKG/'report.json';require(not out.exists(),'fresh validation directory required')
 sources=[RTL,BENCH,INVALID,PKG/'run_validation.py'];before={str(p):sha(p) for p in sources}
 host=host_sample();require(host['MemAvailable_kib']>=8*1024*1024,'host requires >=8GiB MemAvailable')
 require(host['memory_psi_full_avg10']<1.0 and host['cpu_psi_some_avg10']<5.0,'host PSI admission gate failed')
 versions={'iverilog':version(TOOLS['iverilog'],['-V']),'vvp':version(TOOLS['vvp'],['-V']),'verilator':version(TOOLS['verilator'],['--version'])}
 commands=[];negative=[];status='FAIL';failure=None
 try:
  require(all(TOOLS[x] for x in ('iverilog','vvp','verilator')),'required simulator unavailable')
  ivbin=PKG/'owner_behavior.vvp'
  c=run_cmd('icarus_behavior_compile',[TOOLS['iverilog'],'-g2012','-Wall','-s','tb_capacity_owner','-Ptb_capacity_owner.QUIET_CYCLES=2','-Ptb_capacity_owner.TIMEOUT_CYCLES=8','-o',str(ivbin),str(RTL),str(BENCH)])
  commands.append(c);require(c['returncode']==0,'Icarus owner compile failed')
  c=run_cmd('icarus_behavior_sim',[TOOLS['vvp'],str(ivbin)]);commands.append(c)
  require(c['returncode']==0 and 'PASS_OWNER_LEAF_CASES=PASS' in logtext(c) and
          'PASS_OWNER_UNKNOWN_INPUTS_FOUR_STATE' in logtext(c),'Icarus owner behavioral/four-state run failed')
  vlt=PKG/'verilator_obj';vlt.mkdir()
  c=run_cmd('verilator_behavior_compile',[TOOLS['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_capacity_owner',
      '-j','2','--Mdir',str(vlt),'-GQUIET_CYCLES=2','-GTIMEOUT_CYCLES=32',str(RTL),str(BENCH)])
  commands.append(c);require(c['returncode']==0,'strict Verilator owner compile failed')
  c=run_cmd('verilator_behavior_sim',[str(vlt/'Vtb_capacity_owner')]);commands.append(c)
  require(c['returncode']==0 and 'PASS_OWNER_LEAF_CASES=PASS' in logtext(c) and
          'PASS_OWNER_UNKNOWN_INPUTS=NOT_APPLICABLE_TWO_STATE' in logtext(c),'Verilator two-state owner behavioral run failed')

  invalid_cases=[('quiet_below_min',1,8),('timeout_equal_quiet',2,2),('timeout_shorter_than_quiet',4,3)]
  for case,q,t in invalid_cases:
   ibin=PKG/(case+'.vvp')
   c=run_cmd(case+'_icarus_compile',[TOOLS['iverilog'],'-g2012','-Wall','-s','tb_capacity_owner_invalid',
     f'-Ptb_capacity_owner_invalid.QUIET_CYCLES={q}',f'-Ptb_capacity_owner_invalid.TIMEOUT_CYCLES={t}',
     '-o',str(ibin),str(RTL),str(INVALID)])
   commands.append(c);require(c['returncode']==0,case+' Icarus invalid-parameter compile failed')
   c=run_cmd(case+'_icarus_reject',[TOOLS['vvp'],str(ibin)]);commands.append(c)
   require(c['returncode']!=0 and 'Capacity owner requires at least two quiet cycles and a longer positive timeout' in logtext(c),
     case+' was not rejected by Icarus')
   vdir=PKG/(case+'_verilator_obj');vdir.mkdir()
   c=run_cmd(case+'_verilator_compile',[TOOLS['verilator'],'--binary','--timing','--assert','--Wall','--top-module','tb_capacity_owner_invalid',
     '-j','2','--Mdir',str(vdir),f'-GQUIET_CYCLES={q}',f'-GTIMEOUT_CYCLES={t}',str(RTL),str(INVALID)])
   commands.append(c);require(c['returncode']==0,case+' strict Verilator invalid-parameter compile failed')
   c=run_cmd(case+'_verilator_reject',[str(vdir/'Vtb_capacity_owner_invalid')]);commands.append(c)
   require(c['returncode']!=0 and 'Capacity owner requires at least two quiet cycles and a longer positive timeout' in logtext(c),
     case+' was not rejected by Verilator')
   negative.append({'case':case,'quiet_cycles':q,'timeout_cycles':t,'icarus_rc':1,'verilator_rc':c['returncode'],
      'expected_fatal_text':'Capacity owner requires at least two quiet cycles and a longer positive timeout'})
  status='PASS_OWNER_OBSERVER_CONTRACT_SIMULATION_ONLY'
 except BaseException as error:failure=repr(error)
 after={str(p):sha(p) for p in sources};unchanged=before==after
 if not unchanged:status='FAIL'
 prior_v1=PKG.parent/'ddr-capacity-owner-validation-v1/report.json'
 prior_v2=PKG.parent/'ddr-capacity-owner-validation-v2/report.json'
 prior_v3=PKG.parent/'ddr-capacity-owner-validation-v3/report.json'
 prior_v4=PKG.parent/'ddr-capacity-owner-validation-v4/report.json'
 prior_v5=PKG.parent/'ddr-capacity-owner-validation-v5/report.json'
 prior_v6=PKG.parent/'ddr-capacity-owner-validation-v6/report.json'
 prior_v2=PKG.parent/'ddr-capacity-owner-validation-v2/report.json'
 prior_v3=PKG.parent/'ddr-capacity-owner-validation-v3/report.json'
 report={'schema':'ddr-capacity-owner-validation-v1','status':status,'failure':failure,
  'started_utc':commands[0]['started_utc'] if commands else utc(),'finished_utc':utc(),
  'host_admission':host,'host_final':host_sample(),'cgroup':host['cgroup'],
  'cgroup_limits_requested':{'MemoryMax':'4GiB','MemorySwapMax':0,'CPUQuota':'200%','TasksMax':256},
  'source_hashes_before':before,'source_hashes_after':after,'sources_unchanged':unchanged,
  'prior_failed_attempts':[{'path':str(p),'sha256':sha(p),'status':json.loads(p.read_text())['status']} for p in (prior_v1,prior_v2,prior_v3)],
  'tool_versions':versions,'commands':commands,'invalid_parameter_cases':negative,
  'timeouts_seconds_per_command':TIMEOUT,'unknown_inputs_scope':{'icarus':'four-state X seed/VALID cases','verilator':'NOT_APPLICABLE_TWO_STATE'},
  'scope':'Private ownership observer control only; no mux/MIG/PCIe/physical qualification.',
  'hardware_executed':False,'vivado_executed':False,'lease_used':False,'physical_capacity_qualified':False,'model_run_executed':False}
 out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'status':status,'failure':failure,'report':str(out),'sources_unchanged':unchanged,
  'commands':[(x['name'],x['returncode']) for x in commands]},indent=2))
 return 0 if status.startswith('PASS') else 1
if __name__=='__main__':raise SystemExit(main())
