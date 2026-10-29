#!/usr/bin/env python3
"""Icarus behavior-only FI_XOR leaf test, recording the actual unsuppressed vendor warning."""
from pathlib import Path
import datetime,hashlib,json,os,re,shutil,signal,subprocess,sys,time
ROOT=Path('/home/fedora/rknpu-fpga');BASE=Path(__file__).resolve().parent
PREP=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v4/preparation.json'
SOURCE=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/056/mig_7series_v4_2_fi_xor.v'
LOCAL=BASE/'source/mig_7series_v4_2_fi_xor.v';BENCH=BASE/'tests/tb_mig_fi_xor.sv';OUTPUT=BASE/'runs';REPORT=BASE/'report.json'
TOP='tb_mig_fi_xor';EXPECTED='PASS fi_xor_leaf seed=00003588 scenarios=38 byte_lanes=9 low72_only=1 write_clear=1';TIMEOUT=300
child=None
record={'schema':'mig-fi-xor-icarus-behavior-v1','status':'PREPARED','warning_suppression_used':False}
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,msg):
 if not ok:raise ValueError(msg)
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save():REPORT.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
def cgdir():
 rel=next(x.split('::',1)[1].lstrip('/') for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
 return Path('/sys/fs/cgroup')/rel
def members(pgid):
 found=[]
 for ent in Path('/proc').iterdir():
  if not ent.name.isdigit():continue
  try:
   f=(ent/'stat').read_text().rsplit(')',1)[1].split()
   if int(f[2])==pgid and f[0] not in {'Z','X'}:found.append(int(ent.name))
  except (FileNotFoundError,ProcessLookupError,ValueError,IndexError):pass
 return sorted(found)
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
def version(argv):
 p=subprocess.run(argv,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=30)
 return {'argv':argv,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
def run(name,argv,expected_marker=None):
 global child
 outp=BASE/(name+'.stdout.log');errp=BASE/(name+'.stderr.log');need(not outp.exists() and not errp.exists(),'Fresh command logs required')
 entry={'name':name,'argv':argv,'cwd':str(ROOT),'timeout_seconds':TIMEOUT,'started_utc':stamp(),'status':'RUNNING',
        'stdout_log':str(outp.resolve()),'stderr_log':str(errp.resolve())};record['commands'].append(entry);save();start=time.monotonic()
 with outp.open('xb') as out,errp.open('xb') as err:
  child=subprocess.Popen(argv,cwd=ROOT,stdout=out,stderr=err,start_new_session=True);entry.update(pid=child.pid,pgid=child.pid);save()
  while child.poll() is None:
   if time.monotonic()-start>=TIMEOUT:
    entry['status']='TIMEOUT';entry['seconds']=time.monotonic()-start;save();stop(signal.SIGTERM);raise TimeoutError(name+' exceeded300s')
   time.sleep(.2)
  rc=child.returncode
 child=None;stdout=outp.read_text(errors='replace');stderr=errp.read_text(errors='replace');failure=None
 diagnostics=re.findall(r'(?im)^.*(?:%Warning|\bwarning:|%Error|\berror:).*$','\n'.join((stdout,stderr)))
 if expected_marker is None:
  known=r'.*mig_7series_v4_2_fi_xor\.v:106: warning: Anachronistic use of begin/end to surround generate schemes\.'
  if rc!=0:failure=f'{name} compile returned {rc}'
  elif len(diagnostics)!=1 or re.fullmatch(known,diagnostics[0]) is None:
   failure=f'{name} diagnostics differ from the one recorded vendor-style warning: '+repr(diagnostics)
  else:entry['recorded_vendor_warnings']=diagnostics
 else:
  if rc!=0:failure=f'{name} returned {rc}'
  lines=stdout.splitlines();passes=[x for x in lines if x.startswith('PASS fi_xor_leaf ')]
  allowed=[expected_marker]+[x for x in lines if x.startswith('$finish called at ')]
  if passes!=[expected_marker] or lines!=allowed:failure=f'{name} native output differs: '+repr(lines[:20])
  if stderr:failure=failure or f'{name} unexpected stderr: '+repr(stderr[:1000])
 entry.update(returncode=rc,seconds=time.monotonic()-start,finished_utc=stamp(),status='FAIL' if failure else 'PASS',
              stdout_sha256=sha(outp),stderr_sha256=sha(errp),diagnostics=diagnostics)
 if failure:entry['error']=failure
 entry['owned_process_group_absent']=not members(entry['pgid']);save()
 if failure:raise ValueError(failure)
 return entry

def main():
 global record
 need(not OUTPUT.exists() and not REPORT.exists(),'Fresh Icarus behavior receipt required')
 prep=json.loads(PREP.read_text());expected=prep['copied_source_hashes']['hdl/056/mig_7series_v4_2_fi_xor.v']
 need(sha(SOURCE)==sha(LOCAL)==expected,'Frozen vendor leaf source mismatch')
 need(prep['copied_file_count']==160 and prep['source_copy_manifest_sha256']=='85ed4aed6a3761b2e12f86b21bc9a5adc79e60049148ac958290bcb30650ff69','Strict source-preparation binding changed')
 cg=cgdir();limits={k:(cg/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
 need(limits=={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'},'Wrong cgroup '+repr(limits))
 iverilog=shutil.which('iverilog');vvp=shutil.which('vvp');need(iverilog and vvp,'Icarus13/VVP missing')
 ivv=version([iverilog,'-V']);vvv=version([vvp,'-V'])
 need(ivv['returncode']==vvv['returncode']==0,'Icarus version probe failed')
 need(ivv['stdout'].startswith('Icarus Verilog version 13.'),'Expected Icarus Verilog13')
 need(vvv['stderr'].startswith('Icarus Verilog runtime version 13.'),'Expected Icarus runtime13')
 OUTPUT.mkdir()
 record.update(status='RUNNING_ICARUS_BEHAVIOR_WITH_RECORDED_VENDOR_WARNING',scope='Actual FI_XOR leaf simulation only; compile warning is recorded unsuppressed; no controller/ECC decoder/memory/PHY/physical qualification.',
  started_utc=stamp(),tools={'iverilog':{'path':str(Path(iverilog).resolve()),'sha256':sha(iverilog)},'vvp':{'path':str(Path(vvp).resolve()),'sha256':sha(vvp)}},
  tool_versions={'iverilog':ivv,'vvp':vvv},cgroup=limits,source_inputs={str(SOURCE):sha(SOURCE),str(LOCAL):sha(LOCAL),str(BENCH):sha(BENCH),str(PREP):sha(PREP),str(Path(__file__).resolve()):sha(__file__)},
  source_closure_count=160,source_closure_manifest_sha256=prep['source_copy_manifest_sha256'],commands=[],hardware_accessed=False,vivado_executed=False,flash_written=False,
  warning_policy='No suppression. Icarus emitted the exact source-line106 generate-style warning; behavioral run proceeds only if compile rc0 and no other diagnostics.')
 save();img=OUTPUT/'fi.vvp'
 run('iverilog_compile',[iverilog,'-g2012','-Wall','-s',TOP,'-o',str(img),str(LOCAL),str(BENCH)])
 record['iverilog_binary_sha256']=sha(img);save()
 run('vvp_run',[vvp,str(img)],EXPECTED)
 after={p:sha(p) for p in record['source_inputs']};need(after==record['source_inputs'],'Bound source changed')
 warnings=record['commands'][0]['recorded_vendor_warnings']
 record.update(status='PASS_FI_XOR_LEAF_ICARUS_BEHAVIOR_WITH_RECORDED_VENDOR_WARNING',finished_utc=stamp(),source_inputs_after=after,all_inputs_unchanged=True,
  compile_returncode=record['commands'][0]['returncode'],compile_warning_count=len(warnings),compile_warning_free=False,
  recorded_vendor_warning=warnings[0],simulator_marker=EXPECTED,scenario_count=38,byte_lanes=9,
  physical_capacity_qualified=False,physical_ecc_injection_qualified=False,memory_or_ecc_decoder_simulated=False,phy_simulated=False)
 save()
if __name__=='__main__':
 try:main()
 except BaseException as error:
  if child is not None and child.poll() is None:stop(signal.SIGTERM)
  record.update(status='FAIL',error=repr(error),finished_utc=stamp(),physical_capacity_qualified=False,
   physical_ecc_injection_qualified=False,memory_or_ecc_decoder_simulated=False,phy_simulated=False)
  save();print(json.dumps({'status':record['status'],'error':record['error'],'report':str(REPORT)},indent=2));raise SystemExit(1)
