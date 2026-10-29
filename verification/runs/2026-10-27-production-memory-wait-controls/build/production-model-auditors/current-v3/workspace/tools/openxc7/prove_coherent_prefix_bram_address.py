#!/usr/bin/env python3
"""Prove mapped address decoding at a coherent actual producer-output boundary.

The preserved semantic-cut attempt reaches FDCE: synthesis shares upstream
logic across that cut. Trace every compared semantic signal together, stopping
only at exact known register Q outputs or the audited zero-register DSP P
outputs. These producer bits are unconstrained binary values; they are not
assumed initialized, reachable or numerically correct. Keep all shared
combinational logic and derive both the actual address and reference from it.
No missing input/net/model is repaired; neither failed prover is changed.
This is a binary combinational property, not temporal/startup, full numerical,
physical implementation or hardware acceptance. No SHA256SUMS file is emitted.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'cmac')]
import prove_sparse_prefix_bram_address as previous
from audit_empty_output_pairs import source_shaped
from audit_prefix_config_contract import dsp_contract
from place_prefix_board import bind_report, verify_bindings
import unisim_board_models as models
from check_dsp_prefix_unisim_models import DSP_SHA

base = previous.old
FAILED = base.ROOT / 'build/openxc7/prefix-bram-address-sparse-output-proof-1791436318614640675/report.json'
CONTROL = base.ROOT / 'tests/cmac/test_coherent_prefix_bram_address_control.py'
PASS = 'PROVED_ACTUAL_FULL_PREFIX_COHERENT_BINARY_BRAM_ADDRESS_AND_REQUEST_CONE_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'
RESET_PIN = dict(FDCE='CLR', FDPE='PRE', FDRE='R', FDSE='S')
STATE_MODELS = {kind: models.CACHE / ('verilog/src/unisims/' + kind + '.v') for kind in RESET_PIN}
DSP_MODEL = models.CACHE / 'verilog/src/unisims/DSP48E1.v'


def validate_register(cell, pin, bit):
    kind, c, d, p = cell['type'], cell['connections'], cell['port_directions'], cell['parameters']
    assert kind in RESET_PIN and pin == 'Q' and bit == 0, 'Not an exact registered Q cut'
    inputs = {'C', 'CE', 'D', RESET_PIN[kind]}
    assert set(c) == set(d) == inputs | {'Q'}, 'Unmodeled register interface'
    assert d == {**{name: 'input' for name in inputs}, 'Q': 'output'}
    assert all(len(bits) == 1 for bits in c.values())
    assert all(type(w) is int and w >= 2 or w in ('0','1') for bits in c.values() for w in bits)
    assert set(p) <= {'INIT','IS_C_INVERTED','IS_D_INVERTED','IS_' + RESET_PIN[kind] + '_INVERTED'}
    assert all(value in ('0','1') if key != 'INIT' else value in ('0','1','x') for key,value in p.items())
    assert type(c['Q'][0]) is int and c['Q'][0] >= 2


def validate_producer(cell, pin, bit):
    if cell['type'] in RESET_PIN:
        validate_register(cell, pin, bit)
        return 'REGISTER_Q_ALL_BINARY_VALUES_NOT_INITIALIZATION_OR_TRANSITION_PROOF'
    if cell['type'] == 'DSP48E1':
        dsp_contract(cell)
        assert pin == 'P' and 0 <= bit < 48 and cell['port_directions'][pin] == 'output'
        assert len(cell['connections'][pin]) == 48
        assert all(type(w) is int and w >= 2 for w in cell['connections'][pin])
        return 'AUDITED_DSP_P_ALL_BINARY_VALUES_NOT_MULTIPLIER_OR_NUMERICAL_PROOF'
    raise AssertionError('Unsupported opaque producer: ' + cell['type'])


def trace_coherent(signals, get_driver):
    assert set(signals) == set(base.WIDTHS)
    assert all(len(signals[k]) == base.WIDTHS[k] for k in signals)
    nodes, cuts, visited = {}, {}, set()
    def visit(wire, stack):
        if wire in ('0','1') or wire in visited: return
        assert type(wire) is int and wire >= 2 and wire not in stack, 'Unknown/cyclic coherent cone wire'
        name, cell, pin, bit = get_driver(wire)
        assert cell['connections'][pin][bit] == wire
        if cell['type'] in RESET_PIN or cell['type'] == 'DSP48E1':
            role = validate_producer(cell, pin, bit)
            cuts[wire] = dict(cell=name, pin=pin, bit=bit, role=role, original_primitive=cell)
        else:
            ins, outs = validate_cell(cell)
            assert pin in outs and name not in cuts
            assert name not in nodes or nodes[name] == cell
            nodes[name] = cell
            for port in ins:
                for upstream in cell['connections'][port]: visit(upstream, stack | {wire})
        visited.add(wire)
    for bits in signals.values():
        for wire in bits: visit(wire, set())
    assert nodes and cuts and len(cuts) <= 512 and len(nodes) <= 20000, 'Missing/unbounded coherent producer cut'
    return nodes, cuts


def verify_failed(before):
    first = previous.verify_failed(before)
    report = json.loads(FAILED.read_text())
    assert report['status'] == 'FAIL' and report['stage'] == 'actual_full_driver_census_and_address_cone' and report['finished_utc']
    assert report['error'] == "AssertionError('Unsupported/sequential address-cone primitive: FDCE')"
    assert [c['label'] for c in report['commands']] == ['software_controls','generated_check','yosys_version']
    assert all(c['returncode'] == 0 and c['status'] == 'PASS_TOOL_EXECUTION_ONLY' for c in report['commands'])
    assert 'address_decoder_binary_cut_proved' not in report and report['original_failure_relabelled'] is False
    bind_report(FAILED, report, before); verify_bindings(before)
    for kind,path in STATE_MODELS.items():
        assert base.digest(path) == models.PINS[kind]
        text = path.read_text()
        assert 'output Q,' in text and 'input ' + RESET_PIN[kind] in text
    assert base.digest(DSP_MODEL) == DSP_SHA
    assert re.search(r'output\s+\[47:0\]\s+P\b', DSP_MODEL.read_text())
    return dict(**first, semantic_cut_failure_report=str(FAILED),
                shared_upstream_logic_requires_coherent_producer_cut=True,
                unknown_INIT_not_coerced_or_assumed_initialized=True,
                DSP_P_not_assumed_numerically_correct=True)


# A primitive's unconnected output is not a repaired input. Both CARRY4
# outputs are internally defined by the pinned original model even when one
# has no external connection; all connected output declarations remain strict.
COHERENT_OUTPUT = """        inputs = dict(CI=1, CYINIT=1, DI=4, S=4); outputs = {}; assert p == {}
        for output in ('CO','O'):
            if output in c or output in d:
                outputs[output] = 4
        assert outputs, 'No observable CARRY4 output'
"""
CELL_SOURCE = source_shaped(inspect.getsource(base.validate_cell), ((previous.OLD_OUTPUT, COHERENT_OUTPUT),))
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL, PASS=PASS,
                 verify_failed=verify_failed, trace_coherent=trace_coherent,
                 STATE_MODELS=STATE_MODELS, DSP_MODEL=DSP_MODEL)
exec(compile(CELL_SOURCE,__file__ + ':validated-combinational-cell','exec'),NAMESPACE)
validate_cell = NAMESPACE['validate_cell']

OLD_CUT = "    cuts = {w: f'{k}[{i}]' if WIDTHS[k] > 1 else k for k in INPUTS for i, w in enumerate(signals[k])}\n"
NEW_CUT = "    cuts = {wire: 'producer_cut[' + str(i) + ']' for i,wire in enumerate(sorted(producer_cuts))}\n"
OLD_HEADER = """    lines = ['module prefix_bram_address_miter #(parameter NEGATIVE=0) (',
             'input [31:0] req_addr, input req_valid,rsp_valid,rst_n, output ok);']
"""
NEW_HEADER = """    lines = ['module prefix_bram_address_miter #(parameter NEGATIVE=0) (',
             'input [' + str(len(cuts)-1) + ':0] producer_cut, output ok);']
"""
OLD_REFERENCE = "    lines += ['wire aligned = !req_addr[0];',\n"
NEW_REFERENCE = """    lines.append('wire [31:0] req_addr = ' + bus(signals['req_addr']) + ';')
    for semantic in ('req_valid','rsp_valid','rst_n'):
        lines.append('wire ' + semantic + ' = ' + bit(signals[semantic][0]) + ';')
""" + OLD_REFERENCE
MITER_REPLACEMENTS = (('def miter(signals, nodes):','def miter(signals, nodes, producer_cuts):'),
                      (OLD_CUT,NEW_CUT),(OLD_HEADER,NEW_HEADER),(OLD_REFERENCE,NEW_REFERENCE))
MITER_SOURCE = source_shaped(inspect.getsource(base.miter), MITER_REPLACEMENTS)
exec(compile(MITER_SOURCE,__file__ + ':coherent-miter','exec'),NAMESPACE)
miter = NAMESPACE['miter']
OLD_TRACE = '            nodes = trace_cone(signals, get_driver)\n'
NEW_TRACE = """            nodes, cuts = trace_coherent(signals, get_driver)
        report['actual_producer_cuts'] = {str(wire): record for wire,record in cuts.items()}
        report['symbolic_binary_input_bits'] = len(cuts)
        report['semantic_signal_values_derived_from_shared_actual_logic'] = True
"""
MAIN_REPLACEMENTS = (('prefix-bram-address-sparse-output-proof-','prefix-bram-address-coherent-proof-'),
    ('symbolic_binary_input_bits=35','symbolic_binary_input_bits=None'),
    ('Path(sys.executable).resolve(), Path(shutil.which(\'yosys\')).resolve(),',
     'Path(sys.executable).resolve(), Path(shutil.which(\'yosys\')).resolve(), *STATE_MODELS.values(), DSP_MODEL,'),
    (OLD_TRACE,NEW_TRACE), ('source.write_text(miter(signals, nodes))','source.write_text(miter(signals, nodes, cuts))'))
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE,MAIN_REPLACEMENTS)
NAMESPACE['MAIN_SOURCE'] = MAIN_SOURCE


def main():
    exec(compile(MAIN_SOURCE,__file__ + ':coherent-main','exec'),NAMESPACE)
    NAMESPACE['main']()


if __name__=='__main__': main()
