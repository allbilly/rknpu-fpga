#!/usr/bin/env python3
"""Fresh small native v2 import/scan/routes and explicit corruption controls.

Retain fresh v1 positive/unsupported-output rejection, all eight existing v2
carry/pair rejections, new literal-output negatives and 49/50/286 native routes.
Every original cell BEL, logical endpoint, primitive parameter and selected
four-DSP/six-BRAM feature must compare. The added 50th LUT is test-only with
no connected output; it is not a full placement or numerical FPGA/RK result.
No old gate/source/log is edited or comparison view used for execution.
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
import build_empty_output_checker as build
import route_strict_search_board as support
from probe_imported_empty_lut import BASE, NAME, fixture, actual_empty_lut, check_rejection
from probe_imported_carry_checker import corrupt_checkpoint
from place_prefix_board import bind_report, verify_bindings
from compare_full_imported_export import full_export_view
from evidence import source_revision

ROOT = support.ROOT
CONTROL = ROOT / 'tests/cmac/test_empty_output_checker_probe.py'
PASS = 'QUALIFIED_SMALL_NATIVE_LITERAL_EMPTY_OUTPUT_V2_IMPORT_SCAN_ROUTES_NOT_FULL_TRANSFER_NUMERICAL_OR_PHYSICAL_SIGNOFF'
NEW_REASONS = {
    'missing_empty_output': 'RKNPU empty-output import: missing literal LUT output declaration.',
    'unknown_empty_output': 'RKNPU empty-output import: invalid literal LUT output declaration.',
    'nonarray_empty_output': 'RKNPU empty-output import: invalid literal LUT output declaration.',
    'wrong_empty_direction': 'RKNPU empty-output import: invalid literal LUT output declaration.',
    'missing_empty_mapping': 'RKNPU empty-output import: requires one annotated logical LUT output.',
    'duplicate_logical_output': 'RKNPU empty-output import: requires one annotated logical LUT output.',
    'missing_connected_output': 'RKNPU empty-output import: missing literal LUT output declaration.',
    'incomplete_empty_input_mapping': 'RKNPU imported placement scan: incomplete logical input mapping.',
}
FLAGS = ('full_placement_transfer_admitted', 'full_board_native_routing_executed', 'full_board_numerical_acceptance',
         'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted',
         'hardware_programmed', 'comparison_views_used_for_execution', 'full_input_modified')


def verify_build(report):
    assert report['status'] == build.BUILT and report['stage'] == 'complete' and report['finished_utc']
    assert report['profile'] == 'fixed-lut-v2' and report['changed_objects_relative_to_qualified_carry_engine'] == 2
    assert [c['label'] for c in report['commands']] == ['software_controls', 'generated_check', 'compiler_version',
        'relink_qualified_parent_identity', 'compile_xilinx', 'compile_json_frontend', 'link_empty_output_checker', 'native_version']
    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0 for c in report['commands'])
    for key in ('qualified_parent_relink_byte_identical', 'default_and_v1_import_unchanged',
                'original_native_validity_guards_preserved', 'source_declared_empty_PORT_OUT_preserved'):
        assert report[key] is True
    for key in ('native_requalification_executed', 'full_placement_transfer_admitted', 'connected_graph_changed',
                'old_v1_behavior_changed', 'numerical_acceptance', 'physical_fit_verified', 'timing_signoff',
                'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed',
                'warning_checks_suppressed', 'second_JSON_parse_added'):
        assert report[key] is False
    assert report['production_source_before'] == report['production_source_after']


def new_corruption(original, kind):
    assert kind in NEW_REASONS
    bad = deepcopy(original); cells = next(iter(bad['modules'].values()))['cells']; lower = cells[NAME]
    if kind == 'missing_empty_output': del lower['connections']['O5']
    elif kind == 'unknown_empty_output': lower['connections']['O5'] = ['x']
    elif kind == 'nonarray_empty_output': lower['connections']['O5'] = None
    elif kind == 'wrong_empty_direction': lower['port_directions']['O5'] = 'input'
    elif kind == 'missing_empty_mapping': del lower['attributes']['X_ORIG_PORT_O5']
    elif kind == 'duplicate_logical_output':
        lower['connections']['O6'] = []; lower['port_directions']['O6'] = 'output'; lower['attributes']['X_ORIG_PORT_O6'] = 'O'
    elif kind == 'missing_connected_output':
        upper = next(c for c in cells.values() if c['attributes']['NEXTPNR_BEL'] == lower['attributes']['NEXTPNR_BEL'][:-4] + '6LUT')
        del upper['connections']['O6']
    else: lower['attributes']['X_ORIG_PORT_A1'] = 'I0'
    assert bad != original
    return bad


def reject_log(code, text, reason):
    assert code == 125 and ('ERROR: ' + reason) in text
    assert not re.search(r'(?im)\bWARNING:|Assertion failure|Segmentation fault|sorry:', text)
    for marker in ('RKNPU imported placement scan: passed', 'Running router2', 'Routing complete.', 'Program finished normally.'):
        assert marker not in text, 'Invalid input reached routing/completion'


def compare_route(before, after):
    with support.SiteBELMap(support.DATABASE, support.CONSTIDS) as database:
        footprint = support.verify_routed_footprint(after, support.physical_footprint(before, database), {})
    view, metadata = full_export_view(before, after)
    identity = support.assert_circuit_identity(support.proof_module(before), support.proof_module(view, before['ports']))
    return dict(footprint=footprint, logical_identity=identity, comparison_only_port_annotations=metadata)


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args(); built_path = args.build.resolve(strict=True)
    out = ROOT / f'build/openxc7/empty-output-checker-qualification-{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py'); shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=support.timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], candidate_build_report=str(built_path), valid_routes={},
        full_target_parallel_products=512, fresh_old_corruption_rejections=0, fresh_literal_corruption_rejections=0,
        production_source_before=source_revision(), **{key: False for key in FLAGS})
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, reason=None, timeout=1800):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT), log=str(out / (label + '.log')),
                    status='RUNNING', expected_returncode=125 if reason else 0, timeout_seconds=timeout)
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
            if reason: reject_log(code, text, reason)
            else: assert code == 0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', text), text[-4000:]
            step['status'] = 'PASS_EXPECTED_REJECTION_ONLY' if reason else 'PASS_TOOL_EXECUTION_ONLY'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        before = {}; parent, _ = support.verify_small_evidence(before)
        built = json.loads(built_path.read_text()); verify_build(built); bind_report(built_path, built, before)
        assert built['parent_executable'] == parent['executable'] and support.digest(built['executable']['path']) == built['executable']['sha256']
        template = built_path.parent / 'check_imported_placement.inc'
        old_template = Path(built['parent_build_report']).parent / 'check_imported_placement.inc'
        assert template.read_text() == build.candidate.checker_template(old_template.read_text())
        assert (built_path.parent / 'himbaechel/uarch/xilinx/xilinx.cc').read_text() == build.builder.checked_source(build.builder.TAG_SOURCE.read_text(), template.read_text())
        assert (built_path.parent / 'frontend/json_frontend.cc').read_text() == build.candidate.frontend_source(build.candidate.FRONTEND.read_text())
        for path in {Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve()} | {
                Path(m.__file__).resolve() for m in list(sys.modules.values())
                if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')}:
            sha = support.digest(path); assert str(path) not in before or before[str(path)] == sha; before[str(path)] = sha
        verify_bindings(before); report.update(source=before, executable=built['executable'], native_version=built['native_version'], stage='software_controls')
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        assert run('version', [built['executable']['path'], '--version'], timeout=60).strip() == built['native_version']
        design49 = json.loads(BASE.read_text()); design50, _ = fixture(design49, actual_empty_lut())
        fifty = out / 'test-only-50.json'; fifty.write_text(json.dumps(design50, indent=2) + '\n')
        original_q = json.loads(support.checker.NATIVE.read_text())
        command = next(c for c in original_q['commands'] if c['label'] == 'valid-forced')
        xdc = Path(next(v[4:] for v in command['argv'] if v.startswith('xdc=')))
        def argv_for(path, design, label, profile='fixed-lut-v2', fasm=False, literal_xdc=xdc):
            output = out / (label + '-routed.json')
            argv = support.checker.checkpoint.resume_argv(built['executable']['path'], path, next(iter(design['modules'])), literal_xdc, output, route=True)
            argv += ['-o', 'rknpu-check-imported-placement=' + profile]
            if fasm: argv += ['-o', 'fasm=' + str(out / (label + '.fasm')), '-o', 'placement=' + str(out / (label + '-placement.json'))]
            return argv, output
        report['stage'] = 'native_rejections'; save()
        argv, output = argv_for(fifty, design50, 'v1_empty_output', 'fixed-lut-v1')
        text = run('v1_empty_output', argv, 'RKNPU imported placement scan: changed logical output mapping.'); check_rejection(125, text); assert not output.exists()
        for kind, reason in support.small.REASONS.items():
            bad = corrupt_checkpoint(design49, kind); path = out / (kind + '.json'); path.write_text(json.dumps(bad, indent=2) + '\n')
            argv, output = argv_for(path, bad, kind); run(kind, argv, 'RKNPU imported placement scan: ' + reason); assert not output.exists()
            report['fresh_old_corruption_rejections'] += 1
        for kind, reason in NEW_REASONS.items():
            bad = new_corruption(design50, kind); path = out / (kind + '.json'); path.write_text(json.dumps(bad, indent=2) + '\n')
            argv, output = argv_for(path, bad, kind); run(kind, argv, reason); assert not output.exists()
            report['fresh_literal_corruption_rejections'] += 1
        report['stage'] = 'native_positive_routes'; save()
        transfer = json.loads(support.checker.TRANSFER.read_text())
        path286 = support.checker.TRANSFER.parent / 'corrected-transfer-input.json'; design286 = json.loads(path286.read_text())
        for label, path, design, cells, pairs, roles, empty, profile, literal_xdc in (
            ('v1_49', BASE, design49, 49, 9, 8, None, 'fixed-lut-v1', xdc),
            ('v2_49', BASE, design49, 49, 9, 8, 0, 'fixed-lut-v2', xdc),
            ('v2_50', fifty, design50, 50, 10, 8, 1, 'fixed-lut-v2', xdc),
            ('v2_286', path286, design286, 286, 98, 0, 0, 'fixed-lut-v2', support.checker.TRANSFER.parent / 'literal.xdc')):
            argv, output = argv_for(path, design, label, profile, True, literal_xdc)
            text = run(label, argv); support.check_full_scan(text, cells, pairs, roles)
            if empty is None: assert 'RKNPU empty-output import:' not in text
            else: assert text.count(f'RKNPU empty-output import: preserved {empty} literal disconnected LUT outputs; connected graph unchanged.') == 1
            original = next(iter(design['modules'].values())); after = next(iter(json.loads(output.read_text())['modules'].values()))
            compared = compare_route(original, after); assert compared['logical_identity']['logical_board']['cells'] == cells
            if label == 'v2_50':
                assert after['cells'][NAME]['connections']['O5'] == [] and after['cells'][NAME]['port_directions']['O5'] == 'output'
                assert compared['comparison_only_port_annotations']['restored_empty_plain_LUT_outputs'] == 0
            if cells == 286:
                features, repeated = support.checker.checkpoint.parse_native_features((out / (label + '.fasm')).read_text())
                selected = json.loads(support.checker.checkpoint.SELECTED.read_text())
                originals = {n: selected[s] for n, s in transfer['control_origins'].items()}
                placements = json.loads((out / (label + '-placement.json')).read_text())
                with support.SiteBELMap(support.DATABASE, support.CONSTIDS) as database:
                    compared['primitive_features'] = support.checker.compare_selected(features, {n: placements[n] for n in originals}, originals,
                        {n: after['cells'][n] for n in originals}, database.global_label)
                compared.update(FASM_features=len(features), repeated_STEPDOWN_lines=repeated)
            report['valid_routes'][label] = compared; save()
        verify_bindings(before); report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=PASS, stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = support.timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): support.digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
