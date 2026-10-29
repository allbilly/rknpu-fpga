#!/usr/bin/env python3
"""Guarded future fresh-source full512 constrained synthesis preparation."""
from pathlib import Path
import datetime,hashlib,json,os,re,signal,subprocess,sys,time

OUT=Path(__file__).resolve().parent
PREP=OUT/'preparation.json'
COPY_MANIFEST=OUT/'source-copy-manifest.json'
TCL=OUT/'synth.tcl'
VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
LIMIT=3600
CHILD=None

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def need(ok,msg):
 if not ok:raise ValueError(msg)
def cgroup():
 line=next(x for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
 base=Path('/sys/fs/cgroup')/line[3:].lstrip('/')
 return {'path':str(base),'memory.max':(base/'memory.max').read_text().strip(),'memory.swap.max':(base/'memory.swap.max').read_text().strip(),'cpu.max':(base/'cpu.max').read_text().strip(),'pids.max':(base/'pids.max').read_text().strip()}
def psi(path,key):
 line=next(x for x in Path(path).read_text().splitlines() if x.startswith(key+' '))
 return float(dict(x.split('=') for x in line.split()[1:])['avg10'])
def cleanup():
 global CHILD
 if CHILD is not None and CHILD.poll() is None:
  os.killpg(CHILD.pid,signal.SIGTERM)
  try:CHILD.wait(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(CHILD.pid,signal.SIGKILL);CHILD.wait()
def interrupted(sig,frame):raise InterruptedError('Fresh shared-data constrained synthesis interrupted '+str(sig))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
prep=json.loads(PREP.read_text())
need(prep['status']=='READY_FOR_ROOT_REVIEWED_SYNTH_ONLY','Preparation is not root-reviewed and launch-ready')
need(prep['launchable'] is True and prep['root_review_authorized_before_launch'] is True,'Root approval must be recorded before launch')
need(prep['cmac_terminal_profile']['profile']=='cmac_terminal_full8' and prep['cmac_terminal_profile']['dynamic_result_bits']==10,'Unexpected CMAC terminal profile')
need(sha(Path(__file__))==prep['run_synth_sha256'],'Future runner changed since preparation review')
need(sha(TCL)==prep['synth_tcl_sha256'],'Synthesis Tcl changed since preparation review')
need(sha(COPY_MANIFEST)==prep['source_copy_manifest_sha256'],'Source copy manifest changed')
need(not (OUT/'synthesis').exists(),'Fresh synthesis output directory required')
for f in prep['files']:
 copied=OUT/'source'/f['relative_path']
 need(sha(copied)==f['sha256'],'Prepared source copy changed: '+str(copied))
 need(sha(f['origin_path'])==f['sha256'],'Original bound source changed: '+f['origin_path'])
limits=cgroup();required={'memory.max':'12884901888','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'}
need({k:limits[k] for k in required}==required,'Future run requires exact cgroup 12GiB/no-swap/2CPU/256: '+repr(limits))
mem=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M).group(1))*1024
cpup=psi('/proc/pressure/cpu','some');memp=psi('/proc/pressure/memory','full')
need(mem>=17179869184 and cpup<5 and memp<1,'Fresh host admission failed')
out=OUT/'synthesis';out.mkdir()
version=subprocess.run([str(VIVADO),'-version'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=30,check=True).stdout
argv=[str(VIVADO),'-mode','batch','-source',str(TCL),'-log',str(out/'vivado.log'),'-journal',str(out/'vivado.jou')]
tcl_text=TCL.read_text()
need(len(re.findall(r'(?m)^\s*synth_design\b',tcl_text))==1 and len(re.findall(r'(?m)^\s*opt_design\b',tcl_text))==1,'Expected one fresh synth_design and one default opt_design')
need(not re.search(r'(?m)^\s*(place_design|phys_opt_design|route_design|write_bitstream|program_hw|open_hw)\b',tcl_text),'Unauthorized placement/route/image/hardware stage in Tcl')
need(not re.search(r'(?m)^\s*(set_false_path|set_clock_groups|set_max_delay|set_bus_skew)\b',tcl_text),'CDC exceptions must remain in the reviewed source-bound helpers')
need(not re.search(r'(?m)^\s*set_property\s+.*(waiver|severity|PACKAGE_PIN|IOSTANDARD)\b',tcl_text),'Unauthorized broad/electrical mutation')
r={'schema':'shared-data-constrained-fresh-source-synth-v4','status':'RUNNING','scope':'Fresh source full152 constrained synthesis, default opt, strict proof/resource reports and checkpoint only. No placement, route, bitstream, electrical or hardware acceptance.','started_utc':utc(),'argv':argv,'cwd':str(out),'timeout_seconds':LIMIT,'cgroup':limits,'host_admission_sample':{'memavailable_bytes':mem,'cpu_pressure_some_avg10':cpup,'memory_pressure_full_avg10':memp},'vivado_version_lines':version.splitlines()[:5],'vivado_sha256':sha(VIVADO),'synth_tcl_sha256':sha(TCL),'preparation_sha256':sha(PREP),'source_copy_manifest_sha256':sha(COPY_MANIFEST),'input_hashes_before':{f['origin_path']:sha(f['origin_path']) for f in prep['files']},'hardware_accessed':False,'bitstream_emitted':False,'place_design_executed':False,'phys_opt_design_executed':False,'route_design_executed':False}
report=out/'run.json';report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
r['copied_hashes_before']={f['relative_path']:sha(OUT/'source'/f['relative_path']) for f in prep['files']}
r['control_hashes_before']={str(x):sha(x) for x in [PREP,COPY_MANIFEST,TCL,Path(__file__).resolve()]}
report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
start=time.monotonic()
try:
 with (out/'stdout.log').open('w') as so,(out/'stderr.log').open('w') as se:
  env={**os.environ,'RK_SHARED_DATA_CONSTRAINED_ROOT_REVIEW':'APPROVED'}
  CHILD=subprocess.Popen(argv,cwd=out,env=env,stdout=so,stderr=se,start_new_session=True)
  r['vivado_pid']=CHILD.pid;report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
  try:r['returncode']=CHILD.wait(timeout=LIMIT)
  except subprocess.TimeoutExpired:r['returncode']=124;cleanup()
 stdout=(out/'stdout.log').read_text(errors='replace')
 r['completion_marker_found']='READY_SHARED_DATA_CONSTRAINED_SYNTHESIS_ONLY_ROOT_REVIEW_REQUIRED' in stdout.splitlines()
 r['input_hashes_after']={f['origin_path']:sha(f['origin_path']) for f in prep['files']};r['inputs_unchanged']=r['input_hashes_after']==r['input_hashes_before']
 r['status']='PASS_FRESH_SOURCE_CONSTRAINED_SYNTHESIS_ONLY' if r['returncode']==0 and r['completion_marker_found'] and r['inputs_unchanged'] else ('TIMEOUT' if r['returncode']==124 else 'FAIL')
except BaseException as e:r.update(status='FAIL',error=repr(e));cleanup()
finally:
 r['finished_utc']=utc();r['elapsed_seconds']=time.monotonic()-start
 try:
  r['input_hashes_after']={f['origin_path']:sha(f['origin_path']) for f in prep['files']};r['inputs_unchanged']=r['input_hashes_after']==r['input_hashes_before']
  r['copied_hashes_after']={f['relative_path']:sha(OUT/'source'/f['relative_path']) for f in prep['files']}
  r['control_hashes_after']={n:sha(n) for n in r['control_hashes_before']}
  r['copies_and_controls_unchanged']=(r['copied_hashes_after']==r['copied_hashes_before'] and r['control_hashes_after']==r['control_hashes_before'])
  if not r['inputs_unchanged'] or not r['copies_and_controls_unchanged']:r['status']='FAIL_SOURCE_COPY_OR_CONTROL_DRIFT'
 except BaseException as e:r['rehash_error']=repr(e);r['status']='FAIL_INPUT_REHASH'
 for p in out.iterdir():
  if p.is_file() and p.name!='run.json':r.setdefault('output_hashes',{})[p.name]=sha(p)
 report.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':r['status'],'report':str(report),'returncode':r.get('returncode'),'elapsed_seconds':r.get('elapsed_seconds'),'error':r.get('error')},indent=2),flush=True)
sys.exit(0 if r['status']=='PASS_FRESH_SOURCE_CONSTRAINED_SYNTHESIS_ONLY' else 1)
