"""Derive route inputs only from fresh retirement synthesis and root-reviewed source gates."""
from pathlib import Path
import datetime
import hashlib
import json
import re

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
PREP=ROOT/'build/full512-capacity-retire-route-prep-v1'
SYNTH=ROOT/'build/full512-capacity-retire-vivado-run-v1'
SOURCE=ROOT/'build/full512-capacity-retire-vivado-prep-v1'
FAST=ROOT/'build/full512-capacity-retire-fast-model-v1/root-result-review.json'
PAIRED=ROOT/'build/full512-capacity-retire-snapshot-controls-v1/root-paired-v3-review.json'
CONTROLLER=ROOT/'build/full512-capacity-retire-controller-v1/root-result-review.json'
SYNTH_REVIEW_STATUS='PASS_ROOT_FRESH_FULL512_RETIRE_SYNTHESIS_ONLY'
SYNTH_PRODUCER_STATUS='PASS_FRESH_FULL512_RETIRE_SYNTHESIS_ONLY'
FAST_STATUS='PASS_ROOT_RETIRE_SNAPSHOT_FAST_PARENT_MODEL_ONLY'
PAIRED_STATUS='PASS_ROOT_PAIRED_RETIRE_ADAPTER_AND_MONITOR_CONTRACT_ONLY'
CONTROLLER_STATUS='PASS_ROOT_FULL512_RETIRE_CAPACITY_CONTROLLER_MODEL_ONLY'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def need(condition,message):
    if not condition:
        raise RuntimeError(message)


def write_exclusive(path,value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value,indent=2,sort_keys=True)+'\n')


def main():
    # Do not inspect or derive anchors from any old admission-profile checkpoint.
    review_path=SYNTH/'root-synth-review.json'
    if not review_path.is_file():
        print(json.dumps(dict(status='PENDING_ROOT_FRESH_FULL512_RETIRE_SYNTHESIS_ONLY',
                              native_launched=False,hardware_accessed=False)))
        return 0
    review=load(review_path)
    need(review.get('status')==SYNTH_REVIEW_STATUS,'Fresh retirement synthesis root review not passed')
    producer_path=SYNTH/'report.json'
    producer=load(producer_path)
    need(producer.get('status')==SYNTH_PRODUCER_STATUS and
         producer.get('all_inputs_unchanged') is True and producer.get('all_owned_groups_stopped') is True,
         'Fresh retirement synthesis producer is incomplete')
    need(sha(producer_path)==review.get('producer_sha256'),'Root review does not bind exact synth producer')
    need(producer.get('input_hashes_before')==producer.get('input_hashes_after'),'Fresh synth inputs changed')
    for path,digest in producer['input_hashes_before'].items():
        need(sha(path)==digest,'Changed retirement synthesis input: '+path)
    for path,digest in producer.get('outputs',{}).items():
        need(sha(path)==digest,'Changed retirement synthesis output: '+path)
    dcp=SYNTH/'output/post_opt.dcp'
    need(dcp.is_file() and sha(dcp)==review.get('post_opt_dcp_sha256'),'Fresh post-opt DCP missing/mismatched')

    # These are retirement-candidate gates, never the predecessor admission results.
    gate_specs=[
      ('fast_parent',FAST,FAST_STATUS),
      ('paired_adapter_monitor',PAIRED,PAIRED_STATUS),
      ('capacity_controller',CONTROLLER,CONTROLLER_STATUS)]
    gate_rows={}
    for name,path,status in gate_specs:
        if not path.is_file():
            print(json.dumps(dict(status='PENDING_RETIREMENT_ROUTE_SOURCE_GATES',missing=name,
                                  native_launched=False,hardware_accessed=False)))
            return 0
        gate=load(path)
        need(gate.get('status')==status,'Fresh retirement source gate failed: '+name)
        gate_rows[name]=dict(path=str(path),sha256=sha(path),status=status)

    manifest_path=SOURCE/'source-copy-manifest.json'
    manifest=load(manifest_path)
    source_preparation_path=SOURCE/'preparation.json'
    source_preparation=load(source_preparation_path)
    rows=manifest.get('files',[])
    need(manifest.get('file_count')==len(rows)==171 and manifest.get('hdl_count')==163 and
         manifest.get('xdc_count')==2 and manifest.get('constraint_helper_count')==6,
         'Retirement source-copy inventory changed')
    need(source_preparation.get('source_copy_manifest_path')==str(manifest_path) and
         source_preparation.get('source_copy_manifest_sha256')==sha(manifest_path),
         'Retirement preparation is not bound to its exact source-copy manifest')
    adapter_path=ROOT/'build/full512-capacity-retire-snapshot-variant-v1/rk_ddr_capacity_axi.sv'
    derivation_path=Path(source_preparation['candidate_derivation_path'])
    need(source_preparation.get('candidate_derivation_sha256')==sha(derivation_path) and
         source_preparation.get('candidate_adapter_path')==str(adapter_path) and
         source_preparation.get('candidate_adapter_sha256')==sha(adapter_path),
         'Retirement preparation candidate derivation/adapter binding changed')
    adapter_rows=[row for row in rows if row.get('relative_path')=='hdl/158/rk_ddr_capacity_axi.sv']
    need(len(adapter_rows)==1 and adapter_rows[0].get('origin_path')==str(adapter_path) and
         adapter_rows[0].get('origin_sha256')==sha(adapter_path),
         'Retirement snapshot adapter source binding changed')
    for path in (source_preparation_path,manifest_path,derivation_path,adapter_path):
        expected=producer['input_hashes_before'].get(str(path))
        need(expected==sha(path),'Fresh synthesis producer does not bind retirement input: '+str(path))
    input_files=dict(producer['input_hashes_before'])
    for row in rows:
        need(sha(row['copied_path'])==row['copied_sha256'],'Retirement source changed: '+row['relative_path'])
        input_files[row['copied_path']]=row['copied_sha256']

    facts_path=SYNTH/'output/constrained_synthesis_facts.tsv'
    facts=[line.split('\t') for line in facts_path.read_text().splitlines()]
    observations=[row for row in facts if row[:2]==['ZERO_NET','post_opt']]
    need(len(observations)==101 and all(row[7:11]==['GROUND','1','1','1'] for row in observations),
         'Fresh retirement post-opt anchors incomplete')
    anchors=sorted({row[6] for row in observations})
    need(len(anchors)==3,'Unexpected retirement post-opt anchor inventory')
    anchor_path=BASE/'expected-anchors.txt'
    with anchor_path.open('x') as stream:
        stream.write('\n'.join(anchors)+'\n')

    template=PREP/'route.tcl.in'
    text=template.read_text()
    need(text.count('@POST_OPT_DCP_SHA256@')==1,'Ambiguous DCP hash substitution token')
    rendered=text.replace('@POST_OPT_DCP_SHA256@',sha(dcp))
    need(not re.search(r'@[A-Z0-9_]+@',rendered),'Unresolved route template token')
    route_tcl=PREP/'route.tcl'
    with route_tcl.open('x') as stream:
        stream.write(rendered)
    source_manifest_sha=sha(manifest_path)
    route_env=dict(RK_CAPACITY_ROUTE_POST_OPT_DCP=str(dcp.resolve()),
                   RK_CAPACITY_ROUTE_POST_OPT_DCP_SHA256=sha(dcp),
                   RK_CAPACITY_ROUTE_EXPECTED_ANCHOR_FILE=str(anchor_path.resolve()),
                   RK_CAPACITY_ROUTE_SOURCE_MANIFEST_SHA256=source_manifest_sha)
    preparation=dict(status='PREPARED_FULL512_RETIRE_ROUTE_FROM_FRESH_SYNTH',
      top='ypcb_ddr_dual_top',part='xc7k480tffg1156-2',
      vivado_launcher='/home/fedora/vivado/2026.1/Vivado/bin/vivado',
      synth_tcl=str(route_tcl.resolve()),route_environment=route_env,
      source_count=171,source_profile='full512 CH1 retirement-compressed capacity adapter',
      fresh_synthesis_review_path=str(review_path),fresh_synthesis_review_sha256=sha(review_path),
      fresh_synthesis_report_path=str(producer_path),fresh_synthesis_report_sha256=sha(producer_path),
      post_opt_dcp_path=str(dcp.resolve()),post_opt_dcp_sha256=sha(dcp),
      source_manifest_path=str(manifest_path.resolve()),source_manifest_sha256=source_manifest_sha,
      expected_anchor_path=str(anchor_path.resolve()),expected_anchor_sha256=sha(anchor_path),
      retirement_source_gates=gate_rows,
      root_route_approval_path=str(BASE/'root-review.json'),
      root_route_approval_status='ROOT_APPROVED_FULL512_RETIRE_FRESH_PLACE_ROUTE_ONLY',
      route_timing_review_status='PASS_ROOT_FULL512_RETIRE_ROUTE_TIMING',
      route_runner_success_status='PASS_FRESH_FULL512_RETIRE_ROUTE_REQUIRES_ROOT_REVIEW',
      scope='Fresh placement/route only; no bitstream, hardware, memory-retirement or PHY claim.',
      prospective_limits=dict(memory_gib=12,cpu=4,swap=0,pids=512,deadline_seconds=14400,
                              host_available_min_gib=20))
    preparation_path=BASE/'preparation.json'
    write_exclusive(preparation_path,preparation)

    bound=dict(input_files)
    for path in [review_path,producer_path,facts_path,dcp,manifest_path,adapter_path,
                 source_preparation_path,derivation_path,FAST,PAIRED,CONTROLLER,
                 Path(__file__),BASE/'run_route.py',BASE/'review_route.py',
                 BASE/'prelaunch-resource-profile.json',preparation_path,anchor_path,template,route_tcl,
                 PREP/'preparation.json',PREP/'static-audit.json',*sorted((PREP/'helpers').glob('*.tcl'))]:
        bound[str(path.resolve())]=sha(path)
    write_exclusive(BASE/'input-manifest.json',dict(files=bound,source_count=171,
        source_manifest_sha256=source_manifest_sha,anchor_names=anchors,
        retirement_source_gates={name:row['sha256'] for name,row in gate_rows.items()}))
    print(json.dumps(dict(status=preparation['status'],inputs=len(bound),anchors=anchors,
                          native_launched=False,hardware_accessed=False)))


if __name__=='__main__':
    raise SystemExit(main())
