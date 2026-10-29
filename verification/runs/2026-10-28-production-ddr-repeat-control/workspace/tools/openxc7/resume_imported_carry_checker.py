#!/usr/bin/env python3
"""Finish small checker qualification from its completed 49-cell native route.

Keep the failed parent unchanged. Revalidate its complete native placement,
eight corruption rejections and actual 49-cell scan/route; compare that saved
route with explicit empty-CARRY metadata and execute the remaining literal
286-cell DSP/BRAM scan/route. No comparison view is an execution input.
This is not full-size transfer, placed fit, physical signoff or a bitstream.
No SHA256SUMS file is written.
"""
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_imported_placement_checker as first
from probe_imported_carry_checker import scan_log, EXTRA_REASONS, verify_extension_evidence, corrupt_checkpoint
from compare_imported_carry_export import carry_export_view
from qualify_static_exp_candidate import LABELS, probe_argv, check_log, validate_placed
from place_prefix_board import verify_bindings

ROOT = first.ROOT
PARENT = ROOT / 'build/openxc7/imported-placement-checker-qualification-1791426415757842131/report.json'
CONTROL = ROOT / 'tests/cmac/test_imported_carry_export.py'
GATE_CONTROL = ROOT / 'tests/cmac/test_imported_carry_checker_resume.py'
REASONS = {**first.REASONS, **EXTRA_REASONS}
PASS = 'QUALIFIED_SMALL_NATIVE_IMPORTED_CHECKPOINT_SCAN_AND_ROUTES_WITH_EXACT_CARRY_EMPTY_PORT_VIEW_NOT_FULL_TRANSFER_OR_SIGNOFF'
FLAGS = ('full_placement_transfer_admitted', 'full_board_native_routing_executed', 'full_board_numerical_acceptance',
         'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted',
         'hardware_programmed', 'comparison_views_used_for_execution')


def verify_parent_metadata(parent):
    assert parent['status'] == 'FAIL' and parent['stage'] == 'fresh_valid_import_scan_and_route' and parent['finished_utc']
    assert parent['error'] == "AssertionError('Unmodeled empty-input primitive')"
    assert parent['full_target_parallel_products'] == 512 and parent['native_corruption_rejections'] == 8
    assert parent['valid_routes'] == {}
    assert [c['label'] for c in parent['commands']] == ['software_controls', 'generated_check', 'version', *LABELS, *REASONS, 'fixed_49']
    for command in parent['commands']:
        expected = 125 if command['label'] in {'invalid-forced', *REASONS} else 0
        assert command['returncode'] == command['expected_returncode'] == expected
        assert command['status'] == ('PASS_EXPECTED_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY')
    assert all(parent[key] is False for key in FLAGS), 'Failed small parent cannot grant physical/full acceptance'


def compare_route(before, after):
    with first.checkpoint.SiteBELMap(first.checkpoint.DATABASE, first.checkpoint.CONSTIDS) as database:
        footprint = first.checkpoint.verify_routed_footprint(after, first.checkpoint.physical_footprint(before, database), {})
    view, annotations = carry_export_view(before, after)
    identity = first.checkpoint.assert_circuit_identity(first.checkpoint.proof_module(before),
        first.checkpoint.proof_module(view, before['ports']))
    return dict(footprint=footprint, logical_identity=identity, comparison_only_empty_port_annotations=annotations)


def main():
    out = ROOT / f'build/openxc7/imported-carry-checker-resume-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    for path in (Path(__file__), CONTROL, GATE_CONTROL): shutil.copyfile(path, out / ('executed_' + path.name))
    report = dict(status='RUNNING', stage='admission', started_utc=first.checkpoint.timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], original_failed_report=str(PARENT), original_failure_relabelled=False,
        reused_completed_source_bound_native_49_scan_and_route=True, fresh_native_286_scan_and_route_executed=False,
        full_target_parallel_products=512, **{key: False for key in FLAGS},
        production_source_before=first.checkpoint.source_revision())
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, timeout=1800):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), cwd=str(ROOT),
                    expected_returncode=0, timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as process:
                step['pid'] = process.pid; save()
                try: code = process.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code; text = Path(step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', text), text[-4000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        q, before = verify_extension_evidence()
        parent = json.loads(PARENT.read_text()); verify_parent_metadata(parent)
        for path, sha in parent['source'].items():
            assert path not in before or before[path] == sha, 'Conflicting parent source'
            before[path] = sha
        for path, sha in parent['artifacts'].items():
            resolved = (ROOT / path).resolve(strict=True)
            assert resolved.is_relative_to(PARENT.parent), 'Parent artifact escaped its run directory'
            key = str(resolved)
            assert key not in before or before[key] == sha, 'Conflicting parent artifact binding'
            before[key] = sha
        files = {PARENT, Path(__file__).resolve(), CONTROL, GATE_CONTROL, Path(sys.executable).resolve()}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in files:
            value = first.checkpoint.digest(path)
            assert str(path) not in before or before[str(path)] == value, 'Changed continuation input'
            before[str(path)] = value
        verify_bindings(before)
        built = json.loads(Path(parent['candidate_build_report']).read_text()); first.verify_build_metadata(built)
        assert built['executable'] == parent['executable'] and built['native_version'] == parent['native_version']
        assert first.checkpoint.digest(Path(built['executable']['path'])) == built['executable']['sha256']
        assert parent['production_source_before'] == report['production_source_before'] == q['production_source_before']
        report.update(source=before, executable=built['executable'], native_version=built['native_version'],
                      software_runtime=dict(executable=str(Path(sys.executable).resolve()), version=sys.version), stage='software_controls')
        for control in (CONTROL, GATE_CONTROL):
            run(control.stem, [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', control.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        report['stage'] = 'revalidate_completed_native_controls'; save()
        forced = first.NATIVE.parent / 'valid-forced-placed.json'
        forced_design = json.loads(forced.read_text())
        original49 = next(iter(forced_design['modules'].values()))
        forced_step = next(c for c in q['commands'] if c['label'] == 'valid-forced')
        forced_xdc = Path(next(a[4:] for a in forced_step['argv'] if a.startswith('xdc=')))
        for step in parent['commands']:
            label, text = step['label'], Path(step['log']).read_text()
            if label in LABELS:
                check_log(step['returncode'], text, step['expected_returncode'])
                old = next(c for c in q['commands'] if c['label'] == label)
                fixture = Path(old['fixture']); xdc = Path(next(a[4:] for a in old['argv'] if a.startswith('xdc=')))
                output = PARENT.parent / (label + '-placed.json')
                assert step['argv'] == probe_argv(built['executable']['path'], fixture, xdc, output)
                if label == 'invalid-forced': assert not output.exists()
                else: assert validate_placed(output, 47 if label == 'counter' else 49,
                        None if label == 'counter' else fixture) == step['placement_checks']
            elif label in REASONS:
                scan_log(step['returncode'], text, rejection=REASONS[label])
                bad = PARENT.parent / (label + '.json')
                invalid_output = PARENT.parent / (label + '-invalid-output.json')
                assert json.loads(bad.read_text()) == corrupt_checkpoint(forced_design, label), 'Changed actual corruption input'
                expected_argv = first.checkpoint.resume_argv(built['executable']['path'], bad, 'top', forced_xdc, invalid_output, route=True)
                expected_argv += ['-o', 'rknpu-check-imported-placement=fixed-lut-v1']
                assert step['argv'] == expected_argv, 'Changed native corruption invocation'
                assert not invalid_output.exists()
            elif label == 'fixed_49':
                scan_log(step['returncode'], text, 49, 9)
                routed = PARENT.parent / 'fixed_49-routed.json'
                expected_argv = first.checkpoint.resume_argv(built['executable']['path'], forced,
                    next(iter(forced_design['modules'])), forced_xdc, routed, route=True)
                expected_argv += ['-o', 'rknpu-check-imported-placement=fixed-lut-v1',
                    '-o', 'fasm=' + str(PARENT.parent / 'fixed_49.fasm'),
                    '-o', 'placement=' + str(PARENT.parent / 'fixed_49-placement.json')]
                assert step['argv'] == expected_argv, 'Changed completed native 49-cell invocation'
            else: assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', text)
        routed49 = next(iter(json.loads((PARENT.parent / 'fixed_49-routed.json').read_text())['modules'].values()))
        result49 = compare_route(original49, routed49)
        assert result49['logical_identity']['logical_board']['cells'] == 49
        assert result49['comparison_only_empty_port_annotations']['restored_empty_CARRY4_ports_by_direction'] == {'input': 2, 'output': 6}
        report.update(saved_native_49_comparison=result49, unchanged_preplacement_positives=3,
                      original_preplacement_truth_comparisons=1024, imported_corruptions_revalidated=8, stage='fresh_286_scan_and_route')
        path = first.TRANSFER.parent / 'corrected-transfer-input.json'
        transfer = json.loads(first.TRANSFER.read_text())
        assert first.checkpoint.digest(path) == transfer['hardware_input_sha256']
        design = json.loads(path.read_text()); context, original286 = next(iter(design['modules'].items()))
        routed, fasm, placement = (out / name for name in ('routed-286.json', 'control-286.fasm', 'placement-286.json'))
        argv = first.checkpoint.resume_argv(built['executable']['path'], path, context, first.TRANSFER.parent / 'literal.xdc', routed, route=True)
        argv += ['-o', 'rknpu-check-imported-placement=fixed-lut-v1', '-o', 'fasm=' + str(fasm), '-o', 'placement=' + str(placement)]
        report['fresh_native_286_scan_and_route_executed'] = True
        scan_log(0, run('native_286_scan_and_route', argv), 286, 98)
        after286 = next(iter(json.loads(routed.read_text())['modules'].values()))
        result286 = compare_route(original286, after286)
        assert result286['logical_identity']['logical_board']['cells'] == 286
        features, repeated = first.checkpoint.parse_native_features(fasm.read_text())
        selected = json.loads(first.checkpoint.SELECTED.read_text())
        originals = {n: selected[s] for n, s in transfer['control_origins'].items()}
        places = json.loads(placement.read_text())
        with first.checkpoint.SiteBELMap(first.checkpoint.DATABASE, first.checkpoint.CONSTIDS) as database:
            result286['primitive_features'] = first.compare_selected(features, {n: places[n] for n in originals}, originals,
                {n: after286['cells'][n] for n in originals}, database.global_label)
        result286.update(FASM_features=len(features), repeated_STEPDOWN_lines=repeated)
        report['fresh_native_286_comparison'] = result286
        verify_bindings(before)
        report['production_source_after'] = first.checkpoint.source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=PASS, stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = first.checkpoint.timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): first.checkpoint.digest(p)
            for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
