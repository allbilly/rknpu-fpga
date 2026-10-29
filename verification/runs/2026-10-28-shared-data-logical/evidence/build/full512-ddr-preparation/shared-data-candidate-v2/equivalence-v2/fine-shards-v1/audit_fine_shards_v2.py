#!/usr/bin/env python3
"""Independent efficient audit of the V2 full and sharded equivalence receipts."""
import datetime,hashlib,json,pathlib
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');EQ=ROOT/'build/full512-ddr-preparation/shared-data-candidate-v2/equivalence-v2';OUT=EQ/'fine-shards-v1'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def load(p):return json.loads(p.read_text())
def markers(p):return [x.strip() for x in p.read_text(errors='replace').splitlines() if x.startswith('PASS shared_cell_equivalence')]
def fields(line):
 d={}
 for tok in line.split():
  if '=' in tok:
   k,v=tok.split('=',1);d[k]=v
 return d
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
def xs(x):
 x^=(x<<13)&0xffffffff;x&=0xffffffff
 x^=x>>17;x&=0xffffffff
 x^=(x<<5)&0xffffffff;x&=0xffffffff
 return x
def boundaries(start,c):
 # One linear scan of the fixed V2 xorshift stream, six draws per frame/lane.
 result=[start];x=start
 for frame in range(10000):
  for _ in range(6*c):x=xs(x)
  result.append(x)
 return result

report=load(OUT/'report.json');baseline=load(EQ/'reviewed-run-report-v1.json')
need(report['status']=='PASS_FINE_ICARUS_SHARDS_AND_PRIOR_VERILATOR_FULL_RUN','fine shard runner status not PASS')
need(report['sources_unchanged'] and len(report['commands'])==26,'fine shard runner sources or command count changed')
need(baseline['status']=='FAIL_ICARUS_SHARD' and baseline['stopped_at']=='iverilog_C32_first0_count5000','historical aggregate C32 timeout was changed')
byname={x['name']:x for x in report['commands']}
baseline_byname={x['name']:x for x in baseline['commands']}
need(len(byname)==26,'duplicate/missing shard command rows')
# Verify the preexisting C8 Icarus 10k pass and full Verilator 10k outputs.
c8=baseline_byname.get('iverilog_C8_first0_count10000');need(c8 is not None,'C8 run absent from preserved baseline receipt')
need(c8['returncode']==0 and not c8['timed_out'] and c8['timeout_seconds']==300,'C8 prior run not a full pass')
c8log=EQ/c8['stdout_path'];line8=next((x for x in markers(c8log) if x.startswith('PASS shared_cell_equivalence C=8 ')),None)
need(line8 is not None,'C8 marker absent');f8=fields(line8)
need((int(f8['first']),int(f8['count']),int(f8['directed']),int(f8['full_raw']),int(f8['finite_exp']),f8['seed'])==(0,10000,8,2500,7500,'0x3588da7a'),'C8 pass metrics mismatch')
vltlog=EQ/'verilator_full_run.stdout.log';vltlines=markers(vltlog);vlt={}
for c in (8,32,64):
 line=next((x for x in vltlines if x.startswith(f'PASS shared_cell_equivalence C={c} ')),None)
 need(line is not None,f'full VLT C{c} marker absent');f=fields(line)
 need((int(f['first']),int(f['count']),int(f['directed']),int(f['full_raw']),int(f['finite_exp']),f['seed'])==(0,10000,8,2500,7500,'0x3588da7a'),f'full VLT metrics differ C{c}')
 vlt[c]=f
need('PASS shared_cell_equivalence_all selected_C=0 first=0 count=10000 raw_goldens_unchanged=1 DUTs_unmodified=1' in vltlines,'full VLT terminal marker absent')
# Derive exact prefix/suffix RNG states in one bounded pass per C.
state={c:boundaries(int(vlt[c]['rng_start'],16),c) for c in (8,32,64)}
need(all(state[c][10000]==int(vlt[c]['rng_end'],16) for c in (8,32,64)),'full VLT RNG end does not match fixed draw contract')
plan={32:[(i*1000,1000) for i in range(10)],64:[(i*625,625) for i in range(16)]}
results={}
for c,ranges in plan.items():
 completed=[];records=[]
 for first,count in ranges:
  name=f'iverilog_C{c}_first{first}_count{count}';r=byname[name]
  need(r['returncode']==0 and not r['timed_out'] and r['timeout_seconds']==300,f'{name} did not finish under cap')
  out=OUT/r['stdout_path'];err=OUT/r['stderr_path'];need(err.stat().st_size==0,f'{name} stderr is nonempty')
  line=next((x for x in markers(out) if x.startswith(f'PASS shared_cell_equivalence C={c} ')),None)
  need(line is not None,f'{name} pass marker is missing');f=fields(line)
  raw=sum(1 for k in range(first,first+count) if k%4==0)
  need((int(f['first']),int(f['count']),int(f['directed']),int(f['full_raw']),int(f['finite_exp']),f['seed'])==(first,count,8,raw,count-raw,'0x3588da7a'),f'{name} frame/class counts differ')
  need(int(f['rng_start'],16)==state[c][first] and int(f['rng_end'],16)==state[c][first+count],f'{name} stream boundary mismatch')
  completed.append((first,first+count));records.append({'name':name,'frames':count,'raw':raw,'finite':count-raw,
   'rng_start':f['rng_start'],'rng_end':f['rng_end'],'runtime_seconds':r['seconds'],
   'stdout_sha256':sha(out),'stderr_sha256':sha(err)})
 need(completed[0][0]==0 and completed[-1][1]==10000 and all(completed[i][1]==completed[i+1][0] for i in range(len(completed)-1)),f'C{c} ranges not a disjoint complete union')
 need(sum(x['raw'] for x in records)==2500 and sum(x['finite'] for x in records)==7500,f'C{c} aggregate class count differs')
 results[str(c)]={'coverage':[list(x) for x in completed],'frames':10000,'raw':2500,'finite':7500,'shards':records,
                  'rng_start_full':f"{state[c][0]:08x}",'rng_end_full':f"{state[c][10000]:08x}"}
# Hash every v2 runner-declared input again after simulator work.
for path,h in report['source_hashes_before'].items():
 p=pathlib.Path(path);need(p.is_file() and sha(p)==h,f'source drift or missing file after run: {path}')
need(report['source_hashes_before']==report['source_hashes_after'],'runner source maps changed during sim runs')
result={'status':'PASS_INDEPENDENT_FINE_SHARD_COVERAGE_RNG_AND_LOG_AUDIT',
 'scope':'Read-only postprocessing of the reviewed V2 simulator receipts; one fixed seed, all per-command output markers, disjoint frame unions and RNG stream boundaries verified. No simulation or hardware command executed.',
 'runner_report_sha256':sha(OUT/'report.json'),'baseline_timeout_report_sha256':sha(EQ/'reviewed-run-report-v1.json'),
 'c32_first_half_timeout_receipt_sha256':sha(EQ/'c32-first-half-boundary-stop-v1.json'),
 'source_hashes_verified':len(report['source_hashes_before']),'same_v2_vvp_sha256':sha(EQ/'sim_iverilog_reviewed.vvp'),
 'c8_prior_icarus':{'first':0,'count':10000,'raw':2500,'finite':7500,'marker':line8,'stdout_sha256':sha(c8log),
                     'runtime_seconds':c8['seconds']},
 'full_verilator':{str(c):{'first':0,'count':10000,'raw':2500,'finite':7500,'rng_start':vlt[c]['rng_start'],
                           'rng_end':vlt[c]['rng_end']} for c in (8,32,64)},
 'fine_icarus_shards':results,'completed_fine_shards':sum(len(x['shards']) for x in results.values()),
 'seed':'0x3588da7a','directed_cases_each_run':8,'hardware_accessed':False,
 'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(OUT/'independent-audit-v2.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':result['status'],'completed_fine_shards':result['completed_fine_shards'],
 'C32':{'frames':results['32']['frames'],'raw':results['32']['raw'],'finite':results['32']['finite']},
 'C64':{'frames':results['64']['frames'],'raw':results['64']['raw'],'finite':results['64']['finite']},
 'report_path':str(OUT/'independent-audit-v2.json'),'sha256':sha(OUT/'independent-audit-v2.json')},indent=2))
