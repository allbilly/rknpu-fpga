#!/usr/bin/env python3
"""Root-owned authorized TinyStories full-model tests. Volatile SRAM only; no flash."""
from pathlib import Path
import datetime,fcntl,hashlib,json,os,re,signal,socket,subprocess,sys,time
ROOT=Path('/home/fedora/rknpu-fpga');HW=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from tools.host.native_link import render_bridge
from tools.tinystories.progress import require_memory,available_memory_kib
VIVADO=Path('/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/vivado_lab')
HWSERVER=VIVADO.with_name('hw_server')
TARGET='localhost:3125/xilinx_tcf/Xilinx/80802026a77a01'
LEASE=Path('/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock')
QUIESCING=False
def handle_signal(signum,frame):
 if not QUIESCING:raise InterruptedError('Hardware test interrupted by signal '+str(signum))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,handle_signal)
def stop_owned(child):
 global QUIESCING
 QUIESCING=True
 if child.poll() is None:
  try:os.killpg(child.pid,signal.SIGTERM)
  except ProcessLookupError:pass
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:
   try:os.killpg(child.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   child.wait()
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(c,m):
 if not c:raise RuntimeError(m)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def write(p,r):p.write_text(json.dumps(r,indent=2)+'\n')
def literal(s):
 s=str(s);need(not any(c in s for c in '{}\\\r\n'),'Unsafe Tcl path');return '{'+s+'}'
def run_tcl(script,trial):
 argv=[str(VIVADO),'-mode','batch','-source',str(script),'-log',str(trial/'vivado.log'),'-journal',str(trial/'vivado.jou')]
 command=dict(argv=argv,started_utc=now(),script_sha256=sha(script))
 with (trial/'stdout.log').open('w') as log:
  child=None;interrupted=None
  try:
   previous_mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
   # This runner is single threaded; restore the caller's signal mask before child exec.
   try:child=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,cwd=trial,start_new_session=True,preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK,previous_mask))
   finally:signal.pthread_sigmask(signal.SIG_SETMASK,previous_mask)
   command['pid']=child.pid;write(trial/'command.json',command)
   code=child.wait(timeout=180)
  except BaseException as error:
   interrupted=error;command['error']=str(error)
   command['timed_out']=isinstance(error,subprocess.TimeoutExpired)
   if child is not None:stop_owned(child)
   code=child.returncode if child is not None else None
 command.update(returncode=code,finished_utc=now(),status='PASS' if interrupted is None and code==0 else 'FAIL')
 write(trial/'command.json',command)
 if interrupted is not None:raise interrupted
 need(code==0,'Native hardware Tcl failed: '+str(trial))
 return command
review_path=HW/'image-review.json';review=json.loads(review_path.read_text())
need(review['status']=='PASS_REVIEWED_TINYSTORIES_FULL512_DUAL_IMAGE' and review['part']=='xc7k480tffg1156-2','Image review missing')
need(review['flash_authorized'] is False and review['programming_scope']=='volatile-sram','Wrong authorization')
bit=Path(review['bitstream']['path'])
def check_review():
 for name,digest in review['bound_files'].items():need(sha(name)==digest,'Changed reviewed input: '+name)
 need(sha(bit)==review['bitstream']['sha256'],'Changed reviewed bitstream')
 need(review['usr_access']=='1e01179c' and review['compiled_led_active_low']==0,'Wrong source image/pad encoding')
check_review()
require_memory(4096)
pressure=Path('/proc/pressure/memory').read_text()
need(any(line.startswith('full ') and float(dict(item.split('=') for item in line.split()[1:])['avg10'])<1.0 for line in pressure.splitlines()),'Host memory pressure is not stable')
run=HW/'physical-tests';run.mkdir(exist_ok=False)
record=dict(status='ADMITTED_AUTHORIZED_VOLATILE_USER2_TEST',started_utc=now(),authorization='User: u can start fpga test if needed',image_review_sha256=sha(review_path),bitstream_sha256=sha(bit),part=review['part'],target=TARGET,lease=str(LEASE),hardware_programmed=False,flash_written=False,loads=[],tests=[])
write(run/'report.json',record)
lease=LEASE.open('a+b');server=bridge=worker=None
try:
 fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB);record['lease_acquired']=True
 controllers=[]
 names={'hw_server','openocd','xsdb','openFPGALoader','fxload','xvcserver','xvc-server','xvc_server'}
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:
   comm=(proc/'comm').read_text().strip()
   if comm in names:controllers.append(dict(pid=int(proc.name),name=comm))
  except (FileNotFoundError,PermissionError,ProcessLookupError):pass
 need(not controllers,'Other hardware controller present: '+repr(controllers))
 for port in (3121,3125,3721,3741):
  with socket.socket() as sock:
   sock.settimeout(.2);need(sock.connect_ex(('127.0.0.1',port))!=0,'Hardware debug port already listening: '+str(port))
 usb=subprocess.run(['lsusb','-d','03fd:0008'],capture_output=True,text=True,timeout=10)
 need(usb.returncode==0 and len(usb.stdout.strip().splitlines())==1,'Expected one initialized DLC10')
 record['lsusb']=usb.stdout.strip()
 match=re.fullmatch(r'Bus (\d{3}) Device (\d{3}):.*',usb.stdout.strip());need(match,'Cannot identify USB node')
 node='/dev/bus/usb/'+match[1]+'/'+match[2]
 owners=subprocess.run(['fuser',node],capture_output=True,text=True,timeout=10)
 need(owners.returncode==1 and not owners.stdout.strip(),'USB cable owned or ownership check failed');record['usb_node']=node
 def start_owned(argv,log,cwd):
  previous_mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
  try:return subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,cwd=cwd,start_new_session=True,preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,previous_mask))
  finally:signal.pthread_sigmask(signal.SIG_SETMASK,previous_mask)
 with (run/'hw-server.log').open('w') as serverlog:
  server=start_owned([str(HWSERVER),'-s','tcp::3125'],serverlog,run)
  record.update(status='RUNNING_AUTHORIZED_VOLATILE_USER2_TEST',hw_server_pid=server.pid,initial_available_memory_kib=available_memory_kib(),native_tool='Vivado Lab2026.1.1');write(run/'report.json',record)
  deadline=time.monotonic()+20
  while True:
   need(server.poll() is None,'Owned hw_server exited')
   with socket.socket() as sock:
    sock.settimeout(.2);connected=sock.connect_ex(('127.0.0.1',3125))==0
   if connected:break
   need(time.monotonic()<deadline,'Owned server start timeout');time.sleep(.1)
  def program(index):
   need(sha(review_path)==record['image_review_sha256'],'Image review changed');check_review()
   trial=run/('load-'+str(index));trial.mkdir()
   text=(HW/'program-template.tcl.in').read_text()
   for marker,value in dict(TARGET=literal(TARGET),BITSTREAM=literal(bit),RECEIPT=literal(trial/'program.tsv'),USR_ACCESS=literal(review['usr_access'])).items():
    need(text.count('@'+marker+'@')==1,'Wrong program template');text=text.replace('@'+marker+'@',value)
   script=trial/'program.tcl';script.write_text(text)
   load=dict(status='STARTED',action='program-sram',started_utc=now(),hardware_programmed=False,flash_written=False,bitstream_sha256=sha(bit),image_review_sha256=sha(review_path),target=TARGET,expected_dna_port='004E544714C705C',source_sha256=review['source_sha256'],program_tcl_sha256=sha(script))
   write(trial/'load.json',load)
   try:
    record['hardware_programming_may_have_occurred']=True;write(run/'report.json',record)
    command=run_tcl(script,trial)
    pairs=[line.split('\t',1) for line in (trial/'program.tsv').read_text().splitlines()]
    need(all(len(p)==2 for p in pairs),'Bad programming receipt');actual=dict(pairs);need(len(actual)==len(pairs),'Duplicate fields')
    expected=dict(TARGET=TARGET,DNA_PORT='004E544714C705C',TCK_HZ='3000000',IDCODE_BEFORE='23751093',IDCODE_AFTER='23751093',INIT_COMPLETE='1',DONE='1',PROGRAM_RETURNED='1',PROGRAMMED='1',CLEANUP='1',PASS='1',PROGRAM_FILE=str(bit))
    need(all(actual.get(k)==v for k,v in expected.items()),'Program identity/INIT/DONE/cleanup failed: '+repr(actual))
    need(actual.get('USR_ACCESS','').lower()==review['usr_access'],'Wrong source-derived USR_ACCESS')
    load.update(status='PASS',hardware_programmed=True,finished_utc=now(),native=actual,command=command)
   except BaseException as error:
    load.update(status='FAIL',error=str(error),finished_utc=now(),hardware_programming_may_have_occurred=True);write(trial/'load.json',load);raise
   write(trial/'load.json',load);record['hardware_programmed']=True;record['loads'].append(dict(name=trial.name,status='PASS',receipt_sha256=sha(trial/'load.json')));write(run/'report.json',record)
   print(json.dumps(dict(name=trial.name,status='PASS_VOLATILE_PROGRAM')),flush=True)
  def jobs(name,mode):
   global bridge,worker
   check_review();require_memory(3072);trial=run/name;trial.mkdir()
   script=trial/'bridge.tcl';script.write_text(render_bridge(TARGET,'localhost:3125',review['usr_access'],trial/'ready.txt',3741))
   command=dict(started_utc=now(),bridge_script_sha256=sha(script),mode=mode,load_receipt_sha256=record['loads'][-1]['receipt_sha256'])
   argv=[str(VIVADO),'-mode','batch','-source',str(script),'-log',str(trial/'vivado.log'),'-journal',str(trial/'vivado.jou')];command['bridge_argv']=argv
   with (trial/'bridge-stdout.log').open('w') as bridgelog,(trial/'worker-stdout.log').open('w') as workerlog:
    bridge=start_owned(argv,bridgelog,trial);command['bridge_pid']=bridge.pid;write(trial/'command.json',command)
    deadline=time.monotonic()+90
    while not (trial/'ready.txt').exists():
     need(bridge.poll() is None,'Native bridge exited before audited READY')
     need(time.monotonic()<deadline,'Native bridge READY timeout');time.sleep(.1)
    need((trial/'ready.txt').read_text().strip()=='PASS_AUDITED_NATIVE_USER2_BRIDGE_READY','Wrong READY marker')
    argv=[sys.executable,str(ROOT/'tools/tinystories/run_model.py'),'--package',str(ROOT/'build/tinystories-preparation/260k-first-v2'),'--backend','jtag','--catalog',str(ROOT/'build/tinystories-programs/all-v1/report.json'),'--catalog-sha256',review['catalog_sha256'],'--min-mem-available-mib','2048','--memory-wait-budget-seconds','900','--steps',mode,'--prompt','' if mode=='1' else 'Once upon a time','--quit-bridge','--out',str(trial/'jobs')];command['worker_argv']=argv
    worker=start_owned(argv,workerlog,trial);command['worker_pid']=worker.pid;write(trial/'command.json',command)
    code=worker.wait(timeout=14400);command['worker_returncode']=code
    need(code==0,'Physical raw-job worker failed: '+str(trial))
    bridge_code=bridge.wait(timeout=20);command['bridge_returncode']=bridge_code
    need(bridge_code==0,'Native bridge cleanup failed')
   child_report=json.loads((trial/'jobs/report.json').read_text());need(child_report['status']=='PASS_PHYSICAL_HYBRID_MODEL_EXECUTION_REQUIRES_INDEPENDENT_AUDIT' and child_report['bridge_quit_ack'],'Physical child report failed')
   command.update(status='PASS',finished_utc=now(),worker_report_sha256=sha(trial/'jobs/report.json'));write(trial/'command.json',command)
   result=dict(name=name,status='PASS',forward_positions=child_report['result']['forward_positions'],raw_jobs=child_report['raw_jobs'],report_sha256=sha(trial/'jobs/report.json'));record['tests'].append(result);write(run/'report.json',record)
   print(json.dumps(dict(name=name,status='PASS',forward_positions=child_report['result']['forward_positions'],raw_jobs=child_report['raw_jobs'])),flush=True)
  def compare_projection_receipts(name,positions):
   actual=json.loads((run/name/'jobs/dense-calls.json').read_text())
   expected=json.loads((ROOT/'build/tinystories-full-oracle/v1/donor-dense-calls.json').read_text())[:positions*36]
   fields=('name','input_fp16_sha256','output_fp16_sha256')
   need(len(actual)==len(expected)==positions*36 and all(all(a[k]==e[k] for k in fields) for a,e in zip(actual,expected)),'Actual dense input/output bytes differ from fixed same-policy oracle')
   record[name+'_projection_receipts_matched']=len(actual);write(run/'report.json',record)
  program(1)
  jobs('one-complete-forward-position','1')
  compare_projection_receipts('one-complete-forward-position',1)
  actual=(run/'one-complete-forward-position/jobs/logits.bin').read_bytes()
  expected=(ROOT/'build/tinystories-full-oracle/v1/donor-logits.bin').read_bytes()[:512*4]
  need(len(actual)==512*4 and actual==expected,'First full hardware logit row differs from fixed CPU test oracle; do not proceed')
  record['first_forward_logits_match_donor_bit_exact']=True;write(run/'report.json',record)
  jobs('greedy32','32')
  compare_projection_receipts('greedy32',32)
  actual=(run/'greedy32/jobs/logits.bin').read_bytes()
  expected=(ROOT/'build/tinystories-full-oracle/v1/donor-logits.bin').read_bytes()
  need(len(actual)==32*512*4 and actual==expected,'Full hardware logit sequence differs from fixed CPU test oracle')
  record['all_32_forward_logits_match_donor_bit_exact']=True;write(run/'report.json',record)
  check_review();record['status']='PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT'
except BaseException as error:
 record.update(status='FAIL_USER2_PHYSICAL_TEST',error=str(error));raise
finally:
 QUIESCING=True
 for name,child in [('worker',worker),('bridge',bridge),('hw_server',server)]:
  if child is not None:
   stop_owned(child);record['owned_'+name+'_exit']=child.returncode
 record['finished_utc']=now();record['artifacts']={str(p.relative_to(run)):sha(p) for p in sorted(run.rglob('*')) if p.is_file() and p.name!='report.json'}
 write(run/'report.json',record)
 fcntl.flock(lease,fcntl.LOCK_UN);lease.close()
print(json.dumps(dict(status=record['status'],loads=len(record['loads']),flash_written=False,report=str(run/'report.json'))),flush=True)
