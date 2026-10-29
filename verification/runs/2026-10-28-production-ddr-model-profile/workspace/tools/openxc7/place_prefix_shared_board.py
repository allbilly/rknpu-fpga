#!/usr/bin/env python3
"""Full shared-prefix HeAP placement characterization; not physical signoff.

Require completed actual full packing/configuration/capacity evidence first.
Freshly repack the same literal physical input using the already-qualified
corrected-DSP HeAP engine. Retain normal refinement, every native legality
guard, all 512 products, the exact -2 part, 50 MHz and seed 3588. No old
placement, input-group assignment, CPU tensor fixup, routing or bits are used.
"""
import argparse
import json
import mmap
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, source_revision, timestamp
from pack_prefix_shared_board import validate_prepared, digest
from pack_prefix_board import TOP, DATABASE, packing_xdc, native_export_module
from audit_corrected_full_pack_identity import layout, records
from place_native_heap_board import placement_argv, verify_full_argv, verify_placed_module
from qualify_native_heap_clock_features import verify_qualification, check_heap_log
from check_full_native_features import routed_primitives, full_inventory
from check_corrected_dsp_features import verify_corrected_packed
from probe_prefix_native_config import verify_clock_admission

PACKED = 'PACKED_FULL_C32K16_SHARED_PREFIX_NATIVE_RESOURCE_CHARACTERIZATION_NOT_PLACED_FIT_OR_SIGNOFF'
HEAP_QUALIFICATION = ROOT / 'build/openxc7/native-heap-clock-features-1791461172554993544/report.json'
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_place_control.py'
NATIVE_TIMEOUT = 43200


def validate_pack(report):
    assert report['status'] == PACKED and report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['retained_cmac_dsps'],
            report['retained_shell_dsps'], report['intended_part'], report['intended_clock_period_ns'], report['seed']) == (
                32, 16, 512, 512, 3, 'xc7k480tffg1156-2', 20, 3588)
    counts = report['native_census']['primitive_counts']
    assert counts['DSP48E1_DSP48E1'] == 515 and counts['RAMB36E1_RAMB36E1'] == 6 and counts['SLICE_FFX'] == 17519
    assert sum(counts.values()) == report['native_census']['cells']
    assert len(report['retained_kernel_dsps']) == 16 and set(report['retained_kernel_dsps'].values()) == {32}
    assert (report['DSP_configurations_compared'], report['extra_tile_only_ties_compared']) == (515, 4120)
    assert report['native_packing_executed'] is True and report['clock_constraint_admitted'] is True
    assert report['production_source_before'] == report['production_source_after']
    bound = report['LUT_sharing_bound']
    assert bound['lut_cells'] == counts['SLICE_LUTX'] and bound['physical_LUT_positions'] == 298600
    assert bound['lower_bound_exceeds_device'] is False and bound['necessary_position_lower_bound'] <= 298600, \
        'This packed graph still exceeds the necessary LUT capacity bound'
    assert bound['maximum_five_to_smaller_matching'] == bound['minimum_cut_capacity']
    for key in ('physical_fit_verified', 'native_placement_executed', 'placement_assignment_generated', 'hardware_execution_input_changed'):
        assert bound[key] is False
    for key in ('native_placement_executed', 'native_routing_executed', 'full_circuit_equivalence_claimed',
                'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
                'drc_signoff', 'bitstream_emitted', 'hardware_programmed', 'complete_ordinary_wire_identity_proved'):
        assert report[key] is False
    labels = ['software_controls', 'DSP_feature_controls', 'LUT_census_controls', 'LUT_matching_controls',
              'generated_check', 'version', 'native_pack']
    assert [s['label'] for s in report['commands']] == labels
    assert all(s['returncode'] == 0 and s['status'] == 'PASS_TOOL_EXECUTION_ONLY' for s in report['commands'])
    argv = report['commands'][-1]['argv']
    assert argv[0] == report['executable']['path']
    for flag, value in (('--chipdb', str(DATABASE)), ('--device', 'xc7k480tffg1156-2'), ('--top', TOP),
                        ('--freq', '50'), ('--seed', '3588'), ('--json', report['execution_input']), ('--write', report['packed_design'])):
        assert argv.count(flag) == 1 and argv[argv.index(flag) + 1] == value
    assert '--pack-only' in argv and '--Werror' in argv and '--timing-allow-fail' not in argv
    assert argv.count('-o') == 1 and argv[argv.index('-o') + 1].startswith('xdc=')
    assert argv == [report['executable']['path'], '--chipdb', str(DATABASE), '--device', 'xc7k480tffg1156-2',
        '--top', TOP, '--json', report['execution_input'], '-o', argv[argv.index('-o') + 1], '--pack-only',
        '--freq', '50', '--seed', '3588', '--Werror', '--debug', '--write', report['packed_design']], 'Unmodeled native packing argument'


def packed_names(path):
    """Exact complete pinned-writer name census, not a placement assignment."""
    names = set()
    with Path(path).open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        begin, end = layout(data)
        for name, raw in records(data, begin, end):
            assert name not in names, 'Duplicate packed cell name'
            names.add(name)
    return names


def compare_placement(design, version, counts, groups, names):
    module, translation = native_export_module(design, version)
    assert set(module['cells']) == names, 'Changed complete placed cell membership'
    checks = verify_placed_module(module, counts, groups)
    assert checks['bound_cells'] == checks['unique_bel_slots'] == len(names)
    return checks, translation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packed', type=Path, required=True)
    args = parser.parse_args()
    pp = args.packed.resolve(strict=True)
    assert pp.is_relative_to(ROOT / 'build/openxc7') and pp.name == 'report.json'
    pack = json.loads(pp.read_text())
    validate_pack(pack)  # No tools/output on RUNNING, reduced target or capacity conflict.
    resource.setrlimit(resource.RLIMIT_AS, (12 * 1024**3, 12 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    out = ROOT / f'build/openxc7/full-prefix-shared-native-heap-place-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], packed_report=str(pp), qualification=str(HEAP_QUALIFICATION),
        channels=32, kernels=16, parallel_products=512, intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
        seed=3588, production_source_before=source_revision(), host_native_timeout_seconds=NATIVE_TIMEOUT,
        native_packing_executed=False, native_placement_executed=False, native_routing_executed=False,
        packed_context_reloaded=False, old_placement_reused=False, input_group_assignment_used=False,
        numerical_netlist_acceptance=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, timeout=120):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')),
                    status='RUNNING', timeout_seconds=timeout)
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
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-3500:]
            if label == 'native_place':
                check_heap_log(code, text)
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    print(out / 'report.json', flush=True)
    try:
        candidate, before = verify_qualification(HEAP_QUALIFICATION)
        for manifest in (pack['source'], pack['artifacts']):
            for name, sha in manifest.items():
                path = (ROOT / name).resolve(strict=True)
                assert str(path) not in before or before[str(path)] == sha, 'Conflicting admitted source'
                before[str(path)] = sha
        prepared_path = Path(pack['prepared_report']).resolve(strict=True)
        assert str(prepared_path) in before
        prepared = json.loads(prepared_path.read_text())
        validate_prepared(prepared)
        assert prepared['production_source_after'] == pack['production_source_after'] == candidate['production_source_after'] == report['production_source_before']
        paths = {pp, CONTROL, Path(sys.executable).resolve(), ROOT / 'tests/cmac/test_native_heap_board_control.py'}
        paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in paths:
            sha = digest(path)
            assert str(path) not in before or before[str(path)] == sha
            before[str(path)] = sha
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed full shared placement input/source'
        input_path = Path(pack['execution_input']).resolve(strict=True)
        assert input_path == Path(prepared['pack_input']).resolve(strict=True) and str(input_path) in before
        packed_path = Path(pack['packed_design']).resolve(strict=True)
        assert packed_path.parent == pp.parent and str(packed_path) in before
        names = packed_names(packed_path)
        assert len(names) == pack['native_census']['cells']
        report.update(source=before, stage='software_controls', executable=candidate['executable'], native_version=candidate['native_version'],
                      prepared_report=str(prepared_path), execution_input=str(input_path), original_prepared_input_repacked=False)
        save()
        for label, name in (('software_controls', CONTROL.name), ('native_heap_guard_controls', 'test_native_heap_board_control.py')):
            run(label, [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        executable = candidate['executable']['path']
        assert run('version', [executable, '--version'], 60).strip() == candidate['native_version']
        text, constraints = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        assert constraints == pack['constraint_translation']
        xdc = out / 'literal.place-only.xdc'
        xdc.write_text(text)
        output = out / 'placed.json'
        argv = placement_argv(executable, input_path, xdc, output)
        verify_full_argv(argv)
        report.update(stage='native_place', native_packing_executed=True, native_placement_executed=True,
                      original_prepared_input_repacked=True, constraint_translation=constraints)
        log = run('native_place', argv, NATIVE_TIMEOUT)
        verify_clock_admission(log, constraints)
        report['stage'] = 'full_unique_BEL_and_DSP_checks'
        save()
        design = json.loads(output.read_text())
        checks, translation = compare_placement(design, candidate['native_version'], pack['native_census']['primitive_counts'],
                                                pack['retained_kernel_dsps'], names)
        del design
        selected = json.loads((pp.parent / 'actual-DSP-BRAM-input.json').read_text())
        placed = routed_primitives(output, selected)
        assert full_inventory(selected, placed) == pack['retained_kernel_dsps']
        for name, cell in selected.items():
            if cell['type'] == 'DSP48E1':
                verify_corrected_packed(cell, placed[name])
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed full placement source/input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='PLACED_FULL_C32K16_SHARED_PREFIX_NATIVE_HEAP_NORMAL_REFINEMENT_NOT_ROUTED_FIT_OR_SIGNOFF', stage='complete',
            placed_design=str(output), placement_checks=checks, native_export_top_translation=translation,
            retained_cmac_dsps=512, retained_shell_dsps=3, retained_kernel_dsps=pack['retained_kernel_dsps'],
            DSP_configurations_compared=515, extra_tile_only_ties_compared=4120)
    except BaseException as error:
        report.update(status='FAIL_PREFIX_SHARED_NATIVE_HEAP_PLACE', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.iterdir() if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
