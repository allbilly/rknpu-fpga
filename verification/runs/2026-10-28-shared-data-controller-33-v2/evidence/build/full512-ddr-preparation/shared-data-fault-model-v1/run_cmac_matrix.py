"""Execute explicit full512 controller workload/fault cases on one frozen ELF.

Raw K65 bytes and all SV errors/watchdogs remain unchanged. These prospective
combined-design wall deadlines do not alter earlier EW-only run contracts.
"""
from pathlib import Path
import argparse,datetime,hashlib,json,os,re,signal,subprocess,time
BASE=Path(__file__).resolve().parent
SPECS={
 'numerical_k65':(0,1,0,1800), 'repeat_k65':(0,2,0,3600),
 'unknown_command':(1,1,0,1800), 'rmw_ue':(2,1,0,1800),
 'dropped_return':(3,1,0,1800), 'phy_write_stall':(4,1,0,1800),
 'calibration_loss':(5,1,0,1800), 'queued_calibration_loss':(6,2,0,3600),
 'ctrl_timeout':(7,1,0,1800), 'late_pending_fault':(8,1,0,1800),
 'host_memory_timeout':(9,1,0,1800), 'joint_reset_recovery':(2,1,1,3600)}
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cases',nargs='+',choices=SPECS,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
need(len(args.cases)==len(set(args.cases)),'Duplicate selected case')
prep_path=BASE/'preparation.json';compile_path=BASE/'native-compile-v2/report.json';prep=json.loads(prep_path.read_text());compiled=json.loads(compile_path.read_text())
need(compiled['status']=='PASS_JOINED_MODEL_NATIVE_COMPILE_ONLY' and all(c['returncode']==0 for c in compiled['commands']),'Unqualified actual joined compiler')
binary=Path(compiled['binary_path']);need(sha(binary)==compiled['binary_sha256']=='120a413d661c4bc03631142c3b2b70559cbdf9b2ba121b3c2ab3f5505f3af8bf','Changed admitted combined ELF')
case=prep['cmac_case'];fixture=Path(case['case_dir']);need((case['address'],case['amount'],case['tasks'],case['lines'],case['csr_base'])==(0x100e0000,45,1,320,256),'Changed K65 contract')
inputs=dict(prep['inputs'])|dict(prep['files'])|dict(compiled['source_hashes_before'])
for p in [prep_path,compile_path,Path(__file__).resolve(),binary,*sorted(fixture.iterdir())]:
 if p.is_file():inputs[str(p)]=sha(p)
need(all(sha(n)==h for n,h in inputs.items()),'Changed matrix source/fixture')
need(len((fixture/'upload.txt').read_text().splitlines())==320 and sum(int(x.split()[1],16)!=0 for x in (fixture/'upload.txt').read_text().splitlines())==173,'Changed original full raw BO inventory')
cg=Path('/sys/fs/cgroup')/next(x[3:].strip().lstrip('/') for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
limits={n:(cg/n).read_text().strip() for n in ['memory.max','memory.swap.max','cpu.max','pids.max']};need(limits=={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'128'},'Require4GiB/2CPU/no-swap/128task scope')
out=args.out.resolve();need(out.is_relative_to(BASE) and not out.exists(),'Fresh contained matrix output required');out.mkdir();report=out/'report.json'
r=dict(status='RUNNING_PRIVATE_FULL512_CMAC_CONTROLLER_MATRIX',started_utc=now(),scope='Actual raw CMAC/EW endpoint plus AXI/UI/MC; encoded PHY and calibration remain modeled. No physical DDR, image or hardware qualification.',binary_sha256=sha(binary),kernel_limits=limits,source_inputs=inputs,selected=args.cases,prospective_specs={n:dict(negative=SPECS[n][0],jobs=SPECS[n][1],reset_recovery=SPECS[n][2],timeout_seconds=SPECS[n][3]) for n in args.cases},cases=[],hardware_accessed=False,cpu_arithmetic_or_layout_repair=False,sv_bench_and_error_expectations_unchanged=True)
child=None

def save():report.write_text(json.dumps(r,indent=2)+'\n')
def interrupted(sig,frame):raise InterruptedError('Owned matrix interrupted '+str(sig))
for sig in [signal.SIGINT,signal.SIGTERM,signal.SIGHUP]:signal.signal(sig,interrupted)
try:
 save()
 for name in args.cases:
  need(all(sha(n)==h for n,h in inputs.items()),'Input drift before case')
  negative,jobs,recovery,deadline=SPECS[name];folder=out/name;folder.mkdir();actual=folder/'actual-bo.txt'
  argv=[str(binary),'+CASE='+str(fixture),'+OUTPUT='+str(actual),'+START=100e0000','+AMOUNT=45','+NTASKS=1','+NLINES=320','+JOBS='+str(jobs),'+NEGATIVE='+str(negative),'+RESET_RECOVERY='+str(recovery),'+CSR_BASE=100']
  item=dict(name=name,status='RUNNING',started_utc=now(),argv=argv,timeout_seconds=deadline);r['cases'].append(item);save();start=time.monotonic()
  with (folder/'stdout.log').open('x') as stdout,(folder/'stderr.log').open('x') as stderr:
   child=subprocess.Popen(argv,cwd=BASE,stdout=stdout,stderr=stderr,start_new_session=True);item['pid']=child.pid;save();item['returncode']=child.wait(timeout=deadline)
  item['seconds']=time.monotonic()-start
  text=(folder/'stdout.log').read_text();need(item['returncode']==0 and not (folder/'stderr.log').read_bytes(),'Native matrix failed: '+name)
  need(not re.search(r'(?mi)^(?:FATAL:|ERROR:|FAIL|%Error)|Assertion failed|\bwarning:',text),'Unadmitted native runtime diagnostic')
  markers=[x for x in text.splitlines() if x.startswith('PASS ')];need(len(markers)==1,'Missing/extra matrix result')
  match=re.fullmatch(r'PASS jtag_dual_ddr_read_snapshot csr_base=00000100 jobs=(\d+) negative=(\d+) recovered=(\d+) lines=320 uploaded_nonzero=(\d+) rawtasks=1 phy_user_returns=(\d+) read64_packets=(\d+) read64_axi_reads=(\d+) scope=actual_AXI_UI_MC_modeled_PHY',markers[0]);need(match is not None,'Changed actual controller completion contract')
  submitted,mode,recovered,nonzero,returns,packets,reads=map(int,match.groups())
  need((submitted,mode,recovered,nonzero)==(0 if negative==9 else jobs+recovery,negative,recovery,0 if negative==9 else 173),'Wrong controller matrix workload inventory')
  need(packets==reads and returns>0,'Wrong snapshot/PHY observations')
  successful=negative==0 or negative==6 or recovery==1
  if successful:
   need(actual.is_file() and actual.read_bytes()==(fixture/'expected.txt').read_bytes() and len(actual.read_text().splitlines())==320,'Incomplete/different actual raw BO')
   item.update(actual_bo_sha256=sha(actual),complete_raw_bo_bytes=20480)
  else:need(not actual.exists(),'Faulted work must not produce a successful BO capture')
  item.update(status='PASS',marker=markers[0],finished_utc=now(),phy_returns=returns,read64_packets=packets)
  save();print('PASS_CONTROLLER_CASE',name,round(item['seconds'],3),flush=True);child=None
 r['status']='PASS_SELECTED_SHARED_DATA_CMAC_CONTROLLER_CASES_ONLY'
except BaseException as error:
 r.update(status='FAIL_SHARED_DATA_CMAC_CONTROLLER_MATRIX',error=repr(error))
 if r['cases'] and r['cases'][-1]['status']=='RUNNING':r['cases'][-1]['status']='FAIL'
finally:
 if child is not None and child.poll() is None:
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
 r['all_inputs_unchanged']=all(sha(n)==h for n,h in inputs.items())
 if not r['all_inputs_unchanged']:r['status']='FAIL_MATRIX_INPUT_DRIFT'
 r['output_hashes']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p!=report};r['finished_utc']=now();save()
print(r['status'],report,flush=True)
raise SystemExit(0 if r['status'].startswith('PASS_') else 1)
