#!/usr/bin/env python3
"""Fresh full nine-mode replay of an archived, unchanged DSP board executable.

Only the precise source-bound mode-0 wall timeout is eligible. Recheck the
original circuit/bench/models and every archived byte before reuse. Rerun the
real negative plus all nine modes with unchanged HDL and raw-command fixtures.
A longer host wall budget is not a change to the HDL timeout or FPGA gates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import archive_dsp_prefix_observed_mapped_board as archive

replay = archive.replay
PASS = 'PASS_FULL_C32K16_REUSED_EXECUTABLE_RAW_BOARD_NINE_MODE_UNISIM_MAPPED_ONLY'
DEFAULT_BUDGET = 86400


def validate_budget(seconds):
    assert type(seconds) is int and 14400 < seconds <= 172800, 'Require a bounded longer host wall budget'
    return seconds


def timeout_metadata(report, directory):
    archive.verify_terminal_metadata(report)
    assert report['status'] == 'FAIL' and report['stage'] == 'mode0' and report['tests'] == []
    assert report['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE'
    binary = directory / 'board.vvp'
    labels = ['yosys_version', 'iverilog_version', 'vvp_version', 'model_commit', 'model_clean',
              'export', 'compile', 'negative', 'mode0']
    assert [Path(step['log']).stem for step in report['commands']] == labels
    for label, step in zip(labels[:-1], report['commands'][:-1], strict=True):
        assert step['status'] == 'PASS' and step['returncode'] == int(label == 'negative')
    last = report['commands'][-1]
    argv = ['vvp', str(binary), '+MODE=0']
    assert last['status'] == 'FAIL' and last['argv'] == argv and last['cwd'] == '.'
    assert last.get('returncode') is None and last['seconds'] >= 14400
    assert report['error'] == repr(subprocess.TimeoutExpired(argv, 14400)), 'Only the actual host wall timeout is eligible'
    assert set(report['execution_inputs']) == {'negative', 'mode0'}


def archive_metadata(index, parent, path, expected_members):
    assert index['status'] == 'ARCHIVED_TERMINAL_FULL_C32K16_PREFIX_OBSERVED_MAPPED_BOARD_RUN_ONLY'
    assert index['finished_utc'] and index['original_run_status'] == 'FAIL'
    assert index['original_run_report'] == str(path.relative_to(ROOT))
    assert index['source_sha256'] == parent['source']['sha256']
    assert index['members']['files'] == expected_members
    assert index['verified_members'] == len(expected_members) and expected_members
    encoded = ''.join(f'{expected_members[name]}  {name}\n' for name in sorted(expected_members, key=Path))
    assert hashlib.sha256(encoded.encode()).hexdigest() == index['members']['sha256']
    assert re.fullmatch('[0-9a-f]{64}', index['archive_sha256']) and index['archive_bytes'] > 0
    for flag in ('numerical_netlist_acceptance', 'model_four_state_yosys_equivalence',
                 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert index[flag] is False


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_bundle(index_path, parent, path):
    index = json.loads(index_path.read_text())
    expected = dict(parent['source']['files'])
    for name, value in parent['artifacts']['files'].items():
        assert name not in expected or expected[name] == value
        expected[name] = value
    expected.update(fingerprint([path, Path(archive.__file__).resolve()])['files'])
    archive_metadata(index, parent, path, expected)
    bundle = index_path.parent / 'evidence.tar.gz'
    assert bundle.stat().st_size == index['archive_bytes'] and digest(bundle) == index['archive_sha256']
    assert (index_path.parent / 'archive_SHA256SUMS').read_text() == index['archive_sha256'] + '  evidence.tar.gz\n'
    seen = set()
    with tarfile.open(bundle, 'r|gz') as packed:
        for member in packed:
            assert member.isfile() and member.name in expected and member.name not in seen
            assert not Path(member.name).is_absolute() and '..' not in Path(member.name).parts
            stream = packed.extractfile(member)
            assert stream is not None
            with stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected[member.name]
            seen.add(member.name)
    assert seen == set(expected)
    return index, bundle


def verify_reusable_execution(parent, path):
    replay.verify_manifest(parent['compile_inputs'])
    replay.verify_manifest(parent['compiled_executable'])
    binary = path.parent / 'board.vvp'
    assert parent['compiled_executable']['files'] == {
        str(binary.relative_to(ROOT)): parent['artifacts']['files'][str(binary.relative_to(ROOT))]}
    inputs = [ROOT / name for name in parent['compile_inputs']['files']]
    binding = fingerprint([*inputs, binary])
    assert parent['execution_inputs']['negative'] == binding == parent['execution_inputs']['mode0']
    for step in parent['commands'][:7]:
        assert not re.search(r'(?im)\b(?:warning|error)\s*:|\bsorry:|FATAL:', (ROOT / step['log']).read_text())
    negative = parent['commands'][7]
    assert negative['argv'] == ['vvp', str(binary), '+MODE=0']
    cwd = path.parent / 'negative-golden-cwd'
    assert negative['cwd'] == str(cwd.relative_to(ROOT))
    assert negative['result'] == replay.simulation_result((ROOT / negative['log']).read_text(), 1, 0, True)
    fixture = cwd / 'tests/cmac/array_data'
    assert (fixture / replay.WRITES.name).read_text() == replay.negative_golden(replay.WRITES.read_text())
    assert (fixture / replay.READS.name).read_bytes() == replay.READS.read_bytes()
    assert (ROOT / parent['commands'][-1]['log']).stat().st_size == 0
    return binary, inputs, binding, cwd


def runtime_identity(binary):
    selected = shutil.which('vvp')
    assert selected, 'vvp runtime unavailable'
    program = Path(selected).resolve()
    with binary.open('rb') as stream:
        header = stream.readline().decode().strip()
    assert header.startswith('#! ') and Path(header[3:].strip()).resolve() == program
    return dict(path=str(program), sha256=digest(program), bytes=program.stat().st_size)


def validate_completed(report):
    assert (report['status'], report['stage']) in (('RUNNING', 'mode8'), (PASS, 'complete'))
    assert not report.get('error')
    assert report['numerical_netlist_acceptance'] is (report['status'] == PASS)
    if report['status'] == PASS:
        assert report['finished_utc'] and report['source']['files'] and report['artifacts']['files']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['modes'],
            report['intended_part'], report['intended_clock_period_ns']) == (
                32, 16, 512, list(range(9)), 'xc7k480tffg1156-2', 20)
    assert report['parent_status'] == 'FAIL' and report['original_failure_preserved'] is True
    assert report['reused_compiled_executable'] is True and report['negative_reexecuted'] is True
    validate_budget(report['wall_timeout_seconds'])
    labels = ['runtime_version', 'negative', *('mode' + str(mode) for mode in range(9))]
    assert [Path(step['log']).stem for step in report['commands']] == labels
    assert all(step['status'] == 'PASS' and step['returncode'] == int(label == 'negative')
               for label, step in zip(labels, report['commands'], strict=True))
    assert [test['mode'] for test in report['tests']] == list(range(9))
    assert all(test['status'] == 'PASS' for test in report['tests'])
    assert report['commands'][1]['result'] == 'REJECTED_EXACT_FIRST_OUTPUT_GOLDEN_BIT'
    for mode, test, step in zip(range(9), report['tests'], report['commands'][2:], strict=True):
        assert test['result'] == step['result'] == replay.simulation_result(step['result'], 0, mode)
    assert set(report['execution_inputs']) == {'negative', *('mode' + str(mode) for mode in range(9))}
    assert all(value == report['reused_execution_inputs'] for value in report['execution_inputs'].values())
    for flag in ('model_four_state_yosys_equivalence', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[flag] is False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-report', type=Path, required=True)
    parser.add_argument('--failure-archive', type=Path, required=True, help='Verified failure archive index.json')
    parser.add_argument('--wall-timeout', type=int, default=DEFAULT_BUDGET)
    args = parser.parse_args()
    budget = validate_budget(args.wall_timeout)
    path = replay.mapping.mapper.replay.workspace_path(args.parent_report)
    index_path = replay.mapping.mapper.replay.workspace_path(args.failure_archive)
    out = ROOT / f'build/rknpu-dsp-prefix-observed-board-continuation/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    imported = {Path(module.__file__).resolve() for module in list(sys.modules.values())
                if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools')}
    controls = ROOT / 'tests/cmac/test_dsp_prefix_observed_board_resume_control.py'
    initial = {path, index_path, Path(__file__).resolve(), controls, *imported}
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
                  source=fingerprint(initial), commands=[], tests=[], execution_inputs={},
                  parent_report=str(path.relative_to(ROOT)), failure_archive=str(index_path.relative_to(ROOT)),
                  parent_status='FAIL', original_failure_preserved=True, reused_compiled_executable=True,
                  negative_reexecuted=False, wall_timeout_seconds=budget, python_version=sys.version,
                  channels=32, kernels=16, parallel_products=512, modes=list(range(9)),
                  intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
                  upstream_model_commit=replay.models.COMMIT, model_four_state_yosys_equivalence=False,
                  numerical_netlist_acceptance=False, physical_fit_verified=False,
                  bitstream_emitted=False, hardware_programmed=False, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, label, cwd=ROOT, mode=None, negative=False):
        step = dict(argv=list(map(str, argv)), cwd=str(cwd.relative_to(ROOT)) or '.', status='RUNNING',
                    log=str((out / (label + '.log')).relative_to(ROOT)), wall_timeout_seconds=budget)
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                      start_new_session=True) as process:
                    step['pid'] = process.pid
                    save()
                    try:
                        code = process.wait(timeout=budget)
                    except BaseException:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        step['returncode'] = process.wait()
                        raise
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            if mode is None:
                assert code == 0 and not re.search(r'(?im)\b(?:warning|error)\s*:|\bsorry:|FATAL:', text)
            else:
                step['result'] = replay.simulation_result(text, code, mode, negative)
            step['status'] = 'PASS'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(SystemExit(128 + signum)))
    save()
    print(out / 'report.json', flush=True)
    try:
        parent = json.loads(path.read_text())
        timeout_metadata(parent, path.parent)
        assert archive.verify_run(path) == parent
        index, bundle = verify_bundle(index_path, parent, path)
        binary, inputs, binding, negative_cwd = verify_reusable_execution(parent, path)
        tracked = initial | {bundle, index_path.parent / 'archive_SHA256SUMS', binary, *inputs,
                             *(ROOT / name for name in parent['source']['files'])}
        report.update(source=fingerprint(tracked), parent_source_sha256=parent['source']['sha256'],
                      parent_archive_sha256=index['archive_sha256'], reused_compile_inputs=parent['compile_inputs'],
                      reused_compiled_executable_manifest=parent['compiled_executable'], reused_execution_inputs=binding,
                      parent_compile_seconds=parent['commands'][6]['seconds'], runtime_program=runtime_identity(binary))
        for item in sorted(tracked):
            if item.suffix in ('.py', '.sv', '.v', '.ys', '.hex'):
                target = out / 'snapshot' / item.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(item.read_bytes())
        report['stage'] = 'runtime_version'
        save()
        program = report['runtime_program']['path']
        version = run([program, '-V'], 'runtime_version').splitlines()[0]
        assert version == parent['vvp_version'], 'Changed runtime version'
        report['vvp_version'] = version
        for label, mode, cwd in [('negative', 0, negative_cwd), *(('mode' + str(mode), mode, ROOT) for mode in replay.MODES)]:
            assert fingerprint([*inputs, binary]) == binding and runtime_identity(binary) == report['runtime_program']
            report['stage'] = label
            report['execution_inputs'][label] = binding
            save()
            run([program, binary, '+MODE=' + str(mode)], label, cwd, mode, label == 'negative')
            assert fingerprint([*inputs, binary]) == binding and runtime_identity(binary) == report['runtime_program']
            if label == 'negative':
                report['negative_reexecuted'] = True
            else:
                report['tests'].append(dict(mode=mode, status='PASS', result=report['commands'][-1]['result']))
            save()
        validate_completed(report)
        assert fingerprint(tracked) == report['source'] and json.loads(path.read_text()) == parent
        replay.verify_manifest(parent['source'])
        replay.verify_manifest(parent['artifacts'])
        assert digest(bundle) == index['archive_sha256'] and json.loads(index_path.read_text()) == index
        report.update(status=PASS, stage='complete', numerical_netlist_acceptance=True)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([item for item in out.rglob('*') if item.is_file() and item.name != 'report.json'])
        save()


if __name__ == '__main__':
    main()
