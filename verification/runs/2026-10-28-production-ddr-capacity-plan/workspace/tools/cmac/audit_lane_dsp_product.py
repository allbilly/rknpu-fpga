#!/usr/bin/env python3
"""Source-bound unshifted Booth integer certificate, not whole-lane signoff.

Compose the completed actual recoder and integer-tree/range results using
exact integer polynomial coefficients from the elaborated wiring. This is
not another HDL/SAT run, sampling, a multiply black-box assumption, or a
runtime FPGA arithmetic fallback. Shift/compensation and candidate-multiply
binding, full array/board, X/reset and physical acceptance remain separate.
"""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
from test_fixed_array_board import verify_manifest
import audit_lane_dsp_ranges as ranges
import prove_lane_dsp_components as components

RECODER_REFERENCE="""(
    input wire [2:0] code,
    input wire sign,
    input wire [14:0] magnitude,
    output wire [31:0] difference,
    output wire mismatch
);
    wire [16:0] selected;
    wire inverted;
    NV_NVDLA_CMAC_CORE_MAC_booth donor (
        .code(code), .is_8bit(1'b0), .sign(sign),
        .src_data({1'b0,magnitude}), .out_data(selected), .out_inv(inverted)
    );
    wire signed [31:0] positive = $signed({17'd0,magnitude});
    reg signed [31:0] digit_product;
    always @* begin
        case(code)
            3'b000,3'b111:digit_product=0;
            3'b001,3'b010:digit_product=positive;
            3'b011:digit_product=positive<<<1;
            3'b100:digit_product=-(positive<<<1);
            3'b101,3'b110:digit_product=-positive;
        endcase
    end
    wire [31:0] expected = 32'h00010000 + (sign ? -digit_product:digit_product);
    wire [31:0] actual = {15'd0,selected} + {31'd0,inverted};
    assign difference = actual ^ expected ^ `RK_COMPONENT_FLIP;
    assign mismatch = |difference;
"""


def validate_reference(text):
    normalize=lambda s:re.sub(r'\s+',' ',s).strip()
    marker='module cmac_booth_recoding_lemma'
    assert text.count(marker)==1
    body=text.split(marker)[1].split('endmodule',1)[0]
    assert normalize(body)==normalize(RECODER_REFERENCE),'Changed actual recoder theorem statement'
    prefix="`ifdef RK_COMPONENT_NEGATIVE\n`define RK_COMPONENT_FLIP 1\n`else\n`define RK_COMPONENT_FLIP 0\n`endif"
    assert text.count(prefix)==1,'Changed real proof negative/positive selection'


def validate_components(report,directory):
    assert report['status']=='PASS_INDEPENDENT_DSP_COMPONENT_LEMMAS_ONLY'
    assert report['stage']=='complete' and report['finished_utc']
    assert set(report['lemmas'])==set(components.DOMAINS)
    for manifest in (report['source'],report['artifacts'],
            *report['lowering_inputs'].values(),*report['proof_inputs'].values()):verify_manifest(manifest)
    labels=['version']
    for top,(inputs,width,conditional) in components.DOMAINS.items():
        assert report['lemmas'][top]==dict(status='PASS_COMPONENT_ONLY',free_input_bits=sum(inputs.values()),
            compared_output_bits=width,conditional_on_no_unsigned_row_sum_overflow=conditional)
        for mode in ('negative','actual'):
            stem=top+'_'+mode;labels += [stem+'_lowering',stem+'_sat']
            graph=directory/(stem+'.json');script=directory/(stem+'_sat.ys')
            components.validate_graph(json.loads(graph.read_text()),top)
            assert script.read_text()==('read_json '+json.dumps(str(graph))+'\n'+
                'sat -verify -prove mismatch 0 -show-inputs -show-outputs -timeout 900\n')
            step=next(c for c in report['commands'] if Path(c['log']).stem==stem+'_sat')
            assert step['argv']==['yosys','-Q','-T','-s',str(script)]
            components.validate_sat((ROOT/step['log']).read_text(),step['returncode'],mode=='negative')
    assert [Path(s['log']).stem for s in report['commands']]==labels
    assert all(s['status']=='PASS' and s['returncode']==(1 if Path(s['log']).stem.endswith('_negative_sat') else 0)
        for s in report['commands'])
    validate_reference(components.MITERS.read_text())


def range_statement(design):
    # Reports serialize the three tree-shape tuples as JSON lists. Preserve
    # every value and field, including widths/bounds, in the same encoding.
    return json.loads(json.dumps(ranges.validate_wiring(design)))


def validate_range(report,directory):
    assert report['status']=='PASS_SOURCE_BOUND_UNSIGNED_DONOR_RANGES_ONLY'
    assert report['stage']=='complete' and report['finished_utc'] and report['donor_range_bound_proved'] is True
    assert [Path(s['log']).stem for s in report['commands']]==['version','lowering']
    assert all(s['status']=='PASS' and s['returncode']==0 for s in report['commands'])
    for manifest in (report['source'],report['artifacts'],report['lowering_inputs']):verify_manifest(manifest)
    parent_path=ROOT/report['parent_report'];parent=json.loads(parent_path.read_text())
    ranges.validate_parent(parent);ranges.validate_bindings(parent,parent_path.parent)
    graph=directory/'rows.json'
    assert str(graph.relative_to(ROOT)) in report['artifacts']['files']
    design=json.loads(graph.read_text())
    assert report['ranges']==range_statement(design),'Changed actual wiring/range statement'
    for field in ('composed_lane_proof','binary_lane_sum_equivalence','multiply_distributivity_proved',
            'full_array_numerical_acceptance','raw_board_numerical_acceptance',
            'physical_fit_verified','bitstream_emitted','hardware_programmed'):assert report[field] is False
    return design,parent_path,parent


def source_terms(design):
    ranges.validate_wiring(design)
    module=design['modules'][ranges.TOP];cells=module['cells']
    coefficients=defaultdict(int)
    for tree,scale in [('low_tree',1),('high_tree',256)]:
        # Each verified integer tree sums five little-endian 24-bit words;
        # the verified final wiring gives the high group its eight-bit shift.
        for i,bit in enumerate(cells[tree]['connections']['INPUT']):
            if type(bit) is int:coefficients[bit] += scale*(1 << (i%24))
            else:assert bit=='0'
    weights=[];codes=[];outputs=[]
    for i in range(8):
        pins=cells[f'booth[{i}].recode']['connections'];selected=pins['out_data'];inv=pins['out_inv'][0]
        weight=coefficients[selected[0]]
        assert all(coefficients[bit]==weight*(1<<j) for j,bit in enumerate(selected))
        assert coefficients[inv]==weight and weight>0,'Selected/inversion coefficient mismatch'
        weights.append(weight);codes.append(pins['code']);outputs += selected+[inv]
    assert len(set(outputs))==144 and set(outputs)==set(coefficients),'Aliased or unaccounted actual recoder outputs'
    return weights,codes,module['ports']['op_a']['bits'][:15]


def polynomial_certificate(weights,codes,operand_bits,bias=0x55550000,digit_coefficients=(1,1,-2)):
    assert len(weights)==len(codes)==8 and len(operand_bits)==15
    assert len(set(operand_bits))==15 and all(type(b) is int for b in operand_bits)
    assert all(type(w) is int and w>0 for w in weights)
    truth=[0,1,1,2,-2,-1,-1,0]
    for code in range(8):
        assert sum(digit_coefficients[j]*((code>>j)&1) for j in range(3))==truth[code], 'Changed digit polynomial'
    assert bias==65536*sum(weights),'Changed Booth bias'
    coefficients=defaultdict(int)
    for weight,bits in zip(weights,codes):
        assert len(bits)==3
        for coefficient,bit in zip(digit_coefficients,bits):
            if type(bit) is int:
                assert bit in operand_bits,'Unknown digit input'
                coefficients[bit] += weight*coefficient
            else:assert bit=='0','Changed digit endpoint padding'
    expected={bit:1<<i for i,bit in enumerate(operand_bits)}
    assert dict(coefficients)==expected,'Nonzero product coefficient residual'
    # The signed recoder's proven 32-bit equality lifts to integers: both
    # sides lie in [2,131070], not across a modular boundary. All rows fit
    # their widths by the separately completed actual range/tree proof.
    magnitude_max=(1<<15)-1;product_max=magnitude_max*magnitude_max
    recoder_min,recoder_max=65536-2*magnitude_max,65536+2*magnitude_max
    assert 0<=recoder_min<=recoder_max<(1<<17)
    assert product_max<(1<<31) and 0<=bias-product_max<=bias+product_max<(1<<32)
    return dict(actual_digit_weights=weights,booth_bias=bias,booth_bias_hex=hex(bias),
        radix4_digit_truth_table=truth,operand_bit_product_coefficients=[coefficients[b] for b in operand_bits],
        coefficient_residuals=[coefficients[b]-expected[b] for b in operand_bits],
        common_magnitude_b_domain=[0,magnitude_max],common_sign_factor_domain=[-1,1],
        recoder_integer_output_interval=[recoder_min,recoder_max],
        signed_product_interval=[-product_max,product_max],
        biased_unsigned_product_interval=[bias-product_max,bias+product_max],
        identity='unshifted row_a + row_b = 0x55550000 + sign_factor * magnitude_a * magnitude_b',
        basis='Exact integer polynomial distribution with all 15 operand bits free; the common B magnitude and sign factor are those of all eight source-audited actual recoders. No sampled magnitude, narrowed input domain, truncation assumption or whole-lane acceptance.')


def negative_certificates(weights,codes,bits):
    checks=[]
    for name,reason,kwargs in [
            ('wrong_bias','Changed Booth bias',dict(bias=0x55550001)),
            ('wrong_digit','Changed digit polynomial',dict(digit_coefficients=(1,2,-2)))]:
        try:polynomial_certificate(weights,codes,bits,**kwargs)
        except AssertionError as error:
            assert str(error)==reason;checks.append(dict(name=name,status='PASS_EXPECTED_CERTIFICATE_REJECTION',reason=reason))
        else:raise AssertionError('Corrupted integer certificate accepted')
    changed=list(weights);changed[0]+=1
    try:polynomial_certificate(changed,codes,bits,bias=65536*sum(changed))
    except AssertionError as error:
        assert str(error)=='Nonzero product coefficient residual'
        checks.append(dict(name='wrong_weight',status='PASS_EXPECTED_CERTIFICATE_REJECTION',reason=str(error)))
    else:raise AssertionError('Corrupted source weight certificate accepted')
    return checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--range-report',type=Path,required=True)
    parser.add_argument('--component-report',type=Path,required=True)
    args=parser.parse_args();paths=[args.range_report.resolve(),args.component_report.resolve()]
    assert all(p.is_relative_to(ROOT) for p in paths)
    parents=[json.loads(p.read_text()) for p in paths]
    design,tree_path,tree=validate_range(parents[0],paths[0].parent)
    validate_components(parents[1],paths[1].parent)
    for donor in ranges.DONORS:
        name=str(donor.relative_to(ROOT))
        assert parents[0]['source']['files'][name]==parents[1]['source']['files'][name]==tree['source']['files'][name]
    imported=[Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools')]
    dependencies={ROOT/name for r in [*parents,tree] for manifest in (r['source'],r['artifacts']) for name in manifest['files']}
    tracked=[Path(__file__).resolve(),*paths,tree_path,*dependencies,*imported]
    before=fingerprint(tracked);out=ROOT/f'build/rknpu-dsp-product-certificate/{time.time_ns()}'
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='certificate',started_utc=timestamp(),source=before,
        supervisor_pid=os.getpid(),python_version=sys.version,commands=[],
        parent_reports=[str(p.relative_to(ROOT)) for p in [*paths,tree_path]],
        parent_source_sha256=[r['source']['sha256'] for r in [*parents,tree]],
        inherited_actual_tool_versions=[r['tool_version'] for r in [*parents,tree]],
        new_hdl_or_sat_execution=False,unshifted_donor_product_identity_proved=False,
        binary_lane_sum_equivalence=False,composed_lane_proof=False,
        candidate_multiply_binding_proved=False,shift_compensation_binding_proved=False,
        full_array_numerical_acceptance=False,raw_board_numerical_acceptance=False,
        physical_fit_verified=False,bitstream_emitted=False,hardware_programmed=False,
        scope=__doc__)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    save();generated=[]
    try:
        for path in sorted(set([Path(__file__).resolve(),*paths,tree_path,*imported])):
            target=out/'snapshot'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(path.read_bytes());generated.append(target)
        weights,codes,bits=source_terms(design)
        report['negative_certificate_checks']=negative_certificates(weights,codes,bits)
        report['certificate']=polynomial_certificate(weights,codes,bits)
        validate_range(parents[0],paths[0].parent);validate_components(parents[1],paths[1].parent)
        assert fingerprint(tracked)==before
        report.update(status='PASS_SOURCE_BOUND_UNSHIFTED_DONOR_PRODUCT_CERTIFICATE_ONLY',stage='complete',
            finished_utc=timestamp(),unshifted_donor_product_identity_proved=True,
            artifacts=fingerprint([*dependencies,*generated]))
    except BaseException as error:
        report.update(status='FAIL',finished_utc=timestamp(),error=repr(error),
            artifacts=fingerprint([p for p in [*dependencies,*generated] if p.is_file()]));raise
    finally:save()
    print(out/'report.json',flush=True)


if __name__=='__main__':main()
