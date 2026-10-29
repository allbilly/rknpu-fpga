#!/usr/bin/env python3
"""Root-owned authorized volatile SRAM tests; never writes configuration flash."""
from pathlib import Path
import datetime,fcntl,hashlib,json,os,re,signal,socket,subprocess,sys,time
ROOT=Path('/home/fedora/rknpu-fpga');HW=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from tools.hardware import sample_cmac512 as observer
VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
HWSERVER=VIVADO.with_name('hw_server')
TARGET='localhost:3125/xilinx_tcf/Xilinx/80802026a77a01'
BSDL=Path('/home/fedora/vivado/2026.1/Vivado/data/parts/xilinx/kintex7/public/bsdl/xc7k480t_ffg1156.bsd')
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
need(review['status']=='PASS_REVIEWED_CMAC512_IMAGE' and review['part']=='xc7k480tffg1156-2','Image review missing')
need(review['flash_authorized'] is False and review['programming_scope']=='volatile-sram','Wrong authorization scope')
bit=Path(review['bitstream']['path']);source=Path(review['source_report']['path'])
for name,digest in review['bound_files'].items():need(sha(name)==digest,'Changed reviewed input: '+name)
need(sha(bit)==review['bitstream']['sha256'],'Changed reviewed bitstream')
need(review['usr_access']=='ac6fee7e' and type(review['compiled_led_active_low']) is int and review['compiled_led_active_low']==0,'Wrong image tag/pad encoding')
run=HW/'physical-tests';run.mkdir(exist_ok=False)
record=dict(status='ADMITTED_AUTHORIZED_VOLATILE_TEST',started_utc=now(),authorization='User: u can start fpga test if needed',image_review_sha256=sha(review_path),bitstream_sha256=sha(bit),part=review['part'],target=TARGET,lease=str(LEASE),hardware_programmed=False,flash_written=False,tests=[])
write(run/'report.json',record)
lease=LEASE.open('a+b');server=None
try:
 fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
 record['lease_acquired']=True
 # Check again under the lease, before starting our private server.
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
 need(usb.returncode==0 and len(usb.stdout.strip().splitlines())==1,'Expected one initialized DLC10 cable')
 record['lsusb']=usb.stdout.strip()
 match=re.fullmatch(r'Bus (\d{3}) Device (\d{3}):.*',usb.stdout.strip());need(match,'Cannot identify USB node')
 node='/dev/bus/usb/'+match[1]+'/'+match[2]
 owners=subprocess.run(['fuser',node],capture_output=True,text=True,timeout=10)
 need(owners.returncode==1 and not owners.stdout.strip(),'USB cable already owned or ownership check failed')
 record['usb_node']=node
 with (run/'hw-server.log').open('w') as serverlog:
  previous_mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
  try:server=subprocess.Popen([str(HWSERVER),'-s','tcp::3125'],stdout=serverlog,stderr=subprocess.STDOUT,start_new_session=True,preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK,previous_mask))
  finally:signal.pthread_sigmask(signal.SIG_SETMASK,previous_mask)
  record.update(status='RUNNING_AUTHORIZED_VOLATILE_TEST',hw_server_pid=server.pid);write(run/'report.json',record)
  deadline=time.monotonic()+20
  while True:
   need(server.poll() is None,'Owned hw_server exited')
   with socket.socket() as sock:
    sock.settimeout(.2);connected=sock.connect_ex(('127.0.0.1',3125))==0
   if connected:break
   need(time.monotonic()<deadline,'Owned hw_server start timeout');time.sleep(.1)
  def observe(name,kind,load=None):
   out=run/name
   observer.prepare(bit,source,BSDL,out,TARGET,'localhost:3125',0)
   plan=json.loads((out/'plan.json').read_text())
   need(sha(out/'capture.tcl')==plan['tcl_sha256'],'Observer changed')
   run_tcl(out/'capture.tcl',out)
   decoded=observer.decode(out/'plan.json',out/'capture.tsv',kind,load)
   write(out/'observation.json',decoded)
   result=dict(name=name,status=decoded['status'],report_sha256=sha(out/'observation.json'),heartbeat_transitions=decoded['heartbeat_transitions'])
   record['tests'].append(result);write(run/'report.json',record)
   print(json.dumps(result),flush=True)
  observe('baseline','baseline')
  for index in (1,2,3):
   need(sha(review_path)==record['image_review_sha256'],'Image review changed before load')
   for name,digest in review['bound_files'].items():need(sha(name)==digest,'Reviewed input changed before load: '+name)
   need(sha(bit)==review['bitstream']['sha256'],'Bitstream changed before load')
   trial=run/('load-'+str(index));trial.mkdir()
   template=HW/'program-template.tcl.in';text=template.read_text()
   for marker,value in dict(TARGET=literal(TARGET),BITSTREAM=literal(bit),RECEIPT=literal(trial/'program.tsv'),USR_ACCESS=literal(review['usr_access'])).items():
    need(text.count('@'+marker+'@')==1,'Wrong program template');text=text.replace('@'+marker+'@',value)
   script=trial/'program.tcl';script.write_text(text)
   load=dict(status='STARTED',action='program-sram',started_utc=now(),hardware_programmed=False,flash_written=False,bitstream_sha256=sha(bit),image_review_sha256=sha(review_path),target=TARGET,expected_dna_port='004E544714C705C',source_report_sha256=sha(source),profile=observer.PROFILE,source_sha256=observer.SOURCE_SHA,compiled_led_active_low=review['compiled_led_active_low'],program_tcl_sha256=sha(script))
   write(trial/'load.json',load)
   try:
    record['hardware_programming_may_have_occurred']=True;write(run/'report.json',record)
    command=run_tcl(script,trial)
    lines=(trial/'program.tsv').read_text().splitlines();pairs=[line.split('\t',1) for line in lines]
    need(all(len(p)==2 for p in pairs),'Bad programming receipt')
    actual=dict(pairs);need(len(actual)==len(pairs),'Duplicate programming receipt fields')
    expected=dict(TARGET=TARGET,DNA_PORT='004E544714C705C',TCK_HZ='3000000',IDCODE_BEFORE='23751093',IDCODE_AFTER='23751093',INIT_COMPLETE='1',DONE='1',PROGRAM_RETURNED='1',PROGRAMMED='1',CLEANUP='1',PASS='1',PROGRAM_FILE=str(bit))
    need(all(actual.get(k)==v for k,v in expected.items()),'Programming identity/INIT/DONE/cleanup did not pass: '+repr(actual))
    need(actual.get('USR_ACCESS','').lower()==review['usr_access'],'USR_ACCESS did not match')
    load.update(status='PASS',hardware_programmed=True,idcode='0x23751093',finished_utc=now(),native=actual,command=command)
   except BaseException as error:
    load.update(status='FAIL',error=str(error),finished_utc=now(),hardware_programming_may_have_occurred=True)
    write(trial/'load.json',load);raise
   write(trial/'load.json',load);record['hardware_programmed']=True;write(run/'report.json',record)
   print(json.dumps(dict(name=trial.name,status='PASS_VOLATILE_PROGRAM')),flush=True)
   observe('post-load-'+str(index),'post-load' if index==1 else 'reconfiguration',trial/'load.json')
   if index==1:observe('repeat-1','repeat',trial/'load.json')
  record['status']='PASS_CMAC512_PHYSICAL_STARTUP_AND_RECONFIGURATION'
except BaseException as error:
 record.update(status='FAIL_CMAC512_PHYSICAL_TEST',error=str(error));raise
finally:
 QUIESCING=True
 if server is not None:
  stop_owned(server)
  record['owned_hw_server_exit']=server.returncode
 record['finished_utc']=now()
 record['artifacts']={str(p.relative_to(run)):sha(p) for p in sorted(run.rglob('*')) if p.is_file() and p.name!='report.json'}
 write(run/'report.json',record)
 fcntl.flock(lease,fcntl.LOCK_UN);lease.close()
print(json.dumps(dict(status=record['status'],loads=3,flash_written=False,report=str(run/'report.json'))),flush=True)
