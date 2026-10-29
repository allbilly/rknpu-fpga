#!/usr/bin/env python3
"""Replay all nine unchanged raw-board modes using the bound DSP binary.

Requires completed full C32/K16 native fixtures, actual mapped-lane fixtures,
and source-bound composed binary lane evidence. Reuses only the verified full
board compile; no smaller array, recompiled bench, CPU fixup or physical claim.
"""
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
import prepare_dsp_board as preparation
import prove_lane_dsp_composed as composed
import test_dsp_array_native as native
import replay_mapped_lane_dsp as leaf_replay
from test_fixed_array_board import verify_manifest, validate_result as board_result

MODES = tuple(range(9))
UNPROVEN = ('full_array_mapped_numerical_acceptance', 'physical_fit_verified',
    'bitstream_emitted', 'hardware_programmed')


def workspace_path(name):
    path = (ROOT / name).resolve()
    assert path.is_relative_to(ROOT) and path.is_file(), 'Missing or external evidence: ' + str(name)
    return path


def command_contract(report, labels, negative=()):
    assert [Path(c['log']).stem for c in report['commands']] == list(labels), 'Incomplete or extra commands'
    for label, step in zip(labels, report['commands']):
        assert step['status'] == 'PASS' and step['returncode'] == int(label in negative), label


def validate_native_metadata(report):
    assert report['status'] == 'PASS_FULL_C32K16_DSP_ARRAY_NATIVE_FIXTURES_ONLY'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert report['native_array_fixture_acceptance'] is True
    assert (report['channels'], report['kernels'], report['parallel_products'],
        report['frames'], report['expected_outputs'], report['seed']) == (32, 16, 512, 208, 3328, '0x35883216')
    assert report['expected_result'] == report['result'] == native.EXPECTED
    command_contract(report, ('iverilog_version', 'vvp_version', 'compile', 'negative_test', 'actual_test'),
        ('negative_test',))
    for field in (*UNPROVEN, 'raw_board_numerical_acceptance', 'binary_lane_sum_equivalence'):
        assert report[field] is False, 'Overstated native evidence: ' + field


def validate_prepared_metadata(report):
    assert report['status'] == 'PREPARED_COMPILED_FULL_C32K16_DSP_RAW_BOARD_ONLY'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    assert report['compiled_hierarchy'] == {'rk_cmac_fp16_cell_dsp': 16, 'rk_cmac_fp16_lane_dsp': 512}
    command_contract(report, ('rom_check', 'version', 'compile'))
    for field in ('native_array_fixture_acceptance', 'raw_board_numerical_acceptance',
        'mapped_array_numerical_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[field] is False, 'Compile preparation is not acceptance: ' + field


def validate_composed_metadata(report):
    assert report['status'] == 'PASS_COMPOSED_BINARY_LANE_SUM_TAG_CERTIFICATE_ONLY'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert (report['relevant_binary_input_bits'], report['compared_binary_output_bits']) == (37, 40)
    for field in ('binary_lane_sum_equivalence', 'composed_lane_proof',
        'candidate_multiply_binding_proved', 'shift_compensation_binding_proved'):
        assert report[field] is True
    for field in ('new_positive_monolithic_sat_proof', 'full_array_numerical_acceptance',
        'raw_board_numerical_acceptance', 'isolated_mapped_binary_fixture_acceptance',
        'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[field] is False
    command_contract(report, ('version', 'actual_lowering', 'negative_lowering', 'negative_sat'), ('negative_sat',))


def verify_evidence(value):
    """Verify every nested binding, not just the top-level source manifest."""
    if isinstance(value, dict):
        if isinstance(value.get('files'), dict):
            verify_manifest(value)
        for item in value.values():
            verify_evidence(item)
    elif isinstance(value, list):
        for item in value:
            verify_evidence(item)


def verify_native(path):
    report = json.loads(path.read_text()); validate_native_metadata(report); verify_evidence(report)
    lane_path = workspace_path(report['lane_report'])
    lane = json.loads(lane_path.read_text()); native.validate_leaf_metadata(lane)
    assert report['lane_source_sha256'] == lane['source']['sha256']
    verify_evidence(lane)
    for label in ('native_negative', 'native_actual', 'mapped_negative', 'mapped_actual'):
        step = next(c for c in lane['commands'] if Path(c['log']).stem == label + '_test')
        native.validate_lane_result(workspace_path(step['log']).read_text(), step['returncode'], label.endswith('negative'))
    # A replay must preserve its failed parent and freshly execute the complete
    # mapped positive, not inherit the old timed-out command as a PASS.
    if 'resume_commands' in lane:
        failed = json.loads(workspace_path(lane['parent_report']).read_text())
        leaf_replay.validate_parent(failed); leaf_replay.validate_bindings(failed)
        assert lane['commands'][:13] == leaf_replay.inherited_commands(failed)
        assert lane['commands'][-1] == lane['resume_commands'][-1]
        assert [Path(c['log']).stem for c in lane['resume_commands']] == [
            'iverilog_version', 'vvp_version', 'mapped_negative_test', 'mapped_actual_test']
        for step in lane['resume_commands']:
            label = Path(step['log']).stem
            assert step['status'] == 'PASS' and step['returncode'] == int(label == 'mapped_negative_test')
            if label.endswith('_test'):
                assert step['argv'][2:] == ['+SAMPLES=4096']
                native.validate_lane_result(workspace_path(step['log']).read_text(), step['returncode'],
                    label == 'mapped_negative_test')
    installed = lane['installed_model']
    assert hashlib.sha256(Path(installed['path']).read_bytes()).hexdigest() == installed['sha256']
    assert hashlib.sha256(workspace_path(installed['frozen']).read_bytes()).hexdigest() == installed['sha256']
    vector_path = workspace_path(report['vector_report'])
    vectors = json.loads(vector_path.read_text()); native.validate_vectors(vectors); verify_evidence(vectors)
    data = vector_path.parent / 'vectors.hex'
    assert len(data.read_text().splitlines()) == 208
    bench = path.parent / native.BENCH.name
    assert bench.read_text() == native.array_bench(native.BENCH.read_text())
    negative = path.parent / 'negative_vectors.hex'
    assert negative.read_text() == native.negative_vectors(data.read_text())
    binary = path.parent / 'sim.vvp'
    assert report['execution_inputs'] == fingerprint([binary])
    donor = ROOT / 'rtl/vendor/nvdla'
    sources = [donor / 'compat/nv_assert_never.v', donor / 'compat/nv_assert_no_x.v',
        *native.SOURCES[:4], native.DSP_CELL, native.DSP_ARRAY]
    assert report['compile_inputs'] == fingerprint([*sources, bench])
    assert report['commands'][2]['argv'] == list(map(str, ['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST',
        '-DASSERT_ON', f'-I{donor}', '-s', 'tb_cmac_fp16_array', '-Ptb_cmac_fp16_array.ATOMIC_C=32',
        '-Ptb_cmac_fp16_array.ATOMIC_K=16', '-o', binary, *sources, bench]))
    for label, stimulus, is_negative in (('negative_test', negative, True), ('actual_test', data, False)):
        step = next(c for c in report['commands'] if Path(c['log']).stem == label)
        assert step['argv'] == ['vvp', str(binary), f'+VECTORS={stimulus}', '+COUNT=208']
        assert report['stimulus_inputs'][label] == fingerprint([stimulus])
        native.validate_result(workspace_path(step['log']).read_text(), step['returncode'], is_negative)
    for item in (lane_path, vector_path, data, native.BENCH, *sources):
        assert str(item.relative_to(ROOT)) in report['source']['files'], 'Unbound native prerequisite'
    return report


def verify_prepared(path, spec):
    report = json.loads(path.read_text()); validate_prepared_metadata(report); verify_evidence(report)
    join = path.parent / Path(preparation.JOIN).name
    assert join.read_text() == preparation.dsp_join((ROOT / preparation.JOIN).read_text())
    sources = preparation.simulation_sources(spec, join); bench = ROOT / spec['bench']
    assert report['simulation_sources'] == [str(p.relative_to(ROOT)) for p in sources]
    assert report['compile_inputs'] == fingerprint([*sources, bench])
    binary = path.parent / 'sim.vvp'
    assert str(binary.relative_to(ROOT)) in report['artifacts']['files']
    assert report['commands'][2]['argv'] == list(map(str, ['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST',
        '-DASSERT_ON', '-I' + str(ROOT / 'rtl/vendor/nvdla'), '-s', bench.stem,
        '-o', binary, *sources, bench]))
    assert preparation.validate_compiled_hierarchy(binary.read_text()) == report['compiled_hierarchy']
    for item in (preparation.SPEC, bench, ROOT / spec['constraints'], ROOT / preparation.JOIN, *sources,
        *sorted((ROOT / 'tests/cmac/array_data').iterdir())):
        assert str(item.relative_to(ROOT)) in report['source']['files'], 'Unbound board prerequisite'
    for step in report['commands']:
        text = workspace_path(step['log']).read_text()
        assert not re.search(r'(?im)\b(?:error|warning):|sorry:|FATAL:', text)
    return report, binary, sources


def verify_composed(path):
    report = json.loads(path.read_text()); validate_composed_metadata(report); verify_evidence(report)
    product_path = workspace_path(report['parent_report']); product = composed.validate_parent(product_path)
    assert report['parent_source_sha256'] == product['source']['sha256']
    contract = json.loads(composed.CONTRACT.read_text())
    texts = {m['source']: (ROOT / m['source']).read_text() for m in contract['modules']}
    assert report['composition_certificate'] == composed.alignment_certificate(contract, texts, product['certificate'])
    for mode in ('actual', 'negative'):
        assert report['graphs'][mode] == composed.validate_graph(json.loads((path.parent / (mode + '.json')).read_text()))
        step = next(c for c in report['commands'] if Path(c['log']).stem == mode + '_lowering')
        assert step['source_bound_array_lowering_notices'] == composed.product.ranges.audit_lowering_log(
            workspace_path(step['log']).read_text())
    step = report['commands'][-1]
    composed.product.components.validate_sat(workspace_path(step['log']).read_text(), step['returncode'], True)
    return report


def validate_board_result(text, code, mode):
    assert code == 0 and not re.search(r'(?im)\b(?:error|warning):|sorry:|FATAL:', text), text[-3000:]
    return board_result(text, mode)


def validate_suite(tests):
    assert [test['mode'] for test in tests] == list(MODES), 'All nine ordered four-state modes required'
    for test in tests:
        assert test['status'] == 'PASS'
        assert board_result(test['result'], test['mode']) == test['result']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--prepared-report', type=Path, required=True)
    parser.add_argument('--composed-report', type=Path, required=True)
    args = parser.parse_args()
    native_path, prep_path, proof_path = map(workspace_path,
        (args.native_report, args.prepared_report, args.composed_report))
    preparation.validate_sources(); spec = json.loads(preparation.SPEC.read_text())
    accepted = verify_native(native_path)
    prepared, binary, sources = verify_prepared(prep_path, spec)
    proof = verify_composed(proof_path)
    assert prepared['tool_version'] == accepted['tool_version']
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    parents = {'native': (native_path, accepted), 'prepared': (prep_path, prepared), 'composed': (proof_path, proof)}
    tracked = {Path(__file__).resolve(), native_path, prep_path, proof_path, binary, *imported}
    for _, parent in parents.values():
        tracked.update(ROOT / name for name in parent['source']['files'])
    tracked.update(sources)
    before = fingerprint(tracked); execution = fingerprint([binary])
    stimulus_files = sorted((ROOT / 'tests/cmac/array_data').iterdir())
    stimuli = fingerprint(stimulus_files)
    out = ROOT / f'build/rknpu-dsp-board-replay/{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='preflight', started_utc=timestamp(), source=before,
        python_version=sys.version, supervisor_pid=os.getpid(), commands=[], tests=[], channels=32,
        kernels=16, parallel_products=512, modes=list(MODES), four_state_mode_not_run=None,
        parent_reports={n: str(p.relative_to(ROOT)) for n, (p, _) in parents.items()},
        parent_source_sha256={n: p['source']['sha256'] for n, (_, p) in parents.items()},
        simulation_sources=prepared['simulation_sources'], compile_inputs=prepared['compile_inputs'],
        execution_inputs=execution, stimulus_inputs=stimuli, compiled_hierarchy=prepared['compiled_hierarchy'],
        inherited_compile_only=True, native_array_fixture_acceptance=True,
        source_bound_composed_lane_acceptance=True, raw_board_numerical_acceptance=False,
        full_array_mapped_numerical_acceptance=False, physical_fit_verified=False,
        bitstream_emitted=False, hardware_programmed=False,
        scope='All nine original full C32/K16 raw K65 board four-state modes, unchanged final QWORD/BRAM oracle/bench, 512 lanes/16 kernels. Only completed source-bound full-board compile reused; fresh executions required. No baseline promotion, mapped array/board, physical FPGA/RK, fit/timing/electrical/DRC or bitstream acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, mode=None):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=14400 if mode is not None else 1800)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            if mode is not None:
                marker = validate_board_result(text, code, mode)
                report['tests'].append(dict(mode=mode, status='PASS', result=marker, log=step['log']))
            else:
                assert code == 0 and not re.search(r'(?im)\b(?:error|warning):|sorry:', text), text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - start, 3); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save(); generated = []
    try:
        # Freeze report/source provenance; large compiled binaries are bound
        # directly, not duplicated into a pretend newly compiled artifact.
        snapshots = {native_path, prep_path, proof_path, Path(__file__).resolve(), *imported,
            *(p for p in tracked if str(p.relative_to(ROOT)).startswith(('rtl/', 'tests/', 'fpga/')))}
        for path in sorted(snapshots):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
        report['tool_version'] = run(['iverilog', '-V'], 'iverilog_version').splitlines()[0]
        report['runtime_version'] = run(['vvp', '-V'], 'vvp_version').splitlines()[0]
        assert report['tool_version'] == accepted['tool_version'] == prepared['tool_version']
        assert report['runtime_version'] == accepted['runtime_version']
        assert fingerprint(tracked) == before; report['stage'] = 'simulation'; save()
        for mode in MODES:
            run(['vvp', binary, f'+MODE={mode}'], f'mode_{mode}', mode)
            assert fingerprint([binary]) == execution and fingerprint(stimulus_files) == stimuli
            assert fingerprint(tracked) == before
        validate_suite(report['tests'])
        verify_native(native_path); verify_prepared(prep_path, spec); verify_composed(proof_path)
        preparation.validate_sources(); assert fingerprint(tracked) == before
        report.update(status='PASS_FULL_C32K16_DSP_RAW_BOARD_FOUR_STATE_FIXTURES_ONLY', stage='complete',
            finished_utc=timestamp(), raw_board_numerical_acceptance=True,
            artifacts=fingerprint([binary, *generated, *out.glob('*.log')]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [binary, *generated, *out.glob('*.log')] if p.is_file()])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
