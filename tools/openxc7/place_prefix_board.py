#!/usr/bin/env python3
"""Full C32/K16 native placement characterization; no routing or bitstream.

Repack the unchanged prepared input in a fresh context, then use the qualified
static placer with its final BEL legality check. Complete placement is not
numerical acceptance, routed fit, complete DSP/-2 timing or electrical signoff.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_prefix_board import (ROOT, TOP, QUALIFICATION, DATABASE, CONSTIDS,
    JSON_WRITER, timestamp, digest, audit, packing_xdc, native_export_module,
    verify_prepared_metadata)
from qualify_static_exp_candidate import verify_precision_qualification

PACKED = 'PACKED_FULL_C32K16_NATIVE_RESOURCE_CHARACTERIZATION_NOT_PLACED_FIT_OR_SIGNOFF'
PLACED = 'PLACED_FULL_C32K16_NATIVE_LEGALITY_CHARACTERIZATION_NOT_ROUTED_FIT_OR_SIGNOFF'
PACK_PARENT = ROOT / 'build/openxc7/full-prefix-native-pack-1791394643587130253/report.json'
ABSENT_ACCEPTANCE = ('native_routing_executed', 'numerical_netlist_acceptance',
    'physical_fit_verified', 'timing_signoff', 'electrical_verified',
    'bitstream_emitted', 'hardware_programmed')


def verify_packed_metadata(report):
    assert report['status'] == PACKED and report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'],
            report['retained_cmac_dsps'], report['retained_shell_dsps'],
            report['intended_part'], report['intended_clock_period_ns'], report['seed']) == (
                32, 16, 512, 512, 3, 'xc7k480tffg1156-2', 20, 3588)
    assert report['native_packing_executed'] is True and report['native_placement_executed'] is False
    assert all(report[key] is False for key in ABSENT_ACCEPTANCE)
    groups = report['retained_kernel_dsps']
    assert len(groups) == 16 and set(groups.values()) == {32}
    assert report['native_packed_cell_counts']['DSP48E1_DSP48E1'] == 515
    assert report['native_packed_cell_counts']['RAMB36E1_RAMB36E1'] == 6
    assert [Path(step['log']).stem for step in report['commands']] == ['version', 'help', 'native_pack']
    assert all(step['returncode'] == 0 and step['status'] == 'PASS_TOOL_EXECUTION_ONLY'
               for step in report['commands'])
    assert report['constraint_translation']['target_period_ns'] == 20.0
    assert report['constraint_translation']['signoff_constraint_profile'] is False
    assert report['native_export_top_translation']['graph_data_changed'] is False


def bind_report(path, report, before):
    """Revalidate sources and own-directory artifacts, never trust a PASS label."""
    for name, sha in report['source'].items():
        source = Path(name).resolve(strict=True)
        assert source.is_absolute() and re.fullmatch('[0-9a-f]{64}', sha)
        assert str(source) not in before or before[str(source)] == sha, 'Conflicting source binding'
        before[str(source)] = sha
    for name, sha in report['artifacts'].items():
        assert not Path(name).is_absolute(), 'Artifact path must be project-relative'
        artifact = (ROOT / name).resolve(strict=True)
        assert artifact.is_relative_to(path.parent), 'Artifact outside parent attempt'
        assert re.fullmatch('[0-9a-f]{64}', sha)
        assert str(artifact) not in before or before[str(artifact)] == sha, 'Conflicting artifact binding'
        before[str(artifact)] = sha
    before[str(path)] = digest(path)


def verify_bindings(before):
    for name, sha in before.items():
        assert digest(name) == sha, 'Changed placement input: ' + name


def placement_argv(executable, input_path, constraints, output):
    # No --no-pack: reload the original physical input, not packed macro state.
    # No limited-refinement, --force, --timing-allow-fail or clock relaxation.
    return list(map(str, [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
        '--top', TOP, '--json', input_path, '-o', 'xdc=' + str(constraints),
        '--placer', 'static', '--no-route', '--freq', '50', '--seed', '3588',
        '--Werror', '--verbose', '--write', output]))


def precision_source_transition(original, changed):
    """Only two overload selections; never weaken finite assertions/objective."""
    expected = original
    for name in ('emin', 'emax'):
        call = f'std::exp({name})'
        assert expected.count(call) == 1, 'Unexpected original static exponential contract'
        expected = expected.replace(call, f'std::exp(static_cast<double>({name}))')
    assert changed == expected, 'Additional static placer changes are not admitted'
    assert changed.count('NPNR_ASSERT') == original.count('NPNR_ASSERT')


def verify_native_tool_transition(qualification_path):
    inventory = verify_precision_qualification(qualification_path)
    candidate = json.loads(qualification_path.read_text())
    qualification_report = json.loads(Path(candidate['build_report']).read_text())
    build_path = Path(qualification_report['candidate_build_report'])
    built = json.loads(build_path.read_text())
    assert Path(built['parent_qualification']).resolve() == QUALIFICATION.resolve(), 'Wrong qualified base engine'
    old = json.loads(QUALIFICATION.read_text())
    original = QUALIFICATION.parent / 'common/place/placer_static.cc'
    changed = build_path.parent / 'common/place/placer_static.cc'
    assert str(original) in candidate['inputs'] and str(changed) in candidate['inputs']
    precision_source_transition(original.read_text(), changed.read_text())
    old_report = json.loads(Path(old['build_report']).read_text())
    old_link = next(c['argv'] for c in old_report['commands'] if Path(c['log']).stem == 'link-candidate')
    new_link = next(c['argv'] for c in built['commands'] if c['label'] == 'link_precision_candidate')
    old_obj = str(QUALIFICATION.parent / 'placer_static.cc.o')
    new_obj = str(build_path.parent / 'placer_static.cc.o')
    assert old_link.count(old_obj) == new_link.count(new_obj) == 1
    expected_link = [new_obj if item == old_obj else item for item in old_link]
    expected_link[expected_link.index('-o') + 1] = candidate['executable']['path']
    expected_link = ['-Wl,--dependency-file=' + candidate['executable']['path'] + '.d'
                     if item.startswith('-Wl,--dependency-file=') else item for item in expected_link]
    assert new_link == expected_link, 'Additional native link changes are not admitted'
    return inventory, candidate, dict(original_qualification=str(QUALIFICATION),
        selected_qualification=str(qualification_path), original_executable=old['executable'],
        selected_executable=candidate['executable'], changed_exponential_calls=2,
        only_static_placer_object_replaced=True, parent_relink_byte_identical=True,
        fresh_native_positive_placements=3, fresh_lut_output_comparisons=1024,
        assertions_objective_clock_and_full_geometry_unchanged=True,
        packing_routing_timing_objects_unchanged=True, global_donor_pointer_changed=False)


def verify_placed_module(module, expected_counts, kernel_groups=None):
    """Check complete unique bindings, not physical signoff or LUT-slot fit."""
    settings = module['settings']
    for key in ('pack', 'place'):
        assert re.fullmatch('[01]{32}', settings[key]) and int(settings[key], 2) == 1, 'Missing native ' + key
    assert 'route' not in settings or (re.fullmatch('[01]{32}', settings['route'])
                                     and int(settings['route'], 2) == 0), 'Unexpected routing execution'
    assert settings['placer'] == 'static' and float(settings['target_freq']) == 50_000_000
    counts = Counter(cell['type'] for cell in module['cells'].values())
    assert dict(counts) == expected_counts, 'Placed primitive membership/counts changed'
    bels = {}
    for name, cell in module['cells'].items():
        bel = cell.get('attributes', {}).get('NEXTPNR_BEL')
        assert isinstance(bel, str) and re.fullmatch(r'[^\s/]+/[^\s/]+', bel), 'Missing/invalid cell BEL: ' + name
        assert bel not in bels, 'Duplicate native BEL: ' + bel
        bels[bel] = name
    assert bels, 'Empty native placement'
    groups = {}
    if kernel_groups is not None:
        assert len(kernel_groups) == 16 and set(kernel_groups.values()) == {32}
        assert counts['DSP48E1_DSP48E1'] == 515 and counts['RAMB36E1_RAMB36E1'] == 6
        for group in kernel_groups:
            groups[group] = sum(cell['type'] == 'DSP48E1_DSP48E1'
                for name, cell in module['cells'].items() if name.startswith(group + '.'))
        assert groups == kernel_groups, 'Changed retained kernel DSP membership'
    return dict(bound_cells=len(bels), unique_bel_slots=len(bels),
        primitive_counts=dict(counts), retained_kernel_dsps=groups,
        native_legality_scope='QUALIFIED_STATIC_REFINEMENT_FINAL_BEL_VALIDITY_CHECK_NOT_COMPLETE_ARCHITECTURE_SIGNOFF',
        full_placed_numerical_acceptance=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packed', type=Path, default=PACK_PARENT)
    parser.add_argument('--precision-qualification', type=Path, required=True,
                        help='Fresh source-bound native qualification of the isolated double-exp engine')
    args = parser.parse_args()
    packed_path = (ROOT / args.packed).resolve(strict=True)
    assert packed_path.is_relative_to(ROOT / 'build/openxc7')
    out = ROOT / f'build/openxc7/full-prefix-native-place-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(),
        supervisor_pid=os.getpid(), commands=[], channels=32, kernels=16, parallel_products=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        native_packing_executed=False, native_placement_executed=False,
        **{key: False for key in ABSENT_ACCEPTANCE}, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(argv, label, timeout=21600):
        log = out / (label + '.log')
        step = dict(argv=list(map(str, argv)), cwd=str(ROOT), log=str(log.relative_to(ROOT)),
                    timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step)
        start = time.monotonic()
        save()
        try:
            with log.open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                step['pid'] = proc.pid
                save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = log.read_text()
            assert code == 0, text[-3000:]
            assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-3000:]
            if label == 'native_place':
                assert 'Running Static placer...' in text
                assert 'Running simulated annealing placer for refinement.' in text
                assert 'Running post-placement legalisation...' in text
                assert 'Program finished normally.' in text
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        packed = json.loads(packed_path.read_text())
        verify_packed_metadata(packed)
        before = {}
        bind_report(packed_path, packed, before)
        prepared_path = (ROOT / packed['prepared_report']).resolve(strict=True)
        assert prepared_path.is_relative_to(ROOT / 'build/openxc7')
        assert str(prepared_path) in before, 'Unbound preparation report'
        prepared = json.loads(prepared_path.read_text())
        verify_prepared_metadata(prepared)
        assert set(prepared['retained_kernel_instances']) == set(packed['retained_kernel_dsps'])
        bind_report(prepared_path, prepared, before)
        report.update(source=before, packed_report=str(packed_path.relative_to(ROOT)),
            prepared_report=str(prepared_path.relative_to(ROOT)))
        save()
        verify_bindings(before)
        qualification_path = args.precision_qualification.resolve(strict=True)
        assert qualification_path.is_relative_to(Path('/home/fedora/soDLA/build/ypcb'))
        inventory, candidate, tool_transition = verify_native_tool_transition(qualification_path)
        before.update(candidate['inputs'])
        executable = Path(candidate['executable']['path'])
        for path in (QUALIFICATION, qualification_path, DATABASE, CONSTIDS, executable, JSON_WRITER, Path(__file__)):
            before[str(path.resolve())] = digest(path)
        for module in list(sys.modules.values()):
            if getattr(module, '__file__', None):
                path = Path(module.__file__).resolve()
                if path.is_relative_to(ROOT / 'tools'):
                    before[str(path)] = digest(path)
        verify_bindings(before)
        report['timing_inventory'] = inventory
        report['native_tool_transition'] = tool_transition
        report['native_version'] = run([executable, '--version'], 'version', 60).strip()
        assert report['native_version'] == packed['native_version'], 'Changed admitted native producer'
        help_text = run([executable, '--help'], 'help', 60)
        assert all(option in help_text for option in ('--no-route', '--placer', '--Werror'))
        assert 'static' in help_text
        text, translation = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        assert translation == packed['constraint_translation'], 'Changed constraint translation'
        constraints = out / 'ypcb.place-only.literal.xdc'
        constraints.write_text(text)
        report['constraint_translation'] = translation
        input_path = (ROOT / prepared['pack_input']).resolve(strict=True)
        assert input_path.is_relative_to(prepared_path.parent) and str(input_path) in before
        output = out / 'placed.json'
        report.update(stage='native_place', native_packing_executed=True, native_placement_executed=True,
                      original_prepared_input_repacked=True, packed_context_reloaded=False)
        run(placement_argv(executable, input_path, constraints, output), 'native_place')
        design = json.loads(output.read_text())
        module, labels = native_export_module(design, report['native_version'])
        report['native_export_top_translation'] = labels
        report['placement_checks'] = verify_placed_module(module,
            packed['native_packed_cell_counts'], packed['retained_kernel_dsps'])
        del design, module
        verify_bindings(before)
        report.update(status=PLACED, stage='complete', retained_cmac_dsps=512, retained_shell_dsps=3,
                      placed_design=str(output.relative_to(ROOT)))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.iterdir()
                               if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
