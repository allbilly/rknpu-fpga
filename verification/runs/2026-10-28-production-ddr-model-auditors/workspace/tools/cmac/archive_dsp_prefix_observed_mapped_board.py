#!/usr/bin/env python3
"""Freeze a terminal full-prefix mapped-board run, never a live or inferred PASS.

Executed inputs, source snapshots, tool/model logs and actual output artifacts
are packaged with member hashes. Rechecking or archiving does not rerun HDL,
establish physical acceptance or turn a recorded failed gate into a PASS.
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
from test_fixed_array_board import verify_manifest
import test_dsp_prefix_observed_mapped_board as replay

PASS = 'PASS_FULL_C32K16_PREFIX_OBSERVABLE_RAW_BOARD_NINE_MODE_UNISIM_MAPPED_ONLY'


def verify_terminal_metadata(report):
    assert report['status'] in (PASS, 'FAIL'), 'Cannot archive a live/unaccepted-profile run'
    assert report['finished_utc'] and report['source']['files'] and report['artifacts']['files']
    assert (report['channels'], report['kernels'], report['parallel_products'],
            report['intended_part'], report['intended_clock_period_ns']) == (
                32, 16, 512, 'xc7k480tffg1156-2', 20)
    assert report['configurations'] == dict(kernel_dsp_configurations=32, shell_dsp_configurations=3,
                                           physical_cmac_dsps=512, total_physical_dsps=515)
    assert report['modes'] == list(range(9)) and report['upstream_model_commit'] == replay.models.COMMIT
    assert report['model_four_state_yosys_equivalence'] is False
    for flag in ('physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[flag] is False
    if report['status'] == 'FAIL':
        assert report.get('error') and report['numerical_netlist_acceptance'] is False
        return
    assert report['stage'] == 'complete' and report['numerical_netlist_acceptance'] is True
    assert report['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE'
    labels = ['yosys_version', 'iverilog_version', 'vvp_version', 'model_commit', 'model_clean',
              'export', 'compile', 'negative', *('mode' + str(mode) for mode in range(9))]
    assert [Path(step['log']).stem for step in report['commands']] == labels
    assert all(step['status'] == 'PASS' and step['returncode'] == int(label == 'negative')
               for label, step in zip(labels, report['commands']))
    assert [test['mode'] for test in report['tests']] == list(range(9))
    assert all(test['status'] == 'PASS' for test in report['tests'])


def verify_successful_execution(report, directory):
    """Revalidate actual logs and exact executable/input binding, not markers alone."""
    compiled = report['compiled_executable']
    inputs = report['compile_inputs']
    verify_manifest(compiled)
    verify_manifest(inputs)
    assert set(report['execution_inputs']) == {'negative', *('mode' + str(mode) for mode in range(9))}
    binary = directory / 'board.vvp'
    assert compiled['files'] == {str(binary.relative_to(ROOT)): report['artifacts']['files'][str(binary.relative_to(ROOT))]}
    expected = fingerprint([*(ROOT / name for name in inputs['files']), binary])
    commands = report['commands']
    for label, step in zip(('negative', *('mode' + str(mode) for mode in range(9))), commands[7:]):
        mode = 0 if label == 'negative' else int(label.removeprefix('mode'))
        assert step['argv'] == ['vvp', str(binary), '+MODE=' + str(mode)]
        expected_cwd = str((directory / 'negative-golden-cwd').relative_to(ROOT)) if label == 'negative' else '.'
        assert step['cwd'] == expected_cwd
        text = (ROOT / step['log']).read_text()
        result = replay.simulation_result(text, step['returncode'], mode, label == 'negative')
        assert step['result'] == result and report['execution_inputs'][label] == expected
        if label != 'negative':
            assert report['tests'][mode]['result'] == result
    negative = directory / 'negative-golden-cwd/tests/cmac/array_data'
    assert (negative / replay.WRITES.name).read_text() == replay.negative_golden(replay.WRITES.read_text())
    assert (negative / replay.READS.name).read_bytes() == replay.READS.read_bytes()
    for step in commands[:7]:
        text = (ROOT / step['log']).read_text()
        assert not re.search(r'(?im)\b(?:warning|error)\s*:|\bsorry:|FATAL:', text)


def verify_run(path):
    report = json.loads(path.read_text())
    verify_terminal_metadata(report)
    verify_manifest(report['source'])
    verify_manifest(report['artifacts'])
    parent_path = replay.mapping.mapper.replay.workspace_path(report['mapping_report'])
    parent = json.loads(parent_path.read_text())
    replay.verify_mapping_report(parent)
    assert report['parent_source_sha256'] == parent['source']['sha256']
    assert str(parent_path.relative_to(ROOT)) in report['source']['files']
    carry_path = replay.mapping.mapper.replay.workspace_path(report['carry_truth_report'])
    carry = json.loads(carry_path.read_text())
    replay.verify_carry_report(carry)
    assert str(carry_path.relative_to(ROOT)) in report['source']['files']
    for value in (parent, carry):
        verify_manifest(value['source'])
        verify_manifest(value['artifacts'])
    graph = parent_path.parent / 'mapped_hierarchy.json'
    assert str(graph.relative_to(ROOT)) in report['source']['files']
    kernel = parent['preserved_kernel']
    design = json.loads(graph.read_text())
    implementation = dict(modules={name: design['modules'][name] for name in (replay.TOP, kernel)})
    replay.models.verify_configurations(implementation, replay.TOP, kernel)
    original = replay.BENCH.read_text()
    bench = path.parent / replay.BENCH.name
    edits = json.loads((path.parent / 'bench_reference_edits.json').read_text())
    replay.verify_bound_bench(implementation['modules'][replay.TOP], original, bench.read_text(), edits)
    module_export, module_aliases = replay.implementation_module_aliases(implementation)
    exported, instance_aliases = replay.hardware_instance_aliases(module_export)
    assert json.loads((path.parent / 'hardware_name_aliases.json').read_text()) == dict(
        modules=module_aliases, instances=instance_aliases)
    assert (path.parent / 'mapped_board.v').read_text() == replay.structural_board_verilog(exported)
    kinds = {cell['type'] for body in implementation['modules'].values() for cell in body['cells'].values()
             if cell['type'] not in (kernel, '$scopeinfo')}
    for source, expected in replay.models.selected_models(kinds).items():
        assert report['source']['files'][str(source.relative_to(ROOT))] == expected
        frozen = path.parent / 'models' / source.name
        assert frozen.read_bytes() == source.read_bytes()
    if report['status'] == PASS:
        roundtrip = json.loads((path.parent / 'export_roundtrip.json').read_text())
        assert replay.circuit_signature(roundtrip) == replay.circuit_signature(exported)
        verify_successful_execution(report, path.parent)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    path = replay.mapping.mapper.replay.workspace_path(args.report)
    destination = (ROOT / args.destination).resolve()
    assert destination.is_relative_to(ROOT / 'verification/runs') and not destination.exists()
    report = verify_run(path)
    paths = {path, Path(__file__).resolve(), *(ROOT / name for name in report['source']['files']),
             *(ROOT / name for name in report['artifacts']['files'])}
    source = fingerprint(paths)
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / 'evidence.tar.gz'
    with tarfile.open(archive, 'w:gz', compresslevel=6) as bundle:
        for item in sorted(paths):
            assert item.is_file() and item.resolve().is_relative_to(ROOT)
            bundle.add(item, arcname=str(item.relative_to(ROOT)), recursive=False)
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        assert len(members) == len(source['files'])
        assert {member.name for member in members} == set(source['files'])
        for member in members:
            assert member.isfile() and not Path(member.name).is_absolute() and '..' not in Path(member.name).parts
            stream = bundle.extractfile(member)
            assert stream is not None
            with stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == source['files'][member.name]
    assert fingerprint(paths) == source and json.loads(path.read_text()) == report
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    index = dict(status='ARCHIVED_TERMINAL_FULL_C32K16_PREFIX_OBSERVED_MAPPED_BOARD_RUN_ONLY',
                 finished_utc=timestamp(), original_run_status=report['status'], original_run_report=str(path.relative_to(ROOT)),
                 source_sha256=report['source']['sha256'], verified_members=len(members),
                 archive_sha256=sha, archive_bytes=archive.stat().st_size, members=source,
                 numerical_netlist_acceptance=report['numerical_netlist_acceptance'],
                 model_four_state_yosys_equivalence=False, physical_fit_verified=False,
                 bitstream_emitted=False, hardware_programmed=False,
                 scope='Exact terminal run/source/artifact bundle. Independent circuit, binding, model-byte and actual-log checks; no new HDL execution or physical acceptance. Referenced upstream parents stay hash-bound; their entire transitive artifact sets are not duplicated.')
    (destination / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
    (destination / 'archive_SHA256SUMS').write_text(sha + '  evidence.tar.gz\n')
    print(json.dumps(dict(status=index['status'], original_status=report['status'],
                          verified_members=len(members), archive_sha256=sha,
                          archive_bytes=index['archive_bytes']), indent=2))


if __name__ == '__main__':
    main()
