#!/usr/bin/env python3
"""Isolated binary carry-prefix lemma, fresh XC7 area and full lane fixtures.

Never alter the running DSP array/board, reduce its 512 products, emit a
bitstream or treat binary leaf equivalence as four-state/physical acceptance.
"""
from collections import Counter
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
import check_lane_dsp as lane
from prove_lane_dsp_components import validate_sat
from lane_dsp_library import timing_only_view

HELPER = ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv'
CANDIDATE = ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv'
LEMMA = ROOT / 'tests/cmac/cmac_discarded_carry_miter.sv'
MITER = ROOT / 'tests/cmac/cmac_lane_dsp_prefix_miter.sv'
TOP = 'cmac_discarded_carry_miter'
EXPECTED = 'PASS LANE_DSP_BINARY_FIXTURES comparisons=135680 seed=3588d501 samples=4096'
# Exact operators observed in the executed comparator lowering. In particular,
# $shiftx is the unsigned one-bit selection greater[shift], not an assumption.
COMPARATOR_CELLS = {'$and', '$eq', '$gt', '$logic_and', '$logic_or', '$not',
    '$shiftx', '$shl', '$sub', '$xor'}


def candidate_source(original):
    changes = [('module rk_cmac_fp16_lane_dsp (', 'module rk_cmac_fp16_lane_dsp_prefix ('),
        ("    wire [31:0] low_mask = (32'h00000001 << shift_amount) - 32'd1;\n", ''),
        ('    wire discarded_carry = (original_row_a & low_mask) > (biased_sum & low_mask);',
         '''    wire discarded_carry;
    rk_cmac_fp16_discarded_carry prefix (
        .first_row(original_row_a), .total(biased_sum),
        .shift(exp_sft[2:0]), .carry(discarded_carry)
    );''')]
    for before, after in changes:
        assert original.count(before) == 1, 'Changed original lane contract'
        original = original.replace(before, after)
    return original


def validate_sources():
    assert CANDIDATE.read_text() == candidate_source(lane.SOURCES[3].read_text()), 'Extra candidate arithmetic/glue change'
    assert LEMMA.read_text().count('assign mismatch = reference_carry ^ actual_carry;') == 1
    assert LEMMA.read_text().count('assign reference_carry = (first_row & mask) > (total & mask);') == 1
    assert MITER.read_text().count('rk_cmac_fp16_lane_dsp reference (') == 1
    assert MITER.read_text().count('rk_cmac_fp16_lane_dsp_prefix actual (') == 1
    assert MITER.read_text().count('assign difference = {reference_lane ^ actual_lane, reference_tag ^ actual_tag};') == 1


def validate_graph(design):
    assert set(design['modules']) == {TOP}
    module = design['modules'][TOP]
    widths = {'first_row': ('input', 32), 'total': ('input', 32), 'shift': ('input', 3),
        'reference_carry': ('output', 1), 'actual_carry': ('output', 1), 'mismatch': ('output', 1)}
    assert {n: (p['direction'], len(p['bits'])) for n, p in module['ports'].items()} == widths
    bits = [b for n in ('first_row', 'total', 'shift') for b in module['ports'][n]['bits']]
    assert all(type(b) is int for b in bits) and len(set(bits)) == 67, 'Reduced or coupled lemma inputs'
    kinds = Counter(c['type'] for c in module['cells'].values())
    assert set(kinds) <= COMPARATOR_CELLS, ('State, assumptions or unmodeled cells', dict(kinds))
    assert '$mul' not in kinds, 'Independent comparator lemma must not hide a multiply axiom'
    assert all(type(b) is int for n in ('reference_carry', 'actual_carry') for b in module['ports'][n]['bits'])
    selectors = [c for c in module['cells'].values() if c['type'] == '$shiftx']
    assert len(selectors) == 1, 'Changed indexed carry selection'
    selector = selectors[0]
    assert {k: int(v, 2) for k, v in selector['parameters'].items()} == {
        'A_SIGNED': 0, 'A_WIDTH': 8, 'B_SIGNED': 0, 'B_WIDTH': 3, 'Y_WIDTH': 1}
    assert selector['port_directions'] == {'A': 'input', 'B': 'input', 'Y': 'output'}
    assert selector['connections']['B'] == module['ports']['shift']['bits']
    assert selector['connections']['Y'] == module['ports']['actual_carry']['bits']
    prefix = selector['connections']['A']
    assert len(prefix) == 8 and prefix[0] == '0'
    assert all(type(b) is int for b in prefix[1:]) and len(set(prefix[1:])) == 7
    return dict(kinds)


def mapping_diagnostics(text):
    """Only exact donor memory notices and the measured ABC notice are known.

    Each occurs three times in the measured original lane mapping: initial
    parse plus the two parameter specializations. Any other message/count/site
    fails. ABC's default scorr step also issues one combinational-network
    notice between scorr and dc2; the lane separately must contain no flops.
    Its combinational early-return cases are in the upstream primary source:
    https://github.com/berkeley-abc/abc/blob/master/src/base/abci/abc.c
    This is not a waiver of unknown warnings or FPGA DRC/timing.
    """
    donor = lane.SOURCES[0]
    expected = Counter({
        f'Warning: Replacing memory \\temp_array with list of registers. See {donor}:41, {donor}:33': 3,
        f'Warning: Replacing memory \\input_array with list of registers. See {donor}:33, {donor}:28': 3,
        'ABC: Warning: The network is combinational (run "fraig" or "fraig_sweep").': 1})
    warnings = [s for s in text.splitlines() if re.search(r'(?i)\bwarning:', s)]
    assert Counter(warnings) == expected, ('Unexpected mapping diagnostic count/source/site', warnings)
    context = 'ABC: + scorr \nABC: Warning: The network is combinational (run "fraig" or "fraig_sweep").\nABC: + dc2 '
    assert text.count(context) == 1, 'Changed ABC diagnostic step or context'
    assert not re.search(r'(?im)ERROR:|FATAL:|sorry:', text), 'Failed mapping diagnostics'
    return dict(expected)


def main():
    validate_sources()
    out = ROOT / f'build/rknpu-dsp-prefix-carry/{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    negative = out / 'negative_lemma.sv'
    negative.write_text(LEMMA.read_text().replace('assign mismatch = reference_carry ^ actual_carry;',
        "assign mismatch = reference_carry ^ actual_carry ^ 1'b1;"))
    wrappers = out / 'area_wrappers.sv'
    wrappers.write_text('\n'.join('module cmac_lane_' + name + '_area(input [15:0] op_a,op_b, input [3:0] exp_sft, '
        'input pair_nz, output [31:0] lane_sum, output [7:0] res_tag);\n' + module +
        ' actual(.op_a,.op_b,.exp_sft,.pair_nz,.lane_sum,.res_tag);\nendmodule\n'
        for name, module in (('reference', 'rk_cmac_fp16_lane_dsp'), ('actual', 'rk_cmac_fp16_lane_dsp_prefix'))))
    sources = [*lane.SOURCES[:4], HELPER, CANDIDATE]
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [*sources, LEMMA, MITER, lane.BENCH, negative, wrappers, Path(__file__).resolve(),
        ROOT / 'rtl/vendor/nvdla/LICENSE', *imported]
    before = fingerprint(tracked); generated = [negative, wrappers]
    report = dict(status='RUNNING', stage='binary_lemma', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[],
        lemma_free_binary_inputs=67, source_bound_lane_binary_inputs=37, compared_lane_outputs=40,
        expected_native_comparisons=135680, seed='0x3588d501',
        source_bound_binary_lane_equivalence=False, native_binary_fixture_acceptance=False,
        four_state_leaf_acceptance=False, mapped_numerical_acceptance=False,
        full_array_numerical_acceptance=False, raw_board_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False, scope=__doc__)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, kind='command', timeout=1800):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=timeout)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            if kind.startswith('sat_'): validate_sat(text, code, kind == 'sat_negative')
            elif kind == 'native_negative':
                assert code == 1 and 'LANE_DSP_MISMATCH' in text and 'PASS ' not in text
                assert not re.search(r'(?im)warning:|sorry:', text)
            elif kind == 'xc7_mapping':
                assert code == 0, text[-4000:]
                report.setdefault('mapping_diagnostics', {})[label] = mapping_diagnostics(text)
            else:
                assert code == 0 and not re.search(r'(?im)^Warning:|\bwarning:|ERROR:|FATAL:|sorry:', text), text[-4000:]
                if kind == 'native_actual':
                    assert [s for s in text.splitlines() if s.startswith('PASS ')] == [EXPECTED]
                    report['native_result'] = EXPECTED
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - start, 3); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save(); print(out / 'report.json', flush=True)
    try:
        report['tool_version'] = run(['yosys', '-V'], 'yosys_version').strip()
        report['iverilog_version'] = run(['iverilog', '-V'], 'iverilog_version').splitlines()[0]
        report['vvp_version'] = run(['vvp', '-V'], 'vvp_version').splitlines()[0]
        for p in sorted(set(tracked)):
            target = out / 'snapshot' / p.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(p.read_bytes()); generated.append(target)
        for name, miter in (('negative', negative), ('actual', LEMMA)):
            graph, script = out / (name + '.json'), out / (name + '_lowering.ys')
            script.write_text('read_verilog -sv ' + ' '.join(json.dumps(str(p)) for p in (HELPER, miter)) +
                '\nhierarchy -check -top ' + TOP + '\nproc\nflatten -noscopeinfo\nopt -full\ncheck -assert\nwrite_json ' + json.dumps(str(graph)) + '\n')
            generated += [graph, script]
            report.setdefault('lowering_inputs', {})[name] = fingerprint([HELPER, miter, script]); save()
            run(['yosys', '-Q', '-T', '-s', script], name + '_lowering')
            report.setdefault('lemma_graph_cells', {})[name] = validate_graph(json.loads(graph.read_text()))
            proof = out / (name + '_sat.ys'); generated.append(proof)
            proof.write_text('read_json ' + json.dumps(str(graph)) + '\nsat -verify -prove mismatch 0 -show-inputs -show-outputs -timeout 900\n')
            binding = fingerprint([graph, proof]); report.setdefault('proof_inputs', {})[name] = binding; save()
            run(['yosys', '-Q', '-T', '-s', proof], name + '_sat', 'sat_' + name, 1000)
            assert fingerprint([graph, proof]) == binding
        validate_sources(); report['source_bound_binary_lane_equivalence'] = True
        report['stage'] = 'xc7_area'; save()
        for name in ('reference', 'actual'):
            top = 'cmac_lane_' + name + '_area'; netlist, script = out / (name + '_xc7.json'), out / (name + '_xc7.ys')
            script.write_text(lane.area_script([*sources, wrappers], top, netlist)); generated += [netlist, script]
            binding = fingerprint([*sources, wrappers, script]); report.setdefault('mapping_inputs', {})[name] = binding; save()
            run(['yosys', '-Q', '-T', '-s', script], name + '_xc7_mapping', 'xc7_mapping')
            assert fingerprint([*sources, wrappers, script]) == binding
            design = json.loads(netlist.read_text()); counts = lane.validate_area(design, top, 1)
            assert not any(v for k, v in counts.items() if k.startswith('FD'))
            _, audit = timing_only_view(design['modules'])
            report.setdefault('timing_qualifier_counter_audit', {})[name] = audit
            report.setdefault('mapped_cells', {})[name] = counts
            report.setdefault('mapped_lut_primitives', {})[name] = sum(v for k, v in counts.items() if k.startswith('LUT'))
        report['stage'] = 'native_binary'; save()
        for name, defines in (('negative', ['-DRK_LANE_DSP_NEGATIVE']), ('actual', [])):
            binary = out / (name + '.vvp'); generated.append(binary)
            binding = fingerprint([*sources, MITER, lane.BENCH]); report.setdefault('native_compile_inputs', {})[name] = binding; save()
            run(['iverilog', '-g2012', *defines, '-s', 'tb_cmac_lane_dsp', '-o', binary, *sources, MITER, lane.BENCH], name + '_compile')
            execution = fingerprint([binary]); report.setdefault('execution_inputs', {})[name] = execution; save()
            run(['vvp', binary, '+SAMPLES=4096'], name + '_native', 'native_' + name)
            assert fingerprint([*sources, MITER, lane.BENCH]) == binding and fingerprint([binary]) == execution
        assert fingerprint(tracked) == before; validate_sources()
        report.update(status='PASS_ISOLATED_DSP_PREFIX_CARRY_BINARY_AND_AREA_ONLY', stage='complete',
            finished_utc=timestamp(), native_binary_fixture_acceptance=True,
            artifacts=fingerprint([*generated, *out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *out.glob('*.log')] if p.is_file()])); raise
    finally: save()
    print(report['status'], flush=True)


if __name__ == '__main__': main()
