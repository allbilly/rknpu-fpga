"""Independent exact-image, target, complete-wire and recovery review."""
from pathlib import Path
import datetime,hashlib,importlib.util,json,re,sys

ROOT=Path('/home/fedora/rknpu-fpga');BASE=Path(__file__).resolve().parent;OUT=BASE/'physical-test'
sys.path.insert(0,str(ROOT))
from tools.ddr.audit_raw_case import replay as replay_raw
from tools.ddr.audit_capacity import audit as audit_capacity
from tools.tinystories.audit_scans import commands

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(p):return json.loads(Path(p).read_text())
def need(ok,message):
    if not ok:raise RuntimeError(message)
def verify(mapping,base=None):
    for p,h in mapping.items():need(sha((base/p) if base is not None else p)==h,'Changed qualified file '+str(p))
def group_members(pgid):
    found=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            fields=(p/'stat').read_text().rsplit(')',1)[1].split()
            if int(fields[2])==pgid and fields[0] not in ('Z','X'):found.append(int(p.name))
        except (OSError,ValueError,IndexError):pass
    return found

p=OUT/'report.json';producer_sha=sha(p);r=load(p);prep=load(BASE/'preparation.json')
need(r['status']=='PASS_DEVICE_FULL512_RETIRE_CAPACITY_AND_RECONFIGURED_RAW_JOBS_REQUIRES_ROOT_REVIEW','Physical trial incomplete/failed')
need(r['hardware_accessed'] is True and r['hardware_programmed'] is True and r['flash_written'] is False,'Wrong actual programming scope')
need(r['live_joint_reset_tested'] is False and r['ecc_injection_qualified'] is False and r['pcie_tested'] is False,'Unsupported physical claim')
verify(prep['frozen_inputs']);image=load(BASE/'image-review.json');approval=load(BASE/'execution-approval.json')
need(sha(BASE/'image-review.json')==prep['image_review_sha256']==r['image_review_sha256'],'Image review binding drift')
need(sha(BASE/'execution-approval.json')==prep['execution_approval_sha256']==r['execution_approval_sha256'],'Execution binding drift')
need(image['status']=='PASS_ROOT_REVIEWED_FULL512_RETIRE_IMAGE' and approval['status']=='ROOT_APPROVED_FULL512_RETIRE_VOLATILE_TRIAL' and approval['approved'] is True,'Actual image/execution approval missing')
verify(image['bound_files']);verify(prep['hardware_source_manifest']['files'])
need(sha(image['bitstream_path'])==image['bitstream_sha256']==r['bitstream_sha256']=='de982cd7e6c41d13de8e1f047c92fd515ab590e6958339a1dd37135642bef2a4','Wrong tested bitfile')
need(r['source_tag']==image['source_tag']==prep['source_tag']=='2c8f17dd','Wrong tested source tag')
need(r['target']==image['target']=='localhost:3125/xilinx_tcf/Xilinx/80802026a77a01' and
     r['expected_dna_port']==image['expected_dna_port']=='004E544714C705C' and
     r['expected_raw_idcode']==image['expected_raw_idcode']=='23751093','Wrong audited target')
need(r['lease_admission']['lease_inode']==prep['lease_inode']==9121364 and not r['lease_admission']['controllers'],'Wrong lease/concurrent controller')
need(Path(prep['lease_path']).stat().st_ino==9121364,'Shared lease replaced')
verify(r['artifacts'],OUT)
need(set(r['artifacts'])=={str(q.relative_to(OUT)) for q in OUT.rglob('*') if q.is_file() and q!=p},'Incomplete physical artifact census')
need(r['owned_groups_absent_before_lease_release'] is True and len(r['owned_groups'])==9,'Incomplete owned process cleanup')
for g in r['owned_groups']:
    need(not g['members_after'] and not g['zombies_after'] and not group_members(g['pgid']),'Owned group remains live')
    need(g['returncode'] in ((0,-15) if g['pid']==r['hw_server_pid'] else (0,)),'Owned native operation failed')
need([x['epoch'] for x in r['load_receipts']]==[1,2],'Both deliberate SRAM configurations required')
versions=[]
for row in r['load_receipts']:
    receipt_path=Path(row['path']);need(sha(receipt_path)==row['sha256'],'Programming receipt changed')
    fields={}
    for line in receipt_path.read_text().splitlines():
        k,v=line.split('\t',1);need(k not in fields,'Duplicate programming field');fields[k]=v
    expected=dict(TARGET=r['target'],DNA_PORT='004E544714C705C',TCK_HZ='3000000',IDCODE_BEFORE='23751093',IDCODE_AFTER='23751093',
        PROGRAM_FILE=image['bitstream_path'],BITSTREAM_SHA256=r['bitstream_sha256'],PROGRAM_RETURNED='1',INIT_COMPLETE='1',DONE='1',
        USR_ACCESS='2c8f17dd',PROGRAMMED='1',CLEANUP='1',PASS='1')
    need(fields==expected,'Target/image/configuration receipt differs')
    directory=receipt_path.parent;cmd=load(directory/'command.json')
    need(cmd['returncode']==0 and cmd['cleanup']['returncode']==0 and not cmd['cleanup']['members_after'],'Load did not finish naturally')
    need(sha(directory/'program.tcl')==cmd['script_sha256'],'Generated loader changed')
    text=(directory/'stdout.log').read_text()
    need('PASS_FULL512_DUAL_DDR_VOLATILE_SRAM_LOAD' in text,'Missing audited loader marker')
    version=[line for line in text.splitlines() if 'Vivado Lab Edition v' in line or 'SW Build ' in line]
    need(version,'Missing actual physical tool version');versions.append(version[:2])

need([x['name'] for x in r['phases']]==['scratch','epoch-1-cmac','epoch-1-ew','capacity','epoch-2-cmac','epoch-2-ew'],'Wrong physical phase order')
spec=importlib.util.spec_from_file_location('root_scratch_wire_audit',prep['scratch_auditor_path'])
scratch=importlib.util.module_from_spec(spec);spec.loader.exec_module(scratch)
summary=[];totals={'scans':0,'commands':0};bo_bytes=0;jobs=tasks=0
for row in r['phases']:
    name=row['name'];directory=OUT/name;trace=directory/'native-scans.jsonl';audit_path=directory/'independent-wire-audit.json'
    need(row['status']=='PASS_DEVICE_PHASE_REQUIRES_WIRE_AUDIT' and sha(trace)==row['trace_sha256'] and
         sha(audit_path)==row['wire_audit_sha256'],'Physical phase/trace/audit drift')
    need(row['bridge_cleanup']['returncode']==0 and not row['bridge_cleanup']['members_after'],'Bridge not naturally stopped')
    need(sha(directory/'bridge/bridge.tcl')==row['bridge_script_sha256'],'Bridge script drift')
    stats={}
    if name=='scratch':
        a=scratch.replay(commands(trace,stats));need(a['checked_bytes']==768,'Wrong scratch byte census')
        saved=load(audit_path);need(all(saved.get(k)==v for k,v in a.items()),'Scratch replay differs')
    elif name=='capacity':
        a=audit_capacity(trace);stats=a['scan_statistics'];need(a==load(audit_path),'Fresh capacity replay differs')
        result=row['result'];need(result['device_status']==0x68 and result['completed_writes']==result['completed_reads']==67108864 and
            result['base']==0 and result['size']==1<<31 and result['full_window_executed'] is True and result['seed']==0x3588c350,'Wrong complete physical sweep witness')
        need(result['fault_codes']==result['fault_sources']==0 and a['lines_per_trial']==33554432 and a['trials']==2,'Physical BIST failure or partial span')
        progress=[json.loads(line) for line in (directory/'progress.jsonl').read_text().splitlines()]
        need(len(progress)==a['snapshots'] and progress[-1]['status']==0x68,'Incomplete actual progress history')
    else:
        profile='cmac' if name.endswith('cmac') else 'ew';case=next(c for c in prep['normal_cases'] if c['profile']==profile)
        a=replay_raw(commands(trace,stats),case['upload'],case['expected'],profile=profile,command_address=case['command_address'],amount=case['amount'],tasks=case['tasks'],tag=case['tag'])
        saved=load(audit_path);need(all(saved.get(k)==v for k,v in a.items()) and saved['scan_statistics']==stats,'Fresh raw-job replay differs')
        need(sha(directory/'observed.txt')==sha(case['expected']),'Actual complete BO differs from unchanged golden')
        need(row['result']['checked_bo_bytes']==a['complete_bo_bytes'] and row['result']['cpu_arithmetic_or_layout_repair'] is False and
            row['result']['source_commands_rewritten'] is False,'Wrong raw execution boundary')
        bo_bytes+=a['complete_bo_bytes'];jobs+=1;tasks+=case['tasks']
    need(stats['idcodes']==stats['tap_resets']==1 and stats['commands']>0 and stats['scans']>0,'Incomplete actual TAP trace')
    for k in totals:totals[k]+=stats[k]
    summary.append(dict(name=name,trace_sha256=sha(trace),audit_sha256=sha(audit_path),scan_statistics=stats))
need((jobs,tasks,bo_bytes)==(4,6,245760),'Incomplete pre/post-reconfiguration numerical coverage')
verify(prep['frozen_inputs']);verify(image['bound_files']);verify(r['artifacts'],OUT);need(sha(p)==producer_sha,'Producer mutated during independent review')
result=dict(status='PASS_ROOT_PHYSICAL_FULL512_TWO_GIB_CAPACITY_AND_RECONFIGURED_RAW_JOBS',
    utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),reviewer_sha256=sha(__file__),producer_sha256=producer_sha,
    source_manifest_sha256=prep['source_manifest_sha256'],source_tag='2c8f17dd',bitstream_sha256=r['bitstream_sha256'],
    target=r['target'],dna_port=r['expected_dna_port'],raw_idcode=r['expected_raw_idcode'],frequency_hz=3000000,
    physical_tool_versions=versions,frozen_inputs_rehashed=len(prep['frozen_inputs']),physical_artifacts_rehashed=len(r['artifacts']),
    phase_reviews=summary,total_scan_statistics=totals,capacity_base=0,capacity_bytes=1<<31,lines_per_trial=33554432,trials=2,
    completed_writes=67108864,completed_reads=67108864,device_status='0x68',fault_codes=0,fault_sources=0,
    four_retirement_ECC_witnesses_required_by_qualified_mapped_BIST=True,independent_external_fence_event_counter=False,
    memory_payloads_of_entire_sweep_observed_on_jtag=False,full_capacity_qualified=True,
    deliberate_volatile_loads=2,normal_jobs=jobs,normal_tasks=tasks,complete_normal_BO_bytes_before_ACK=bo_bytes,scratch_bytes=768,
    recovery_path='Audited volatile reconfiguration, full hardware initialization, original BO reload and raw K65/SUB9 execution',
    owned_groups_absent_before_lease_release=True,flash_written=False,live_joint_reset_tested=False,
    ecc_injection_qualified=False,pcie_tested=False,full_TinyStories_on_this_image_qualified=False,
    scope='Exact retirement-capacity bitfile/target and six complete actual scan traces. Full two-trial 2GiB mapped BIST management witnesses plus pre/post-reconfiguration raw numerical execution. The BIST compares internally; USER2 does not dump all DDR payloads. No physical FI/PCIe/live-reset/full-model/RK-equivalence claim.')
with (BASE/'root-result-review.json').open('x') as f:f.write(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('phase_reviews','physical_tool_versions')},sort_keys=True))
