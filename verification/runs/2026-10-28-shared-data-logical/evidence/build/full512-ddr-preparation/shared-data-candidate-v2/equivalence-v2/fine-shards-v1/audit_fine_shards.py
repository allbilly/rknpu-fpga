#!/usr/bin/env python3
"""Independent read-only postprocessor for reviewed V2 equivalence shards."""
import datetime,hashlib,json,pathlib,re
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');EQ=ROOT/'build/full512-ddr-preparation/shared-data-candidate-v2/equivalence-v2';OUT=EQ/'fine-shards-v1'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def load(p):return json.loads(p.read_text())
def markers(p):return [x.strip() for x in p.read_text(errors='replace').splitlines() if x.startswith('PASS shared_cell_equivalence')]
def parse(line):
 d={}
 for tok in line.split():
  if '=' in tok:
   k,v=tok.split('=',1);d[k]=v
 return d
need=lambda ok,msg: (_ for _ in ()).throw(RuntimeError(msg)) if not ok else None
report=load(OUT/'report.json');parent=load(EQ/'reviewed-run-report-v1.json')
need(report['status']=='PASS_FINE_ICARUS_SHARDS_AND_PRIOR_VERILATOR_FULL_RUN','fine-shard runner did not report PASS')
need(report['sources_unchanged'] is True and len(report['commands'])==26,'fine shard source stability or command count changed')
# Audit the already completed exact C8 run on the same VVP and seed.
c8=next(x for x in parent['commands'] if x['name']=='iverilog_C8_first0_count10000')
need(c8['returncode']==0 and c8['timed_out'] is False and c8['timeout_seconds']==300,'C8 prior case was not a complete PASS')
c8log=EQ/c8['stdout_path'];c8marks=markers(c8log)
c8line=next((x for x in c8marks if x.startswith('PASS shared_cell_equivalence C=8 ')),None)
need(c8line is not None,'C8 log lacks exact pass marker')
c8f=parse(c8line)
need((int(c8f['first']),int(c8f['count']),int(c8f['full_raw']),int(c8f['finite_exp']),c8f['seed'])==(0,10000,2500,7500,'0x3588da7a'),'C8 complete frame/class count differs')
# Full VLT output supplies the reference stream boundary state for every C.
vlt=EQ/'verilator_full_run.stdout.log';vltmarks=markers(vlt);vlt_fields={}
for c in (8,32,64):
 ln=next((x for x in vltmarks if x.startswith(f'PASS shared_cell_equivalence C={c} ')),None)
 need(ln is not None,f'Verilator full marker absent C={c}')
 f=parse(ln);need((int(f['first']),int(f['count']),int(f['full_raw']),int(f['finite_exp']),f['seed'])==(0,10000,2500,7500,'0x3588da7a'),f'Verilator count mismatch C={c}')
 vlt_fields[c]=f
need(any(x=='PASS shared_cell_equivalence_all selected_C=0 first=0 count=10000 raw_goldens_unchanged=1 DUTs_unmodified=1' for x in vltmarks),'full VLT terminal marker absent')

def xs(x):
 x ^= (x<<13)&0xffffffff;x &=0xffffffff;x ^= x>>17;x &=0xffffffff;x ^= (x<<5)&0xffffffff;x &=0xffffffff;return x
def advance(x,n):
 for _ in range(n):x=xs(x)
 return x
# Validate actual shard output logs, not the runner's aggregate claims alone.
shards={32:[(i*1000,1000) for i in range(10)],64:[(i*625,625) for i in range(16)]}
rec_by_name={x['name']:x for x in report['commands']};audit={}
for c,ranges in shards.items():
 intervals=[];items=[]
 full_start=int(vlt_fields[c]['rng_start'],16);full_end=int(vlt_fields[c]['rng_end'],16)
 need(full_end==advance(full_start,6*c*10000),f'full VLT RNG advance mismatch C={c}')
 for first,count in ranges:
  name=f'iverilog_C{c}_first{first}_count{count}';r=rec_by_name[name]
  need(r['returncode']==0 and r['timed_out'] is False and r['timeout_seconds']==300,f'shard failed/timed out: {name}')
  out=OUT/r['stdout_path'];err=OUT/r['stderr_path'];need(err.stat().st_size==0,f'shard stderr nonempty: {name}')
  lines=markers(out);ln=next((x for x in lines if x.startswith(f'PASS shared_cell_equivalence C={c} ')),None)
  need(ln is not None,f'shard marker absent: {name}')
  f=parse(ln);raw=sum(1 for k in range(first,first+count) if k%4==0)
  need((int(f['first']),int(f['count']),int(f['directed']),int(f['full_raw']),int(f['finite_exp']),f['seed'])==(first,count,8,raw,count-raw,'0x3588da7a'),f'shard count/seed mismatch: {name}')
  need(f['rng_start']==f'{advance(full_start,6*c*first):08x}' and f['rng_end']==f'{advance(full_start,6*c*(first+count)):08x}',f'RNG boundary mismatch: {name}')
  intervals.append((first,first+count));items.append({'name':name,'marker':ln,'stdout_sha256':sha(out),'stderr_sha256':sha(err),
   'runtime_seconds':r['seconds'],'rng_start':f['rng_start'],'rng_end':f['rng_end'],'raw':raw,'finite':count-raw})
 intervals.sort();need(intervals[0][0]==0 and intervals[-1][1]==10000 and all(intervals[i][1]==intervals[i+1][0] for i in range(len(intervals)-1)),f'disjoint union incomplete C={c}')
 need(sum(x['raw'] for x in items)==2500 and sum(x['finite'] for x in items)==7500,f'aggregate classes mismatch C={c}')
 audit[str(c)]={'intervals':[list(x) for x in intervals],'frame_count':sum(b-a for a,b in intervals),
                'full_raw':sum(x['raw'] for x in items),'finite_exp':sum(x['finite'] for x in items),'shards':items}
need(len(rec_by_name)==len(report['commands'])==26,'unexpected shard command rows')
result={'status':'PASS_INDEPENDENT_POSTPROCESS_REVIEWED_SHARED_CELL_EQUIVALENCE_SHARDS',
 'scope':'Independent hash/log/marker/count/RNG-boundary audit of existing source-bound simulator outputs; no simulator or hardware command executed.',
 'runner_report_sha256':sha(OUT/'report.json'),'baseline_report_sha256':sha(EQ/'reviewed-run-report-v1.json'),
 'verilator_full_log_sha256':sha(vlt),'c8_baseline_stdout_sha256':sha(c8log),
 'same_vvp_sha256':report['same_Icarus_VVP_sha256'] if 'same_Icarus_VVP_sha256' in report else sha(EQ/'sim_iverilog_reviewed.vvp'),
 'full_verilator':{str(c):{'rng_start':vlt_fields[c]['rng_start'],'rng_end':vlt_fields[c]['rng_end']} for c in (8,32,64)},
 'c8_completed_prior_case':{'first':0,'count':10000,'raw':2500,'finite':7500,'marker':c8line,'runtime_seconds':c8['seconds']},
 'c32_c64_shards':audit,'all_26_shards_completed':True,'hardware_accessed':False,'reviewed_waivers_used':'-Wno-fatal only for compile, exact six root-reviewed warnings; no kind suppression.',
 'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
(OUT/'independent-audit-v1.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':result['status'],'shards':26,'C32_frames':audit['32']['frame_count'],'C64_frames':audit['64']['frame_count'],
 'C32_raw_finite':[audit['32']['full_raw'],audit['32']['finite_exp']],'C64_raw_finite':[audit['64']['full_raw'],audit['64']['finite_exp']],
 'sha256':sha(OUT/'independent-audit-v1.json')},indent=2))
