"""Root acceptance of the completed DDR model workload, not global DDR signoff."""
from pathlib import Path
import datetime
import hashlib
import json

ROOT=Path('/home/fedora/rknpu-fpga')
BASE=Path(__file__).resolve().parent
PHYSICAL=BASE/'physical-test/physical-tests'
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def read(path):return json.loads(Path(path).read_text())
parent_path=PHYSICAL/'report.json';parent=read(parent_path)
parent_sha=sha(parent_path)
assert parent['status']=='PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT'
assert parent['memory_profile']=='ddr' and parent['selected_physical_channel']==1
assert parent['forward_positions']==32 and parent['owned_process_groups_absent_before_final_audit']
assert parent['cpu_dense_fallback'] is False and parent['flash_written'] is False
assert parent['owned_worker_exit']==parent['owned_bridge_exit']==0
assert parent['owned_hw_server_exit']==-15
assert len(parent['loads'])==1 and parent['loads'][0]['status']=='PASS'
for row in parent['owned_process_groups']:
    assert not row['live_after'] and not row['zombies_after']
    assert not (Path('/proc')/str(row['pid'])).exists(),row['pid']
assert not Path('/proc/1145189').exists()
actual={str(path.relative_to(PHYSICAL)) for path in PHYSICAL.rglob('*') if path.is_file()}
assert actual==set(parent['artifacts'])|{'report.json'}
for name,digest in parent['artifacts'].items():assert sha(PHYSICAL/name)==digest,name
image_path=BASE/'physical-test/image-review.json';image=read(image_path)
assert sha(image_path)==parent['image_review_sha256']=='223b0dc3cc1a78a804a6f75b1d20baf3649bbe8265b192577580bbf4e258264a'
for name,digest in image['bound_files'].items():assert sha(name)==digest,name
canonical=ROOT/'build/full512-ddr-preparation/full512-bitfile-audit-v2/v12-image-review.json'
assert sha(canonical)=='04ee9140232ebc4c2a263c66eb934c10b9b1ec83fa240a83278b244daf1efb18'
assert sha(image['bitstream']['path'])==parent['bitstream_sha256']=='d627b7155c4a4ad6b948424fbd28240a666ea6071bfe8c5d5b19f7da051b0031'
load_path=PHYSICAL/'load-1/load.json';load=read(load_path)
assert sha(load_path)==parent['loads'][0]['receipt_sha256']
assert load['status']=='PASS' and load['flash_written'] is False
assert load['native']['TARGET']==parent['target']=='localhost:3125/xilinx_tcf/Xilinx/80802026a77a01'
assert load['native']['DNA_PORT']=='004E544714C705C'
assert load['native']['IDCODE_BEFORE']==load['native']['IDCODE_AFTER']=='23751093'
assert load['native']['TCK_HZ']=='3000000' and load['native']['USR_ACCESS']=='5e99f881'
assert load['native']['DONE']==load['native']['INIT_COMPLETE']==load['native']['PASS']=='1'
index=read(BASE/'phase-audit-index.json')
assert [row['phase'] for row in index['phases']]==[
    'one-complete-forward-position','repeated-complete-forward-position','greedy32']
for row in index['phases']:
    assert sha(row['audit_path'])==row['audit_sha256']
    assert sha(row['audit_command_path'])==row['audit_command_sha256']
    assert sha(row['parent_report_snapshot_path'])==row['parent_report_snapshot_sha256']
    command=read(row['audit_command_path'])
    assert command['status']=='PASS' and command['returncode']==0
    assert not command['process_group']['live_after'] and not command['process_group']['zombies_after']
    assert not (Path('/proc')/str(command['pid'])).exists()
    audit=read(row['audit_path'])
    worker=PHYSICAL/row['phase']/'jobs/report.json'
    assert sha(worker)==row['worker_report_sha256']==audit['worker_report_sha256']
    assert audit['image_review_sha256']==parent['image_review_sha256']
    assert audit['positions']==(32 if row['phase']=='greedy32' else 1)
    assert audit['status']==row['status']
root_audit_path=BASE/'root-independent-full32-raw-audit.json';audit=read(root_audit_path)
assert audit['status']=='PASS_INDEPENDENT_PHYSICAL_DDR_TINYSTORIES_32_POSITION_RAW_WIRE_MODEL_AUDIT'
assert audit['full32_positions_accepted'] is True and audit['memory_profile']=='ddr'
assert audit['positions']==32 and audit['raw_jobs']==7424 and audit['tasks']==11136
assert audit['actual_projection_pairs']==1152 and audit['output_bo_bytes']==30408704
assert audit['weight_tiles_checked_before_use']==3712
assert audit['wire']['scans']==2984893 and audit['wire']['commands']==994963
assert audit['physical_report_sha256']==parent_sha
stored=read(index['phases'][-1]['audit_path'])
for key in ('positions','raw_jobs','tasks','actual_projection_pairs','output_bo_bytes','logits_sha256',
            'generated_tokens','text','wire','worker_report_sha256','physical_report_sha256'):
    assert audit[key]==stored[key],key
worker_path=PHYSICAL/'greedy32/jobs/report.json';worker=read(worker_path)
assert worker['completed_positions']==32 and worker['completed_projections']==1152
assert worker['logit_values']==16384 and worker['raw_jobs']==7424 and worker['raw_completed_tasks']==11136
assert worker['cpu_dense_fallback'] is False and worker['bridge_quit_ack'] is True
assert len(worker['result']['generated_tokens'])==28
assert worker['result']['generated_tokens']==audit['generated_tokens']
assert worker['memory_namespace_status_checks']['ew']['status']==worker['memory_namespace_status_checks']['cmac']['status']=='0x010'
bram_path=ROOT/'build/tinystories-streaming-model-audit/full32-idle-wait-v1.json'
bram=read(bram_path)
assert bram['logits_sha256']==audit['logits_sha256'] and bram['generated_tokens']==audit['generated_tokens']
assert sha(parent_path)==parent_sha
result={
    'status':'PASS_ROOT_REVIEWED_COMPLETE_FULL512_CH1_DDR_TINYSTORIES_INFERENCE',
    'accepted':True,'full32_positions_accepted':True,
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer_sha256':sha(__file__),
    'source_tag':'5e99f881','bitstream_sha256':parent['bitstream_sha256'],
    'canonical_image_review_sha256':sha(canonical),'model_image_review_sha256':sha(image_path),
    'physical_report_sha256':parent_sha,'worker_report_sha256':sha(worker_path),
    'independent_root_raw_audit_sha256':sha(root_audit_path),'original_public_audit_sha256':index['phases'][-1]['audit_sha256'],
    'source_bound_files_rehashed':len(image['bound_files']),'physical_artifacts_rehashed':len(parent['artifacts']),
    'positions':32,'learned_fpga_projections':1152,'raw_jobs':7424,'tasks':11136,
    'exact_logits':16384,'generated_tokens':28,'complete_output_bo_bytes_before_ack':30408704,
    'actual_scans':2984893,'actual_commands':994963,'logits_sha256':audit['logits_sha256'],
    'text':audit['text'],'same_loaded_epoch_first_and_repeated_bos':True,
    'matches_prior_bram_full32_logits_and_tokens':True,'single_volatile_load':True,
    'owned_process_groups_closed':True,'parent_receipt_rewritten':False,
    'hardware_accessed_by_review':False,'flash_written':False,
    'full_capacity_ecc_injection_recovery_pcie_and_rk_equivalence_qualified':False,
    'scope':'Selected one-prompt hybrid TinyStories workload; every learned projection on full512 FPGA/CH1 DDR; CPU host operators explicit',
}
with (BASE/'root-full32-review.json').open('x') as stream:
    json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps(result,sort_keys=True))
