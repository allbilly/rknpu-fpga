#!/usr/bin/env python3
"""Run selected EW-bank cases on the frozen dual-namespace DDR model ELF.

Preparation only until root review authorizes execution. This worker selects
CSR_BASE=0 explicitly, consumes only copied original EW fixtures, and never
claims the 21-case union from a selected subset.
"""
from pathlib import Path
import argparse,datetime,hashlib,json,os,re,signal,subprocess,sys,time

BASE=Path(__file__).resolve().parent
PREP=BASE/'ew-matrix-preparation-v1.json'
VECTORS=BASE/'ew-vectors-v1'
ELF=Path('/home/fedora/rknpu-fpga/build/full512-ddr-preparation/shared-data-fault-model-v1/native-compile-v2/obj/Vtb_jtag_dual_ddr_async')
TIMEOUT_GRACE=10
CHILD=None

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def need(ok,msg):
 if not ok:raise ValueError(msg)
def load(path):return json.loads(Path(path).read_text())
def cgroup():
 line=next(x for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
 p=Path('/sys/fs/cgroup')/line[3:].lstrip('/')
 return {'path':str(p),'memory.max':(p/'memory.max').read_text().strip(),
         'memory.swap.max':(p/'memory.swap.max').read_text().strip(),
         'cpu.max':(p/'cpu.max').read_text().strip(),'pids.max':(p/'pids.max').read_text().strip()}
def cleanup():
 global CHILD
 if CHILD is not None and CHILD.poll() is None:
  os.killpg(CHILD.pid,signal.SIGTERM)
  try:CHILD.wait(timeout=TIMEOUT_GRACE)
  except subprocess.TimeoutExpired:os.killpg(CHILD.pid,signal.SIGKILL);CHILD.wait()
def interrupted(sig,frame):raise InterruptedError('Selected EW read-snapshot matrix interrupted '+str(sig))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)

def case_command(case,outpath):
 s=case['spec']
 return [str(ELF),'+CASE='+str(VECTORS/s['case']),'+OUTPUT='+str(outpath),
         '+START='+format(s['address'],'08x'),'+AMOUNT='+str(s['amount']),
         '+NTASKS='+str(s['tasks']),'+NLINES='+str(s['lines']),
         '+JOBS='+str(s['jobs']),'+NEGATIVE='+str(s['negative']),
         '+RESET_RECOVERY='+str(s['reset_recovery']),'+CSR_BASE=0']

def run(selected,out):
 global CHILD
 prep=load(PREP);union=load(VECTORS/'all21.json')
 need(prep['status']=='READY_FOR_ROOT_REVIEWED_EW_EXECUTION' and
      prep['execution_authorized_before_run'] is True,
      'EW matrix execution remains blocked until root review')
 need(prep['scope']=='EW_ONLY_SELECTED_CASES_NO_FULL21_CLAIM','Changed EW selection scope')
 need(prep['source_worker_sha256']==sha(Path(__file__)),'EW worker changed since preparation')
 need(prep['independent_all21_union_sha256']==sha(VECTORS/'all21.json'),'Independent all21 union changed')
 need(prep['parent_read_snapshot_build_report_sha256']==sha(VECTORS/'parent-read-snapshot-build-report.json'),'Parent native report changed')
 need(union['status']=='PASS_INDEPENDENT_SAME_ELF_ALL21_READ_SNAPSHOT_LOGICAL_UNION_ONLY' and
      union['case_count']==21 and prep['case_count']==21,
      'Independent all21 specification is not the frozen input')
 need(len(selected)>0 and len(selected)==len(set(selected)),'Select one or more unique EW cases')
 cases=prep['case_specs'];need(set(selected)<=set(cases) and len(cases)==21,'Selected case outside exact 21-case union')
 need(sha(ELF)==prep['elf_sha256']=='120a413d661c4bc03631142c3b2b70559cbdf9b2ba121b3c2ab3f5505f3af8bf','Frozen actual dual-endpoint ELF changed')
 for p,h in prep['source_input_hashes'].items():need(Path(p).is_file() and sha(p)==h,'Frozen input changed: '+p)
 for item in prep['vector_files']:
  dst=BASE/item['relative_path']
  need(dst.is_file() and sha(dst)==item['sha256'],'Frozen EW vector copy changed: '+str(dst))
 limits=cgroup();required={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'128'}
 need({k:limits[k] for k in required}==required,'Requires own4GiB/2CPU/no-swap/128task cgroup: '+repr(limits))
 affinity=sorted(os.sched_getaffinity(0))
 need(affinity==[7],'Requires the prepared single-CPU affinity [7]: '+repr(affinity))
 out=Path(out).resolve();need(out.is_relative_to(BASE/'ew-matrix-runs') and not out.exists(),'Fresh contained EW matrix output required')
 out.mkdir(parents=True)
 report={'schema':'selected-ew-read-snapshot-matrix-v1','status':'RUNNING','scope':'Selected EW namespace cases on the frozen dual-endpoint simulation ELF. CSR_BASE=0 only. Modeled PHY only; no physical DDR claim and no complete 21-case union claim.',
         'started_utc':now(),'binary_sha256':sha(ELF),
         'parent_read_snapshot_build_report_sha256':prep['parent_read_snapshot_build_report_sha256'],
         'independent_all21_union_sha256':prep['independent_all21_union_sha256'],
         'selected_cases':selected,'source_input_hashes_before':prep['source_input_hashes'],
         'cpu_affinity':affinity,
         'vector_files_before':{x['relative_path']:x['sha256'] for x in prep['vector_files']},'cgroup':limits,
         'hardware_accessed':False,'vivado_executed':False,'flash_written':False,'cpu_arithmetic_or_layout_repair':False,
         'csr_base':'0x00000000','full21_union_claim':False,'cases':[]}
 rp=out/'report.json'
 def save():rp.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 save();start=time.monotonic()
 try:
  for name in selected:
   for p,h in prep['source_input_hashes'].items():need(sha(p)==h,'Input drift before EW case: '+p)
   case=cases[name];spec=case['spec'];trial=out/name;trial.mkdir()
   observed=trial/'observed.txt';argv=case_command(case,observed)
   timeout=case['timeout_seconds']
   require_fields=('name','case','address','amount','tasks','lines','jobs','negative','reset_recovery')
   union_case=union['cases'][name]['result']
   need({k:spec[k] for k in require_fields}=={k:union_case['spec'][k] for k in require_fields},'Case specification differs from all21 union')
   need(timeout==union_case['command']['timeout_seconds'],'Case deadline differs from all21 union')
   proc_info={'status':'RUNNING','started_utc':now(),'argv':argv,'timeout_seconds':timeout}
   (trial/'command.json').write_text(json.dumps(proc_info,indent=2,sort_keys=True)+'\n');save()
   case_start=time.monotonic()
   with (trial/'stdout.log').open('x') as so,(trial/'stderr.log').open('x') as se:
    CHILD=subprocess.Popen(argv,cwd=BASE,stdout=so,stderr=se,start_new_session=True,
        env={**os.environ,'MAKEFLAGS':'','MFLAGS':''})
    proc_info['pid']=CHILD.pid;(trial/'command.json').write_text(json.dumps(proc_info,indent=2,sort_keys=True)+'\n')
    try:proc_info['returncode']=CHILD.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
     cleanup();proc_info['returncode']=124
     proc_info.update(status='TIMEOUT',finished_utc=now(),seconds=time.monotonic()-case_start,
         stdout_sha256=sha(trial/'stdout.log'),stderr_sha256=sha(trial/'stderr.log'))
     (trial/'command.json').write_text(json.dumps(proc_info,indent=2,sort_keys=True)+'\n')
     case_record={'name':name,'status':'TIMEOUT','spec':spec,'timeout_seconds':timeout,
                  'expected_marker':case['expected_ew_marker'],'command':proc_info}
     (trial/'result.json').write_text(json.dumps(case_record,indent=2,sort_keys=True)+'\n')
     report['cases'].append(case_record);save()
     raise TimeoutError('Preserved original all21 deadline expired for '+name)
   proc_info.update(status='EXITED',finished_utc=now(),seconds=time.monotonic()-case_start,
       stdout_sha256=sha(trial/'stdout.log'),stderr_sha256=sha(trial/'stderr.log'))
   (trial/'command.json').write_text(json.dumps(proc_info,indent=2,sort_keys=True)+'\n')
   log=(trial/'stdout.log').read_text(errors='replace');err=(trial/'stderr.log').read_text(errors='replace')
   need(proc_info['returncode']==0 and not err,'EW simulation command failed: '+name)
   need(not re.search(r'(?mi)^(?:FATAL:|ERROR:|FAIL|%Error)|Assertion failed|\bwarning:',log),'Unexpected EW runtime diagnostic: '+name)
   markers=[x for x in log.splitlines() if x.startswith('PASS jtag_dual_ddr_read_snapshot csr_base=')]
   need(len(markers)==1,'Expected exactly one dual-endpoint EW PASS marker: '+name)
   old=union_case['marker'];prefix='PASS jtag_ew_ddr_read_snapshot '
   need(old.startswith(prefix),'Changed original union marker prefix: '+name)
   expected_marker='PASS jtag_dual_ddr_read_snapshot csr_base=00000000 '+old[len(prefix):]
   need(case['expected_ew_marker']==expected_marker,
        'Prepared EW marker differs from exact union metrics under CSR_BASE=0: '+name)
   need(markers[0]==case['expected_ew_marker'],
        'EW marker differs from exact union metrics under CSR_BASE=0: '+name)
   if spec['negative']==10:
    need('CHECKED partial_task_fault completed=1 ui_code=5' in log,'Partial-task fault did not retain one task and E5')
   expbytes=union_case['observed_text_bytes'];expsha=union_case['observed_sha256']
   if expbytes:
    expected_file=VECTORS/spec['case']/'expected.txt'
    need(sha(expected_file)==expsha and expected_file.stat().st_size==expbytes,'Original EW expected capture disagrees with union: '+name)
    need(observed.is_file() and observed.stat().st_size==expbytes and sha(observed)==expsha and
         observed.read_bytes()==expected_file.read_bytes(),'EW full BO capture differs from original expected bytes: '+name)
   else:
    need(not observed.exists() or observed.stat().st_size==0,'Error case produced unexpected output capture: '+name)
   case_record={'name':name,'status':'PASS','spec':spec,'expected_metrics':union_case['metrics'],
       'timeout_seconds':timeout,'expected_marker':expected_marker,'observed_marker':markers[0],
       'observed_bytes':expbytes,'observed_sha256':expsha,'readback_exact':bool(expbytes)}
   (trial/'result.json').write_text(json.dumps(case_record,indent=2,sort_keys=True)+'\n')
   report['cases'].append(case_record);save();print('PASS_EW_SELECTED_CASE',name,flush=True);CHILD=None
  report['status']='PASS_SELECTED_EW_READ_SNAPSHOT_CASES_ONLY'
 except BaseException as error:
  report.update(status='FAIL_EW_SELECTED_READ_SNAPSHOT_CASES',error=repr(error))
  if CHILD is not None and CHILD.poll() is None:cleanup()
 finally:
  report['all_source_inputs_unchanged']=all(Path(p).is_file() and sha(p)==h for p,h in prep['source_input_hashes'].items())
  report['all_vector_copies_unchanged']=all(sha(VECTORS/x['relative_path'])==x['sha256'] for x in prep['vector_files'])
  if not report['all_source_inputs_unchanged'] or not report['all_vector_copies_unchanged']:
   report['status']='FAIL_EW_MATRIX_INPUT_DRIFT'
  report['finished_utc']=now();report['elapsed_seconds']=time.monotonic()-start
  report['output_hashes']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p!=rp};save()
 print(report['status'],rp,flush=True)
 return 0 if report['status']=='PASS_SELECTED_EW_READ_SNAPSHOT_CASES_ONLY' else 1

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--case',action='append',required=True,help='Repeat for an explicitly selected case from frozen all21.json')
 parser.add_argument('--out',type=Path,required=True)
 args=parser.parse_args(argv)
 return run(args.case,args.out)

if __name__=='__main__':raise SystemExit(main())
