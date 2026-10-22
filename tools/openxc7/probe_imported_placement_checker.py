#!/usr/bin/env python3
"""Qualify the opt-in checkpoint scan with fresh small native controls.

Re-execute the unchanged pre-placement negatives/positives, then import real
source-bound fixed checkpoints, reject corrupt copies before routing, and
check fresh successful routes against every original BEL/logical connection.
This is not full placement-transfer admission, physical signoff or a bitstream.
No original input, expectation, vendor model or SHA256SUMS file is modified.
"""
import argparse
from copy import deepcopy
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
import probe_corrected_dsp_checkpoint as checkpoint
from build_imported_placement_checker import TEMPLATE, TAG_SOURCE, OLD_OBJECT, checked_source, link_argv
from qualify_static_exp_candidate import LABELS, probe_argv, check_log, validate_placed
from verify_corrected_native_evidence import verify_corrected_evidence
from audit_postplace_lut_pairs import audit_pairs
from resume_corrected_dsp_checkpoint import empty_input_view
from check_full_corrected_native_features import compare_selected
from place_prefix_board import verify_bindings

ROOT = checkpoint.ROOT
CONTROL = ROOT / 'tests/cmac/test_imported_placement_checker_probe.py'
NATIVE = ROOT / 'build/openxc7/dsp-constant-qualification-1791414657664905509/report.json'
TRANSFER = ROOT / 'build/openxc7/corrected-placement-transfer-control-1791420228939723426/report.json'
FIXTURE_OBSERVATION = ROOT / 'build/openxc7/transfer-software-fixture-observation-20261008T004909Z/report.json'
REASONS = {
    'wrong_A6_tie': 'wrong paired output/A6 mode contract',
    'logical_A6': 'wrong paired output/A6 mode contract',
    'shared_pin_mismatch': 'different nets on a shared physical pin',
    'missing_logical_annotation': 'missing logical input annotation/direction',
    'connected_5LUT_A6': 'connected 5LUT A6',
    'latch_in_5FF': 'native BEL legality rejected',
}
BUILT = 'BUILT_OPT_IN_NATIVE_IMPORTED_PLACEMENT_CHECKER_NOT_QUALIFIED_OR_FULL_TRANSFER_SIGNOFF'


def verify_build_metadata(built):
    assert built['status'] == BUILT and built['stage'] == 'complete' and built['finished_utc']
    assert built['changed_objects_relative_to_corrected_encoder'] == 1
    assert built['corrected_parent_relink_byte_identical'] is True
    assert built['original_source_and_old_assertions_preserved'] is True
    assert built['preexisting_prerouted_loop_index_corrected_to_API_size_t'] is True
    assert built['warning_checks_suppressed'] is False
    assert built['actual_original_source'] == str(TAG_SOURCE) and built['actual_original_object'] == str(OLD_OBJECT)
    assert built['production_source_before'] == built['production_source_after']
    assert [c['label'] for c in built['commands']] == ['software_controls', 'generated_check', 'compiler_version',
        'relink_corrected_parent_identity', 'compile_imported_placement_probe', 'link_imported_placement_probe', 'native_version']
    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0 for c in built['commands'])
    for key in ('native_requalification_executed', 'full_placement_transfer_admitted', 'physical_fit_verified',
                'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert built[key] is False, 'Build-only acceptance escalation: ' + key


def corrupt_checkpoint(original, kind):
    assert kind in REASONS
    bad = deepcopy(original)
    module = next(iter(bad['modules'].values()))
    route = module['settings'].get('route', '0')
    assert re.fullmatch('[01]{1,32}', route) and int(route, 2) == 0, 'Routed/unknown checkpoint stage'
    cells = module['cells']
    lower, upper = cells['captured_pair_lut0'], cells['captured_pair_lut1']
    if kind == 'wrong_A6_tie': upper['connections']['A6'] = list(lower['connections']['A5'])
    elif kind == 'logical_A6': upper['attributes']['X_ORIG_PORT_A6'] = 'I5'
    elif kind == 'shared_pin_mismatch': upper['connections']['A3'] = list(lower['connections']['A1'])
    elif kind == 'missing_logical_annotation': upper['attributes'].pop('X_ORIG_PORT_A3')
    elif kind == 'connected_5LUT_A6':
        lower['connections']['A6'] = list(upper['connections']['A6']); lower['port_directions']['A6'] = 'input'
    else:
        targets = [c for c in cells.values() if c['type'] == 'SLICE_FFX' and c['attributes']['NEXTPNR_BEL'].endswith('5FF')]
        assert targets, 'Missing actual 5FF corruption target'
        targets[0]['attributes']['X_FF_AS_LATCH'] = '1'
    assert bad != original
    return bad


def scan_log(code, text, cells=None, pairs=None, rejection=None):
    begin = 'RKNPU imported placement scan: begin before clock/general routing.'
    assert text.count(begin) == 1, 'Native scan did not execute exactly once'
    assert not re.search(r'(?im)\bWARNING:|sorry:|target is ignored|matched nothing', text)
    if rejection:
        assert code == 125 and ('RKNPU imported placement scan: ' + rejection) in text
        assert 'RKNPU imported placement scan: passed' not in text
        assert 'Running router2' not in text and 'Routing complete.' not in text, 'Invalid input reached routing'
        return
    assert code == 0 and not re.search(r'(?im)\b(?:ERROR|FATAL):', text)
    marker = f'RKNPU imported placement scan: passed {cells} bound cells and {pairs} fixed logic pairs; original tags restored and caches invalidated.'
    assert text.count(marker) == 1
    for required in ('Running router1 to check that route is legal...', 'Routing complete.',
                     'Running post-routing legalisation...', 'Program finished normally.'):
        assert required in text, 'Missing successful native route marker'
    assert text.index(marker) < text.index('Routing complete.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args(); build_path = args.build.resolve(strict=True)
    out = ROOT / f'build/openxc7/imported-placement-checker-qualification-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py'); shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=checkpoint.timestamp(), supervisor_pid=os.getpid(),
                  scope=__doc__, source={}, commands=[], candidate_build_report=str(build_path),
                  full_target_parallel_products=512, full_placement_transfer_admitted=False,
                  full_board_native_routing_executed=False, full_board_numerical_acceptance=False,
                  physical_fit_verified=False, timing_signoff=False, electrical_verified=False, drc_signoff=False,
                  bitstream_emitted=False, hardware_programmed=False, comparison_views_used_for_execution=False,
                  production_source_before=checkpoint.source_revision())
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, expected=0, timeout=600, checker=None, **extra):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), cwd=str(ROOT),
                    expected_returncode=expected, timeout_seconds=timeout, status='RUNNING', **extra)
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as process:
                step['pid'] = process.pid; save()
                try: code = process.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code; text = Path(step['log']).read_text()
            assert code == expected, text[-4000:]
            if checker: checker(code, text)
            else: assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', text), text[-4000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY' if code == 0 else 'PASS_EXPECTED_REJECTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        q, before = verify_corrected_evidence()
        built, transfer = (json.loads(p.read_text()) for p in (build_path, TRANSFER))
        verify_build_metadata(built)
        assert transfer['status'] == 'PASS_SMALL_NATIVE_OLD_PLACEMENT_EXACT_DSP_CORRECTION_RELOAD_AND_ROUTE_NOT_FULL_TRANSFER_OR_SIGNOFF'
        assert transfer['stage'] == 'complete' and transfer['finished_utc']
        verify_bindings(transfer['source'])
        observation = json.loads(FIXTURE_OBSERVATION.read_text()); verify_bindings(observation['source'])
        before.update(observation['source'])
        for path, sha in {**built['inputs'], **transfer['source']}.items():
            assert path not in before or before[path] == sha, 'Conflicting qualified input binding'
            before[path] = sha
        for path, sha in built['artifacts'].items(): before[str((ROOT / path).resolve())] = sha
        for path, sha in transfer['artifacts'].items(): before[str((ROOT / path).resolve())] = sha
        files = [build_path, TRANSFER, FIXTURE_OBSERVATION, NATIVE, Path(__file__).resolve(), CONTROL,
                 Path(sys.executable).resolve(), TEMPLATE]
        forced = NATIVE.parent / 'valid-forced-placed.json'
        assert checkpoint.digest(forced) == q['artifacts'][str(forced.relative_to(ROOT))]
        transfer_input = TRANSFER.parent / 'corrected-transfer-input.json'
        assert checkpoint.digest(transfer_input) == transfer['hardware_input_sha256']
        files.extend([forced, transfer_input])
        files.extend(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for p in files:
            sha = checkpoint.digest(p)
            assert str(p) not in before or before[str(p)] == sha, 'Changed new probe input'
            before[str(p)] = sha
        verify_bindings(before)
        source = build_path.parent / 'himbaechel/uarch/xilinx/xilinx.cc'
        assert source.read_text() == checked_source(TAG_SOURCE.read_text(), TEMPLATE.read_text())
        parent = json.loads(Path(built['parent_build_report']).read_text())
        parent_link = next(c for c in parent['commands'] if c['label'] == 'link_DSP_constant_candidate')
        native_link = next(c for c in built['commands'] if c['label'] == 'link_imported_placement_probe')
        assert native_link['argv'] == link_argv(parent_link['argv'], Path(built['executable']['path']),
                                              {OLD_OBJECT: build_path.parent / 'xilinx.cc.o'})
        executable = built['executable']['path']
        assert checkpoint.digest(Path(executable)) == built['executable']['sha256']
        report.update(source=before, executable=built['executable'], native_version=built['native_version'],
                      software_runtime=dict(executable=str(Path(sys.executable).resolve()), version=sys.version), stage='software_controls')
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        assert run('version', [executable, '--version'], timeout=60).strip() == built['native_version']
        report['stage'] = 'unchanged_preplacement_controls'; save()
        for label in LABELS:
            old = next(c for c in q['commands'] if c['label'] == label)
            fixture = Path(old['fixture']); argv = old['argv']; xdc = Path(next(a[4:] for a in argv if a.startswith('xdc=')))
            output = out / (label + '-placed.json')
            expected = 125 if label == 'invalid-forced' else 0
            run(label, probe_argv(executable, fixture, xdc, output), expected=expected,
                checker=lambda c, t, e=expected: check_log(c, t, e))
            if expected: assert not output.exists()
            else: report['commands'][-1]['placement_checks'] = validate_placed(output, 47 if label == 'counter' else 49, None if label == 'counter' else fixture)
        original = json.loads(forced.read_text()); module = next(iter(original['modules'].values()))
        pair_check = audit_pairs(module); assert pair_check['logic_pairs_compared'] == 9 and pair_check['six_input_naive_tag_unions'] == 1
        old = next(c for c in q['commands'] if c['label'] == 'valid-forced')
        forced_xdc = Path(next(a[4:] for a in old['argv'] if a.startswith('xdc=')))
        report['stage'] = 'native_scan_corruption_controls'; save()
        for kind, reason in REASONS.items():
            bad = out / (kind + '.json'); bad.write_text(json.dumps(corrupt_checkpoint(original, kind), indent=2) + '\n')
            invalid_output = out / (kind + '-invalid-output.json')
            argv = checkpoint.resume_argv(executable, bad, 'top', forced_xdc, invalid_output, route=True)
            argv += ['-o', 'rknpu-check-imported-placement=fixed-lut-v1']
            run(kind, argv, expected=125, checker=lambda c, t, why=reason: scan_log(c, t, rejection=why))
            assert not invalid_output.exists(), 'Invalid checkpoint output was published'
        report.update(native_corruption_rejections=len(REASONS), stage='fresh_valid_import_scan_and_route')
        selected = json.loads(checkpoint.SELECTED.read_text()); report['valid_routes'] = {}
        for label, path, xdc, cells, pairs in (('fixed_49', forced, forced_xdc, 49, 9),
            ('corrected_transfer_286', transfer_input, TRANSFER.parent / 'literal.xdc', 286, 98)):
            design = json.loads(path.read_text()); context, before_module = next(iter(design['modules'].items()))
            assert audit_pairs(before_module)['logic_pairs_compared'] == pairs
            routed, fasm, placement = (out / (label + name) for name in ('-routed.json', '.fasm', '-placement.json'))
            argv = checkpoint.resume_argv(executable, path, context, xdc, routed, route=True)
            argv += ['-o', 'rknpu-check-imported-placement=fixed-lut-v1', '-o', 'fasm=' + str(fasm), '-o', 'placement=' + str(placement)]
            run(label, argv, timeout=1800, checker=lambda c, t, n=cells, p=pairs: scan_log(c, t, n, p))
            after_module = next(iter(json.loads(routed.read_text())['modules'].values()))
            with checkpoint.SiteBELMap(checkpoint.DATABASE, checkpoint.CONSTIDS) as database:
                footprint = checkpoint.verify_routed_footprint(after_module, checkpoint.physical_footprint(before_module, database), {})
            view, annotations = empty_input_view(before_module, after_module, include_luts=False)
            identity = checkpoint.assert_circuit_identity(checkpoint.proof_module(before_module), checkpoint.proof_module(view, before_module['ports']))
            result = dict(bound_cells_scanned=cells, fixed_pairs_scanned=pairs, footprint=footprint, logical_identity=identity,
                          comparison_only_empty_input_annotations=annotations)
            if cells == 286:
                features, repeated = checkpoint.parse_native_features(fasm.read_text())
                originals = {n: selected[s] for n, s in transfer['control_origins'].items()}
                places = json.loads(placement.read_text())
                with checkpoint.SiteBELMap(checkpoint.DATABASE, checkpoint.CONSTIDS) as database:
                    result['primitive_features'] = compare_selected(features, {n: places[n] for n in originals}, originals,
                        {n: after_module['cells'][n] for n in originals}, database.global_label)
                result.update(FASM_features=len(features), repeated_STEPDOWN_lines=repeated)
            report['valid_routes'][label] = result; save()
        verify_bindings(before)
        report['production_source_after'] = checkpoint.source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status='QUALIFIED_OPT_IN_NATIVE_FIXED_CHECKPOINT_SCAN_AND_SMALL_ROUTES_NOT_FULL_TRANSFER_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = checkpoint.timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): checkpoint.digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
