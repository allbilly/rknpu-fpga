"""Independently accept completed native facts; preserve the producer's marker bug."""
from pathlib import Path
import datetime,hashlib,json,re
BASE=Path(__file__).resolve().parent;OUT=BASE/'output';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
r=json.loads((BASE/'report.json').read_text());need(r['status']=='FAIL_READ_ONLY_POST_OPT_INVENTORY' and r['returncode']==0 and r['error']=="ValueError('Missing exact query terminal marker')",'Unexpected producer state')
need(r['all_inputs_unchanged'] is True and r['input_hashes_before']==r['input_hashes_after'],'Changed actual native inputs')
for n,h in r['input_hashes_before'].items():need(sha(n)==h,'Changed actual native input '+n)
for n,h in r['output_hashes'].items():need(sha(OUT/n)==h,'Changed actual native output '+n)
stdout=(OUT/'stdout.log').read_text();need(stdout.splitlines().count('PASS_READ_ONLY_DUAL_CDC_AND_RESET_INVENTORY')==1 and not (OUT/'stderr.log').read_bytes(),'Missing actual native finish or stderr')
need(not re.search(r'(?m)^ERROR:|^CRITICAL WARNING:',stdout),'Blocking native query diagnostic')
facts=(OUT/'inventory-facts.txt').read_text();lines=facts.splitlines()
for value in ['TOTAL_CONSTANT_ROWS\t35','TOTAL_CONSTANT_NET_OBSERVATIONS\t101','STATUS_CHAIN_COUNT\t9','BOARD_RESET_BANK_COUNT\t4','LOGICAL_UI0_EQUALS_PHYSICAL_C1\t1','LOGICAL_UI1_EQUALS_PHYSICAL_C0\t1']:
 need(value in lines,'Incomplete strict inventory: '+value)
objects={}
for label in ['MIG_WRAPPER','MIG_CORE','C0_INFRA','C1_INFRA','C0_CONTROLLER','C1_CONTROLLER','C0_RESET_SOURCE','C1_RESET_SOURCE']:
 count=[x for x in lines if x.startswith('EXACT_CELL_COUNT_'+label+'\t')];need(len(count)==1 and count[0].endswith('COUNT=1'),'Missing actual mapped object '+label)
 row=[x for x in lines if x.startswith('EXACT_CELL_'+label+'\t')];need(len(row)==1,'Missing mapped object properties')
 fields=dict(re.findall(r'(\w+)=([^ ]*)',row[0].split('\t',1)[1]));need(fields['IS_BLACKBOX']=='0','Mapped object became black box');objects[label]=fields
for label,ref in [('MIG_WRAPPER','top_mig_7series_0_0'),('MIG_CORE','top_mig_7series_0_0_mig'),('C0_INFRA','mig_7series_v4_2_infrastructure'),('C1_INFRA','mig_7series_v4_2_infrastructure'),('C0_CONTROLLER','mig_7series_v4_2_memc_ui_top_axi'),('C1_CONTROLLER','mig_7series_v4_2_memc_ui_top_axi')]:need(objects[label]['ORIG_REF_NAME']==ref and objects[label]['IS_PRIMITIVE']=='0','Changed real controller source identity '+label)
for label,clock in [('C0_RESET_SOURCE','clk_pll_i'),('C1_RESET_SOURCE','clk_pll_i_1')]:
 need(objects[label]['REF_NAME']=='FDPE' and objects[label]['INIT']=="1'b1",'Changed controller reset source FF')
 need('EXACT_CELL_CLOCK_'+label+'\tCLOCK='+clock+' PERIOD=7.500' in lines,'Wrong actual reset source clock')
need(len([x for x in lines if x.startswith('EW_ZERO_CODE_FACT\t')])==4 and len([x for x in lines if x.startswith('CMAC_ZERO_TASK_FACT\t')])==31,'Incomplete constant source rows')
record=dict(status='PASS_INDEPENDENT_POST_OPT_NATIVE_STRUCTURE_AND_CONSTANT_INVENTORY_ONLY',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),native_returncode=0,producer_sha256=sha(BASE/'report.json'),native_checker_failure_preserved=True,checker_failure_disposition='Producer looked for stdout terminal marker in facts TSV; actual stdout has exactly one standalone marker and native exit0',input_count_rehashed=len(r['input_hashes_before']),post_opt_dcp_sha256=r['dcp_sha256'],synthesis_facts_sha256=r['synthesis_facts_sha256'],inventory_facts_sha256=sha(OUT/'inventory-facts.txt'),source_objects=objects,constant_rows=35,constant_observations=101,status_chains=9,board_reset_banks=4,constraints_applied=False,routed_timing_qualified=False,hardware_accessed=False)
p=BASE/'root-review.json';need(not p.exists(),'Fresh root review required');p.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps({k:v for k,v in record.items() if k!='source_objects'},indent=2))
