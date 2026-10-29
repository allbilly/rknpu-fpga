#!/usr/bin/env python3
"""Strict Verilator-only follow-up after preserving Icarus warning failure."""
from pathlib import Path
import datetime,hashlib,json,os,re,shlex,shutil,signal,subprocess,sys,time
ROOT=Path('/home/fedora/rknpu-fpga');BASE=Path(__file__).resolve().parent
PREP=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v4/preparation.json'
SOURCE=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/056/mig_7series_v4_2_fi_xor.v'
LOCAL=BASE/'source/mig_7series_v4_2_fi_xor.v';BENCH=BASE/'tests/tb_mig_fi_xor.sv'
OUTPUT=BASE/'runs';REPORT=BASE/'report.json';TOP='tb_mig_fi_xor'
EXPECTED='PASS fi_xor_leaf seed=00003588 scenarios=38 byte_lanes=9 low72_only=1 write_clear=1'
TIMEOUT=300;child=None;record={'schema':'mig-fi-xor-verilator-validation-v1','status':'PREPARED'}
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(v,msg):
 if not v:raise ValueError(msg)
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save():REPORT.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
def cgdir():
 rel=next(x.split('::',1)[1].lstrip('/') for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
 return Path('/sys/fs/cgroup')/rel
def members(pgid):
 r=[]
 for ent in Path('/proc').iterdir():
  if not ent.name.isdigit():continue
  try:
   f=(ent/'stat').read_text().rsplit(')',1)[1].split()
   if int(f[2])==pgid and f[0] not in {'Z','X'}:r.append(int(ent.name))
  except (FileNotFoundError,ProcessLookupError,ValueError,IndexError):pass
 return sorted(r)
def stop(sig):
 global child
 if child is None:return
 try:os.killpg(child.pid,sig)
 except ProcessLookupError:pass
 try:child.wait(timeout=10)
 except subprocess.TimeoutExpired:pass
 if members(child.pid):
  try:os.killpg(child.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  if child.poll() is None:child.wait()
def run(name,argv,cwd,expected_marker=None):
 global child
 outp=BASE/(name+'.stdout.log');errp=BASE/(name+'.stderr.log');need(not outp.exists() and not errp.exists(),'Fresh command logs required')
 cmd={'name':name,'argv':argv,'cwd':str(cwd),'timeout_seconds':TIMEOUT,'status':'RUNNING','started_utc':stamp(),
      'stdout_log':str(outp.resolve()),'stderr_log':str(errp.resolve())};record['commands'].append(cmd);save();start=time.monotonic()
 with outp.open('xb') as so,errp.open('xb') as se:
  child=subprocess.Popen(argv,cwd=cwd,stdout=so,stderr=se,start_new_session=True)
  cmd.update(pid=child.pid,pgid=child.pid);save()
  while child.poll() is None:
   if time.monotonic()-start>=TIMEOUT:
    cmd.update(status='TIMEOUT',returncode=None);save();stop(signal.SIGTERM);raise TimeoutError(name+' exceeded300 seconds')
   time.sleep(.2)
  rc=child.returncode
 child=None;stdout=outp.read_text(errors='replace');stderr=errp.read_text(errors='replace')
 diagnostics=re.findall(r'(?im)^.*(?:%Warning|\bwarning:|%Error|\berror:).*$','\n'.join((stdout,stderr)))
 failure=None
 if diagnostics:failure=name+' emitted strict unsuppressed warning/error diagnostics: '+repr(diagnostics[:25])
 if expected_marker:
  lines=stdout.splitlines();passes=[x for x in lines if x.startswith('PASS fi_xor_leaf ')]
  allowed=[expected_marker]
  allowed.extend(x for x in lines if x.startswith('- ') and 'Verilog $finish' in x)
  if rc!=0 or passes!=[expected_marker]:failure=failure or name+' missing exact native PASS marker'
  if lines!=allowed:failure=failure or name+' unexpected runtime output: '+repr(lines[:20])
  if stderr:failure=failure or name+' unexpected stderr: '+repr(stderr[:1000])
 elif rc!=0:failure=name+' returned '+str(rc)
 cmd.update(returncode=rc,seconds=time.monotonic()-start,finished_utc=stamp(),status='FAIL' if failure else 'PASS',
            stdout_sha256=sha(outp),stderr_sha256=sha(errp),diagnostics=diagnostics)
 if failure:cmd['error']=failure
 cmd['owned_process_group_absent']=not members(cmd['pgid'])
 save()
 if failure:raise ValueError(failure)
def main():
 global record
 need(not OUTPUT.exists() and not REPORT.exists(),'Fresh Verilator follow-up required')
 prep=json.loads(PREP.read_text());expected=prep['copied_source_hashes']['hdl/056/mig_7series_v4_2_fi_xor.v']
 need(expected==sha(SOURCE)==sha(LOCAL),'Selected vendor FI_XOR source changed')
 need(prep['copied_file_count']==160 and prep['source_copy_manifest_sha256']=='85ed4aed6a3761b2e12f86b21bc9a5adc79e60049148ac958290bcb30650ff69','Strict source prep changed')
 cg=cgdir();limits={x:(cg/x).read_text().strip() for x in ('memory.max','memory.swap.max','cpu.max','pids.max')}
 required={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'};need(limits==required,'Wrong cgroup '+repr(limits))
 OUTPUT.mkdir();verilator=shutil.which('verilator');cxx=shutil.which('c++');need(verilator and cxx,'Required strict tool missing')
 def version(argv):
  p=subprocess.run(argv,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=30)
  need(p.returncode==0,'Version command failed: '+repr(argv));return {'argv':argv,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
 versions={'verilator':version([verilator,'--version']),'cxx':version([cxx,'--version'])}
 need(versions['verilator']['stdout'].startswith('Verilator 5.048'),'Expected Verilator5.048')
 record.update(status='RUNNING_VERILATOR_ONLY_FI_XOR_LEAF',scope='Strict Verilator simulation of actual vendor FI_XOR leaf only; no controller, memory, ECC decoder, PHY, physical injection, or hardware qualification.',
  started_utc=stamp(),cgroup=limits,tool_paths={x:{'path':str(Path(p).resolve()),'sha256':sha(p)} for x,p in [('verilator',verilator),('cxx',cxx)]},
  tool_versions=versions,previous_iverilog_failure='v3 rejected the actual source warning and did not launch this Verilator run',
  source_inputs={str(SOURCE):sha(SOURCE),str(LOCAL):sha(LOCAL),str(BENCH):sha(BENCH),str(PREP):sha(PREP),str(Path(__file__).resolve()):sha(__file__)},
  commands=[],native_timeout_seconds=TIMEOUT,warning_suppression_flags=[],hardware_accessed=False,vivado_executed=False,flash_written=False)
 save();obj=OUTPUT/'obj';image=obj/'sim'
 build=[verilator,'--binary','--timing','--assert','-Wall','--top-module',TOP,'-j','2','-MAKEFLAGS','CXX='+shlex.quote(cxx),'--Mdir',str(obj),'-o','sim',str(LOCAL),str(BENCH)]
 run('verilator_compile',build,ROOT)
 need(image.is_file(),'Verilator simulation executable not produced')
 record['binary_sha256']=sha(image);save()
 run('verilator_run',[str(image)],ROOT,EXPECTED)
 after={p:sha(p) for p in record['source_inputs']};need(after==record['source_inputs'],'Bound source changed during Verilator run')
 record.update(status='PASS_FI_XOR_LEAF_VERILATOR_ONLY',finished_utc=stamp(),source_inputs_after=after,all_inputs_unchanged=True,
  scenario_count=38,byte_lanes=9,upper_seven_words_passthrough=True,initial_zero_mask=True,
  one_cycle_write_clear=True,simultaneous_arm_write_clear_priority=True,mock_reset_unconnected=True,
  physical_capacity_qualified=False,physical_ecc_injection_qualified=False,memory_or_ecc_decoder_simulated=False,phy_simulated=False)
 save()
if __name__=='__main__':
 try:main()
 except BaseException as error:
  if child is not None and child.poll() is None:stop(signal.SIGTERM)
  record.update(status='FAIL',error=repr(error),finished_utc=stamp(),physical_capacity_qualified=False,
   physical_ecc_injection_qualified=False,memory_or_ecc_decoder_simulated=False,phy_simulated=False)
  save();print(json.dumps({'status':record['status'],'error':record['error'],'report':str(REPORT)},indent=2));raise SystemExit(1)
