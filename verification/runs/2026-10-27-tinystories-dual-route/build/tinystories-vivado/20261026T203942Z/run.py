from pathlib import Path
import datetime,hashlib,json,os,signal,subprocess,time
R=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent;P=R/'build/tinystories-fpga-preparation/dual-v1';V=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def need(c,m):
 if not c:raise RuntimeError(m)
d=json.loads((P/'report.json').read_text());review=json.loads((P/'root-build-review.json').read_text());need(review['status']=='PASS_ROOT_DUAL_CHECKPOINT_BUILD_REVIEW','Root build review missing')
inputs={str(P/'source'/n):h for n,h in d['source']['files'].items()}
for p in [P/'report.json',P/'root-build-review.json',P/'build.tcl',W/'launch.tcl',Path(__file__)]:inputs[str(p)]=sha(p)
need(sha(P/'build.tcl')==d['build_tcl_sha256'],'Changed prepared build script')
need(all(sha(p)==h for p,h in inputs.items()),'Changed build admission input')
need(not (P/'implementation').exists(),'Fresh native output required')
env={'RK_TINYSTORIES_PREPARED_SHA':d['source']['sha256'],'RK_CONFIRM_BOARD':'YPCB_00338_1P1','RK_CONFIG_VOLTAGE':'1.8','RK_CFGBVS':'GND','RK_LED_ACTIVE_LOW':'0','RK_EMIT_BITSTREAM':'0'}
argv=[str(V),'-mode','batch','-source',str(W/'launch.tcl'),'-log',str(W/'vivado.log'),'-journal',str(W/'vivado.jou')]
r=dict(status='RUNNING_AUTHORIZED_FULL512_DUAL_CHECKPOINT',started_utc=now(),argv=argv,environment=env,source_sha256=d['source']['sha256'],inputs=inputs,authorization='User: implement REVIEW_AND_PLAN.md, u can build vivado',scope='Fresh HDL synthesis/placement/route and strict retained512/reset/CDC/timing checkpoint gates only; no bitstream/hardware/flash',placement_seed='Vivado default,no override',hardware_accessed=False,bitstream_emitted=False,flash_written=False)
def save():(W/'report.json').write_text(json.dumps(r,indent=2)+'\n')
def interrupt(s,f):raise InterruptedError('Owned build interrupted '+str(s))
for s in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(s,interrupt)
save();child=None;start=time.monotonic()
try:
 with (W/'stdout.log').open('w') as log:
  mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
  try:child=subprocess.Popen(argv,cwd=W,env={**os.environ,**env},stdout=log,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
  finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
  r['pid']=child.pid;save();rc=child.wait(timeout=10800)
 r['returncode']=rc
 need(rc==0,'Native checkpoint flow failed')
 need('PASS_TINYSTORIES_FULL512_DUAL_ROUTED_CHECKPOINT_ONLY' in (W/'stdout.log').read_text().splitlines(),'Missing strict checkpoint completion marker')
 need(all(sha(p)==h for p,h in inputs.items()),'Pinned source/input changed during build')
 r['status']='PASS_FULL512_DUAL_ROUTED_CHECKPOINT_ONLY'
except BaseException as error:
 r.update(status='FAIL_FULL512_DUAL_CHECKPOINT',error=repr(error))
 if child is not None and child.poll() is None:
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
 r['returncode']=None if child is None else child.returncode
 raise
finally:
 r.update(seconds=time.monotonic()-start,finished_utc=now(),input_hashes_unchanged=all(sha(p)==h for p,h in inputs.items()),artifacts={str(p.relative_to(P/'implementation')):sha(p) for p in (P/'implementation').glob('*') if p.is_file()})
 if (W/'failed_stage_unqualified.dcp').exists():r['failed_debug_checkpoint_sha256']=sha(W/'failed_stage_unqualified.dcp')
 save()
print(json.dumps(dict(status=r['status'],report=str(W/'report.json'))))
