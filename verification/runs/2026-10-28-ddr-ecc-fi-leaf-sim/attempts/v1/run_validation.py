#!/usr/bin/env python3
"""Strict dual-simulator test of the frozen 72-bit MIG FI_XOR data leaf only."""
from pathlib import Path
import datetime,hashlib,json,os,re,shutil,signal,subprocess,sys,time
ROOT=Path('/home/fedora/rknpu-fpga')
BASE=Path(__file__).resolve().parent
PKG=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v4'
PREP=PKG/'preparation.json'
SOURCE=PKG/'source/hdl/056/mig_7series_v4_2_fi_xor.v'
LOCAL_SOURCE=BASE/'source/mig_7series_v4_2_fi_xor.v'
BENCH=BASE/'tests/tb_mig_fi_xor.sv'
OUTPUT=BASE/'runs'
REPORT=BASE/'report.json'
TOP='tb_mig_fi_xor'
EXPECTED='PASS fi_xor_leaf seed=00003588 scenarios=38 byte_lanes=9 low72_only=1 write_clear=1'
TIMEOUT=300
child=None;received_signal=None
record={'schema':'mig-fi-xor-leaf-validation-v1','status':'PREPARED'}

def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,msg):
 if not ok:raise ValueError(msg)
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save():REPORT.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
def cgroup_dir():
 rel=next(x.split('::',1)[1].lstrip('/') for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
 return Path('/sys/fs/cgroup')/rel
def members(pgid):
 found=[]
 for ent in Path('/proc').iterdir():
  if not ent.name.isdigit():continue
  try:
   fields=(ent/'stat').read_text().rsplit(')',1)[1].split()
   if int(fields[2])==pgid and fields[0] not in {'Z','X'}:found.append(int(ent.name))
  except (FileNotFoundError,ProcessLookupError,ValueError,IndexError):pass
 return sorted(found)
def stop_owned(sig):
 if child is None:return
 try:os.killpg(child.pid,sig)
 except ProcessLookupError:pass
 try:child.wait(timeout=10)
 except subprocess.TimeoutExpired:pass
 if members(child.pid):
  try:os.killpg(child.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  if child.poll() is None:child.wait()
def on_signal(sig,frame):
 global received_signal
 received_signal=sig;raise InterruptedError('FI_XOR leaf validation interrupted '+str(sig))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,on_signal)
def version(argv,deadline=30):
 p=subprocess.run(argv,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=deadline,text=True)
 return {'argv':argv,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
def run_one(name,argv,cwd,limit,expected_marker=None):
 global child
 need(not (BASE/(name+'.stdout.log')).exists() and not (BASE/(name+'.stderr.log')).exists(), 'Fresh per-command logs required')
 log=dict(name=name,argv=argv,cwd=str(cwd),timeout_seconds=limit,status='RUNNING',started_utc=stamp(),
          stdout_log=str((BASE/(name+'.stdout.log')).resolve()),stderr_log=str((BASE/(name+'.stderr.log')).resolve()))
 record['commands'].append(log);save();start=time.monotonic()
 with Path(log['stdout_log']).open('xb') as out,Path(log['stderr_log']).open('xb') as err:
  child=subprocess.Popen(argv,cwd=cwd,stdout=out,stderr=err,start_new_session=True)
  log.update(pid=child.pid,pgid=child.pid);save()
  while child.poll() is None:
   if time.monotonic()-start>=limit:
    log['status']='TIMEOUT';stop_owned(signal.SIGTERM);log['returncode']=child.returncode
    log['seconds']=time.monotonic()-start;save();raise TimeoutError(name+' exceeded '+str(limit)+' seconds')
   time.sleep(.2)
  rc=child.returncode
 child=None
 out=Path(log['stdout_log']).read_text(errors='replace');err=Path(log['stderr_log']).read_text(errors='replace')
 diagnostics=re.findall(r'(?im)^.*(?:%Warning|\bwarning:|%Error|\berror:).*$','\n'.join((out,err)))
 failure=None
 if diagnostics:failure=name+' emitted unsuppressed warning/error diagnostics: '+repr(diagnostics[:20])
 if expected_marker is not None:
  lines=out.splitlines();passes=[line for line in lines if line.startswith('PASS fi_xor_leaf ')]
  allowed=[expected_marker]
  for line in lines:
   if line.startswith('$finish called at ') or (line.startswith('- ') and 'Verilog $finish' in line):allowed.append(line)
  if rc!=0 or passes!=[expected_marker]:failure=failure or name+' did not produce exact leaf PASS marker'
  if lines!=allowed:failure=failure or name+' produced unexpected runtime output: '+repr(lines[:20])
  if err!='':failure=failure or name+' produced unexpected stderr: '+repr(err[:1000])
 elif rc!=0:failure=failure or name+' failed rc='+str(rc)+'; logs '+log['stdout_log']+' / '+log['stderr_log']
 log.update(returncode=rc,seconds=time.monotonic()-start,finished_utc=stamp(),status='FAIL' if failure else 'PASS',
            stdout_sha256=sha(log['stdout_log']),stderr_sha256=sha(log['stderr_log']),diagnostics=diagnostics)
 if failure:log['error']=failure
 save()
 if failure:raise ValueError(failure)
 return log

def main():
 global record,child
 record['bench_sha256']=sha(BENCH)
 need(not OUTPUT.exists() and not REPORT.exists(),'Fresh FI_XOR validation output required')
 prep=json.loads(PREP.read_text())
 relative='hdl/056/mig_7series_v4_2_fi_xor.v'
 expected=prep['copied_source_hashes'][relative]
 need(prep['copied_file_count']==160 and prep['source_copy_manifest_sha256']=='85ed4aed6a3761b2e12f86b21bc9a5adc79e60049148ac958290bcb30650ff69',
      'Unexpected strict source-closure preparation')
 need(sha(SOURCE)==expected and sha(LOCAL_SOURCE)==expected,'Frozen FI_XOR source copy/origin hash mismatch')
 need(sha(LOCAL_SOURCE)==sha(SOURCE),'Copied selected FI_XOR leaf changed')
 need(sha(BENCH)==record['bench_sha256'],'Private bench changed before launch')
 cg=cgroup_dir();limits={k:(cg/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
 required={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'}
 need(limits==required,'Wrong test cgroup limits: '+repr(limits))
 OUTPUT.mkdir()
 record.update(status='RUNNING',scope='Frozen MIG FI_XOR leaf contract only; no controller, ECC decoder, MIG memory, PHY, physical injection, or hardware qualification.',
               source_inputs={str(SOURCE):expected,str(LOCAL_SOURCE):sha(LOCAL_SOURCE),str(BENCH):sha(BENCH),
               str(PREP):sha(PREP),str(Path(__file__).resolve()):sha(Path(__file__).resolve())},
               source_closure_count=160,source_closure_manifest_sha256=prep['source_copy_manifest_sha256'],
               cgroup=limits,tools={},commands=[],started_utc=stamp())
 save()
 paths={'iverilog':shutil.which('iverilog'),'vvp':shutil.which('vvp'),'verilator':shutil.which('verilator'),'cxx':shutil.which('c++')}
 need(all(paths.values()),'Required simulator/compiler tool missing')
 versions={key:version([path,'-V'] if key=='iverilog' else [path,'--version']) for key,path in paths.items()}
 need(all(v['returncode']==0 for v in versions.values()),'Tool version command failed')
 record['tools']={key:{'path':str(Path(path).resolve()),'sha256':sha(path)} for key,path in paths.items()}
 record['tool_versions']={key:{'argv':v['argv'],'returncode':v['returncode'],'stdout':v['stdout'],'stderr':v['stderr']} for key,v in versions.items()}
 need(versions['iverilog']['stdout'].splitlines()[0].startswith('Icarus Verilog version 13.'),'Expected Icarus Verilog13')
 need(versions['verilator']['stdout'].splitlines()[0].startswith('Verilator 5.048'),'Expected strict Verilator5.048')
 save()
 runroot=OUTPUT;iverilog_dir=runroot/'iverilog';iverilog_dir.mkdir();verilator_dir=runroot/'verilator';verilator_dir.mkdir()
 iv_image=iverilog_dir/'fi.vvp'
 iv_build=[paths['iverilog'],'-g2012','-Wall','-s',TOP,'-o',str(iv_image),str(LOCAL_SOURCE),str(BENCH)]
 run_one('iverilog_compile',iv_build,ROOT,TIMEOUT)
 record['binary_hashes']={'iverilog_vvp':sha(iv_image)};save()
 run_one('iverilog_run',[paths['vvp'],str(iv_image)],ROOT,TIMEOUT,EXPECTED)
 vl_obj=verilator_dir/'obj'
 vl_build=[paths['verilator'],'--binary','--timing','--assert','-Wall','--top-module',TOP,'-j','2','-MAKEFLAGS',
           'CXX='+paths['cxx'],'--Mdir',str(vl_obj),'-o','sim',str(LOCAL_SOURCE),str(BENCH)]
 run_one('verilator_compile',vl_build,ROOT,TIMEOUT)
 vl_image=vl_obj/'sim';need(vl_image.is_file(),'Verilator binary missing')
 record['binary_hashes']['verilator_sim']=sha(vl_image);save()
 run_one('verilator_run',[str(vl_image)],ROOT,TIMEOUT,EXPECTED)
 after={p:sha(p) for p in record['source_inputs']}
 need(after==record['source_inputs'],'FI_XOR selected source/preparation changed during validation')
 record.update(status='PASS_FI_XOR_LEAF_TWO_SIMULATORS_ONLY',finished_utc=stamp(),source_inputs_after=after,
  all_inputs_unchanged=True,scenario_count=38,byte_lanes=9,upper_seven_words_passthrough=True,
  initial_zero_mask=True,one_cycle_write_clear=True,simultaneous_arm_write_clear_priority=True,
  mock_reset_unconnected=True,physical_capacity_qualified=False,physical_ecc_injection_qualified=False,
  memory_or_ecc_decoder_simulated=False,phy_simulated=False,hardware_accessed=False,vivado_executed=False)
 save()
try:
 sys.exit(main() or 0)
except BaseException as error:
 if child is not None and child.poll() is None:stop_owned(signal.SIGTERM)
 if record is None:
  record={'status':'FAIL','error':repr(error),'started_utc':stamp()}
 else:record.update(status='FAIL',error=repr(error),finished_utc=stamp(),physical_capacity_qualified=False,
                    physical_ecc_injection_qualified=False,memory_or_ecc_decoder_simulated=False,phy_simulated=False,
                    hardware_accessed=False,vivado_executed=False)
 save();print(json.dumps({'status':record['status'],'error':record['error'],'report':str(REPORT.resolve())},indent=2));sys.exit(1)
