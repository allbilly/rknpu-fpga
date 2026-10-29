#!/usr/bin/env python3
"""Archive only a terminal, admission-bound full DSP-board continuation.

Recheck unchanged parent failure/circuit/model evidence and the cached binary.
Successful admission needs fresh negative/all-nine logs in this run's own
directory. Packaging preserves FAIL, never establishes FPGA or RK acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import resume_dsp_prefix_observed_mapped_board as resume

STATUS = 'ARCHIVED_TERMINAL_FULL_C32K16_PREFIX_OBSERVED_BOARD_CONTINUATION_ONLY'
LABELS = ['runtime_version', 'negative', *('mode' + str(mode) for mode in range(9))]


def terminal_metadata(report):
    assert report['status'] in (resume.PASS, 'FAIL'), 'Only a terminal continuation profile is eligible'
    assert report['finished_utc'] and report['source']['files'] and report['artifacts']['files']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['modes'],
            report['intended_part'], report['intended_clock_period_ns']) == (
                32, 16, 512, list(range(9)), 'xc7k480tffg1156-2', 20)
    assert report['parent_status'] == 'FAIL' and report['original_failure_preserved'] is True
    assert report['reused_compiled_executable'] is True and report['upstream_model_commit'] == resume.replay.models.COMMIT
    resume.validate_budget(report['wall_timeout_seconds'])
    for flag in ('model_four_state_yosys_equivalence', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[flag] is False
    for name in ('parent_source_sha256', 'parent_archive_sha256'):
        assert re.fullmatch('[0-9a-f]{64}', report[name]), 'Completed source-bound admission required'
    assert report['reused_compile_inputs']['files'] and report['reused_compiled_executable_manifest']['files']
    assert report['reused_execution_inputs']['files'] and report['runtime_program']['path']
    assert re.fullmatch('[0-9a-f]{64}', report['runtime_program']['sha256'])
    labels = [Path(step['log']).stem for step in report['commands']]
    assert labels == LABELS[:len(labels)] and len(labels) <= len(LABELS)
    assert all(step['status'] in ('PASS', 'FAIL') for step in report['commands'])
    failures = [index for index, step in enumerate(report['commands']) if step['status'] == 'FAIL']
    assert not failures or failures == [len(labels) - 1]
    if report['status'] == resume.PASS:
        resume.validate_completed(report)
    else:
        assert report['error'] and report['numerical_netlist_acceptance'] is False


def own_log(directory, step, label):
    path = (ROOT / step['log']).resolve()
    assert path == directory / (label + '.log'), 'Fresh own-run logs required; parent logs cannot substitute'
    assert path.is_file()
    return path.read_text()


def execution_contract(report, directory, binary, negative_cwd, binding, parent_version):
    assert report['reused_execution_inputs'] == binding
    assert set(report['execution_inputs']) <= set(LABELS[1:])
    assert all(value == binding for value in report['execution_inputs'].values())
    completed = []
    negative_passed = False
    program = report['runtime_program']['path']
    for label, step in zip(LABELS, report['commands']):
        text = own_log(directory, step, label)
        assert step['wall_timeout_seconds'] == report['wall_timeout_seconds']
        assert step['seconds'] >= 0 and type(step['pid']) is int and step['pid'] > 0
        if label == 'runtime_version':
            assert step['argv'] == [program, '-V'] and step['cwd'] == '.'
            if step['status'] == 'PASS':
                assert step['returncode'] == 0
                assert not re.search(r'(?im)\b(?:warning|error)\s*:|\bsorry:|FATAL:', text)
                if report['status'] == resume.PASS:
                    assert text.splitlines()[0] == parent_version == report['vvp_version']
            continue
        mode = 0 if label == 'negative' else int(label.removeprefix('mode'))
        assert step['argv'] == [program, str(binary), '+MODE=' + str(mode)]
        expected_cwd = str(negative_cwd.relative_to(ROOT)) if label == 'negative' else '.'
        assert step['cwd'] == expected_cwd and report['execution_inputs'][label] == binding
        if step['status'] == 'PASS':
            result = resume.replay.simulation_result(text, step['returncode'], mode, label == 'negative')
            assert step['result'] == result
            if label == 'negative':
                negative_passed = True
            else:
                completed.append(dict(mode=mode, status='PASS', result=result))
    assert report['tests'] == completed and report['negative_reexecuted'] is negative_passed
    if report['status'] == resume.PASS:
        assert set(report['execution_inputs']) == set(LABELS[1:])


def verify_run(path):
    report = json.loads(path.read_text())
    terminal_metadata(report)
    resume.replay.verify_manifest(report['source'])
    resume.replay.verify_manifest(report['artifacts'])
    parent_path = resume.replay.mapping.mapper.replay.workspace_path(report['parent_report'])
    index_path = resume.replay.mapping.mapper.replay.workspace_path(report['failure_archive'])
    parent = json.loads(parent_path.read_text())
    resume.timeout_metadata(parent, parent_path.parent)
    assert resume.archive.verify_run(parent_path) == parent
    index, bundle = resume.verify_bundle(index_path, parent, parent_path)
    binary, _, binding, negative_cwd = resume.verify_reusable_execution(parent, parent_path)
    assert report['parent_source_sha256'] == parent['source']['sha256']
    assert report['parent_archive_sha256'] == index['archive_sha256']
    assert report['reused_compile_inputs'] == parent['compile_inputs']
    assert report['reused_compiled_executable_manifest'] == parent['compiled_executable']
    assert report['runtime_program'] == resume.runtime_identity(binary)
    required = {parent_path, index_path, bundle, index_path.parent / 'archive_SHA256SUMS', binary,
                Path(resume.__file__).resolve(), ROOT / 'tests/cmac/test_dsp_prefix_observed_board_resume_control.py',
                *(ROOT / name for name in parent['source']['files']),
                *(ROOT / name for name in parent['compile_inputs']['files'])}
    assert {str(item.relative_to(ROOT)) for item in required} <= set(report['source']['files'])
    assert (path.parent / 'snapshot' / Path(resume.__file__).resolve().relative_to(ROOT)).read_bytes() == Path(resume.__file__).read_bytes()
    execution_contract(report, path.parent, binary, negative_cwd, binding, parent['vvp_version'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    path = resume.replay.mapping.mapper.replay.workspace_path(args.report)
    destination = (ROOT / args.destination).resolve()
    assert destination.is_relative_to(ROOT / 'verification/runs') and not destination.exists()
    report = verify_run(path)
    controls = ROOT / 'tests/cmac/test_dsp_prefix_observed_board_continuation_archive_control.py'
    paths = {path, Path(__file__).resolve(), controls, *(ROOT / name for name in report['source']['files']),
             *(ROOT / name for name in report['artifacts']['files'])}
    members = fingerprint(paths)
    destination.mkdir(parents=True, exist_ok=False)
    bundle_path = destination / 'evidence.tar.gz'
    with tarfile.open(bundle_path, 'w:gz', compresslevel=6) as bundle:
        for item in sorted(paths):
            assert item.is_file() and item.resolve().is_relative_to(ROOT)
            bundle.add(item, arcname=str(item.relative_to(ROOT)), recursive=False)
    with tarfile.open(bundle_path, 'r:gz') as bundle:
        stored = bundle.getmembers()
        assert len(stored) == len(members['files'])
        assert {member.name for member in stored} == set(members['files'])
        for member in stored:
            assert member.isfile() and not Path(member.name).is_absolute() and '..' not in Path(member.name).parts
            stream = bundle.extractfile(member)
            assert stream is not None
            with stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == members['files'][member.name]
    assert fingerprint(paths) == members and json.loads(path.read_text()) == report
    sha = resume.digest(bundle_path)
    index = dict(status=STATUS, finished_utc=timestamp(), original_run_status=report['status'],
                 original_run_report=str(path.relative_to(ROOT)), source_sha256=report['source']['sha256'],
                 verified_members=len(stored), archive_sha256=sha, archive_bytes=bundle_path.stat().st_size,
                 members=members, numerical_netlist_acceptance=report['numerical_netlist_acceptance'],
                 model_four_state_yosys_equivalence=False, physical_fit_verified=False,
                 bitstream_emitted=False, hardware_programmed=False,
                 scope='Source/circuit/model/cached-executable and fresh own-run log revalidation. Exact terminal bytes; no new HDL execution, physical or RK-silicon acceptance.')
    (destination / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    (destination / 'archive_SHA256SUMS').write_text(sha + '  evidence.tar.gz\n')
    print(json.dumps(dict(status=STATUS, original_status=report['status'], verified_members=len(stored),
                          archive_sha256=sha, archive_bytes=index['archive_bytes']), indent=2))


if __name__ == '__main__':
    main()
