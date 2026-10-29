from pathlib import Path
import hashlib,json,os,shutil,signal,subprocess,sys,time
ROOT=Path('/home/fedora/rknpu-fpga');sys.path.insert(0,str(ROOT))
from tools.evidence import source_revision,timestamp
OUT=Path(__file__).resolve().parent;WORK=OUT/'workspace'
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,message):
 if not ok:raise ValueError(message)
need(not WORK.exists(),'Fresh workspace required')
core_source_sha=sha(ROOT/'rtl/rk_ew_core.sv');need(core_source_sha=='493195964b189d3cf829c31104d6fcb8d72d5e7dc3a8c8310d2ceb62add2e873','Unexpected rk_ew_core.sv')
before=source_revision();need(before['files'].get('rtl/rk_ew_core.sv')==core_source_sha,'Core source absent from manifest');need(before['sha256']=='2a3d4a7b195ba1995bc6bc547926cb9005b8f7d2ee6a78d9ddeb197cde869b15','Unexpected production source')
r=dict(status='RUNNING_PRIVATE_PRODUCTION_MAKE_TEST',started_utc=timestamp(),scope='Fresh complete source copy and actual serial make-test, original tests/goldens/seeds/deadlines plus11joined-DDR portable controls and55TinyStories controls including MemoryGate55 resource gates; optional observer tool source copied for provenance only and no optional-native qualification; no full joined-MC/mapped/FPGA acceptance',source_before=before,core_source_sha256=core_source_sha,optional_observer_source=dict(path='tools/tinystories/audit_model.py',source_sha256=sha(ROOT/'tools/tinystories/audit_model.py'),included_for_provenance_only=True,optional_native_qualification=False),commands=[],source_inputs={},copied_inputs={},hardware_accessed=False,bitstream_emitted=False)
def save():(OUT/'report.json').write_text(json.dumps(r,indent=2)+'\n')
def stop(sig,frame):raise InterruptedError('Private production refresh interrupted '+str(sig))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,stop)
for folder in ['rtl','fpga','model','tools','tests']:
 shutil.copytree(ROOT/folder,WORK/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copyfile(ROOT/'Makefile',WORK/'Makefile')
for folder in ['rtl','fpga','model','tools','tests']:
 for f in (WORK/folder).rglob('*'):
  if f.is_file():
   n=str(f.relative_to(WORK));r['copied_inputs'][n]=sha(f);r['source_inputs'][n]=sha(ROOT/n);need(r['copied_inputs'][n]==r['source_inputs'][n],'Source copy differs')
r['copied_inputs']['Makefile']=sha(WORK/'Makefile');r['source_inputs']['Makefile']=sha(ROOT/'Makefile')
observer=r['optional_observer_source'];need(observer['path'] in r['source_inputs'] and observer['path'] in r['copied_inputs'],'Optional observer source missing from copied inputs');need(r['source_inputs'][observer['path']]==observer['source_sha256'] and r['copied_inputs'][observer['path']]==observer['source_sha256'],'Optional observer source hash differs');observer['copy_sha256']=r['copied_inputs'][observer['path']]
r['environment_overrides']={'PYTHONPATH':str(WORK)}
child=None
try:
 for name,argv,limit in [('generated_check',['make','generated-check'],120),('production_test',['make','test'],3600)]:
  c=dict(name=name,argv=argv,cwd=str(WORK),status='RUNNING',started_utc=timestamp());r['commands'].append(c);save();start=time.monotonic()
  with (OUT/(name+'.log')).open('w') as log:
   mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
   try:child=subprocess.Popen(argv,cwd=WORK,env={**os.environ,**r['environment_overrides']},stdout=log,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
   finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
   c['pid']=child.pid;save();rc=child.wait(timeout=limit)
  c.update(returncode=rc,seconds=time.monotonic()-start,finished_utc=timestamp(),log_sha256=sha(OUT/(name+'.log')),status='PASS' if rc==0 else 'FAIL');save();need(rc==0,name+' failed')
 need(source_revision()==before,'Production source changed during test')
 need(all(sha(ROOT/n)==h for n,h in r['source_inputs'].items()),'Live copied dependency changed')
 need(all(sha(WORK/n)==h for n,h in r['copied_inputs'].items()),'Copied source changed')
 reports={}
 for n,status in {'numeric_report.json':'PASS','rtl/report.json':'PASS','iverilog/report.json':'PASS','cmac_verilator/report.json':'PASS_RAW_PRODUCT_PATH_ONLY','cmac_iverilog/report.json':'PASS_RAW_PRODUCT_PATH_ONLY'}.items():
  f=WORK/'build'/n;v=json.loads(f.read_text());need(v['status']==status and v['source_revision']==before,'Wrong source/report scope '+n)
  if n=='numeric_report.json':need(v['cases']>1000000 and v['seed']=='0x3588','Wrong numeric corpus')
  else:
   need(all(x['status']=='PASS' and x['returncode']==0 for x in v['commands']),'Failed simulator command')
   need(all(x['status']=='PASS' for x in v['tests']),'Failed simulator test')
  reports[n]=dict(sha256=sha(f),status=v['status'],tests=len(v.get('tests',[])))
 r.update(status='PASS_PRIVATE_COMPLETE_PRODUCTION_MAKE_TEST_ONLY',production_reports=reports,source_after=source_revision())
except BaseException as error:
 r.update(status='FAIL',error=str(error))
 if child is not None and child.poll() is None:
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
finally:
 r['finished_utc']=timestamp();save()
print(OUT/'report.json');sys.exit(0 if r['status'].startswith('PASS_') else 1)
