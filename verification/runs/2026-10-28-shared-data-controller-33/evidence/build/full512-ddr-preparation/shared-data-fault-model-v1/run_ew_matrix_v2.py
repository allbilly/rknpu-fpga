#!/usr/bin/env python3
"""Run selected EW-bank cases on the frozen dual-namespace DDR model ELF.

Preparation only until root review authorizes execution. This worker selects
CSR_BASE=0 explicitly, consumes only copied original EW fixtures, and never
claims the 21-case union from a selected subset.
"""
from pathlib import Path
import argparse,datetime,hashlib,json,os,re,signal,subprocess,sys,time

BASE=Path(__file__).resolve().parent
PREP=BASE/'ew-matrix-preparation-v2.json'
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

def parse_marker_fields(line, prefix):
 need(line.startswith(prefix),'Missing exact EW marker prefix')
 fields={}
 for token in line[len(prefix):].split():
  m=re.fullmatch(r'([a-z][a-z0-9_]*)=([^\s]+)',token)
  need(m is not None,'Malformed EW marker token: '+token)
  key,value=m.groups();need(key not in fields,'Duplicate EW marker field: '+key);fields[key]=value
 return fields

def validate_marker(case, union_case, line):
 spec=case['spec'];metrics=case['expected_metrics']
 prefix='PASS jtag_dual_ddr_read_snapshot csr_base=00000000 '
 fields=parse_marker_fields(line,prefix)
 expected_keys={'jobs','negative','recovered','lines','uploaded_nonzero','rawtasks',
                'phy_user_returns','read64_packets','read64_axi_reads','scope'}
 need(set(fields)==expected_keys,'EW marker field set changed')
 old=union_case['marker'];old_prefix='PASS jtag_ew_ddr_read_snapshot '
 old_fields=parse_marker_fields(old,old_prefix)
 exact={'jobs':int(old_fields['jobs']),'negative':spec['negative'],'recovered':spec['reset_recovery'],
        'lines':spec['lines'],'uploaded_nonzero':metrics['uploaded_nonzero'],
        'rawtasks':spec['tasks'],'read64_packets':metrics['host_read64_packets'],
        'read64_axi_reads':metrics['host_read64_axi_reads'],
        'scope':'actual_AXI_UI_MC_modeled_PHY'}
 for key,value in exact.items():need(fields[key]==str(value),'EW marker '+key+' mismatch')
 try:phy_returns=int(fields['phy_user_returns'],10)
 except ValueError:raise ValueError('EW marker PHY return count is not decimal')
 if metrics['phy_user_returns'] is not None:
  need(phy_returns==metrics['phy_user_returns'],'EW successful PHY return count mismatch')
 else:
  minimum=metrics.get('phy_user_returns_minimum')
  need(isinstance(minimum,int) and phy_returns>=minimum,
       'EW fault PHY return count is below the original minimum')
 # The old namespace marker must bind to precisely the copied union contract.
 need(case['parent_marker']==old,'Prepared parent marker differs from the union')
 need(case['expected_ew_marker']==prefix+old[len(old_prefix):],
      'Prepared dual marker differs from the union suffix')
 need(case['expected_ew_marker'].startswith(prefix),'Prepared dual endpoint marker prefix changed')
 return fields

def validate_inputs(source_hashes, vector_files, base=BASE):
 for path,expected in source_hashes.items():
  need(Path(path).is_file() and sha(path)==expected,'Frozen input changed: '+path)
 for item in vector_files:
  dst=Path(base)/item['relative_path']
  need(dst.is_file() and dst.stat().st_size==item['bytes'] and sha(dst)==item['sha256'],
       'Frozen EW vector copy changed: '+str(dst))

def validate_case_binding(case, union_case):
 spec=case['spec'];union_spec=union_case['spec']
 keys=('name','case','address','amount','tasks','lines','jobs','negative','reset_recovery')
 need({k:spec[k] for k in keys}=={k:union_spec[k] for k in keys},
      'Case specification differs from all21 union')
 need(case['timeout_seconds']==union_case['command']['timeout_seconds'],
      'Case deadline differs from all21 union')
 need(case['expected_metrics']==union_case['metrics'],
      'Expected EW metrics differ from all21 union')
 need(case['observed_text_bytes']==union_case['observed_text_bytes'] and
      case['observed_sha256']==union_case['observed_sha256'],
      'Expected EW output binding differs from all21 union')

def validate_capture(case, union_case, expected_file, observed):
 expected_bytes=union_case['observed_text_bytes'];expected_sha=union_case['observed_sha256']
 if expected_bytes:
  need(expected_file is not None and Path(expected_file).is_file(),
       'Original expected EW capture is missing')
  need(Path(expected_file).stat().st_size==expected_bytes and sha(expected_file)==expected_sha,
       'Original EW expected capture disagrees with the union')
  need(Path(observed).is_file() and Path(observed).stat().st_size==expected_bytes and
       sha(observed)==expected_sha and Path(observed).read_bytes()==Path(expected_file).read_bytes(),
       'EW full BO capture differs from original expected bytes')
 else:
  need(not Path(observed).exists(),
       'Fault case unexpectedly produced an output capture')

def case_command(case,outpath):
 s=case['spec']
 return [str(ELF),'+CASE='+str(VECTORS/s['case']),'+OUTPUT='+str(outpath),
         '+START='+format(s['address'],'08x'),'+AMOUNT='+str(s['amount']),
         '+NTASKS='+str(s['tasks']),'+NLINES='+str(s['lines']),
         '+JOBS='+str(s['jobs']),'+NEGATIVE='+str(s['negative']),
         '+RESET_RECOVERY='+str(s['reset_recovery']),'+CSR_BASE=0']

def run(selected,out):
 global CHILD
 current_case=None
 prep=load(PREP);union=load(VECTORS/'all21.json')
 need(prep['status']=='READY_FOR_ROOT_REVIEWED_EW_EXECUTION' and
      prep['execution_authorized_before_run'] is True,
      'EW matrix execution remains blocked until root review')
 need(prep['scope']=='EW_ONLY_SELECTED_CASES_NO_FULL21_CLAIM','Changed EW selection scope')
 need(prep['source_worker_sha256']==sha(Path(__file__)),'EW worker changed since preparation')
 need(prep['native_compile_report_sha256']==sha(prep['native_compile_report']),
      'Native compile report changed')
 need(prep['parent_read_snapshot_build_report_sha256']==sha(prep['parent_read_snapshot_build_report']),
      'Parent native read-snapshot report changed')
 need(prep['independent_all21_union_sha256']==sha(VECTORS/'all21.json'),'Independent all21 union changed')
 need(prep['parent_read_snapshot_build_report_sha256']==sha(VECTORS/'parent-read-snapshot-build-report.json'),
      'Copied parent native report changed')
 need(union['status']=='PASS_INDEPENDENT_SAME_ELF_ALL21_READ_SNAPSHOT_LOGICAL_UNION_ONLY' and
      union['case_count']==21 and prep['case_count']==21,
      'Independent all21 specification is not the frozen input')
 need(len(selected)>0 and len(selected)==len(set(selected)),'Select one or more unique EW cases')
 cases=prep['case_specs'];need(set(selected)<=set(cases) and len(cases)==21,'Selected case outside exact 21-case union')
 need(sha(ELF)==prep['elf_sha256']=='120a413d661c4bc03631142c3b2b70559cbdf9b2ba121b3c2ab3f5505f3af8bf','Frozen actual dual-endpoint ELF changed')
 validate_inputs(prep['source_input_hashes'],prep['vector_files'])
 limits=cgroup();required={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'128'}
 need({k:limits[k] for k in required}==required,'Requires own4GiB/2CPU/no-swap/128task cgroup: '+repr(limits))
 affinity=sorted(os.sched_getaffinity(0))
 out=Path(out).resolve();need(out.is_relative_to(BASE/'ew-matrix-runs') and not out.exists(),'Fresh contained EW matrix output required')
 out.mkdir(parents=True)
 report={'schema':'selected-ew-read-snapshot-matrix-v2','status':'RUNNING','scope':'Selected EW namespace cases on the frozen dual-endpoint simulation ELF. CSR_BASE=0 only. Modeled PHY only; no physical DDR claim and no complete 21-case union claim.',
         'started_utc':now(),'binary_sha256':sha(ELF),
         'native_compile_report_sha256':prep['native_compile_report_sha256'],
         'parent_read_snapshot_build_report_sha256':prep['parent_read_snapshot_build_report_sha256'],
         'independent_all21_union_sha256':prep['independent_all21_union_sha256'],
         'selected_cases':selected,'source_input_hashes_before':prep['source_input_hashes'],
         'cpu_affinity_at_launch':affinity,
         'vector_files_before':{x['relative_path']:x['sha256'] for x in prep['vector_files']},'cgroup':limits,
         'hardware_accessed':False,'vivado_executed':False,'flash_written':False,'cpu_arithmetic_or_layout_repair':False,
         'csr_base':'0x00000000','full21_union_claim':False,'cases':[]}
 rp=out/'report.json'
 def save():rp.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
 save();start=time.monotonic()
 try:
  for name in selected:
   validate_inputs(prep['source_input_hashes'],prep['vector_files'])
   case=cases[name];spec=case['spec'];trial=out/name;trial.mkdir()
   observed=trial/'observed.txt';argv=case_command(case,observed)
   timeout=case['timeout_seconds']
   union_case=union['cases'][name]['result']
   validate_case_binding(case,union_case)
   proc_info={'status':'RUNNING','started_utc':now(),'argv':argv,'timeout_seconds':timeout}
   case_record={'name':name,'status':'RUNNING','spec':spec,'timeout_seconds':timeout,
                'expected_marker':case['expected_ew_marker'],'command':proc_info}
   current_case=case_record
   report['cases'].append(case_record)
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
     case_record.update(status='TIMEOUT',error='Original union case deadline expired')
     (trial/'result.json').write_text(json.dumps(case_record,indent=2,sort_keys=True)+'\n');save()
     raise TimeoutError('Preserved original all21 deadline expired for '+name)
   proc_info.update(status='EXITED',finished_utc=now(),seconds=time.monotonic()-case_start,
       stdout_sha256=sha(trial/'stdout.log'),stderr_sha256=sha(trial/'stderr.log'))
   (trial/'command.json').write_text(json.dumps(proc_info,indent=2,sort_keys=True)+'\n')
   log=(trial/'stdout.log').read_text(errors='replace');err=(trial/'stderr.log').read_text(errors='replace')
   need(proc_info['returncode']==0 and not err,'EW simulation command failed: '+name)
   need(not re.search(r'(?mi)^(?:FATAL:|ERROR:|FAIL|%Error)|Assertion failed|\bwarning:',log),'Unexpected EW runtime diagnostic: '+name)
   pass_lines=[x for x in log.splitlines() if x.startswith('PASS ')]
   need(len(pass_lines)==1,'Expected exactly one PASS line in EW simulation output: '+name)
   marker_fields=validate_marker(case,union_case,pass_lines[0])
   if spec['negative']==10:
    need('CHECKED partial_task_fault completed=1 ui_code=5' in log,'Partial-task fault did not retain one task and E5')
   expbytes=union_case['observed_text_bytes'];expsha=union_case['observed_sha256']
   expected_file=VECTORS/spec['case']/'expected.txt' if expbytes else None
   validate_capture(case,union_case,expected_file,observed)
   case_record.update({'status':'PASS','expected_metrics':union_case['metrics'],
       'timeout_seconds':timeout,'expected_marker':case['expected_ew_marker'],'observed_marker':pass_lines[0],
       'observed_marker_fields':marker_fields,
       'observed_bytes':expbytes,'observed_sha256':expsha,'readback_exact':bool(expbytes)})
   (trial/'result.json').write_text(json.dumps(case_record,indent=2,sort_keys=True)+'\n')
   save();print('PASS_EW_SELECTED_CASE',name,flush=True);CHILD=None;current_case=None
  report['status']='PASS_SELECTED_EW_READ_SNAPSHOT_CASES_ONLY'
 except BaseException as error:
  if current_case is not None and current_case.get('status')=='RUNNING':
   current_case.update(status='FAIL_POSTCHECK_OR_LAUNCH',error=repr(error))
   cmd=current_case.get('command',{})
   if cmd.get('returncode') is not None:current_case['native_returncode']=cmd['returncode']
   result=out/current_case['name']/'result.json'
   result.write_text(json.dumps(current_case,indent=2,sort_keys=True)+'\n')
  report.update(status='FAIL_EW_SELECTED_READ_SNAPSHOT_CASES',error=repr(error))
  save()
  if CHILD is not None and CHILD.poll() is None:cleanup()
 finally:
  try:report['all_source_inputs_unchanged']=all(Path(p).is_file() and sha(p)==h for p,h in prep['source_input_hashes'].items())
  except OSError:report['all_source_inputs_unchanged']=False
  try:report['all_vector_copies_unchanged']=all(sha(BASE/x['relative_path'])==x['sha256'] for x in prep['vector_files'])
  except OSError:report['all_vector_copies_unchanged']=False
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
