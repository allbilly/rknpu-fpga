"""Independent review of the fresh retirement-compression route; refuses live/failed runs."""
from pathlib import Path
import datetime,hashlib,json,math,re
BASE=Path(__file__).resolve().parent;OUT=BASE/'output'
def sha(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def need(ok,message):
 if not ok:raise RuntimeError(message)
def summary(path):
 lines=Path(path).read_text().splitlines();heads=[i for i,x in enumerate(lines) if re.match(r'^\s*WNS\(ns\)\s+TNS\(ns\)',x)];need(len(heads)==1,'Ambiguous global timing summary')
 selected=None
 for line in lines[heads[0]+1:heads[0]+7]:
  fields=line.split()
  if len(fields)==12:
   try:selected=list(map(float,fields));break
   except ValueError:pass
 need(selected is not None and all(math.isfinite(x) for x in selected),'Missing finite global timing numbers')
 for offset in [0,4,8]:
  need(selected[offset]>=0 and selected[offset+1]==0 and selected[offset+2]==0 and selected[offset+3]>0,'Global setup/hold/pulse fails or lacks endpoint coverage')
 return dict(setup_ns=selected[0],hold_ns=selected[4],pulse_ns=selected[8],setup_endpoints=int(selected[3]),hold_endpoints=int(selected[7]),pulse_endpoints=int(selected[11]))
def table(path):return [x.split('\t') for x in Path(path).read_text().splitlines()]

def pulse_rows(path):
 kinds=('Min Period','Max Period','Low Pulse Width','High Pulse Width')
 counts={kind:0 for kind in kinds};worst=math.inf;in_table=False
 for raw in Path(path).read_text().splitlines():
  text=raw.strip()
  if not text or text.startswith('Clock Name:'):
   in_table=False;continue
  if re.match(r'Check Type\s',text):in_table=True;continue
  if not in_table:continue
  fields=text.split();kind=next((k for k in kinds if [x.lower() for x in fields[:len(k.split())]]==k.lower().split()),None)
  need(kind is not None,'Unrecognized actual pulse check row')
  index=len(kind.split())+3;need(len(fields)>=index+4,'Malformed pulse row')
  values=list(map(float,fields[index:index+3]))
  need(all(math.isfinite(x) for x in values) and values[0]>0 and values[1]>0 and values[2]>=0,'Failed/nonfinite pulse row')
  counts[kind]+=1;worst=min(worst,values[2])
 need(all(n>0 for n in counts.values()),'Missing one of four pulse check kinds')
 return dict(counts=counts,total_rows=sum(counts.values()),worst_reported_slack_ns=worst)

def main():
 producer=BASE/'report.json';producer_sha=sha(producer);r=json.loads(producer.read_text())
 need(r['status']=='PASS_FRESH_FULL512_RETIRE_ROUTE_REQUIRES_ROOT_REVIEW','Fresh retirement-compression route is incomplete/failed')
 need(r['all_inputs_unchanged'] is True and r['all_owned_groups_stopped'] is True and not any(r['owned_groups_after_cleanup'].values()),'Changed input or live owned group')
 need(r['input_hashes_before']==r['input_hashes_after'] and r['input_hashes_before'],'Route before/after binding mismatch')
 for path,digest in r['input_hashes_before'].items():need(sha(path)==digest,'Changed admitted route input: '+path)
 for path,digest in r['outputs'].items():need(sha(path)==digest,'Changed native route output: '+path)
 need(set(r['outputs'])=={str(p) for p in OUT.rglob('*') if p.is_file()},'Missing or extra actual route artifact')
 commands=r['commands'];need(len(commands)==2 and all(c['status']=='PASS' and c['returncode']==0 and not c['live_pids_after_cleanup'] for c in commands),'Incomplete native process matrix')
 need(commands[1]['argv'][-1]==str(BASE.parent/'full512-capacity-retire-route-prep-v1/route.tcl'),'Native command did not run the approved fresh route Tcl')
 for c in commands:
  for stream in ('stdout','stderr'):need(sha(c[stream+'_path'])==c[stream+'_sha256'],'Changed native log')
 need(not Path(commands[1]['stderr_path']).read_bytes(),'Unexpected native route stderr')
 stdout=Path(commands[1]['stdout_path']).read_text()
 need(stdout.splitlines().count('PASS_FULL512_RETIRE_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_ROOT_REVIEW')==1,'Missing exact native completion marker')
 need('SW Build 6511674' in r['actual_tool_version'],'Unexpected actual Vivado version')
 t=summary(OUT/'timing.rpt');pulse=pulse_rows(OUT/'pulse_width.rpt')
 route=(OUT/'route_status.rpt').read_text();counts={}
 for line in route.splitlines():
  m=re.match(r'\s*# of (logical nets|routable nets|fully routed nets|nets with routing errors)\.+\s*:\s*(\d+)\s*:',line)
  if m:counts[m[1]]=int(m[2])
 need(set(counts)=={'logical nets','routable nets','fully routed nets','nets with routing errors'} and counts['routable nets']==counts['fully routed nets']>0 and counts['nets with routing errors']==0,'Incomplete routing or routing errors')
 for label in ['no_clock','unconstrained_internal_endpoints']:
  text=(OUT/('check_timing_'+label+'.rpt')).read_text();found=re.findall(r'(?m)^\s*There are (\d+) .+$',text);need(found and all(int(n)==0 for n in found),'Missing/unconstrained internal timing coverage')
 census=table(OUT/'route_census.tsv');core=[x for x in census if x[0]=='CENSUS'];need(len(core)==2 and {x[1] for x in core}=={'imported_post_opt','post_route'} and all(x[2:]==['ypcb_ddr_dual_top','xc7k480tffg1156-2','16','512','516','242'] for x in core),'Compute/IO source census differs')
 admission=table(OUT/'route_import_facts.tsv')+table(OUT/'route_census.tsv')
 modules=[x for x in admission if x[0]=='ADMISSION_MODULES']
 need(len(modules)==2 and {x[1] for x in modules}=={'imported_post_opt','post_route'} and all(x[2:4]==['1','2'] for x in modules),'Admission-module census missing/changed')
 facts=table(OUT/'route_import_facts.tsv');need(['CONSTANT_PROOF','35','101','3'] in facts and ['CONSTANT_PROOF','post_route','35','101','3'] in facts,'Constant anchors changed through route')
 statuses=table(OUT/'status/reset_status_cdc.tsv');chains=[x for x in statuses if x[0]=='CHAIN'];need(len(chains)==9 and all(x[-1]=='3' for x in chains),'Status synchronizer coverage')
 for x in statuses:
  if x[0]=='TIMED':need(float(x[-1])>=0 and float(x[-2]) in [7.5,20.0],'Status later path cut/fails')
 helper_evidence={}
 for name,result_count in [('ew_job',37),('cmac_job',10)]:
  p=OUT/name/'async_job_cdc.tsv';rows=table(p);payload=[x for x in rows if x[0]=='PAYLOAD'];need(payload==[['PAYLOAD','descriptor','64','40.000'],['PAYLOAD','result',str(result_count),'15.000']],'Job payload/skew scope changed')
  need(sum(x[0]=='SYNC' for x in rows)==9,'Missing job toggle synchronizers');need(sum(x[0]=='ZERO_CODE' for x in rows)==(4 if name=='ew_job' else 0) and sum(x[0]=='ZERO_TASK' for x in rows)==(31 if name=='cmac_job' else 0),'Wrong folded task/code proof');helper_evidence[name]=sha(p)
 for name in ['ew_memory','cmac_memory']:
  p=OUT/name/'async_memory_cdc.tsv';rows=table(p);need([x for x in rows if x[0]=='PAYLOAD']==[['PAYLOAD','request','49','15.000'],['PAYLOAD','response','17','40.000']] and sum(x[0]=='SYNC' for x in rows)==9,'Memory crossing payload/sync scope changed');helper_evidence[name]=sha(p)
 permit=table(OUT/'permit/cmac_permit_cdc.tsv');need(sum(x[0]=='CHAIN' for x in permit)==1 and sum(x[0]=='TIMED' for x in permit)==4,'CMAC permit scope missing')
 for x in permit:
  if x[0]=='TIMED':need(float(x[-1])>=0 and (x[-3],float(x[-2])) in [('max',20.0),('min',0.0)],'Invalid permit path budget')
 reset=table(OUT/'bridge/reset_bridge_board.tsv');need(sum(x[0]=='BANK' for x in reset)==4 and all(x[-1]=='3' for x in reset if x[0]=='BANK'),'Board reset banks missing')
 mailbox=table(OUT/'mailbox/mailbox_cdc.tsv');need(sum(x[0]=='SYNC' for x in mailbox)==6 and sum(x[0]=='PAYLOAD' for x in mailbox)==2,'Mailbox scope missing')
 drc=(OUT/'drc.rpt').read_text();violations={}
 for line in drc.splitlines():
  m=re.match(r'\s*\|\s*([A-Za-z][A-Za-z0-9_-]*-[0-9]+)\s*\|\s*Warning\s*\|[^|]+\|\s*(\d+)\s*\|',line)
  if m:
   need(m[1] not in violations,'Duplicate DRC summary rule');violations[m[1]]=int(m[2])
 need(violations=={'DPIP-1':1032,'DPOP-1':516,'DPOP-2':516,'REQP-1709':2},'Unreviewed default DRC inventory')

 pulse_counts={row[1]:int(row[2]) for row in table(OUT/'pulse_width_counts.tsv')}
 need(pulse_counts=={**pulse['counts'],'TOTAL_ROWS':pulse['total_rows']},'Native/independent pulse row census mismatch')
 drc_counts={row[1]:int(row[2]) for row in table(OUT/'default_drc_counts.tsv')}
 need(drc_counts==violations,'Native/independent DRC census mismatch')
 mig=[row for row in census+facts if row[0]=='MIG_CHANNELS']
 need(len(mig)==2 and {row[1] for row in mig}=={'imported_post_opt','post_route'},'Both real MIG controller censuses missing')
 need(all(row.count('mig_7series_v4_2_memc_ui_top_axi')>=2 and row.count('mig_7series_v4_2_infrastructure')>=2 for row in mig),'Original MIG controller identities changed')
 resource=re.findall(r'RETIRE_ROUTE_RESOURCE_GATE total_luts=(\d+) limit=298600',stdout)
 need(len(resource)==1 and 0<int(resource[0])<=298600,'Missing/over-capacity routed LUT census')
 need(sha(producer)==producer_sha,'Producer changed during root review')
 result=dict(status='PASS_ROOT_FULL512_RETIRE_ROUTE_TIMING',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  reviewer_sha256=sha(__file__),producer_sha256=producer_sha,actual_tool_version=r['actual_tool_version'],
  input_hashes_rehashed=len(r['input_hashes_before']),output_files_rehashed=len(r['outputs']),
  post_route_dcp_sha256=sha(OUT/'post_route.dcp'),post_opt_dcp_sha256=json.loads((BASE/'preparation.json').read_text())['route_environment']['RK_CAPACITY_ROUTE_POST_OPT_DCP_SHA256'],
  route_counts=counts,timing=t,all_pulse_rows=pulse,routed_luts=int(resource[0]),product_dsps=512,total_dsps=516,ports=242,
  status_chains=9,reset_banks=4,default_drc=violations,helper_reports=helper_evidence,
  physical_capacity_qualified=False,hardware_accessed=False,bitstream_emitted=False,
  scope='Fresh retirement-compression route/timing/mapped bindings only; no bitstream, physical memory or RK equivalence acceptance. Native runner label synthesis actually invoked the sealed route.tcl.')
 with (BASE/'root-route-review.json').open('x') as stream:stream.write(json.dumps(result,indent=2,sort_keys=True)+'\n')
 print(json.dumps(result,indent=2,sort_keys=True))
if __name__=='__main__':main()
