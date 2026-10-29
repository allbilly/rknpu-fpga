from pathlib import Path
from collections import defaultdict,Counter
import hashlib,json,datetime,re
W=Path(__file__).resolve().parent
A=W/'post-route-audit-20261026T115834Z';L=W/'post-route-audit-launch-20261026T115834Z'
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,message):
 if not ok:raise ValueError(message)
def driver(value):
 # This field is a Tcl list. For exactly one expected pin, accept its plain
 # serialization or a single braced element (e.g. a name containing [0]).
 match=re.fullmatch(r'\{([^{} ]+)\}',value)
 return match.group(1) if match else value
build=json.loads((W/'run.json').read_text())
need(build['status']=='PASS_REGISTERED_BRAM_FULL512_CHECKPOINT' and build['returncode']==0 and build['environment']['RK_LED_ACTIVE_LOW']=='0','Wrong completed build/generic')
r=json.loads((L/'report.json').read_text());context=json.loads((W/'post-route-audit-context.json').read_text())
need(r['exit_code']==0 and r['input_recheck']=='PASS','Native command did not complete')
need(all(sha(n)==h for n,h in context['inputs'].items()),'Pinned input changed')
need(sha(W/'post-route-audit.tcl')==context['tcl_sha256']==r['audit_tcl_sha256'],'Audit source changed')
need((A/'result.txt').read_text().startswith('PASS_ROUTE_TIMING_IO_DRC_REVIEW;'),'Native result missing')
for name,key in [('stdout.log','stdout_sha256'),('vivado.log','vivado_log_sha256'),('vivado.jou','journal_sha256')]:need(sha(L/name)==r[key],'Native log changed')
cells={};pins={};dsps=defaultdict(dict)
for line in (A/'startup-and-control-facts.tsv').read_text().splitlines():
 p=line.split('\t')
 if p[0]=='CELL':cells[p[1]]=p[2:]
 elif p[0]=='PIN':pins[p[1]]={x.split('=',1)[0]:x.split('=',1)[1] for x in p[2:]}
 elif p[0]=='DSP_PROPERTY':dsps[p[1]][p[2]]=p[3]
expected={f'startup/release_pipe_reg[{i}]' for i in range(64)}|{'startup/rst_n_reg'}
need({n for n,v in cells.items() if n.startswith('startup/') and v[0].startswith('FD')}==expected,'Wrong startup register census')
for n in expected:
 need(cells[n][0]=='FDRE' and cells[n][1]=="INIT=1'b0",'Startup type/INIT changed')
 for pin,source in [('C','SYS_CLK_IBUF_BUFG_inst/O'),('CE','startup/VCC/P'),('R','startup/GND/G')]:need(driver(pins[n+'/'+pin]['DRIVERS'])==source,'Startup control/clock changed')
for i in range(64):
 expected_d='startup/VCC/P' if i==0 else f'startup/release_pipe_reg[{i-1}]/Q'
 need(driver(pins[f'startup/release_pipe_reg[{i}]/D']['DRIVERS'])==expected_d,'Broken startup delay chain')
need(driver(pins['startup/rst_n_reg/D']['DRIVERS'])=='startup/release_pipe_reg[63]/Q','Reset is not registered after64delaystages')
need(len(dsps)==515 and all(d[k]=='0' for d in dsps.values() for k in ['AREG','BREG','MREG','PREG']),'Changed DSP A/B/M/P pipeline selection')
core={n:d for n,d in dsps.items() if '/cmac/kernels[' in n};aux={n:d for n,d in dsps.items() if n not in core}
need(len(core)==512 and len(aux)==3,'Changed full512products/helpercensus')
need(all(d['CREG']=='0' and d['USE_DPORT']=='0' for d in core.values()),'Changed core DSPmode')
need(all(d['CREG']=='1' and driver(pins[n+'/CLK']['DRIVERS']).endswith('/GND/G') for n,d in aux.items()),'Changed helper default CREG/constantclock')
original_net=W.parents[1]/'regmem-closed-mapped-preparation/closed.v'
# Use the actual exported connectivity to distinguish unused default CREG=1
# from an active pipeline stage. All three address helpers select pure multiply.
need(sha(original_net)=='91d13f62ee3f9260d8c99f831ca1ccb239fc60f9c6dabd9c918f4728c7d6768b','Changed actual connectivity export')
net=original_net.read_text()
for n in aux:
    name=n.rsplit('/',1)[1]
    found=list(re.finditer(r'(?m)^    '+re.escape(name)+r'\s*$',net));need(len(found)==1,'Unknown helper specialization')
    start=net.rfind('  DSP48E1 #(',0,found[0].start());end=net.index(');',found[0].end())+2
    block=net[start:end]
    need(".CLK(1'b0)" in block and ".CEC(1'b0)" in block and
         ".OPMODE({1'b0,1'b0,1'b0,1'b0,1'b1,1'b0,1'b1})" in block,'Helper CREG is not inactive pure-multiply mode')
clocks=Counter(driver(pins[n+'/CLK']['DRIVERS']) for n in dsps)
need(all(name.endswith('/GND/G') for name in clocks),'Changed combinational DSPclock configuration')
need(all(d[k]=='0' for d in dsps.values() for k in ['ALUMODEREG','OPMODEREG','INMODEREG','CARRYINREG','CARRYINSELREG']),'Active DSP control register unexpectedly grounded')
for i in range(26):need(cells[f'heartbeat_reg[{i}]'][1]=="INIT=1'b0",'Heartbeat INIT changed')
cones=(A/'function-cones.tsv').read_text();need('PAD\tled_3bits_tri_o[2]\tSTARTPOINTS=heartbeat_reg[25]/C' in cones,'Heartbeat pad cone changed')
for role in [0,1]:
 line=next(line for line in cones.splitlines() if line.startswith(f'PAD\tled_3bits_tri_o[{role}]\t'))
 need('demo/state_reg[3]/C' in line and 'startup/rst_n_reg/C' in line,'PASS/failpad cone changed')
facts=(A/'facts.tsv').read_text()
for exact in ['WAIVERS\t0\n','ROUTED_FULLY\t1\n','ERRORS_IN_ROUTES\t0\n']:need(exact in facts,'Route/waiverfactfailed')
for rule,num in [('DPIP-1',1030),('DPOP-1',515),('DPOP-2',515)]:need(len(re.findall(r'^DRC\t'+rule+r'#[0-9]+\tWARNING$',facts,re.M))==num,'DSP warning inventory changed')
review=dict(status='PASS_ROOT_READONLY_ROUTED_INIT_AND_DSP_WARNING_REVIEW',reviewer='Root exact-source and actual routed-facts review',reviewed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256='ac6fee7e5ebd29b85c727349c5b2def80ba8f7876ceae76ff0bc0b47750ce25d',routed_dcp_sha256=r['routed_dcp_sha256'],native_tcl_exit_code=0,original_wrapper_status=r['status'],original_wrapper_error='Wrapper searched stdout instead of Tcl result.txt, then raised NameError sys; original receipt remains FAIL',scope='Independent read-only review of completed native audit; no rerun/relabel, image or programming admission',startup=dict(flop_count=65,init='0',structure='64 FDRE delay stages plus registered release, same systemclock, CE1/R0, exact predecessor chain',held_cycles=64,release_edge=65,physical_release_edge_measured=False),dsp=dict(total=515,cmac_products=512,auxiliary=3,AREG=0,BREG=0,MREG=0,PREG=0,cmac_CREG=0,auxiliary_CREG_default_unused=1,USE_DPORT=0,clock_driver_counts=dict(clocks),factory_warning_review_complete=True,factory_warning_findings=2060,warning_rules=['DPIP-1','DPOP-1','DPOP-2'],assessment='Core operands and output groups use the qualified external register boundary; helpers select pure multiply with grounded clocks and inactive default CREG=1. The full routed setup/hold/pulse and internal-constraint coverage pass at20ns. Factory advice is retained without severity/rule changes.'),io=dict(part='xc7k480tffg1156-2',pins={'SYS_CLK':'AA28','pass':'P30','fail':'M30','heartbeat':'N30'},iostandard='LVCMOS18',config_voltage='1.8',cfgbvs='GND',led_active_low=0,optical_polarity_measured=False,rail_or_strap_new_measurement=False),reviewer_source_sha256=sha(__file__),routed_timing_review_sha256=sha(W/'root-timing-review.json'),original_wrapper_report_sha256=sha(L/'report.json'),native_audit_outputs={p.name:sha(p) for p in A.iterdir() if p.is_file()},mapped_functional_qualification_complete=False,image_admission=False,programming_approved=False)
(W/'root-init-drc-review.json').write_text(json.dumps(review,indent=2)+'\n');print(W/'root-init-drc-review.json');print('Reviewed65startupFFs,515combinationalDSPs and2060unchangedfactorywarnings')
