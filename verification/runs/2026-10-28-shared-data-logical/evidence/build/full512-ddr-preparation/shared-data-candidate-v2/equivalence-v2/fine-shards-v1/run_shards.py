#!/usr/bin/env python3
"""Fine-grained, source-bound Icarus completion for reviewed shared-cell V2."""
from __future__ import annotations
import datetime,hashlib,json,os,pathlib,signal,subprocess,sys,time
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');CAND=ROOT/'build/full512-ddr-preparation/shared-data-candidate-v2'
EQ=CAND/'equivalence-v2';OUT=EQ/'fine-shards-v1';PREP=CAND/'preparation.json';DUAL=ROOT/'build/tinystories-fpga-preparation/dual-v1'
WARN_REVIEW=EQ/'root-warning-review-v1.json';STRICT=EQ/'report.json';BASELINE=EQ/'reviewed-run-report-v1.json'
TB=EQ/'tb_shared_cell_equivalence.sv';CHECKER=EQ/'shared_cell_checker.sv';REF=EQ/'ref_cell.sv'
VLT_LOG=EQ/'verilator_full_run.stdout.log';IV_C8_LOG=EQ/'iverilog_C8_first0_count10000.stdout.log'
IVBIN=EQ/'sim_iverilog_reviewed.vvp';VLTBIN=EQ/'verilator_obj_reviewed/Vtb_shared_cell_equivalence';BLOCK=1024*1024

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):
 h=hashlib.sha256()
 with pathlib.Path(p).open('rb') as f:
  for b in iter(lambda:f.read(BLOCK),b''):h.update(b)
 return h.hexdigest()
def load(p):return json.loads(pathlib.Path(p).read_text())
def cgroup():
 x={'proc_cgroup':pathlib.Path('/proc/self/cgroup').read_text()}
 for n in ('memory.max','memory.swap.max','cpu.max','pids.max'):
  p=pathlib.Path('/sys/fs/cgroup')/n
  if p.exists():x[n]=p.read_text().strip()
 return x
def kill_group(p):
 try:os.killpg(p.pid,signal.SIGTERM)
 except ProcessLookupError:return
 try:p.wait(timeout=5)
 except subprocess.TimeoutExpired:
  try:os.killpg(p.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  p.wait()
def emit(obj):
 line=json.dumps(obj,sort_keys=True)
 with (OUT/'progress.jsonl').open('a') as f:f.write(line+'\n');f.flush()
 print(line,flush=True)
def run_stream(name,argv,timeout):
 out=OUT/f'{name}.stdout.log';err=OUT/f'{name}.stderr.log';start=utc();t=time.monotonic()
 with out.open('wb') as fo,err.open('wb') as fe:
  p=subprocess.Popen(argv,cwd=ROOT,stdout=fo,stderr=fe,start_new_session=True)
  try:p.wait(timeout=timeout);timed=False
  except subprocess.TimeoutExpired:kill_group(p);timed=True
 rec={'name':name,'argv':argv,'cwd':str(ROOT),'started_utc':start,'finished_utc':utc(),'seconds':time.monotonic()-t,
 'timeout_seconds':timeout,'timed_out':timed,'returncode':p.returncode,'stdout_path':out.name,'stderr_path':err.name,
 'stdout_sha256':sha(out),'stderr_sha256':sha(err),'stdout_bytes':out.stat().st_size,'stderr_bytes':err.stat().st_size,
 'owned_pid':p.pid,'process_group':p.pid}
 emit({'event':'command_complete','name':name,'returncode':p.returncode,'timed_out':timed,'seconds':rec['seconds'],'stdout_bytes':rec['stdout_bytes']})
 return rec
def markers(path):return [s.strip() for s in path.read_text(errors='replace').splitlines() if s.startswith('PASS shared_cell_equivalence')]
def fields_for(lines,c,first):
 for line in lines:
  if not line.startswith('PASS shared_cell_equivalence C='):continue
  f={}
  for tok in line.split():
   if '=' in tok:
    k,v=tok.split('=',1);f[k]=v
  if int(f.get('C',-1))==c and int(f.get('first',-1))==first:return line,f
 return None,None
def xs(x):
 x^=(x<<13)&0xffffffff;x&=0xffffffff
 x^=x>>17;x&=0xffffffff
 x^=(x<<5)&0xffffffff;x&=0xffffffff
 return x
def advance(x,n):
 for _ in range(n):x=xs(x)
 return x

prep=load(PREP);warn=load(WARN_REVIEW);strict=load(STRICT);baseline=load(BASELINE)
need=lambda ok,msg: (_ for _ in ()).throw(RuntimeError(msg)) if not ok else None
need(warn['status']=='REVIEWED_SIX_SPECIFIC_SHARED_CELL_EQUIVALENCE_WARNINGS' and warn['compile_with_Wno_fatal_permitted'] and not warn['warning_kind_suppressions_permitted'],'root warning review changed')
need(strict['status']=='FAIL_STRICT_VERILATOR_COMPILE' and strict['warning_count']==6,'strict warning failure was overwritten')
need(baseline['status']=='FAIL_ICARUS_SHARD' and baseline['stopped_at']=='iverilog_C32_first0_count5000','original C32 5000-frame timeout not preserved')
need(baseline['commands'][3]['name']=='iverilog_C8_first0_count10000' and baseline['commands'][3]['returncode']==0 and not baseline['commands'][3]['timed_out'],'C8 baseline is not complete PASS')
need(IVBIN.is_file() and VLTBIN.is_file(),'same reviewed binary pair is missing')
source_inputs={str(p):sha(p) for p in (PREP,WARN_REVIEW,STRICT,BASELINE,TB,CHECKER,REF,
 VLT_LOG,IV_C8_LOG,IVBIN,VLTBIN,DUAL/'report.json',pathlib.Path(__file__).resolve())}
for m in (prep['inputs'],prep['files']):
 for path,h in m.items():
  p=pathlib.Path(path);need(p.is_file() and sha(p)==h,f'V2 input changed: {p}');source_inputs[str(p)]=h
for rel in ('rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv','rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv',
 'rtl/cmac/experimental/rk_cmac_fp16_rows.sv','rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v','rtl/vendor/nvdla/NV_DW02_tree.v'):
 p=DUAL/'source'/rel;h=load(DUAL/'report.json')['source']['files'][rel];need(p.is_file() and sha(p)==h,f'donor dependency changed: {p}');source_inputs[str(p)]=h
before={p:sha(pathlib.Path(p)) for p in sorted(source_inputs)}
need(all(before[p]==h for p,h in source_inputs.items()),'input hash mismatch at shard start')
# Re-use the exact V2 VVP and previously completed C8 / full Verilator checks.
vlt_lines=markers(VLT_LOG);iv8_lines=markers(IV_C8_LOG)
vlt_fields={};
for c in (8,32,64):
 line,f=fields_for(vlt_lines,c,0);need(f is not None and int(f['count'])==10000 and int(f['full_raw'])==2500,'full Verilator marker missing expected frame counts')
 need(int(f['finite_exp'])==7500 and f['seed']=='0x3588da7a' and int(f['directed'])==8,f'full Verilator contract changed C={c}')
 vlt_fields[c]=f
vlt_rng={c:{'start':int(vlt_fields[c]['rng_start'],16),'end':int(vlt_fields[c]['rng_end'],16)} for c in (8,32,64)}
for c in (8,32,64):need(vlt_rng[c]['end']==advance(vlt_rng[c]['start'],6*c*10000),f'full Verilator RNG edge inconsistent C={c}')
line8,f8=fields_for(iv8_lines,8,0)
need(line8 is not None and int(f8['count'])==10000 and int(f8['full_raw'])==2500 and int(f8['finite_exp'])==7500 and f8['seed']=='0x3588da7a','preserved Icarus C8 PASS marker missing')
need(int(f8['rng_start'],16)==vlt_rng[8]['start'] and int(f8['rng_end'],16)==vlt_rng[8]['end'],'C8 independent run RNG boundaries differ from full Verilator')

plan={32:[(i*1000,1000) for i in range(10)],64:[(i*625,625) for i in range(16)]}
run_records=[];coverage={32:[],64:[]};rng_receipts={32:[],64:[]};stopped_at=None;status='FAIL_FINE_ICARUS_SHARDS'
resources=cgroup();
for c,chunks in plan.items():
 for first,count in chunks:
  name=f'iverilog_C{c}_first{first}_count{count}'
  argv=['vvp',str(IVBIN),f'+C={c}',f'+RANDOM_FIRST={first}',f'+RANDOM_COUNT={count}']
  emit({'event':'start','name':name,'argv':argv})
  rec=run_stream(name,argv,300);run_records.append(rec)
  if rec['returncode']!=0 or rec['timed_out']:
   stopped_at=name;break
  lines=markers(OUT/rec['stdout_path']);line,f=fields_for(lines,c,first)
  expected_raw=sum(1 for frame in range(first,first+count) if frame%4==0)
  need(line is not None and int(f['count'])==count and int(f['directed'])==8 and int(f['full_raw'])==expected_raw and
       int(f['finite_exp'])==count-expected_raw and f['seed']=='0x3588da7a',f'shard PASS marker/count failed: {name}')
  start_expect=advance(vlt_rng[c]['start'],6*c*first)
  end_expect=advance(vlt_rng[c]['start'],6*c*(first+count))
  got_start=int(f['rng_start'],16);got_end=int(f['rng_end'],16)
  need(got_start==start_expect and got_end==end_expect,f'RNG prefix boundary mismatch: {name}')
  coverage[c].append([first,first+count]);rng_receipts[c].append({'first':first,'count':count,'rng_start':f['rng_start'],
    'rng_end':f['rng_end'],'raw':expected_raw,'finite':count-expected_raw})
 if stopped_at:break
if not stopped_at:
 for c in (32,64):
  parts=sorted(coverage[c]);need(parts and parts[0][0]==0 and parts[-1][1]==10000 and
   all(parts[i][1]==parts[i+1][0] for i in range(len(parts)-1)),f'shard coverage gap/overlap C={c}')
  need(sum(b-a for a,b in parts)==10000,'shard set does not cover all 10000 random frames')
  need(sum(x['raw'] for x in rng_receipts[c])==2500 and sum(x['finite'] for x in rng_receipts[c])==7500,
   f'aggregate frame class count differs C={c}')
 status='PASS_FINE_ICARUS_SHARDS_AND_PRIOR_VERILATOR_FULL_RUN'
after={p:sha(pathlib.Path(p)) for p in sorted(source_inputs)}
unchanged=before==after
if not unchanged:status='FAIL_FINE_SHARD_SOURCE_DRIFT'
report={'status':status,'scope':'Fine-grained Icarus CPU-only shards on the same V2 VVP binary; full Verilator and C8 Icarus runs are included only as unchanged source/binary-bound prior evidence. No DUT or numerical inputs changed.',
 'candidate_preparation_sha256':sha(PREP),'root_warning_review_sha256':sha(WARN_REVIEW),'strict_warning_failure_preserved_sha256':sha(STRICT),
 'aggregate_C32_5000_timeout_preserved_sha256':sha(BASELINE),'same_Icarus_VVP_sha256':sha(IVBIN),'same_Verilator_binary_sha256':sha(VLTBIN),
 'source_hashes_before':before,'source_hashes_after':after,'sources_unchanged':unchanged,'resource_scope_actual':resources,
 'tool_versions':{'iverilog':'Icarus 13.0; exact version record in reviewed-run-report-v1','verilator':'5.048; exact version in reviewed-run-report-v1'},
 'verilator_full_markers':{str(c):vlt_fields[c] for c in (8,32,64)},'icarus_C8_prior_marker':f8,
 'shard_plan':{str(k):v for k,v in plan.items()},'completed_coverage':{str(k):v for k,v in coverage.items()},
 'completed_rng_boundaries':{str(k):v for k,v in rng_receipts.items()},'commands':run_records,'stopped_at':stopped_at,
 'contract':{'seed':'0x3588da7a','directed_cases_each_run':8,'random_frames_each_C':10000,'full_raw_per_C':2500,'finite_per_C':7500,
 'capture0_hold_checked_each_case':True,'known_output_check_each_capture':True,'C32_shards':10,'C64_shards':16,
 'runtime_cap_seconds_per_shard':300,'same_generator_draws_per_frame_per_C_lane':6},
 'hardware_accessed':False,'DUT_edited':False,'finished_utc':utc()}
(OUT/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':status,'stopped_at':stopped_at,'sources_unchanged':unchanged,
 'completed_shards':len(run_records),'coverage':{str(k):v for k,v in coverage.items()},
 'report_path':str(OUT/'report.json'),'report_sha256':sha(OUT/'report.json')},indent=2))
sys.exit(0 if status=='PASS_FINE_ICARUS_SHARDS_AND_PRIOR_VERILATOR_FULL_RUN' and unchanged else 1)
