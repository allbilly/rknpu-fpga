#!/usr/bin/env python3
"""Fresh native and actual XC7 DSP/LUT lane replay against donor rows.

Use only a completed source/artifact-bound isolated mapping. The mapped
compile excludes the native candidate body and imports its real DSP48E1
and all LUT/carry primitives with unchanged installed functional models.
This is binary fixture evidence, not formal, full-array or physical signoff.
"""
from collections import Counter
from copy import deepcopy
import argparse
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
from check_lane_dsp import SOURCES, BENCH, validate_area
from test_fixed_array_board import verify_manifest
from test_fixed_mapped_array import circuit_signature, hardware_instance_aliases

MAPPED_TOP = 'cmac_lane_actual_area'
TEST_TOP = 'tb_cmac_lane_dsp'
MARKER = 'PASS LANE_DSP_BINARY_FIXTURES comparisons=135680 seed=3588d501 samples=4096'


def validate_parent_metadata(report):
    assert report['status'] == 'PASS_ISOLATED_LANE_DSP_XC7_AREA_ONLY', 'Completed isolated area required'
    assert [Path(c['log']).stem for c in report['commands']] == ['version', 'reference_xc7_mapping', 'actual_xc7_mapping']
    assert all(c['status'] == 'PASS' and c['returncode'] == 0 for c in report['commands'])
    assert set(report['mapped_cells']) == set(report['mapped_lut_primitives']) == {'reference', 'actual'}
    for label, expected in [('reference', 0), ('actual', 1)]:
        counts = report['mapped_cells'][label]
        assert counts.get('DSP48E1', 0) == expected
        assert sum(v for k, v in counts.items() if k.startswith('LUT')) == report['mapped_lut_primitives'][label] > 0
    for field in ('numerical_equivalence_acceptance', 'mapped_numerical_acceptance',
            'full_array_numerical_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[field] is False, 'Misrepresented area-only scope'


def mapped_miter(text):
    before, after = 'rk_cmac_fp16_lane_dsp candidate (', MAPPED_TOP + ' candidate ('
    assert text.count(before) == 1 and after not in text
    mapped = text.replace(before, after)
    assert mapped.replace(after, before) == text
    return mapped


def validate_result(text, code, negative):
    assert not re.search(r'(?im)\b(?:warning|error):', text), text[-3000:]
    if negative:
        assert code == 1 and 'LANE_DSP_MISMATCH' in text and 'PASS ' not in text
    else:
        assert code == 0 and 'FATAL:' not in text
        assert [line for line in text.splitlines() if line.startswith('PASS ')] == [MARKER]
        return MARKER


def verify_export_domain(design):
    module = design['modules'][MAPPED_TOP]
    assert set(design['modules']) == {MAPPED_TOP}
    counts = Counter(c['type'] for c in module['cells'].values() if c['type'] != '$scopeinfo')
    assert counts['DSP48E1'] == 1
    assert set(counts) <= {'LUT1', 'LUT2', 'LUT3', 'LUT4', 'LUT5', 'LUT6',
        'CARRY4', 'MUXF7', 'MUXF8', 'INV', 'DSP48E1'}, 'Native/state/unmodeled cell in actual mapped circuit'
    assert sum(v for k, v in counts.items() if k.startswith('LUT')) > 0
    return dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--area-report', type=Path, required=True)
    args = parser.parse_args(); parent_path = args.area_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text()); validate_parent_metadata(parent)
    verify_manifest(parent['source']); verify_manifest(parent['artifacts'])
    graph = parent_path.parent / 'actual_xc7.json'
    assert str(graph.relative_to(ROOT)) in parent['artifacts']['files']
    original = json.loads(graph.read_text())
    assert validate_area(original, MAPPED_TOP, 1) == parent['mapped_cells']['actual']
    implementation = dict(original, modules={MAPPED_TOP: deepcopy(original['modules'][MAPPED_TOP])})
    counts = verify_export_domain(implementation)
    assert counts == parent['mapped_cells']['actual'], 'Mapped primitive domain changed'
    aliased, aliases = hardware_instance_aliases(implementation)
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), parent_path, graph, *SOURCES, BENCH,
        ROOT / 'rtl/vendor/nvdla/LICENSE', *imported]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-lane-dsp-mapped-binary/{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='export', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, parent_report=str(parent_path.relative_to(ROOT)),
        parent_source_sha256=parent['source']['sha256'], commands=[], expected_comparisons_per_phase=135680,
        seed='0x3588d501; original 144 directed plus 4096 random operand pairs, all 16 shifts and both masks',
        relevant_binary_input_bits=37, compared_binary_output_bits=40, mapped_cells=counts,
        binary_lane_sum_equivalence=False, isolated_mapped_binary_fixture_acceptance=False,
        full_array_numerical_acceptance=False, raw_board_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Fresh unchanged donor lane fixtures and real negatives for native and actual mapped DSP/LUT circuit. No native candidate body in mapped compile. Functional models only, no SDF/timing or exhaustive binary/X proof. Not full C32/K16 array, raw board, placed fit, electrical/DRC, bitstream, FPGA or RK acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, negative=None):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=1800)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            if negative is not None:
                marker = validate_result(text, code, negative)
                if marker: report.setdefault('results', {})[label] = marker
            else:
                assert code == 0 and 'ERROR:' not in text
                if label not in ('iverilog_version', 'vvp_version'):
                    assert not re.search(r'(?im)\b(?:warning|error):', text), text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save(); generated = []
    try:
        report['yosys_version'] = run(['yosys', '-V'], 'yosys_version').strip()
        assert report['yosys_version'] == parent['tool_version']
        for name in ('iverilog', 'vvp'): report[name + '_version'] = run([name, '-V'], name + '_version').splitlines()[0]
        model = Path(run(['yosys-config', '--datdir'], 'datadir').strip()) / 'xilinx/cells_sim.v'
        frozen = out / 'xilinx_functional_models.v'; frozen.write_bytes(model.read_bytes()); generated.append(frozen)
        model_hash = hashlib.sha256(model.read_bytes()).hexdigest()
        report['installed_model'] = dict(path=str(model), sha256=model_hash, frozen=str(frozen.relative_to(ROOT)))
        for path in sorted(set(tracked)):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        partition, alias_path = out / 'aliased_mapping.json', out / 'hardware_instance_aliases.json'
        partition.write_text(json.dumps(aliased) + '\n'); alias_path.write_text(json.dumps(aliases, indent=2) + '\n')
        netlist, script = out / 'mapped_lane.v', out / 'export.ys'
        # Yosys handles the actual DSP string parameters. No custom exporter
        # defaults/substitution or change to any native/mapped primitive.
        script.write_text('read_json ' + json.dumps(str(partition)) + '\n' +
            'write_verilog -noattr -noexpr -norename -nodec -nohex ' + json.dumps(str(netlist)) + '\n')
        generated += [partition, alias_path, netlist, script]
        export_binding = fingerprint([partition, script]); report['export_inputs'] = export_binding; save()
        run(['yosys', '-Q', '-T', '-s', script], 'export')
        assert fingerprint([partition, script]) == export_binding
        roundtrip, check = out / 'export_roundtrip.json', out / 'roundtrip.ys'
        check.write_text('read_verilog -sv ' + json.dumps(str(netlist)) + '\nwrite_json ' + json.dumps(str(roundtrip)) + '\n')
        generated += [roundtrip, check]; run(['yosys', '-Q', '-T', '-s', check], 'roundtrip')
        assert circuit_signature(json.loads(roundtrip.read_text())) == circuit_signature(aliased), 'Export changed mapped circuit'
        report['export_circuit_identity'] = 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
        adapter = out / 'mapped_miter.sv'; adapter.write_text(mapped_miter(SOURCES[-1].read_text())); generated.append(adapter)
        for phase, sources in [('native', [*SOURCES, BENCH]),
                ('mapped', [*SOURCES[:3], adapter, netlist, frozen, BENCH])]:
            report['stage'] = phase; save()
            if phase == 'mapped':
                assert SOURCES[-2] not in sources and SOURCES[-1] not in sources
                assert adapter.read_text() == mapped_miter(SOURCES[-1].read_text())
            for negative in (True, False):
                label = phase + ('_negative' if negative else '_actual'); binary = out / (label + '.vvp'); generated.append(binary)
                inputs = [*sources, graph, partition, alias_path, roundtrip] if phase == 'mapped' else sources
                binding = fingerprint(inputs); report.setdefault('compile_inputs', {})[label] = binding; save()
                flags = ['-DRK_LANE_DSP_NEGATIVE'] if negative else []
                run(['iverilog', '-g2012', *flags, '-s', TEST_TOP, '-o', binary, *sources], label + '_compile')
                assert fingerprint(inputs) == binding
                executable = fingerprint([binary]); report.setdefault('execution_inputs', {})[label] = executable; save()
                run(['vvp', binary, '+SAMPLES=4096'], label + '_test', negative)
                assert fingerprint(inputs) == binding and fingerprint([binary]) == executable
        assert fingerprint(tracked) == before and hashlib.sha256(model.read_bytes()).hexdigest() == model_hash
        assert frozen.read_bytes() == model.read_bytes()
        validate_parent_metadata(json.loads(parent_path.read_text()))
        assert circuit_signature(json.loads(roundtrip.read_text())) == circuit_signature(aliased)
        assert mapped_miter(SOURCES[-1].read_text()) == adapter.read_text()
        report.update(status='PASS_ISOLATED_ACTUAL_DSP_MAPPED_BINARY_FIXTURES_ONLY', stage='complete', finished_utc=timestamp(),
            isolated_mapped_binary_fixture_acceptance=True, artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *(out.glob('*.log'))] if p.is_file()])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
