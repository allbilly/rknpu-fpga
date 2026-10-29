#!/usr/bin/env python3
from pathlib import Path
import datetime,hashlib,json,os,signal,subprocess,sys,time
ROOT=Path('/home/fedora/rknpu-fpga');OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from tools.tinystories.image_template import render
from tools.tinystories.prepare import require
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
prep=ROOT/'build/tinystories-fpga-preparation/dual-v1'
build=ROOT/'build/tinystories-vivado/20261026T203942Z'
p=json.loads((prep/'report.json').read_text());b=json.loads((build/'report.json').read_text());r=json.loads((build/'root-review.json').read_text())
require(b['status']=='PASS_FULL512_DUAL_ROUTED_CHECKPOINT_ONLY' and r['status']=='PASS_ROOT_FULL512_DUAL_ROUTED_TIMING_AND_RESET_REVIEW_ONLY','Wrong checkpoint review')
require(p['source']['sha256']==b['source_sha256']==r['source_sha256']=='1e01179cf730fdec0faa6644eae1f51dbeee4a5474f3734b327a0f8c7677b425','Source changed')
require(r['dcp_sha256']=='525f982be862136b04231b3761bede9e7ae7e3a7b1e9783e904d19fc69091f1f' and r['build_report_sha256']==sha(build/'report.json'),'Review changed')
inputs=dict(b['inputs']);inputs.update({str(prep/'implementation'/n):v for n,v in b['artifacts'].items()})
for n,entry in p['native'].items():
 q=Path(entry['path']);require(sha(q)==entry['sha256'],'Native report changed');native=json.loads(q.read_text())
 require(native['status'].startswith('PASS_') and len(native['tests'])==5 and all(x['status']=='PASS' for x in native['tests']),'Native suite incomplete')
 inputs[str(q)]=entry['sha256']
for q in (prep/'report.json',build/'report.json',build/'root-review.json',build/'rehash-before-image.json',
          ROOT/'fpga/tinystories/emit.tcl.in',ROOT/'tools/tinystories/image_template.py',
          ROOT/'tests/tinystories/test_image_template.py',ROOT/'tests/tinystories/test_fpga_checks.py',Path(__file__).resolve()):
 inputs[str(q)]=sha(q)
def check():
 for name,value in inputs.items():require(sha(name)==value,'Changed image input '+name)
check()
script=OUT/'emit.tcl';require(not script.exists(),'Fresh emission required')
script.write_text('set_param general.maxThreads 2\n'+render(prep/'implementation/routed.dcp',OUT/'emission',inputs,
 prep/'source/fpga/host/mailbox_cdc.tcl',prep/'source/fpga/tinystories/checks.tcl',p['source']['sha256'][:8]))
inputs[str(script)]=sha(script)
record=dict(status='RUNNING',source_sha256=p['source']['sha256'],inputs=inputs,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
 hardware_accessed=False,flash_written=False,scope='Exact reviewed full512+EW1MiB dual checkpoint image emission; no implementation rerun or hardware action',
 usr_access=p['source']['sha256'][:8],part=p['part'],top=p['top'])
def save():(OUT/'report.json').write_text(json.dumps(record,indent=2)+'\n')
save();start=time.monotonic()
try:
 argv=['/home/fedora/vivado/2026.1/Vivado/bin/vivado','-mode','batch','-source',str(script),'-log',str(OUT/'vivado.log'),'-journal',str(OUT/'vivado.jou')]
 record['argv']=argv;save()
 with (OUT/'stdout.log').open('x') as log:
  child=subprocess.Popen(argv,cwd=OUT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  record['pid']=child.pid;save()
  try:rc=child.wait(timeout=1800)
  except BaseException:
   if child.poll() is None:os.killpg(child.pid,signal.SIGTERM)
   try:child.wait(timeout=15)
   except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
   raise
 record['returncode']=rc;require(rc==0,'Native emission failed')
 require('PASS_SOURCE_REVIEWED_TINYSTORIES_FULL512_DUAL_BITSTREAM_EMISSION' in (OUT/'stdout.log').read_text(),'Missing native pass')
 check();bit=OUT/'emission/tinystories-full512-dual.bit'
 require(bit.is_file() and bit.stat().st_size>18000000,'Missing emitted image')
 record.update(status='PASS_EXACT_FULL512_DUAL_IMAGE_EMISSION_ONLY',bitstream=dict(path=str(bit),sha256=sha(bit),bytes=bit.stat().st_size),input_hashes_unchanged=True)
except BaseException as error:
 record.update(status='FAIL',error=repr(error));raise
finally:
 record.update(seconds=time.monotonic()-start,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  artifacts={str(q.relative_to(OUT)):sha(q) for q in OUT.rglob('*') if q.is_file() and q.name!='report.json'})
 save()
print(record['status'],OUT/'report.json',flush=True)
