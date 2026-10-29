#!/usr/bin/env python3
"""Isolated corrected DSP lane experiment: real HDL, binary SAT and XC7 area.

Not an array/raw-board test. A lane-sum representation may change only after
its donor truncation correction, tags and binary equivalence are established.
"""
from collections import Counter
import hashlib
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
from xc7_primitive_counts import primitive_counts
from lane_dsp_library import timing_only_view

TOP = 'cmac_lane_dsp_miter'
SOURCES = [ROOT / name for name in (
    'rtl/vendor/nvdla/NV_DW02_tree.v', 'rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'rtl/cmac/experimental/rk_cmac_fp16_rows.sv', 'rtl/cmac/experimental/rk_cmac_fp16_lane_dsp.sv',
    'tests/cmac/cmac_lane_dsp_miter.sv')]
BENCH = ROOT / 'tests/cmac/tb_cmac_lane_dsp.sv'
COMBINATIONAL = {'$add', '$and', '$eq', '$gt', '$logic_not', '$logic_or', '$mul', '$mux',
    '$neg', '$not', '$or', '$pmux', '$reduce_bool', '$reduce_or', '$shl', '$shr', '$sub', '$xor',
    '$lt', '$ne', '$reduce_and'}
AREA_INPUTS = {'op_a': 16, 'op_b': 16, 'exp_sft': 4, 'pair_nz': 1}
AREA_OUTPUTS = {'lane_sum': 32, 'res_tag': 8}


def area_script(sources, top, netlist):
    """Flatten the selected lane, so unused miter outputs cannot retain logic."""
    assert top in {'cmac_lane_reference_area', 'cmac_lane_actual_area'}
    return ('read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' +
        ' '.join(json.dumps(str(p)) for p in sources) + '\n' +
        'synth_xilinx -family xc7 -top ' + top + ' -flatten -noiopad\n' +
        'check -assert\nwrite_json ' + json.dumps(str(netlist)) + '\n')


def validate_area(design, top, expected_dsp):
    module = design['modules'][top]
    assert {n: (p['direction'], len(p['bits'])) for n, p in module['ports'].items()} == {
        **{n: ('input', w) for n, w in AREA_INPUTS.items()},
        **{n: ('output', w) for n, w in AREA_OUTPUTS.items()}}
    bits = [b for n in AREA_INPUTS for b in module['ports'][n]['bits']]
    assert all(type(b) is int for b in bits) and len(set(bits)) == 37, 'Reduced or coupled area inputs'
    library_view, _ = timing_only_view(design['modules'])
    counts = dict(primitive_counts(library_view, top))
    assert counts.get('DSP48E1', 0) == expected_dsp, ('Unexpected DSP mapping', counts)
    assert sum(v for k, v in counts.items() if k.startswith('LUT')) > 0, 'Lost mapped lane logic'
    return counts


def validate_graph(design):
    assert set(design['modules']) == {TOP}, 'Unflattened comparison or retained library'
    module = design['modules'][TOP]
    inputs = {n: p for n, p in module['ports'].items() if p['direction'] == 'input'}
    assert {n: len(p['bits']) for n, p in inputs.items()} == {'op_a': 16, 'op_b': 16, 'exp_sft': 4, 'pair_nz': 1}
    bits = [b for p in inputs.values() for b in p['bits']]
    assert all(type(b) is int for b in bits) and len(set(bits)) == 37, 'Reduced or coupled proof domain'
    outputs = {n: len(p['bits']) for n, p in module['ports'].items() if p['direction'] == 'output'}
    assert outputs == {'reference_lane': 32, 'actual_lane': 32, 'reference_tag': 8,
        'actual_tag': 8, 'difference': 40, 'mismatch': 1}
    counts = Counter(c['type'] for c in module['cells'].values())
    assert set(counts) <= COMBINATIONAL, ('State, assumptions or unmodeled cells', counts)
    assert counts['$mul'] == 1, 'Lost actual DSP-targeted multiply in native comparison'
    return dict(counts)


def sanity_miter(text):
    before = 'reference_lane ^ actual_lane, reference_tag ^ actual_tag'
    assert text.count(before) == 1
    return text.replace(before, "reference_lane ^ actual_lane ^ 32'h00000001, reference_tag ^ actual_tag")


def main():
    out = ROOT / f'build/rknpu-lane-dsp-experiment/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    negative = out / 'negative_miter.sv'; negative.write_text(sanity_miter(SOURCES[-1].read_text()))
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [*SOURCES, BENCH, negative, ROOT / 'rtl/vendor/nvdla/LICENSE', Path(__file__).resolve(), *imported]
    report = dict(status='RUNNING', stage='native', started_utc=timestamp(), supervisor_pid=os.getpid(),
        source=fingerprint(tracked), python_version=sys.version, commands=[],
        seed='0x3588d501; 144 directed operand pairs and 4096 random pairs, each with all 16 shifts and both masks',
        expected_native_comparisons=135680, relevant_binary_input_bits=37, compared_binary_output_bits=40,
        binary_lane_sum_equivalence=False, full_array_numerical_acceptance=False,
        raw_board_numerical_acceptance=False, physical_fit_verified=False,
        bitstream_emitted=False, hardware_programmed=False,
        scope='Isolated compensated lane-sum/tag experiment on sign/pre-shifted magnitudes. Retains donor first-row low-bit carry correction; not identical carry-save row encodings, all-X/IEEE arithmetic, reset/configuration, full C32/K16 integration, mapped numerical/UNISIM/DSP timing, FPGA or RK acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, expected='zero', timeout=1800):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)),
            status='RUNNING', expected=expected)
        report['commands'].append(step); save(); started = time.monotonic()
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
            if expected == 'HDL mismatch':
                assert code == 1 and 'LANE_DSP_MISMATCH' in text and 'PASS ' not in text, text[-3000:]
            elif expected == 'SAT countermodel':
                assert code == 1 and 'SAT proof finished - model found: FAIL!' in text
                assert 'Called with -verify and proof did fail!' in text, text[-3000:]
            else:
                assert code == 0 and 'ERROR:' not in text and 'FATAL:' not in text, text[-3000:]
                if label.endswith('_compile'):
                    assert not re.search(r'(?im)\b(?:warning|error):', text), text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save()
    generated = [negative]
    try:
        for path in tracked:
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        report['tool_version'] = run(['yosys', '-V'], 'yosys_version').strip()
        for command in ('iverilog', 'vvp'):
            report[command + '_version'] = run([command, '-V'], command + '_version').splitlines()[0]
        for label, defines in [('native_negative', ['-DRK_LANE_DSP_NEGATIVE']), ('native_actual', [])]:
            executable = out / (label + '.vvp'); generated.append(executable)
            before = fingerprint([*SOURCES, BENCH])
            report.setdefault('native_compile_inputs', {})[label] = before; save()
            run(['iverilog', '-g2012', *defines, '-s', 'tb_cmac_lane_dsp', '-o', executable, *SOURCES, BENCH], label + '_compile')
            assert fingerprint([*SOURCES, BENCH]) == before
            binding = fingerprint([executable]); report.setdefault('native_execution_inputs', {})[label] = binding; save()
            text = run(['vvp', executable, '+SAMPLES=4096'], label + '_test', 'HDL mismatch' if defines else 'zero')
            assert fingerprint([executable]) == binding and fingerprint([*SOURCES, BENCH]) == before
            if not defines:
                marker = 'PASS LANE_DSP_BINARY_FIXTURES comparisons=135680 seed=3588d501 samples=4096'
                assert [l for l in text.splitlines() if l.startswith('PASS ')] == [marker]
                report['native_result'] = marker
        report['stage'] = 'binary_formal'; save()
        for label, miter in [('negative_formal', negative), ('actual_formal', SOURCES[-1])]:
            graph, script = out / (label + '.json'), out / (label + '.ys')
            paths = [*SOURCES[:-1], miter]
            script.write_text('read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' +
                ' '.join(json.dumps(str(p)) for p in paths) + '\n' +
                'hierarchy -check -top ' + TOP + '\nproc\nflatten -noscopeinfo\nopt -full\ncheck -assert\n' +
                'write_json ' + json.dumps(str(graph)) + '\n')
            generated += [graph, script]
            run(['yosys', '-Q', '-T', '-s', script], label + '_lowering')
            report[label + '_cells'] = validate_graph(json.loads(graph.read_text()))
            proof = out / (label + '_sat.ys'); generated.append(proof)
            proof.write_text('read_json ' + json.dumps(str(graph)) + '\n' +
                'sat -verify -prove mismatch 0 -show-inputs -show-outputs -timeout 900\n')
            text = run(['yosys', '-Q', '-T', '-s', proof], label + '_sat',
                'SAT countermodel' if label == 'negative_formal' else 'zero', timeout=1000)
            if label == 'actual_formal':
                assert 'SAT proof finished - no model found: SUCCESS!' in text, text[-3000:]
                report['binary_lane_sum_equivalence'] = True
        report['stage'] = 'xc7_area'; save()
        wrappers = out / 'area_wrappers.sv'
        parts = []
        for label in ('reference', 'actual'):
            parts.append('module cmac_lane_' + label + '_area(input [15:0] op_a,op_b, input [3:0] exp_sft, input pair_nz, output [31:0] lane_sum, output [7:0] res_tag);\n' +
                TOP + ' core(.op_a(op_a),.op_b(op_b),.exp_sft(exp_sft),.pair_nz(pair_nz),' +
                '.reference_lane(' + ('lane_sum' if label == 'reference' else '') + '),' +
                '.reference_tag(' + ('res_tag' if label == 'reference' else '') + '),' +
                '.actual_lane(' + ('lane_sum' if label == 'actual' else '') + '),' +
                '.actual_tag(' + ('res_tag' if label == 'actual' else '') + '),.difference(),.mismatch());\nendmodule\n')
        wrappers.write_text('\n'.join(parts)); generated.append(wrappers)
        for label in ('reference', 'actual'):
            top = 'cmac_lane_' + label + '_area'
            script, netlist = out / (label + '_xc7.ys'), out / (label + '_xc7.json')
            script.write_text(area_script([*SOURCES, wrappers], top, netlist))
            generated += [script, netlist]
            run(['yosys', '-Q', '-T', '-s', script], label + '_xc7_mapping')
            counts = validate_area(json.loads(netlist.read_text()), top, 1 if label == 'actual' else 0)
            report.setdefault('mapped_cells', {})[label] = counts
            report.setdefault('mapped_lut_primitives', {})[label] = sum(v for k, v in counts.items() if k.startswith('LUT'))
        assert fingerprint(tracked) == report['source'], 'Changed experiment source'
        report.update(status='PASS_ISOLATED_CORRECTED_DSP_LANE_BINARY_AND_XC7_AREA_ONLY', stage='complete',
            finished_utc=timestamp(), artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException:
        report.update(status='FAIL', finished_utc=timestamp()); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
