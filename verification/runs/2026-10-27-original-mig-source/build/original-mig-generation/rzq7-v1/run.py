"""Root-reviewed original-profile MIG generation, source products only."""
from pathlib import Path
import datetime,hashlib,json,os,re,signal,subprocess,sys,time
R=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent;P=R/'build/original-mig-preparation/rzq7-v1';G=P/'generation'
sys.path.insert(0,str(R))
from tools.ddr.prepare_original_mig import verify
from tools.hardware.sample_ew import tcl_literal
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(c,m):
 if not c:raise ValueError(m)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def interrupted(signum,frame):raise InterruptedError('Owned IP-generation run interrupted '+str(signum))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
prepared=verify(P);need(not G.exists(),'Fresh original generation required')
controls=R/'build/original-mig-controls/v1/report.json';c=json.loads(controls.read_text())
need(c['status']=='PASS_ORIGINAL_MIG_PREPARATION_AND_MOCK_GENERATION_CONTROLS_ONLY' and len(c['controls'])==14 and c['unit_methods']==5,'Preparation controls missing')
need(c['prepared_report_sha256']==sha(P/'report.json'),'Prepared source review changed')
for n,h in c['tool_sources'].items():need(sha(R/n)==h,'Preparation tool changed')
inputs=dict(prepared['frozen_inputs'])
for p in (P/'report.json',P/'generate.tcl',controls,controls.with_name('unit.log'),Path(__file__).resolve()):inputs[str(p)]=sha(p)
launcher=W/'launch.tcl';need(not launcher.exists(),'Fresh launch required')
launcher.write_text('set_param general.maxThreads 2\nsource '+tcl_literal(P/'generate.tcl')+'\n')
inputs[str(launcher)]=sha(launcher)
def check():
 for p,h in inputs.items():need(sha(p)==h,'Changed generation input '+p)
check();record=dict(status='RUNNING',started_utc=now(),authorization='User goal: implement REVIEW_AND_PLAN.md, u can build vivado, check openTPU and ZYNQ-NVDLA if useful',scope='Standalone unchanged RZQ/7 original two-channel ECC/AXI MIG4.2 source generation only; new generated logic requires independent audit/model qualification and physical clock/electrical review',inputs=inputs,prepared_source_sha256=prepared['frozen_source_sha256'],vivado_executed=False,vendor_ip_generated=False,top_implementation_executed=False,bitstream_emitted=False,hardware_accessed=False,flash_written=False,physical_integration_ready=False)
def save():(W/'report.json').write_text(json.dumps(record,indent=2)+'\n')
save();child=None;start=time.monotonic()
try:
 argv=['/home/fedora/vivado/2026.1/Vivado/bin/vivado','-mode','batch','-source',str(launcher),'-log',str(W/'vivado.log'),'-journal',str(W/'vivado.jou')]
 record['argv']=argv;save()
 with (W/'stdout.log').open('x') as stream:
  watched={signal.SIGINT,signal.SIGTERM,signal.SIGHUP};mask=signal.pthread_sigmask(signal.SIG_BLOCK,watched)
  try:child=subprocess.Popen(argv,cwd=W,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
  finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
  record.update(pid=child.pid,vivado_executed=True);save();rc=child.wait(timeout=1200)
 record['returncode']=rc;need(rc==0,'Native original MIG generation failed')
 text=(W/'stdout.log').read_text();need(not re.search(r'^ERROR:',text,re.M),'Native generator error')
 need([s for s in text.splitlines() if s.startswith('PASS_')]==['PASS_GENERATED_ORIGINAL_MIG_SOURCES_ONLY'],'Native completion missing')
 pairs=[line.split('\t',1) for line in (G/'generation.tsv').read_text().splitlines()];actual=dict(pairs)
 need(len(pairs)==len(actual) and actual==dict(STATUS='PASS_GENERATED_ORIGINAL_MIG_SOURCES_ONLY',PART='xc7k480tffg1156-2',MODULE='top_mig_7series_0_0',TOOL_SHORT='2026.1',SOURCE_INPUTS_UNCHANGED='1',PHYSICAL_INTEGRATION_READY='0',HARDWARE_ACCESSED='0'),'Wrong native generation receipt')
 check();verify(P);need(not list(G.rglob('*.bit')),'Unexpected image product')
 record.update(status='PASS_GENERATED_ORIGINAL_MIG_SOURCES_ONLY',vendor_ip_generated=True,input_hashes_unchanged=True,native_receipt=actual,native_version=(G/'native_version.txt').read_text())
except BaseException as error:
 record.update(status='FAIL',error=repr(error))
 if child is not None and child.poll() is None:
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=15)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
 raise
finally:
 record.update(seconds=time.monotonic()-start,finished_utc=now(),artifacts={str(p.relative_to(G)):sha(p) for p in G.rglob('*') if p.is_file()} if G.exists() else {})
 save()
print(record['status'],W/'report.json',flush=True)
