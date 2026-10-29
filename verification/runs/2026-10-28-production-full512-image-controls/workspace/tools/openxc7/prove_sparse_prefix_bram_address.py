#!/usr/bin/env python3
"""Actual address proof with source-evidenced unused CARRY4 sum output omission.

The preserved first prover rejects a CARRY4 record with no O output declaration.
Pinned UNISIM CO depends only on S/DI/CI/CYINIT/CO feedback, not O. Admit exactly
this absent unused output in a separate validator, without adding a pin, net,
model or execution input. Every input and all present outputs remain strict.
Re-execute the complete census and actual 35-input/14-output SAT/real-negative
procedure. This is not temporal startup, numerical or physical signoff.
"""
import inspect
import json
import mmap
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prove_prefix_bram_address as old
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report, verify_bindings

FAILED = old.ROOT / 'build/openxc7/prefix-bram-address-proof-1791435787314873410/report.json'
CONTROL = old.ROOT / 'tests/cmac/test_sparse_prefix_bram_address_control.py'
PASS = 'PROVED_ACTUAL_FULL_PREFIX_BINARY_BRAM_ADDRESS_WITH_UNUSED_CARRY_SUM_OUTPUT_OMISSION_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'
OLD_OUTPUT = "        inputs = dict(CI=1, CYINIT=1, DI=4, S=4); outputs = dict(CO=4, O=4); assert p == {}\n"
NEW_OUTPUT = """        inputs = dict(CI=1, CYINIT=1, DI=4, S=4); outputs = dict(CO=4); assert p == {}
        # Source-declared unused O may be absent, never an input or CO repair.
        if 'O' in c or 'O' in d:
            outputs['O'] = 4
"""
OLD_BIND = '        before = {}; bind_report(PARENT, parent, before)\n'
NEW_BIND = '        before = {}; report["unused_output_source_witness"] = verify_failed(before); bind_report(PARENT, parent, before)\n'
OLD_SAVE = "    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\\n')\n"
NEW_SAVE = """    (out / 'executed_main.py').write_text(MAIN_SOURCE)
    report['rsp_error_temporal_proved'] = False
    report['original_failure_relabelled'] = False
""" + OLD_SAVE


def verify_primary_source():
    source = (old.MODEL_DIR / 'CARRY4.v').read_text()
    for literal in ('output [3:0] CO,', 'output [3:0] O,',
                    'assign CO_fb = {CO[2:0], CI_in || CYINIT_in};',
                    'assign O = S_in ^ CO_fb;',
                    'assign CO = (S_in & CO_fb) | (~S_in & DI_in);'):
        assert source.count(literal) == 1, 'Changed pinned carry-output contract'


def verify_failed(before):
    report = json.loads(FAILED.read_text())
    assert report['status'] == 'FAIL' and report['stage'] == 'actual_full_driver_census_and_address_cone' and report['finished_utc']
    assert report['error'] == "AssertionError('Unmodeled primitive pin')"
    assert [c['label'] for c in report['commands']] == ['software_controls', 'generated_check', 'yosys_version']
    assert all(c['returncode'] == 0 and c['status'] == 'PASS_TOOL_EXECUTION_ONLY' for c in report['commands'])
    assert report['symbolic_binary_input_bits'] == 35 and report['compared_output_bits'] == 14
    assert 'address_decoder_binary_cut_proved' not in report
    for flag in ('temporal_port_ownership_proved','write_before_read_proved','observable_startup_reset_independence_proved',
                 'full_board_numerical_acceptance','physical_fit_verified','timing_signoff','drc_signoff','electrical_verified',
                 'bitstream_emitted','hardware_programmed','comparison_view_used_for_execution'):
        assert report[flag] is False
    bind_report(FAILED, report, before); verify_bindings(before); verify_primary_source()
    prepared = json.loads(old.PREPARED.read_text()); path = old.ROOT / prepared['pack_input']
    name = 'rk_mapped_cell_85044'
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        start = data.find(b'        ' + json.dumps(name).encode() + b': {')
        end = data.find(b'\n        }', start) + len(b'\n        }')
        assert start >= 0 and end > start
        cell = json.loads(b'{' + data[start:end] + b'}')[name]
    assert cell['type'] == 'CARRY4' and 'O' not in cell['connections'] and 'O' not in cell['port_directions']
    try: old.validate_cell(cell)
    except AssertionError as error: assert str(error) == 'Unmodeled primitive pin'
    else: raise AssertionError('Original sparse-output rejection no longer holds')
    validate_cell(cell)
    return dict(record=name, original_cell=cell, missing_port='O', role='UNUSED_OUTPUT_ONLY',
                pinned_CO_logic_independent_of_O=True, physical_record_modified=False,
                original_failure_report=str(FAILED))


def derive(function, namespace, replacements=()):
    source = source_shaped(inspect.getsource(function), replacements)
    exec(compile(source, __file__ + ':known-source-' + function.__name__, 'exec'), namespace)
    return namespace[function.__name__], source


NAMESPACE = dict(old.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL, PASS=PASS,
                 verify_failed=verify_failed)
validate_cell, CELL_SOURCE = derive(old.validate_cell, NAMESPACE, ((OLD_OUTPUT, NEW_OUTPUT),))
trace_cone, TRACE_SOURCE = derive(old.trace_cone, NAMESPACE)
miter, MITER_SOURCE = derive(old.miter, NAMESPACE)
MAIN_SOURCE = source_shaped(inspect.getsource(old.main),
    (('prefix-bram-address-proof-', 'prefix-bram-address-sparse-output-proof-'), (OLD_BIND, NEW_BIND), (OLD_SAVE, NEW_SAVE)))
NAMESPACE['MAIN_SOURCE'] = MAIN_SOURCE


def main():
    exec(compile(MAIN_SOURCE, __file__ + ':known-main', 'exec'), NAMESPACE)
    NAMESPACE['main']()


if __name__ == '__main__': main()
