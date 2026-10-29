#!/usr/bin/env python3
"""Convert the unchanged small native HeAP FASM; read actual DSP/clock bits.

Admit the completed source-bound HeAP/clock qualification, then run the same
strict pinned converter and exact-part geometry validator on its saved raw
FASM. Retain all 64 corrected DSP requests/readbacks and additionally require
every actual clock-fanout request and positive HCLK bit. Comparison targets
are never converter inputs. Old failures, parsers, native artifacts, circuit,
models, constraints and live full jobs remain untouched. No native P&R rerun,
full-board frame conversion, assembly, bitstream, physical signoff or hardware
programming is implied. No standalone checksum manifest is written.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import probe_corrected_frame_database as original
import qualify_native_heap_clock_features as qualification
import clock_bound_native_features as clock
from audit_empty_output_pairs import source_shaped

ROOT=original.ROOT
QUALIFICATION=ROOT/'build/openxc7/native-heap-clock-features-1791461172554993544/report.json'
NATIVE=qualification.FAILED
CONTROL=ROOT/'tests/cmac/test_native_heap_frame_control.py'
PASS='PASS_SAVED_NATIVE_HEAP_FASM_EXACT_PART_FRAMES_64_DSP_AND_SOURCE_BOUND_CLOCK_BITS_NOT_BITSTREAM_OR_SIGNOFF'
IDENTITY=original.IDENTITY


def verify_heap_evidence():
    q,before=qualification.verify_qualification(QUALIFICATION)
    assert str(NATIVE) in before and str(IDENTITY) in before
    return q,before


def actual_clock_contracts():
    module=next(iter(json.loads((NATIVE.parent/'routed.json').read_text())['modules'].values()))
    return clock.clock_contracts(module)


def saved_fasm_digest():
    saved=json.loads(NATIVE.read_text());qualification.check_saved_metadata(saved)
    return saved['artifacts'][str((NATIVE.parent/'control.fasm').relative_to(ROOT))]


REQUIRED_SOURCE=inspect.getsource(original.required_features)


def required_features(q):
    qualification.verify_metadata(q)
    reference=json.loads(qualification.first.parent.first.NATIVE.read_text())
    contracts=actual_clock_contracts()
    namespace=dict(original.__dict__,NATIVE=NATIVE,parse_native_features=lambda text:
                   clock.parse_clock_bound_features(text,contracts)[:2])
    exec(compile(REQUIRED_SOURCE,__file__+':unchanged-four-DSP-64-feature-requirements','exec'),namespace)
    # Origin metadata is comparison evidence from the already-bound corrected
    # control. Do not alter or relabel any stored qualification/failure report.
    return namespace['required_features'](dict(q,control_origins=reference['control_origins']))


def verify_clock_requests(requests,contracts):
    found=dict.fromkeys(contracts,0)
    assert found and all(re.fullmatch(clock.FLAG,key) and value['value']==1 and value['PIPs']
                         for key,value in contracts.items())
    for request in requests:
        name=request['feature']
        if '.ENABLE_BUFFER.HCLK_CK_BUFHCLK' not in name:continue
        assert name in found,'Unknown/unused converter HCLK request'
        assert request['kind']=='input_lines','Clock enable must come from raw native input'
        assert type(request['value']) is int and request['value']==1
        assert request['start'] is request['end'] is None,'Non-Boolean clock request'
        found[name]+=1
    assert all(found[key]==len(value['PIPs']) for key,value in contracts.items()),'Changed converter clock fanout request count'
    return dict(raw_clock_requests=found,raw_clock_request_count=sum(found.values()),
                no_clock_requests_from_comparison_targets=True)


def verify_clock_bit_locations(locations,words):
    assert locations and all(re.fullmatch(clock.FLAG,key) and len(bits)==1 and bits[0][3] is True
                             for key,bits in locations.items()),'Clock flag lacks one positive physical DB bit'
    result=original.check_feature_bits(locations,words)
    assert result['physical_DB_bits_compared']==len(locations),'Aliased clock configuration bits'
    return result


CLOCK_READBACK_REPLACEMENTS=(
    ("assert len(required) == 64 and set(required.values()) == {'1'}",
     "assert required and all(re.fullmatch(clock.FLAG,key) for key in required) and set(required.values()) == {'1'}"),
    ("info.tile_type in ('DSP_L', 'DSP_R')","info.tile_type in ('HCLK_L', 'HCLK_R')"),
    ('PASS actual corrected DSP frame-bit readback and comparison-only corruption negative',
     'PASS actual source-bound HCLK frame-bit readback and comparison-only corruption negative'))
CLOCK_READBACK_SOURCE=source_shaped(inspect.getsource(original.readback),CLOCK_READBACK_REPLACEMENTS)
CLOCK_READBACK_NAMESPACE=dict(original.__dict__,clock=clock,check_feature_bits=verify_clock_bit_locations)
exec(compile(CLOCK_READBACK_SOURCE,__file__+':same-readback-and-corruption-gates-for-actual-clock-bits','exec'),CLOCK_READBACK_NAMESPACE)
clock_readback=CLOCK_READBACK_NAMESPACE['readback']

OLD_TARGET="        before[str(expected)] = digest(expected)"
NEW_TARGET=OLD_TARGET+'''
        contracts=actual_clock_contracts()
        clock_expected=out/'comparison-only-required-clock-features.json'
        clock_expected.write_text(json.dumps(dict.fromkeys(contracts,'1'),indent=2,sort_keys=True)+'\\n')
        before[str(clock_expected)]=digest(clock_expected)
        report.update(clock_fanout_contracts=contracts,clock_comparison_targets=str(clock_expected),
                      actual_clock_feature_frame_readback_executed=False,clock_targets_used_for_conversion=False)'''
OLD_COUNT="q['native_FASM_features'] + len(q['native_FASM_repeated_idempotent_STEPDOWN_lines'])"
NEW_COUNT=OLD_COUNT+" + sum(len(v)-1 for v in q['native_FASM_repeated_clock_enable_lines'].values())"
OLD_REQUEST="        assert verify_requests(requests, required) == result['counts']"
NEW_REQUEST=OLD_REQUEST+"\n        report['clock_converter_requests']=verify_clock_requests(requests,contracts)"
OLD_READBACK="        assert report['DSP_frame_readback']['actual_frame_bit_corruption_rejected_in_comparison_only'] is True"
NEW_READBACK=OLD_READBACK+'''
        report.update(stage='clock_frame_readback',actual_clock_feature_frame_readback_executed=True)
        clock_readback_path=out/'clock-feature-readback.json'
        run('clock_frame_readback',[frame.PYTHON,'-B',Path(__file__),'--clock-readback',frames,clock_expected,clock_readback_path],120)
        report['clock_frame_readback']=json.loads(clock_readback_path.read_text())
        assert report['clock_frame_readback']['features_compared']==len(contracts)
        assert report['clock_frame_readback']['physical_DB_bits_compared']==len(contracts)
        assert report['clock_frame_readback']['actual_frame_bit_corruption_rejected_in_comparison_only'] is True'''
REPLACEMENTS=(
    ('corrected-frame-database-control-','native-heap-frame-control-'),
    ("    shutil.copyfile(__file__, out / 'executed_source.py')",
     "    shutil.copyfile(__file__, out / 'executed_source.py')\n    shutil.copyfile(CONTROL,out/'executed_control_source.py')\n    (out/'executed_prepared_main.py').write_text(MAIN_SOURCE)"),
    ('q, before = verify_corrected_evidence()','q, before = verify_heap_evidence()'),
    ('native_qualification_report=str(NATIVE),','native_qualification_report=str(QUALIFICATION), saved_native_evidence_report=str(NATIVE),'),
    ('native_control_dsps=4, native_control_brams=6, native_FASM_conversion_executed=False,',
     'native_control_dsps=4, native_control_brams=6, new_native_PNR_executed=False, native_FASM_conversion_executed=False,'),
    ("q['artifacts'][str(fasm.relative_to(ROOT))]",'saved_fasm_digest()'),
    ('    args = parser.parse_args()',"    parser.add_argument('--clock-readback',nargs=3,type=Path,help=argparse.SUPPRESS)\n    args = parser.parse_args()\n    if args.clock_readback:\n        clock_readback(*args.clock_readback)\n        return"),
    (OLD_TARGET,NEW_TARGET),(OLD_COUNT,NEW_COUNT),(OLD_REQUEST,NEW_REQUEST),(OLD_READBACK,NEW_READBACK))
MAIN_SOURCE=source_shaped(inspect.getsource(original.main),REPLACEMENTS)
NAMESPACE=dict(original.__dict__,__file__=__file__,__doc__=__doc__,NATIVE=NATIVE,CONTROL=CONTROL,PASS=PASS,
               QUALIFICATION=QUALIFICATION,MAIN_SOURCE=MAIN_SOURCE,verify_heap_evidence=verify_heap_evidence,required_features=required_features,
               saved_fasm_digest=saved_fasm_digest,actual_clock_contracts=actual_clock_contracts,
               verify_clock_requests=verify_clock_requests,clock_readback=clock_readback)
exec(compile(MAIN_SOURCE,__file__+':strict-saved-HeAP-encoder-chain-control','exec'),NAMESPACE)


def main():NAMESPACE['main']()


if __name__=='__main__':main()
