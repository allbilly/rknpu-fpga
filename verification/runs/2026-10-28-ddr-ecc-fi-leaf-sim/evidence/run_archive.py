from pathlib import Path
import datetime,hashlib,json,pathlib,subprocess,sys,time
ROOT=Path('/home/fedora/rknpu-fpga');BASE=Path(__file__).resolve().parent
PACKER=BASE/'prepare_archive.py';DEST=ROOT/'verification/runs/2026-10-28-ddr-ecc-fi-leaf-sim';REPORT=BASE/'archive-run.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
r={'status':'RUNNING','scope':'Mechanical private v1-v10 FI_XOR leaf text/source/evidence archive plus exactly reviewed V7/V10 native outputs. No tests, Vivado or hardware action.',
 'argv':[sys.executable,str(PACKER)],'cwd':str(ROOT),'started_utc':stamp(),'python_version':sys.version,
 'packer_path':str(PACKER.resolve()),'packer_sha256':sha(PACKER),'global_binding_receipt':str((BASE/'packer-global-bindings.json').resolve()),
 'global_binding_receipt_sha256':sha(BASE/'packer-global-bindings.json'),'destination':str(DEST),
 'stdout_log':str((BASE/'archive.stdout.log').resolve()),'stderr_log':str((BASE/'archive.stderr.log').resolve()),'timeout_seconds':900,
 'hardware_accessed':False,'vivado_executed':False,'flash_written':False}
def save():REPORT.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
assert not DEST.exists() and not REPORT.exists();save();start=time.monotonic()
try:
 with open(r['stdout_log'],'wb') as out,open(r['stderr_log'],'wb') as err:
  child=subprocess.Popen(r['argv'],cwd=r['cwd'],stdout=out,stderr=err,start_new_session=True);r.update(pid=child.pid,pgid=child.pid,launched_utc=stamp());save()
  try:rc=child.wait(timeout=r['timeout_seconds'])
  except subprocess.TimeoutExpired:
   import os,signal
   os.killpg(child.pid,signal.SIGTERM)
   try:child.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
   raise TimeoutError('FI leaf archive exceeded 900 seconds')
 r.update(status='PASS' if rc==0 else 'FAIL',returncode=rc,seconds=time.monotonic()-start,finished_utc=stamp())
 r['stdout_sha256']=sha(r['stdout_log']);r['stderr_sha256']=sha(r['stderr_log'])
 idx=DEST/'index.json';r['index_exists']=idx.is_file()
 if idx.is_file():r['index_sha256']=sha(idx)
except BaseException as e:r.update(status='FAIL',error=repr(e),returncode=(child.returncode if 'child' in locals() else None),seconds=time.monotonic()-start,finished_utc=stamp())
finally:save()
print(json.dumps(r,indent=2,sort_keys=True));raise SystemExit(0 if r['status']=='PASS' else 1)
