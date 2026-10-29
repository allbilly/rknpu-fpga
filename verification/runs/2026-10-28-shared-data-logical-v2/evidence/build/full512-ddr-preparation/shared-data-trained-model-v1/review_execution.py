"""Independent current-source/whole-BO/stage-order audit of the trained run."""
from pathlib import Path
import datetime,hashlib,json,re
BASE=Path(__file__).resolve().parent;RUN=BASE/'execution-v1';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
r=json.loads((RUN/'report.json').read_text());p=json.loads((BASE/'preparation.json').read_text());c=json.loads((BASE/'native-compile-v1/report.json').read_text())
need(r['status']=='PASS_TRAINED_CMAC_EW_CMAC_SAME_EPOCH_CONTROLLER_MODEL_ONLY' and r['returncode']==r['owned_child_exit']==0,'Producer not terminal successful execution')
need(r['binary_sha256']==c['binary_sha256']==sha(c['binary_path'])=='9bd3ce2690c9c28d81abbd9a3b440ad6addafed148d611b8257d5953558c9f9c','Wrong executed ELF')
need(r['all_inputs_unchanged'] is True and r['timeout_seconds']==3600 and r['seconds']<3600,'Changed source/deadline')
for n,h in r['inputs'].items():need(sha(n)==h,'Changed executed source: '+n)
need(sha(RUN/'stdout.log')==r['stdout_sha256'] and not (RUN/'stderr.log').read_bytes() and sha(RUN/'stderr.log')==r['stderr_sha256'],'Changed native output')
text=(RUN/'stdout.log').read_text();need(not re.search(r'(?mi)^FATAL:|^ERROR:|^FAIL|Assertion failed|\bwarning:',text),'Native diagnostic')
marker='PASS trained_tile_dual_ddr cmac_jobs=2 ew_tasks=2 engine_writes=96 rearm=2 checked_bo_lines=4224 phy_user_returns=27614 read64_packets=4226 read64_axi_reads=4226 scope=actual_AXI_UI_MC_modeled_PHY'
need([x for x in text.splitlines() if x.startswith('PASS ')]==[marker],'Changed final numerical/traffic marker')
expected=[(-1,'initialized',0,0,1),(0,'uploaded',265,0,17027),(0,'submitted',265,0,17027),(0,'retired',265,32,19432),(0,'readback_before_ack',265,32,20840),(0,'acknowledged',265,32,20840),(1,'uploaded',274,32,21416),(1,'submitted',274,32,21416),(1,'retired',274,64,21689),(1,'readback_before_ack',274,64,23097),(1,'acknowledged',274,64,23097),(2,'uploaded',285,64,23801),(2,'submitted',285,64,23801),(2,'retired',285,96,26206),(2,'readback_before_ack',285,96,27614),(2,'acknowledged',285,96,27614)]
observed=[];times=[]
for line in text.splitlines():
 if line.startswith('TRAINED_DDR '):
  m=re.fullmatch(r'TRAINED_DDR phase=(-?\d+) stage=(\w+) time=(\d+) uploaded_lines=(\d+) engine_writes=(\d+) phy_returns=(\d+)',line);need(m is not None,'Malformed stage witness')
  phase,stage,timestamp,uploads,writes,returns=m.groups();observed.append((int(phase),stage,int(uploads),int(writes),int(returns)));times.append(int(timestamp))
need(observed==expected and times==sorted(times),'Wrong readback/ACK stage order or intermediate counter')
vectors=Path(p['vectors']);captures=[]
for phase in ['cmac','ew','repeat']:
 actual=RUN/(phase+'-actual.txt');original=vectors/(phase+'_expected.txt');need(actual.read_bytes()==original.read_bytes(),'Actual BO differs from original source')
 rows=actual.read_text().splitlines();need(len(rows)==1408 and actual.stat().st_size==194304,'Incomplete actual ASCII BO')
 addresses=[]
 for row in rows:
  need(re.fullmatch(r'[0-9a-f]{8} [0-9a-f]{128}',row) is not None,'Malformed raw address/BO line');addresses.append(int(row.split()[0],16))
 need(addresses==sorted(set(addresses)) and all(a%64==0 for a in addresses),'Duplicate/unaligned actual BO lines')
 captures.append(dict(phase=phase,raw_bytes=90112,ascii_bytes=194304,sha256=sha(actual)))
parent=BASE.parent/'trained-alternation-source-v2';need(sha(p['bench'])==sha(parent/'tb_jtag_dual_ddr_async.sv'),'Trained bench changed')
for path in vectors.iterdir():
 if path.is_file():need(sha(path)==sha(parent/'vectors'/path.name),'Original trained vectors changed')
record=dict(status='PASS_INDEPENDENT_SHARED_DATA_TRAINED_TILE_SAME_EPOCH_CONTROLLER_REUSE_ONLY',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),producer_sha256=sha(RUN/'report.json'),binary_sha256=r['binary_sha256'],inputs_rehashed=len(r['inputs']),raw_jobs=3,cmac_jobs=2,ew_tasks=2,engine_writes=96,cmac_safe_rearms=2,checked_full_bo_bytes=270336,phy_user_returns=27614,read64_packets=4226,read64_axi_reads=4226,captures=captures,readback_then_ack_stage_order_exact=True,original_trained_commands_and_deltas_unchanged=True,native_seconds=r['seconds'],arithmetic_profile='PRIVATE_SHARED_DATA_CANDIDATE',complete_fault_matrix_qualified=False,full_model_or_physical_ddr_qualified=False,hardware_accessed=False)
out=BASE/'root-execution-review-v1.json';need(not out.exists(),'Fresh root review required');out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
