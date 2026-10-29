"""Independent completed-source/constant-proof/resource gate before routing."""
from pathlib import Path
import datetime,hashlib,json,re
BASE=Path(__file__).resolve().parent;OUT=BASE/'synthesis';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
def flag(x):return x in {'1','TRUE'}
def utilization(path):
 text=path.read_text();need('Vivado v.2026.1' in text and 'xc7k480tffg1156-2' in text,'Changed native utilization tool/part')
 rows=[]
 for line in text.splitlines():
  f=[x.strip() for x in line.strip().split('|')[1:-1]]
  if len(f)==10:rows.append(f)
 top=[r for r in rows if r[0]=='ypcb_ddr_dual_top'];need(len(top)==1 and top[0][1]=='(top)','Missing top utilization row');values=list(map(int,top[0][2:]));need(len(values)==8,'Changed utilization schema')
 need(all(sum(r[0]==name for r in rows)==1 for name in ['c0_u_memc_ui_top_axi','c1_u_memc_ui_top_axi']),'Both actual memory controller blocks required')
 total,logic,ram,srl,ff,b36,b18,dsp=values;need(total==logic+ram+srl and dsp==516,'Inconsistent LUT or DSP census')
 return dict(total_luts=total,logic_luts=logic,lutram=ram,srl=srl,ffs=ff,ramb36=b36,ramb18=b18,total_dsps=dsp,controller_blocks=2)
r=json.loads((OUT/'run.json').read_text());p=json.loads((BASE/'preparation.json').read_text())
need(r['status']=='PASS_FRESH_SOURCE_CONSTRAINED_SYNTHESIS_ONLY' and r['returncode']==0,'Source native run not terminal PASS')
need(r['inputs_unchanged'] and r['copies_and_controls_unchanged'],'Source/control drift')
for before,after in [('input_hashes_before','input_hashes_after'),('control_hashes_before','control_hashes_after')]:
 need(r[before]==r[after],'Changed native input map')
 for n,h in r[before].items():need(sha(n)==h,'Changed actual input '+n)
need(r['copied_hashes_before']==r['copied_hashes_after'],'Copied input map drift')
for n,h in r['copied_hashes_before'].items():need(sha(BASE/'source'/n)==h,'Changed copied input '+n)
need(len(p['files'])==160 and p['hdl_source_count']==152 and p['xdc_source_count']==2 and p['constraint_helper_count']==6,'Wrong complete closure')
for n,h in r['output_hashes'].items():need(sha(OUT/n)==h,'Changed native output '+n)
log=(OUT/'stdout.log').read_text();need(log.splitlines().count('READY_SHARED_DATA_CONSTRAINED_SYNTHESIS_ONLY_ROOT_REVIEW_REQUIRED')==1,'Missing exact source completion')
need(not re.search(r'(?m)^ERROR:|^CRITICAL WARNING:',log),'Blocking actual native diagnostic')
text=(OUT/'constrained_synthesis_facts.tsv').read_text();rows=[x.split('\t') for x in text.splitlines()];need(rows,'Missing source facts')
census=[x for x in rows if x[0]=='CENSUS'];need(len(census)==2 and {x[1] for x in census}=={'pre_opt','post_opt'},'Missing actual stage census')
for row in census:
 d=dict(zip(row[2::2],row[3::2]));need(d['TOP']=='ypcb_ddr_dual_top' and d['PART']=='xc7k480tffg1156-2','Wrong mapped target')
 need({k:d[k] for k in ['KERNELS','PRODUCT_DSPS','TOTAL_DSPS','AUXILIARY_DSPS','SCALAR_PORTS','CONFIG_VOLTAGE','CFGBVS']}=={'KERNELS':'16','PRODUCT_DSPS':'512','TOTAL_DSPS':'516','AUXILIARY_DSPS':'4','SCALAR_PORTS':'242','CONFIG_VOLTAGE':'1.8','CFGBVS':'GND'},'Changed mapped compute/IO/config census')
for stage in ['pre_opt','post_opt']:
 kernels=[x for x in rows if x[:2]==['KERNEL_DSP',stage]];need(len(kernels)==16 and len({x[2] for x in kernels})==16 and all(x[3]=='32' for x in kernels),'Incomplete 16x32 actual product census')
 zeros=[x for x in rows if x[:2]==['ZERO_ROW',stage]];nets=[x for x in rows if x[:2]==['ZERO_NET',stage]];need(len(zeros)==35 and len(nets)==101,'Incomplete actual folded-field proof')
 for profile,kind,bits,width,indices in [('EW','ZERO_CODE',range(4,8),9,{3,5}),('CMAC','ZERO_TASK',range(1,32),11,{3,5,7})]:
  chosen=[x for x in zeros if x[2]==profile];need([int(x[4]) for x in chosen]==list(bits) and all(x[3]==kind and len(x)==width for x in chosen),'Changed constant-field source contract')
  n=[x for x in nets if x[2]==profile];need(len(n)==len(bits)*len(indices),'Missing boundary observations')
  for bit in bits:need({int(x[5]) for x in n if int(x[4])==bit}==indices,'Wrong source/observer/child coverage')
  need(all(x[7:9]==['GROUND','1'] for x in n),'Nonzero or multi-driver constant boundary')
  if stage=='post_opt':need(all(len(x)==11 and flag(x[9]) and flag(x[10]) for x in n),'Constant anchors were not preserved')
anchors=[x for x in rows if x[0]=='ANCHOR_SET'];need(anchors and len({x[1] for x in anchors})==len(anchors) and all(x[2:4]==['GROUND','1'] and flag(x[4]) and flag(x[5]) for x in anchors),'Invalid anchor set')
anchor_names=sorted(x[1] for x in anchors)
for stage in ['pre_opt','post_opt']:need(sorted({x[6] for x in rows if x[:2]==['ZERO_NET',stage]})==anchor_names,'Different source/post-opt anchor names')
clock=[x for x in rows if x[0]=='CLOCK_BINDING'];need(len(clock)==1,'Missing actual clock binding');clock=dict(zip(clock[0][1::2],clock[0][2::2]));need(float(clock['SYS_PERIOD'])==20 and float(clock['UI0_PERIOD'])==float(clock['UI1_PERIOD'])==7.5,'Changed clock period');need(clock['UI0_SOURCE_MIG_C1_PIN'].endswith('/c1_ui_clk') and clock['UI1_SOURCE_MIG_C0_PIN'].endswith('/c0_ui_clk') and len({clock['SYS'],clock['UI0'],clock['UI1']})==3,'Wrong actual clock sources')
pre=utilization(OUT/'pre_opt_utilization.rpt');post=utilization(OUT/'post_opt_utilization.rpt')
drc=(OUT/'post_opt_default_drc.rpt').read_text();need(not re.search(r'(?im)^\s*\|[^\n]*\|\s*(?:Error|Critical Warning)\s*\|',drc),'Blocking post-opt DRC severity')
need('UTLZ-1' not in drc,'Resource DRC failed')
fits=post['total_luts']<=298600
review=dict(status='PASS_FULL512_POST_OPT_RESOURCE_CONSTANT_AND_SOURCE_REHASH_ONLY' if fits else 'NOT_FIT_FULL512_POST_OPT_SOURCE_AUDIT',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),scope='Fresh source synthesis/default-opt, exact clock/constant/structure inventory and nominal resource gate only; route/timing/physical execution unqualified',producer_sha256=sha(OUT/'run.json'),preparation_sha256=sha(BASE/'preparation.json'),post_opt_dcp_sha256=sha(OUT/'post_opt.dcp'),synthesis_facts_sha256=sha(OUT/'constrained_synthesis_facts.tsv'),source_inputs_rehashed=len(r['input_hashes_before']),copied_inputs_rehashed=len(r['copied_hashes_before']),source_hdl_count=152,product_dsps=512,total_dsps=516,scalar_ports=242,pre_opt=pre,post_opt=post,device_luts=298600,nominal_lut_spare=298600-post['total_luts'],constant_rows=35,constant_observations=101,anchor_names=anchor_names,anchor_set_count=len(anchor_names),anchor_set_sha256=hashlib.sha256(('\n'.join(anchor_names)+'\n').encode()).hexdigest(),clock_binding=clock,all_inputs_unchanged=True,route_gate_only=False,post_opt_structure_recheck_pending=True,routed_timing_qualified=False,complete_fault_matrix_qualified=False,hardware_accessed=False)
out=BASE/'root-post-opt-resource-review.json';need(not out.exists(),'Fresh root review required');out.write_text(json.dumps(review,indent=2)+'\n');print(json.dumps(review,indent=2));raise SystemExit(0 if fits else 1)
