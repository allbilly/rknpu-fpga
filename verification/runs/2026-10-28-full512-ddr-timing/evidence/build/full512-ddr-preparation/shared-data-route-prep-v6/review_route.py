"""Independent routed-checkpoint evidence gate, including every pulse row."""
from pathlib import Path
import datetime,hashlib,json,math,re
BASE=Path(__file__).resolve().parent;OUT=BASE/'output'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
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
def pulse_rows(path):
 counts={k:0 for k in ['Min Period','Max Period','Low Pulse Width','High Pulse Width']};worst=math.inf
 for raw in Path(path).read_text().splitlines():
  fields=raw.split();kind=next((k for k in counts if fields[:len(k.split())]==k.split()),None)
  if kind is None:continue
  begin=len(kind.split())+3;need(len(fields)>=begin+4,'Malformed recognized pulse-width row')
  values=list(map(float,fields[begin:begin+3]));need(all(math.isfinite(x) for x in values) and values[0]>0 and values[1]>0 and values[2]>=0,'Failed/invalid pulse-width row')
  counts[kind]+=1;worst=min(worst,values[2])
 need(all(counts[k]>0 for k in ['Min Period','Low Pulse Width','High Pulse Width']),'Missing pulse kind coverage')
 return dict(counts=counts,worst_reported_slack_ns=worst)
def table(path):return [x.split('\t') for x in Path(path).read_text().splitlines()]
def main():
 r=json.loads((BASE/'report.json').read_text());need(r['status']=='PASS_FULL512_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_SOURCE_AUDIT_AND_PHYSICAL_REVIEW' and r['returncode']==0,'Route not completed/passed')
 need(r['all_inputs_unchanged'] is True and r['owned_process_group_stopped'] is True,'Route inputs changed or owned process remains')
 need(r['input_hashes_before']==r['input_hashes_after']==r['input_hashes_expected'],'Route input maps differ')
 for n,h in r['input_hashes_expected'].items():need(sha(n)==h,'Changed actual qualified input '+n)
 for n,h in r['output_hashes'].items():need(sha(OUT/n)==h,'Changed route output '+n)
 need(not (OUT/'stderr.log').read_bytes(),'Unexpected route stderr')
 need((OUT/'stdout.log').read_text().splitlines().count(r['status'])==1,'Missing exact native terminal marker')
 t=summary(OUT/'timing.rpt');pulse=pulse_rows(OUT/'pulse_width.rpt')
 route=(OUT/'route_status.rpt').read_text();counts={}
 for line in route.splitlines():
  m=re.match(r'\s*# of (logical nets|routable nets|fully routed nets|nets with routing errors)\.+\s*:\s*(\d+)\s*:',line)
  if m:counts[m[1]]=int(m[2])
 need(set(counts)=={'logical nets','routable nets','fully routed nets','nets with routing errors'} and counts['routable nets']==counts['fully routed nets']>0 and counts['nets with routing errors']==0,'Incomplete routing or routing errors')
 for label in ['no_clock','unconstrained_internal_endpoints']:
  text=(OUT/('check_timing_'+label+'.rpt')).read_text();found=re.findall(r'(?m)^\s*There are (\d+) .+$',text);need(found and all(int(n)==0 for n in found),'Missing/unconstrained internal timing coverage')
 census=table(OUT/'route_census.tsv');core=[x for x in census if x[0]=='CENSUS'];need(len(core)==2 and {x[1] for x in core}=={'imported_post_opt','post_route'} and all(x[2:]==['ypcb_ddr_dual_top','xc7k480tffg1156-2','16','512','516','242'] for x in core),'Compute/IO source census differs')
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
  m=re.match(r'\s*\|\s*(DPIP-1|DPOP-1|DPOP-2|REQP-1709)\s*\|\s*Warning\s*\|[^|]+\|\s*(\d+)\s*\|',line)
  if m:violations[m[1]]=int(m[2])
 need(violations=={'DPIP-1':1032,'DPOP-1':516,'DPOP-2':516,'REQP-1709':2},'Unreviewed default DRC inventory')
 result=dict(status='PASS_INDEPENDENT_FULL512_DDR_ROUTE_AND_TIMING_ONLY',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),scope='Actual routed checkpoint and internal timing/strict project crossing/reset audits; no image, FPGA application, DDR capacity/ECC or RK silicon acceptance',producer_sha256=sha(BASE/'report.json'),post_route_dcp_sha256=sha(OUT/'post_route.dcp'),source_post_opt_dcp_sha256=r['post_opt_dcp_sha256'],input_hashes_rehashed=len(r['input_hashes_expected']),route_counts=counts,timing=t,all_pulse_rows=pulse,product_dsps=512,total_dsps=516,ports=242,status_chains=9,reset_banks=4,default_drc=violations,helper_reports=helper_evidence,complete_controller_matrix_qualified=False,bitstream_emitted=False,hardware_accessed=False)
 target=BASE/'root-route-review.json';need(not target.exists(),'Fresh root route receipt required');target.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
