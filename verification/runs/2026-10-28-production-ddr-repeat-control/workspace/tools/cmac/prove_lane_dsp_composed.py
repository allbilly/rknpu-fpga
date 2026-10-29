#!/usr/bin/env python3
"""Compose source-bound binary sum/tag equivalence; no physical signoff.

Positive result is a checked mathematical composition of executed SAT lemmas,
actual source wiring/ranges and an exact integer product certificate, not a
new monolithic positive SAT run. Fresh full native lowering and a real SAT
bit-flip negative are required. No narrowed binary domain, runtime CPU fixup,
new X/reset/full-array/mapped/physical/RK acceptance or promotion.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
from test_fixed_array_board import verify_manifest
from check_lane_dsp import SOURCES,TOP,validate_graph,sanity_miter
import audit_lane_dsp_product as product

CONTRACT=ROOT/'tests/cmac/dsp_lane_composition_contract.json'


def canonical_module(text,name,exclusive):
    text=re.sub(r'/\*.*?\*/','',text,flags=re.S)
    text=re.sub(r'//[^\n]*','',text)
    names=re.findall(r'\bmodule\s+(\w+)\b',text)
    assert names.count(name)==1 and (not exclusive or names==[name]),'Extra or missing glue module'
    match=re.search(r'\bmodule\s+'+re.escape(name)+r'\b',text)
    tail=text[match.start():];end=re.search(r'\bendmodule\b',tail)
    assert end
    if exclusive:
        prefix=re.sub(r'\s+',' ',text[:match.start()]).strip()
        suffix=re.sub(r'\s+',' ',tail[end.end():]).strip()
        assert prefix in ('','`timescale 1ns/1ps') and not suffix,'Unmodeled preprocessor/glue statements'
    return re.sub(r'\s+',' ',tail[:end.end()]).strip()


def validate_contract(contract,texts):
    assert contract['schema']=='SOURCE_BOUND_BINARY_LANE_COMPOSITION_CONTRACT_V1'
    expected={'rk_cmac_fp16_rows','rk_cmac_fp16_lane_dsp','cmac_lane_dsp_miter','cmac_discarded_carry_lemma'}
    assert len(contract['modules'])==4 and {m['module'] for m in contract['modules']}==expected
    for module in contract['modules']:
        assert canonical_module(texts[module['source']],module['module'],module['exclusive'])==module['canonical_module'], 'Changed complete glue contract: '+module['module']


def alignment_certificate(contract,texts,integer_certificate):
    validate_contract(contract,texts)
    candidate=texts['rtl/cmac/experimental/rk_cmac_fp16_lane_dsp.sv']
    reference=texts['tests/cmac/cmac_lane_dsp_miter.sv']
    match=re.search(r'biased_sum\s*=\s*\$unsigned\(product\)\s*\+\s*32\'h([0-9a-f]{8});',candidate)
    assert match and int(match.group(1),16)==integer_certificate['booth_bias']==0x55550000
    table=re.findall(r"8'h([0-9a-f]{2}):\s*compensation\s*=\s*32'h([0-9a-f]{8});",reference)
    assert len(table)==8 and len({tag for tag,value in table})==8
    table={int(tag,16):int(value,16) for tag,value in table}
    assert table=={0xf0:0xaaab0000,0x78:0xfaaab000,0x3c:0xffaaab00,0x1e:0xfffaaab0,
        0x0f:0xffffaaab,0x07:0xfffffaab,0x03:0xffffffab,0x01:0xfffffffb}
    bias=integer_certificate['booth_bias'];mask=(1<<32)-1
    assert integer_certificate['biased_unsigned_product_interval']==[357957631,2505310209]
    assert integer_certificate['signed_product_interval']==[-1073676289,1073676289]
    states=[]
    for exp in range(16):
        for nz in (0,1):
            active=bool(nz and not (exp&8));amount=(exp&7)*4
            tag=(0xf0>>(exp&7)) if active else 0
            reference_compensation=table.get(tag,0)
            actual_compensation=(-(bias>>amount)&mask) if active else 0
            assert reference_compensation==actual_compensation,'Changed complete shift/tag compensation table'
            assert 0<=amount<=28
            states.append(dict(exp_sft=exp,pair_nz=nz,active=active,shift_amount=amount,
                output_tag=tag,output_compensation=reference_compensation))
    assert len(states)==32 and len({s['output_tag'] for s in states if s['active']})==8
    return dict(full_miter_binary_input_bits=37,compared_sum_tag_bits=40,all_control_states=states,
        signed_magnitude_a_interval=[-32767,32767],unsigned_magnitude_b_interval=[0,32767],
        candidate_product_signed_width=32,candidate_operand_signed_width=16,
        candidate_unsigned_bias_addition='Modulo 2^32 of a signed 32-bit product plus bias lifts to the unique positive biased sum interval.',
        carry_application='Completed 67-free-bit carry lemma: for S=A+B<2^32 and s=4*k, (A>>s)+(B>>s)=(S>>s)-((A mod 2^s)>(S mod 2^s)). Actual original row A is bound with exp_sft=0,pair_nz=1; the product/range certificate supplies exactly S.',
        compensated_output_application='Active outputs add the same 32-bit modular compensation. Inactive reference rows/tag/default compensation and gated candidate sum/tag all equal zero.',
        basis='Exact entire source glue contracts, fresh complete native miter domain/graph audit, inherited actual conditional SAT carry proof and source-bound unshifted product/range certificate. Not a newly executed positive monolithic SAT or mapped/physical/RK proof.')


def validate_parent(path):
    report=json.loads(path.read_text())
    assert report['status']=='PASS_SOURCE_BOUND_UNSHIFTED_DONOR_PRODUCT_CERTIFICATE_ONLY'
    assert report['stage']=='complete' and report['finished_utc']
    assert report['unshifted_donor_product_identity_proved'] is True and report['new_hdl_or_sat_execution'] is False
    for manifest in (report['source'],report['artifacts']):verify_manifest(manifest)
    paths=[(ROOT/n).resolve() for n in report['parent_reports']]
    assert len(paths)==3 and all(p.is_relative_to(ROOT) for p in paths)
    ranges=json.loads(paths[0].read_text());components=json.loads(paths[1].read_text())
    design,tree_path,tree=product.validate_range(ranges,paths[0].parent)
    assert tree_path==paths[2]
    product.validate_components(components,paths[1].parent)
    weights,codes,bits=product.source_terms(design)
    assert report['certificate']==product.polynomial_certificate(weights,codes,bits)
    assert report['negative_certificate_checks']==product.negative_certificates(weights,codes,bits)
    assert report['parent_source_sha256']==[r['source']['sha256'] for r in (ranges,components,tree)]
    assert components['lemmas']['cmac_discarded_carry_lemma']==dict(status='PASS_COMPONENT_ONLY',
        free_input_bits=67,compared_output_bits=32,conditional_on_no_unsigned_row_sum_overflow=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product-report',type=Path,required=True)
    args=parser.parse_args();parent_path=args.product_report.resolve();assert parent_path.is_relative_to(ROOT)
    parent=validate_parent(parent_path);contract=json.loads(CONTRACT.read_text())
    texts={m['source']:(ROOT/m['source']).read_text() for m in contract['modules']}
    certificate=alignment_certificate(contract,texts,parent['certificate'])
    imported=[Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools')]
    dependencies={ROOT/name for manifest in (parent['source'],parent['artifacts']) for name in manifest['files']}
    tracked=[Path(__file__).resolve(),CONTRACT,parent_path,*SOURCES,*dependencies,*imported]
    before=fingerprint(tracked);out=ROOT/f'build/rknpu-dsp-composed-lane-certificate/{time.time_ns()}'
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='lowering',started_utc=timestamp(),source=before,
        supervisor_pid=os.getpid(),python_version=sys.version,commands=[],
        parent_report=str(parent_path.relative_to(ROOT)),parent_source_sha256=parent['source']['sha256'],
        relevant_binary_input_bits=37,compared_binary_output_bits=40,new_positive_monolithic_sat_proof=False,
        binary_lane_sum_equivalence=False,composed_lane_proof=False,candidate_multiply_binding_proved=False,
        shift_compensation_binding_proved=False,full_array_numerical_acceptance=False,
        raw_board_numerical_acceptance=False,isolated_mapped_binary_fixture_acceptance=False,
        physical_fit_verified=False,bitstream_emitted=False,hardware_programmed=False,scope=__doc__)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(argv,label,negative=False):
        step=dict(argv=list(map(str,argv)),log=str((out/(label+'.log')).relative_to(ROOT)),status='RUNNING')
        report['commands'].append(step);save();start=time.monotonic()
        try:
            with (ROOT/step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                    step['pid']=proc.pid;save()
                    try:code=proc.wait(timeout=1000)
                    except BaseException:
                        try:os.killpg(proc.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                        proc.wait();raise
            step['returncode']=code;text=(ROOT/step['log']).read_text()
            if negative:product.components.validate_sat(text,code,True)
            else:
                assert code==0 and 'ERROR:' not in text,text[-3000:]
                if label.endswith('_lowering'):step['source_bound_array_lowering_notices']=product.ranges.audit_lowering_log(text)
                else:assert not re.search(r'(?im)^Warning:',text)
            step['status']='PASS';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    save();generated=[]
    try:
        report['tool_version']=run(['yosys','-V'],'version').strip()
        for path in sorted(set([Path(__file__).resolve(),CONTRACT,parent_path,*SOURCES,*imported])):
            target=out/'snapshot'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(path.read_bytes());generated.append(target)
        for mode in ('actual','negative'):
            source=SOURCES[-1]
            if mode=='negative':
                source=out/'negative_miter.sv';source.write_text(sanity_miter(SOURCES[-1].read_text()));generated.append(source)
            graph,script=out/(mode+'.json'),out/(mode+'.ys');generated += [graph,script]
            script.write_text('read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST '+
                ' '.join(json.dumps(str(p)) for p in [*SOURCES[:-1],source])+'\n'+
                'hierarchy -check -top '+TOP+'\nproc\nflatten -noscopeinfo\nopt -full\ncheck -assert\n'+
                'write_json '+json.dumps(str(graph))+'\n')
            binding=fingerprint([*SOURCES[:-1],source,script]);report.setdefault('lowering_inputs',{})[mode]=binding;save()
            run(['yosys','-Q','-T','-s',script],mode+'_lowering')
            assert fingerprint([*SOURCES[:-1],source,script])==binding
            design=json.loads(graph.read_text());report.setdefault('graphs',{})[mode]=validate_graph(design)
            multiply=next(c for c in design['modules'][TOP]['cells'].values() if c['type']=='$mul')
            params={n:int(v,2) for n,v in multiply['parameters'].items()}
            assert params['A_SIGNED']==params['B_SIGNED']==1 and params['Y_WIDTH']==32
            assert params['A_WIDTH'] in (16,32) and params['B_WIDTH'] in (16,32)
            report.setdefault('candidate_multiply_parameters',{})[mode]=params;save()
            if mode=='negative':
                proof=out/'negative_sat.ys';generated.append(proof)
                proof.write_text('read_json '+json.dumps(str(graph))+'\n'+
                    'sat -verify -prove mismatch 0 -show-inputs -show-outputs -timeout 900\n')
                report['negative_sat_inputs']=fingerprint([graph,proof]);save()
                run(['yosys','-Q','-T','-s',proof],'negative_sat',True)
                assert fingerprint([graph,proof])==report['negative_sat_inputs']
        assert fingerprint(tracked)==before
        validate_parent(parent_path)
        assert certificate==alignment_certificate(json.loads(CONTRACT.read_text()),
            {m['source']:(ROOT/m['source']).read_text() for m in contract['modules']},parent['certificate'])
        report.update(status='PASS_COMPOSED_BINARY_LANE_SUM_TAG_CERTIFICATE_ONLY',stage='complete',finished_utc=timestamp(),
            binary_lane_sum_equivalence=True,composed_lane_proof=True,candidate_multiply_binding_proved=True,
            shift_compensation_binding_proved=True,composition_certificate=certificate,
            artifacts=fingerprint([*dependencies,*generated,*out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL',finished_utc=timestamp(),error=repr(error),
            artifacts=fingerprint([p for p in [*dependencies,*generated,*out.glob('*.log')] if p.is_file()]));raise
    finally:save()
    print(out/'report.json',flush=True)


if __name__=='__main__':main()
