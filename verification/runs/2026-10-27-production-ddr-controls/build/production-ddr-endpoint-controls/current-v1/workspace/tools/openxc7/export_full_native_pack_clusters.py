#!/usr/bin/env python3
"""Optional exact full-graph cluster export and necessary geometry audit.

Admit a genuinely completed own source-defined small probe first. Repack the
unaltered C32/K16 input with its isolated export ELF and literal packing XDC;
require byte-identical complete output versus the qualified parent's full
523522-cell graph,515 DSPs and six BRAMs. Inspect actual exported XYZ/absolute-Z
constraints against all real database locations. Geometry witnesses ignore
occupancy/fixed BELs/control sets/ports/timing: they are NOT full fit. A zero
candidate is reported separately, never silently accepted. This optional
diagnostic cannot replace or delay existing complete-placement handoffs.
No raw-command bypass, arithmetic/layout fixup, constraints/RTL/default tool
change, physical waiver, bitstream/card/flash access or checksum manifest.
"""
import argparse
from collections import Counter
import json
import mmap
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import probe_native_pack_clusters as original
import probe_source_defined_native_cluster_error as small
import pack_recursive_mux_prefix_shared_board as packer
import cluster_location_geometry as geometry
from audit_corrected_full_pack_identity import layout, records, cell_value
from evidence import ROOT, source_revision, timestamp
from place_prefix_board import verify_bindings
from pack_prefix_board import CONSTIDS, DATABASE, digest

FULL_PACK = ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json'
CONTROL = ROOT / 'tests/cmac/test_full_native_cluster_export_control.py'
LABELS = ['software_controls', 'generated_check', 'compiler_version', 'relink_qualified_parent_identity',
          'dependency_preflight', 'compile_diagnostic_arch', 'link_diagnostic_candidate', 'native_version',
          'parent_native_pack', 'diagnostic_off_native_pack', 'diagnostic_on_native_pack', 'existing_output_real_negative']
EXPORTED = 'EXPORTED_FULL_C32K16_IDENTICAL_PACKED_GRAPH_ALL_CLUSTER_GEOMETRY_WITNESSES_NOT_PLACED_OR_SIGNOFF'
CONFLICT = 'CONFIRMED_IDENTICAL_FULL_PACKED_CLUSTER_ZERO_GEOMETRY_NOT_FULL_DESIGN_INFEASIBILITY_OR_SIGNOFF'


def validate_small_metadata(report):
    assert report['status'] == small.STATUS and report['stage'] == 'complete' and report['finished_utc']
    assert report.get('error') is None
    assert (report['target_c'], report['target_k'], report['full_parallel_products'], report['full_target_dsp'],
            report['full_target_bram'], report['part']) == (32, 16, 512, 515, 6, 'xc7k480tffg1156-2')
    assert report['production_source_before'] == report['production_source_after']
    assert all(report[flag] is False for flag in original.FLAGS)
    assert report['diagnostic_optional_not_new_acceptance_gate'] is True
    assert report['changed_link_objects'] == 1 and report['unchanged_qualified_parent_relink'] is True
    for key in ('parent_off_on_packed_graphs_byte_identical', 'parent_off_on_checksums_identical',
                'existing_metadata_overwrite_rejected', 'exact_actual_parent_arch_source_retained'):
        assert report[key] is True
    assert [step['label'] for step in report['commands']] == LABELS
    for step in report['commands']:
        expected = 125 if step['label'] == LABELS[-1] else 0
        assert step['expected_returncode'] == step['returncode'] == expected
        assert step['status'] == 'PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY'
    certificate = report['native_error_contract']
    assert certificate['exception'] == 'log_execution_error_exception' and certificate['fatal_returncode'] == 125
    assert certificate['fatal_error_remains_rejection'] is True
    assert certificate['does_not_change_hardware_error_expectations'] is True
    checks = report['metadata_checks']
    assert (checks['cells'], checks['cluster_roots'], checks['cluster_children']) == (21, 3, 8)
    assert checks['cluster_metadata_exported'] is True
    assert checks['geometry_fit_checked'] is checks['full_placement_or_timing_acceptance'] is False


def merge(target, source):
    for path, sha in source.items():
        assert Path(path).is_absolute() and Path(path).resolve(strict=True) == Path(path)
        assert path not in target or target[path] == sha, 'Conflicting bound file: ' + path
        target[path] = sha


def admit_small(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('source-defined-native-cluster-export-')
    report = json.loads(path.read_text())
    validate_small_metadata(report)  # No output/native tools on incomplete/failed controls.
    assert report['production_source_after'] == source_revision()
    assert report['native_error_contract'] == small.validate_error_contract()
    before = dict(report['source'])
    for artifact in report['artifacts']:
        assert Path(artifact).resolve(strict=True).is_relative_to(path.parent)
    merge(before, report['artifacts'])
    before[str(path)] = digest(path)
    verify_bindings(before)
    assert (path.parent / 'executed_source.py').read_bytes() == Path(small.__file__).read_bytes()
    assert (path.parent / 'executed_control.py').read_bytes() == small.CONTROL.read_bytes()
    original.verify_source_transition(original.ARCH_SOURCE.read_text(), (path.parent / 'himbaechel/arch.cc').read_text())
    assert digest(path.parent / 'parent-relinked') == report['qualified_parent_executable']['sha256']
    assert digest(report['executable']['path']) == report['executable']['sha256']
    outputs = [path.parent / (name + '-packed.json') for name in ('parent', 'diagnostic_off', 'diagnostic_on')]
    assert outputs[0].read_bytes() == outputs[1].read_bytes() == outputs[2].read_bytes()
    packed = json.loads(outputs[-1].read_text())
    assert original.read_metadata(path.parent / 'clusters.jsonl', packed) == report['metadata_checks']
    assert not (path.parent / 'negative-packed.json').exists()
    for step, name, enabled in zip(report['commands'][8:11], ('parent', 'diagnostic_off', 'diagnostic_on'), (False, False, True)):
        exe = path.parent / 'parent-relinked' if name == 'parent' else Path(report['executable']['path'])
        argv = original.qualified.candidate.pack_argv(exe, path.parent / 'mux_probe.json', path.parent / 'mux_probe.xdc',
                                                     path.parent / (name + '-packed.json'))
        if enabled:
            argv += ['-o', original.OPTION + '=' + str(path.parent / 'clusters.jsonl')]
        assert step['argv'] == argv
        assert re.findall(r'(?m)^Info: Checksum: 0x([0-9a-f]{8})$', Path(step['log']).read_text()) == [report['metadata_checks']['pack_checksum']]
    negative = report['commands'][-1]
    expected = original.qualified.candidate.pack_argv(report['executable']['path'], path.parent / 'mux_probe.json',
                                                      path.parent / 'mux_probe.xdc', path.parent / 'negative-packed.json')
    expected += ['-o', original.OPTION + '=' + str(path.parent / 'clusters.jsonl')]
    assert negative['argv'] == expected
    assert 'ERROR: RKNPU cluster diagnostic cannot create new output\n0 warnings, 1 error' in Path(negative['log']).read_text()
    # Do not accept a report whose producing supervisor/native tools still run.
    for pid in [report['supervisor_pid'], *(step['pid'] for step in report['commands'])]:
        assert not Path(f'/proc/{pid}').exists(), 'Producing owner has not stopped'
    return report, before


def full_command(parent, executable, xdc, output, metadata):
    packer.validate_pack(parent)
    argv = list(parent['commands'][-1]['argv'])
    argv[0] = str(executable)
    argv[argv.index('-o') + 1] = 'xdc=' + str(xdc)
    argv[argv.index('--write') + 1] = str(output)
    return argv + ['-o', original.OPTION + '=' + str(metadata)]


def packed_type_document(path):
    """Complete pinned-writer cell type/name census without huge pin dictionaries."""
    cells = {}
    with Path(path).open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        begin, end = layout(data)
        # Retain the actual pinned writer's creator/module/ports/settings
        # header. Close its empty cell table for parsing; do not manufacture
        # pack/place/route settings to satisfy the comparison reader.
        projected = json.loads(data[:begin] + b'\n      }\n    }\n  }\n}\n')
        assert len(projected['modules']) == 1
        module = next(iter(projected['modules'].values()))
        assert module['cells'] == {}
        for name, raw in records(data, begin, end):
            assert name not in cells
            value = cell_value(raw)
            assert isinstance(value['type'], str) and value['type']
            cells[name] = {'type': value['type']}
    module['cells'] = cells
    # This comparison-only type projection is never an execution input.
    return projected


def audit_clusters(metadata, grid):
    with Path(metadata).open() as stream:
        cells = {row['name']: row for line in stream if (row := json.loads(line))['kind'] == 'cell'}
    classes = {}
    roots = children = 0
    for name, root in cells.items():
        if root['cluster'] != name:
            continue
        roots += 1
        children += len(root['children'])
        members = [{key: row[key] for key in ('name', 'type', 'x', 'y', 'z', 'abs_z')}
                   for row in [root, *(cells[child] for child in root['children'])]]
        key = geometry.geometry_key(members)
        if key not in classes:
            classes[key] = dict(example_root=name, members=members, roots=0, result=geometry.find_witness(members, grid))
        classes[key]['roots'] += 1
    groups = list(classes.values())
    return dict(cluster_roots=roots, cluster_children=children, distinct_geometry_classes=len(groups),
                classes=groups, zero_candidate_classes=sum(not c['result']['compatible'] for c in groups),
                joint_occupancy_or_fixed_bels_checked=False, control_sets_connectivity_or_timing_checked=False,
                full_fit_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--small', type=Path, required=True)
    args = parser.parse_args()
    admitted, before = admit_small(args.small)
    parent = json.loads(FULL_PACK.read_text())
    packer.validate_pack(parent)
    assert parent['executable'] == admitted['qualified_parent_executable']
    assert parent['production_source_after'] == source_revision()
    merge(before, parent['source'])
    merge(before, parent['artifacts'])
    for module in list(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
            path = Path(filename).resolve(strict=True)
            merge(before, {str(path): digest(path)})
    for path in (FULL_PACK, CONTROL, Path(__file__).resolve(), CONSTIDS, DATABASE):
        merge(before, {str(path): digest(path)})
    verify_bindings(before)
    # Additional private full-pack job only; not the shared numerical policy.
    available = int(re.search(r'^MemAvailable:\s+(\d+) kB$', Path('/proc/meminfo').read_text(), re.M)[1])
    assert available >= 8 * 1024**2, 'Insufficient unchanged eight-GiB private full-pack admission headroom'
    resource.setrlimit(resource.RLIMIT_AS, (12 * 1024**3, 12 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    out = ROOT / f'build/openxc7/full-native-cluster-export-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    shutil.copyfile(CONTROL, out / 'executed_control.py')
    report = dict(status='RUNNING', stage='admitted', started_utc=timestamp(), supervisor_pid=os.getpid(),
                  small_qualification=str(args.small.resolve()), parent_full_pack=str(FULL_PACK), source=before, commands=[],
                  channels=32, kernels=16, parallel_products=512, intended_part='xc7k480tffg1156-2',
                  intended_clock_period_ns=20, seed=3588, dsp=515, bram=6, optional_not_new_acceptance_gate=True,
                  production_source_before=source_revision(), **{flag: False for flag in original.FLAGS})

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, timeout=120):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), status='RUNNING',
                    timeout_seconds=timeout)
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                step['pid'] = proc.pid
                save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:warning|error|fatal):', text), text[-3500:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    print(out / 'report.json', flush=True)
    save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        executable = admitted['executable']['path']
        report['executable'] = admitted['executable']
        assert run('native_version', [executable, '--version'], timeout=60).strip() == admitted['native_version']
        old_argv = parent['commands'][-1]['argv']
        original_xdc = Path(old_argv[old_argv.index('-o') + 1].removeprefix('xdc='))
        xdc = out / 'literal.pack-only.xdc'
        shutil.copyfile(original_xdc, xdc)
        assert digest(xdc) == before[str(original_xdc)]
        packed, metadata = out / 'packed.json', out / 'clusters.jsonl'
        report['stage'] = 'native_full_pack'
        log = run('native_full_pack_cluster_export', full_command(parent, executable, xdc, packed, metadata), timeout=3600)
        assert re.findall(r'(?m)^Info: Checksum: 0x([0-9a-f]{8})$', log) == ['77f1fde0']
        assert 'RKNPU read-only pack cluster metadata: 523522 cells, unchanged checksum 77f1fde0' in log
        run('complete_packed_graph_byte_comparison', ['cmp', '--', parent['packed_design'], packed])
        report['stage'] = 'complete_export_census_and_geometry'
        document = packed_type_document(packed)
        module = next(iter(document['modules'].values()))
        counts = dict(Counter(c['type'] for c in module['cells'].values()))
        assert counts == parent['native_census']['primitive_counts'] and sum(counts.values()) == 523522
        report['metadata_checks'] = original.read_metadata(metadata, document)
        assert report['metadata_checks']['pack_checksum'] == '77f1fde0'
        del document
        known = [''] + re.findall(r'^X\((\w+)\)\s*$', CONSTIDS.read_text(), re.M)
        grid = geometry.database_grid(DATABASE.read_bytes(), known)
        report['cluster_geometry'] = audit_clusters(metadata, grid)
        assert report['cluster_geometry']['cluster_roots'] == report['metadata_checks']['cluster_roots']
        assert report['cluster_geometry']['cluster_children'] == report['metadata_checks']['cluster_children']
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        assert all(report[flag] is False for flag in original.FLAGS)
        report.update(status=CONFLICT if report['cluster_geometry']['zero_candidate_classes'] else EXPORTED,
                      stage='complete', complete_packed_graph_byte_identical=True)
    except BaseException as exc:
        report.update(status='FAIL_FULL_NATIVE_CLUSTER_EXPORT_DIAGNOSTIC', error=repr(exc))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()


if __name__ == '__main__':
    main()
