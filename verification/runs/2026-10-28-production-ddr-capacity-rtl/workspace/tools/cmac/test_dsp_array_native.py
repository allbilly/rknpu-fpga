#!/usr/bin/env python3
"""Full C32/K16 DSP candidate, original numerical/hold/reset/X assertions.

Requires completed actual mapped-lane fixture evidence and unchanged oracle
vectors. No formal, full-array mapped, raw-board or physical acceptance.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from dsp_array_contract import (BENCH, DSP_ARRAY, DSP_CELL, FIXED_ARRAY, FIXED_CELL,
    array_bench, validate_sources)
from test_mapped_lane_dsp import MARKER, SOURCES, validate_result as validate_lane_result
from test_fixed_array_board import verify_manifest
from test_fixed_mapped_array import negative_vectors

EXPECTED = ('PASS sized FP16 CMAC C=32 K=16 frames=208 checked_outputs=3328 '
    'retired_outputs=3312 reset_canceled=16 held_cycles=520 faults=1')


def validate_leaf_metadata(report):
    assert report['status'] == 'PASS_ISOLATED_ACTUAL_DSP_MAPPED_BINARY_FIXTURES_ONLY'
    assert report['stage'] == 'complete' and report['isolated_mapped_binary_fixture_acceptance'] is True
    assert (report['relevant_binary_input_bits'], report['compared_binary_output_bits']) == (37, 40)
    assert report['expected_comparisons_per_phase'] == 135680
    assert report['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
    assert report['mapped_cells']['DSP48E1'] == 1
    assert report['results'] == {'native_actual_test': MARKER, 'mapped_actual_test': MARKER}
    labels = ['yosys_version', 'iverilog_version', 'vvp_version', 'datadir', 'export', 'roundtrip'] + [
        phase + '_' + mode + '_' + action for phase in ('native', 'mapped')
        for mode in ('negative', 'actual') for action in ('compile', 'test')]
    assert [Path(c['log']).stem for c in report['commands']] == labels
    for label, command in zip(labels, report['commands']):
        assert command['status'] == 'PASS' and command['returncode'] == (1 if label.endswith('negative_test') else 0)
    for field in ('binary_lane_sum_equivalence', 'full_array_numerical_acceptance',
            'raw_board_numerical_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[field] is False


def validate_vectors(report):
    assert report['status'] == 'PASS_SIZED_CMAC_VECTOR_GENERATION'
    assert (report['channels'], report['kernels'], report['frames'], report['outputs']) == (32, 16, 208, 3328)
    assert report['seed'] == '0x35883216'
    assert report['categories'] == {'uniform_edges': 16, 'one_channel': 32,
        'random_bits': 64, 'random_finite': 64, 'masked_edges': 32}


def validate_result(text, code, negative=False):
    assert not re.search(r'(?im)\b(?:warning|error):|sorry:', text), text[-3000:]
    if negative:
        assert code == 1 and re.search(r'sized array mismatch frame=0(?:\s|$)', text) and 'PASS ' not in text
    else:
        assert code == 0 and 'FATAL:' not in text
        assert [line for line in text.splitlines() if line.startswith('PASS ')] == [EXPECTED]
        return EXPECTED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane-report', type=Path, required=True)
    parser.add_argument('--vector-report', type=Path,
        default=ROOT / 'build/rknpu-cmac-array/c32k16/vectors_report.json')
    args = parser.parse_args(); lane_path, vector_path = args.lane_report.resolve(), args.vector_report.resolve()
    assert lane_path.is_relative_to(ROOT) and vector_path.is_relative_to(ROOT)
    lane = json.loads(lane_path.read_text()); validate_leaf_metadata(lane)
    vectors = json.loads(vector_path.read_text()); validate_vectors(vectors)
    for manifest in (lane['source'], lane['artifacts'], vectors['source'], vectors['artifacts']): verify_manifest(manifest)
    for label in ('native_negative', 'native_actual', 'mapped_negative', 'mapped_actual'):
        for field in ('compile_inputs', 'execution_inputs'): verify_manifest(lane[field][label])
        step = next(c for c in lane['commands'] if Path(c['log']).stem == label + '_test')
        validate_lane_result((ROOT / step['log']).read_text(), step['returncode'], label.endswith('negative'))
    validate_sources()
    vector_data = vector_path.parent / 'vectors.hex'
    assert str(vector_data.relative_to(ROOT)) in vectors['artifacts']['files']
    assert len(vector_data.read_text().splitlines()) == 208
    donor = ROOT / 'rtl/vendor/nvdla'
    sources = [donor / 'compat/nv_assert_never.v', donor / 'compat/nv_assert_no_x.v',
        *SOURCES[:4], DSP_CELL, DSP_ARRAY]
    assert FIXED_CELL not in sources and FIXED_ARRAY not in sources
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), lane_path, vector_path, vector_data, BENCH,
        FIXED_CELL, FIXED_ARRAY, *sources, *imported] + [donor / name for name in
        ('nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'assertion_header.h', 'assertion_task.h', 'LICENSE')]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-dsp-array-native/{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='compile', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[], channels=32, kernels=16,
        parallel_products=512, frames=208, expected_outputs=3328, seed=vectors['seed'],
        lane_report=str(lane_path.relative_to(ROOT)), lane_source_sha256=lane['source']['sha256'],
        vector_report=str(vector_path.relative_to(ROOT)), expected_result=EXPECTED,
        binary_lane_sum_equivalence=False, native_array_fixture_acceptance=False,
        full_array_mapped_numerical_acceptance=False, raw_board_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Full C32/K16 native four-state simulator with unchanged sized-CMAC oracle corpus/bench assertions, exact declared compensated-lane substitution only. All 512 lanes and 16 kernels, holds, reset cancellation, NaN priority and one real X-input rejection retained. Not exhaustive X/binary proof, mapped array/board, packed fit/timing/electrical/DRC, bitstream, FPGA or RK acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, negative=None):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            if negative is not None:
                result = validate_result(text, code, negative)
                if result: report['result'] = result
            else:
                assert code == 0 and 'ERROR:' not in text
                if label == 'compile': assert not re.search(r'(?im)\b(?:warning|error):|sorry:', text)
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save(); generated = []
    try:
        report['tool_version'] = run(['iverilog', '-V'], 'iverilog_version').splitlines()[0]
        report['runtime_version'] = run(['vvp', '-V'], 'vvp_version').splitlines()[0]
        assert report['tool_version'] == lane['iverilog_version'] and report['runtime_version'] == lane['vvp_version']
        for path in sorted(set(tracked)):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        bench, negative = out / BENCH.name, out / 'negative_vectors.hex'
        bench.write_text(array_bench(BENCH.read_text())); negative.write_text(negative_vectors(vector_data.read_text()))
        generated += [bench, negative]; binary = out / 'sim.vvp'; generated.append(binary)
        inputs = [*sources, bench]; binding = fingerprint(inputs); report['compile_inputs'] = binding; save()
        run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
            '-s', 'tb_cmac_fp16_array', '-Ptb_cmac_fp16_array.ATOMIC_C=32', '-Ptb_cmac_fp16_array.ATOMIC_K=16',
            '-o', binary, *sources, bench], 'compile')
        assert fingerprint(inputs) == binding
        executable = fingerprint([binary]); report['execution_inputs'] = executable; report['stage'] = 'simulation'; save()
        for label, path, is_negative in [('negative_test', negative, True), ('actual_test', vector_data, False)]:
            stimulus = fingerprint([path]); report.setdefault('stimulus_inputs', {})[label] = stimulus; save()
            run(['vvp', binary, f'+VECTORS={path}', '+COUNT=208'], label, is_negative)
            assert fingerprint([path]) == stimulus and fingerprint([binary]) == executable and fingerprint(inputs) == binding
        assert bench.read_text() == array_bench(BENCH.read_text()) and fingerprint(tracked) == before
        validate_sources(); validate_vectors(json.loads(vector_path.read_text()))
        for manifest in (lane['source'], lane['artifacts'], vectors['source'], vectors['artifacts']): verify_manifest(manifest)
        report.update(status='PASS_FULL_C32K16_DSP_ARRAY_NATIVE_FIXTURES_ONLY', stage='complete', finished_utc=timestamp(),
            native_array_fixture_acceptance=True, artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *(out.glob('*.log'))] if p.is_file()])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
