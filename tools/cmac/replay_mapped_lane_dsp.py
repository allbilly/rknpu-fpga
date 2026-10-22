#!/usr/bin/env python3
"""Continue an unchanged, bound mapped lane after its real wall-time timeout.

Preserve the failed parent. Reuse only its verified compiled binaries and
completed native/export stages; execute a fresh mapped negative and the full
original positive corpus. Explicit inherited command provenance is retained.
No source/model/assertion changes, reduced corpus or physical acceptance.
"""
import argparse
from copy import deepcopy
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
from test_mapped_lane_dsp import (BENCH, MARKER, SOURCES, validate_result)
from test_fixed_array_board import verify_manifest

LABELS = ['yosys_version', 'iverilog_version', 'vvp_version', 'datadir', 'export', 'roundtrip'] + [
    p + '_' + m + '_' + a for p in ('native', 'mapped')
    for m in ('negative', 'actual') for a in ('compile', 'test')]


def validate_parent(report):
    assert report['status'] == 'FAIL' and report['stage'] == 'mapped' and report['finished_utc']
    assert re.fullmatch(r"TimeoutExpired\(\['vvp', '[^']+/mapped_actual\.vvp', '\+SAMPLES=4096'\], 1800\)", report['error'])
    assert (report['relevant_binary_input_bits'], report['compared_binary_output_bits']) == (37, 40)
    assert report['expected_comparisons_per_phase'] == 135680
    assert report['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
    assert report['mapped_cells']['DSP48E1'] == 1
    assert report['results'] == {'native_actual_test': MARKER}
    assert [Path(c['log']).stem for c in report['commands']] == LABELS
    for label, step in zip(LABELS[:-1], report['commands'][:-1]):
        assert step['status'] == 'PASS' and step['returncode'] == (1 if label.endswith('negative_test') else 0)
    last = report['commands'][-1]
    assert last['status'] == 'FAIL' and last.get('returncode') is None and last['seconds'] >= 1800
    assert last['argv'][0] == 'vvp' and last['argv'][2:] == ['+SAMPLES=4096']
    for field in ('binary_lane_sum_equivalence', 'isolated_mapped_binary_fixture_acceptance',
            'full_array_numerical_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[field] is False


def validate_bindings(report):
    for manifest in (report['source'], report['artifacts']): verify_manifest(manifest)
    for label in ('native_negative', 'native_actual', 'mapped_negative', 'mapped_actual'):
        for field in ('compile_inputs', 'execution_inputs'): verify_manifest(report[field][label])
        if label != 'mapped_actual':
            step = next(c for c in report['commands'] if Path(c['log']).stem == label + '_test')
            validate_result((ROOT / step['log']).read_text(), step['returncode'], label.endswith('negative'))
    installed = report['installed_model']
    assert hashlib.sha256(Path(installed['path']).read_bytes()).hexdigest() == installed['sha256']
    assert hashlib.sha256((ROOT / installed['frozen']).read_bytes()).hexdigest() == installed['sha256']


def inherited_commands(report):
    result = deepcopy(report['commands'][:-1])
    for index, step in enumerate(result):
        step['inherited_from_parent_command_index'] = index
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timed-out-report', type=Path, required=True)
    args = parser.parse_args(); parent_path = args.timed_out_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    parent = json.loads(parent_path.read_text()); validate_parent(parent); validate_bindings(parent)
    for label in ('mapped_negative', 'mapped_actual'):
        step = next(c for c in parent['commands'] if Path(c['log']).stem == label + '_test')
        binary = Path(step['argv'][1]).resolve()
        assert binary.is_relative_to(parent_path.parent)
        assert set(parent['execution_inputs'][label]['files']) == {str(binary.relative_to(ROOT))}
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    dependencies = {ROOT / name for manifest in [parent['source'], parent['artifacts'],
        *parent['compile_inputs'].values(), *parent['execution_inputs'].values()] for name in manifest['files']}
    tracked = [Path(__file__).resolve(), parent_path, *SOURCES, BENCH, *dependencies, *imported]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-dsp-mapped-lane-replay/{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='replay', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=inherited_commands(parent), resume_commands=[],
        parent_report=str(parent_path.relative_to(ROOT)), parent_status='FAIL',
        parent_source_sha256=parent['source']['sha256'], inherited_command_count=13,
        inheritance_contract='Only completed bound commands 0..12 from unchanged hardware/model/bench. The timed-out mapped positive is excluded; a newly executed full positive must pass. Fresh mapped negative and current runtime checks also required. Parent remains FAIL.',
        expected_comparisons_per_phase=135680, relevant_binary_input_bits=37, compared_binary_output_bits=40,
        seed=parent['seed'], mapped_cells=parent['mapped_cells'],
        export_circuit_identity=parent['export_circuit_identity'], installed_model=parent['installed_model'],
        yosys_version=parent['yosys_version'], iverilog_version=parent['iverilog_version'], vvp_version=parent['vvp_version'],
        compile_inputs=parent['compile_inputs'], execution_inputs=parent['execution_inputs'],
        results={'native_actual_test': MARKER}, binary_lane_sum_equivalence=False,
        isolated_mapped_binary_fixture_acceptance=False, full_array_numerical_acceptance=False,
        raw_board_numerical_acceptance=False, physical_fit_verified=False,
        bitstream_emitted=False, hardware_programmed=False,
        scope='Unchanged source-bound compiled mapped-lane continuation only. Completed actual native 135680/export stages explicitly inherited, not newly executed or evidence for changed RTL. Fresh mapped negative and all 135680 original positive comparisons required with 14400-second budget. Not formal, full-array/raw-board, packed fit, physical timing/electrical/DRC, bitstream, FPGA or RK acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, negative=None):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['resume_commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=14400 if negative is False else 1800)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            if negative is not None:
                marker = validate_result(text, code, negative)
                if marker: report['results']['mapped_actual_test'] = marker
            else: assert code == 0 and 'ERROR:' not in text
            step['status'] = 'PASS'; return text, step
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save(); generated = []
    try:
        for command in ('iverilog', 'vvp'):
            text, _ = run([command, '-V'], command + '_version')
            assert text.splitlines()[0] == parent[command + '_version']
        for path in sorted(set([Path(__file__).resolve(), parent_path, *SOURCES, BENCH, *imported])):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        for label, negative in [('mapped_negative', True), ('mapped_actual', False)]:
            step = next(c for c in parent['commands'] if Path(c['log']).stem == label + '_test')
            binary = Path(step['argv'][1]); binding = fingerprint([binary])
            assert binding == parent['execution_inputs'][label]
            _, executed = run(['vvp', binary, '+SAMPLES=4096'], label + '_test', negative)
            assert fingerprint([binary]) == binding; validate_bindings(parent)
            if not negative: report['commands'].append(deepcopy(executed))
        assert fingerprint(tracked) == before
        validate_parent(json.loads(parent_path.read_text())); validate_bindings(parent)
        assert [Path(c['log']).stem for c in report['commands']] == LABELS
        report.update(status='PASS_ISOLATED_ACTUAL_DSP_MAPPED_BINARY_FIXTURES_ONLY', stage='complete',
            finished_utc=timestamp(), isolated_mapped_binary_fixture_acceptance=True,
            artifacts=fingerprint([*dependencies, *generated, *(out.glob('*.log'))]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([*dependencies, *[p for p in generated if p.is_file()], *(out.glob('*.log'))])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
