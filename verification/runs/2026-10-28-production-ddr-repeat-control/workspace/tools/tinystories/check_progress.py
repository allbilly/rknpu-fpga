#!/usr/bin/env python3
"""Read-only completed-prefix comparison; never full hardware qualification.

Running/failed producers retain their own status. Only completion markers
already counted in the atomic worker report are inspected, so unmarked or
partially written trailing rows cannot be accepted. Raw-wire audit is separate.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.ddr.interface import load_json,require
from tools.tinystories.prepare import MODEL_SHA,TOKENIZER_SHA


def sha(data):return hashlib.sha256(data).hexdigest()


def counted_rows(path,count,complete):
    rows=[]
    if count==0 and not complete and not Path(path).exists():return rows
    with Path(path).open('rb') as stream:
        for _ in range(count):
            row=stream.readline()
            require(row.endswith(b'\n'),'Counted progress row is incomplete/missing')
            rows.append(json.loads(row))
        if complete:require(stream.read()==b'','Completed producer has extra progress data')
    return rows


def check(worker,reference):
    worker,reference=Path(worker).resolve(),Path(reference).resolve()
    report_bytes=(worker/'report.json').read_bytes();report=json.loads(report_bytes)
    require(report['backend'] in ('oracle','jtag') and report['model_sha256']==MODEL_SHA and
            report['tokenizer_sha256']==TOKENIZER_SHA,'Unsupported model/reference policy')
    require(report['steps']==32 and report['prompt']=='Once upon a time' and report['cpu_dense_fallback'] is False,
            'This reference applies only to the fixed32-position workload')
    allowed=('RUNNING','FAIL','PASS_CPU_MODEL_REFERENCE_ONLY',
             'PASS_PHYSICAL_HYBRID_MODEL_EXECUTION_REQUIRES_INDEPENDENT_AUDIT')
    require(report['status'] in allowed,'Unsupported producer status')
    completed=report['status'].startswith('PASS_')
    if completed:
        require((report['backend']=='oracle')==(report['status']=='PASS_CPU_MODEL_REFERENCE_ONLY'),
                'Producer completion status disagrees with its backend')
    positions,projections=report['completed_positions'],report['completed_projections']
    require(type(positions) is int and type(projections) is int and 0<=positions<=32 and
            positions*36<=projections<=min(1152,(positions+1)*36),'Inconsistent completed coverage')
    if completed:require(positions==32 and projections==1152,'Short producer cannot claim completion')
    ref=load_json(reference/'report.json')
    require(ref['status']=='PASS_CPU_FULL_TINYSTORIES_DONOR_POLICY_REFERENCE_ONLY' and
            ref['hardware_accessed'] is False,'Unqualified same-policy reference')
    for name in ('donor-result.json','donor-logits.bin','donor-dense-calls.json'):
        require(sha((reference/name).read_bytes())==ref['artifacts'][name],'Reference artifact changed')
    result=load_json(reference/'donor-result.json');gold=(reference/'donor-logits.bin').read_bytes()
    dense=load_json(reference/'donor-dense-calls.json')
    require(result['forward_positions']==32 and result['dense_calls']==1152 and
            len(gold)==32*2048 and len(dense)==1152,'Incomplete reference coverage')
    rows=counted_rows(worker/'positions.jsonl',positions,completed)
    calls=counted_rows(worker/'projection-calls.jsonl',projections,completed)
    actual=b''
    if positions or completed or (worker/'logits.bin').exists():
        with (worker/'logits.bin').open('rb') as stream:
            actual=stream.read(positions*2048)
            require(len(actual)==positions*2048,'Missing counted logit bytes')
            if completed:require(stream.read()==b'','Completed producer has uncounted logit bytes')
    require(actual==gold[:len(actual)],'Counted logits differ from fixed same-policy reference')
    pieces=bytearray();generated=[]
    prompt=result['prompt_tokens']
    keys={'position','input_token','next_token','forced_prompt','stop','piece_hex',
          'logits_offset','logits_bytes','logits_sha256','utc'}
    for index,row in enumerate(rows):
        require(set(row)==keys,'Unknown completed position fields')
        forced=index<len(prompt)-1
        token=prompt[index+1] if forced else result['generated_tokens'][index-(len(prompt)-1)]
        block=actual[index*2048:(index+1)*2048]
        require(row['position']==index and row['input_token']==result['input_tokens'][index] and
                row['next_token']==token and type(row['forced_prompt']) is bool and row['forced_prompt']==forced and
                type(row['stop']) is bool and row['stop']==(token==1),'Recorded token/position differs')
        require(row['logits_offset']==index*2048 and row['logits_bytes']==2048 and
                row['logits_sha256']==sha(block),'Position marker/logit binding differs')
        pieces.extend(bytes.fromhex(row['piece_hex']))
        if not forced:generated.append(token)
    text=pieces.decode('utf-8',errors='replace')
    require(result['text'].startswith(text),'Recorded text is not the reference prefix')
    prefix=report.get('prefix',dict(completed_positions=0,generated_tokens=[],text=''))
    require(prefix['completed_positions']==positions and prefix['generated_tokens']==generated and
            prefix['text']==text,'Atomic report and completed position records differ')
    for index,call in enumerate(calls):
        require(all(call[k]==dense[index][k] for k in ('name','input_fp16_sha256','output_fp16_sha256')),
                'Completed dense byte receipt differs from independent reference')
    if completed:
        require(generated==result['generated_tokens'] and text==result['text'],'Complete output differs')
    return dict(status='MATCHED_RECORDED_COMPLETED_PREFIX_ONLY' if positions or projections else 'NO_COMPLETED_PREFIX_YET',
        producer_status=report['status'],completed_positions_checked=positions,completed_projection_pairs_checked=projections,
        logits_values_checked=positions*512,prefix_logits_sha256=sha(actual),generated_tokens=generated,text=text,
        observed_atomic_report_sha256=sha(report_bytes),reference_report_sha256=sha((reference/'report.json').read_bytes()),
        raw_wire_audited=False,full_hardware_run_accepted=False,hardware_accessed=False,
        scope='Recorded completed-prefix consistency/differential check only; producer status unchanged and raw BO/wire/image audit still required',
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh in-workspace checkpoint receipt required')
    result=check(args.worker,args.reference);result['checker_sha256']=sha(Path(__file__).read_bytes())
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n')
    print(result['status'],result['completed_positions_checked'],result['completed_projection_pairs_checked'])


if __name__=='__main__':main()
