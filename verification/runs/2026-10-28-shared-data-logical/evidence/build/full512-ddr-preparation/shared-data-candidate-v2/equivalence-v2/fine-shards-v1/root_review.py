"""Independently rehash outputs and reproduce the full deterministic RNG stream."""
from pathlib import Path
import datetime,hashlib,json,re
BASE=Path(__file__).resolve().parent;PARENT=BASE.parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
def step(x):
 x^=(x<<13)&0xffffffff;x^=x>>17;x^=(x<<5)&0xffffffff;return x&0xffffffff
def advance(x,n):
 for _ in range(n):x=step(x)
 return x
pattern=re.compile(r'PASS shared_cell_equivalence C=(\d+) directed=8 first=(\d+) count=(\d+) full_raw=(\d+) finite_exp=(\d+) seed=0x3588da7a rng_start=([0-9a-f]{8}) rng_end=([0-9a-f]{8}) capture0_churn=checked')
def marker(line):
 m=pattern.fullmatch(line);need(m is not None,'Different equivalence marker');C,first,count,raw,finite,start,end=m.groups();return tuple(map(int,[C,first,count,raw,finite]))+(int(start,16),int(end,16))
r=json.loads((BASE/'report.json').read_text());old=json.loads((PARENT/'reviewed-run-report-v1.json').read_text());need(r['status']=='PASS_FINE_ICARUS_SHARDS_AND_PRIOR_VERILATOR_FULL_RUN' and r['sources_unchanged'] is True,'Incomplete fine suite')
need(r['source_hashes_before']==r['source_hashes_after'],'Source drift')
for n,h in r['source_hashes_before'].items():need(sha(n)==h,'Changed actual source '+n)
coverage={32:[],64:[]};states={};totals={32:[0,0],64:[0,0]}
for C in (8,32,64):states[C]=advance(0x3588da7a,8*3*C)
initial=dict(states)
for command in r['commands']:
 need(command['returncode']==0 and not command['timed_out'] and command['seconds']<command['timeout_seconds']==300,'Failed/deadline shard')
 stdout=BASE/command['stdout_path'];stderr=BASE/command['stderr_path'];need(sha(stdout)==command['stdout_sha256'] and sha(stderr)==command['stderr_sha256'] and not stderr.read_bytes(),'Changed shard output')
 lines=[s for s in stdout.read_text().splitlines() if s.startswith('PASS shared_cell_equivalence C=')];need(len(lines)==1,'Wrong marker count');C,first,count,raw,finite,start,end=marker(lines[0])
 need(C in coverage and first==(coverage[C][-1][1] if coverage[C] else 0),'Coverage gap/overlap')
 need(command['argv'][2:]==[f'+C={C}',f'+RANDOM_FIRST={first}',f'+RANDOM_COUNT={count}'],'Different executed shard')
 need('PASS shared_cell_equivalence_all selected_C='+str(C)+' first='+str(first)+' count='+str(count)+' raw_goldens_unchanged=1 DUTs_unmodified=1' in stdout.read_text().splitlines(),'Missing full shard finish witness')
 expected_raw=sum(i%4==0 for i in range(first,first+count));need((raw,finite)==(expected_raw,count-expected_raw),'Different raw/finite classes')
 need(start==states[C],'Shard did not start from full-stream RNG prefix');states[C]=advance(states[C],6*C*count);need(end==states[C],'Wrong exact RNG end state')
 coverage[C].append([first,first+count]);totals[C][0]+=raw;totals[C][1]+=finite
for C in (32,64):need(coverage[C][-1][1]==10000 and totals[C]==[2500,7500],'Incomplete full corpus')
selected=[c for c in old['commands'] if c['name'] in ['verilator_full_run','iverilog_C8_first0_count10000']];need(len(selected)==2,'Missing prior full runs')
for command in selected:
 need(command['returncode']==0 and not command.get('timed_out',False),'Prior full run failed')
 stdout=PARENT/command['stdout_path'];stderr=PARENT/command['stderr_path'];need(sha(stdout)==command['stdout_sha256'] and sha(stderr)==command['stderr_sha256'] and not stderr.read_bytes(),'Changed prior native output')
 data=[marker(s) for s in stdout.read_text().splitlines() if s.startswith('PASS shared_cell_equivalence C=')]
 need([x[0] for x in data]==([8,32,64] if command['name']=='verilator_full_run' else [8]),'Wrong full-run C set')
 selected_C=0 if command['name']=='verilator_full_run' else 8
 need(f'PASS shared_cell_equivalence_all selected_C={selected_C} first=0 count=10000 raw_goldens_unchanged=1 DUTs_unmodified=1' in stdout.read_text().splitlines(),'Missing full-run completion witness')
 for C,first,count,raw,finite,start,end in data:
  need((first,count,raw,finite,start)==(0,10000,2500,7500,initial[C]),'Changed full-run corpus')
  actual_end=advance(start,6*C*count);need(end==actual_end,'Full-run RNG differs')
  if C==8:states[C]=actual_end
  else:need(end==states[C],'Shard/full-run boundary mismatch')
record=dict(status='PASS_ROOT_INDEPENDENT_SHARED_DATA_EQUIVALENCE_COVERAGE_RNG_AND_NATIVE_LOG_AUDIT',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),producer_sha256=sha(BASE/'report.json'),parent_full_run_report_sha256=sha(PARENT/'reviewed-run-report-v1.json'),source_inputs_rehashed=len(r['source_hashes_before']),seed='0x3588da7a',random_groups_per_C=10000,raw_groups_per_C=2500,finite_groups_per_C=7500,directed_groups_per_command=8,icarus_shards=26,coverage=coverage,rng_after_directed={str(k):f'{v:08x}' for k,v in initial.items()},rng_after_all_random={str(k):f'{v:08x}' for k,v in states.items()},runtime_caps_unchanged=True,prior_timeouts_preserved=True,scope='Sampled RTL cell equivalence with capture-low hold checks only; not exhaustive proof, full controller, physical FPGA or RK silicon differential acceptance',hardware_accessed=False)
out=BASE/'root-review.json';need(not out.exists(),'Fresh root review required');out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:v for k,v in record.items() if k!='coverage'},indent=2))
