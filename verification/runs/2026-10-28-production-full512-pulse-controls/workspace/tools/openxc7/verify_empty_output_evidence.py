"""Read-only admission of completed source-bound small v2 native evidence.

Recheck actual inputs, argv, rejections, scans, routes, BEL/logical identity,
four-DSP/six-BRAM FASM and exact generated native source. RUNNING, failed,
build-only or software-only reports cannot qualify a full-route handoff.
This does not admit full placement/route, numerical or physical signoff.
"""
import json
from pathlib import Path

import route_strict_search_board as base
import probe_empty_output_checker as probe
import resume_empty_output_qualification as continuation
import fixed_empty_output_fixture as fixed
from place_prefix_board import bind_report, verify_bindings
from probe_imported_empty_lut import BASE, NAME, fixture, actual_empty_lut, check_rejection
from probe_imported_carry_checker import corrupt_checkpoint

QUALIFIED = base.ROOT / 'build/openxc7/empty-output-checker-qualification-1791434347351474071/report.json'
EXPECTED_STATUS = continuation.PASS
POSITIVE = {'v1_49': (49, 9, 8, None), 'v2_49': (49, 9, 8, 0),
            'v2_50': (50, 10, 8, 1), 'v2_286': (286, 98, 0, 0)}
REASONS = {'v1_empty_output': 'RKNPU imported placement scan: changed logical output mapping.',
    **{name: 'RKNPU imported placement scan: ' + reason for name, reason in base.small.REASONS.items()},
    **probe.NEW_REASONS}


def verify_metadata(report):
    assert report['status'] == EXPECTED_STATUS and report['stage'] == 'complete' and report['finished_utc']
    assert report['full_target_parallel_products'] == 512
    assert all(report[key] is False for key in probe.FLAGS)
    assert report['fresh_old_corruption_rejections'] == report['fresh_literal_corruption_rejections'] == 8
    assert report['production_source_before'] == report['production_source_after']
    assert [c['label'] for c in report['commands']] == ['software_controls', 'generated_check', 'version', *REASONS, *POSITIVE]
    for step in report['commands']:
        expected = 125 if step['label'] in REASONS else 0
        assert step['expected_returncode'] == step['returncode'] == expected
        assert step['status'] == ('PASS_EXPECTED_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY')
    assert set(report['valid_routes']) == set(POSITIVE)
    for name, (cells, pairs, roles, empty) in POSITIVE.items():
        compared = report['valid_routes'][name]
        assert compared['logical_identity']['logical_board']['cells'] == cells
    assert report['valid_routes']['v2_50']['comparison_only_port_annotations']['restored_empty_plain_LUT_outputs'] == 0


def verify_qualification(before, path=QUALIFIED):
    path = path.resolve(strict=True); report = json.loads(path.read_text()); verify_metadata(report)
    parent, carry_build = base.verify_small_evidence(before)
    continuation.verify_failed(before)
    built_path = Path(report['candidate_build_report']); built = json.loads(built_path.read_text()); probe.verify_build(built)
    assert built['parent_executable'] == parent['executable'] and built['executable'] == report['executable']
    assert report['native_version'] == built['native_version'] == parent['native_version']
    bind_report(path, report, before); bind_report(built_path, built, before); verify_bindings(before)
    assert base.digest(report['executable']['path']) == report['executable']['sha256']
    template = built_path.parent / 'check_imported_placement.inc'
    old_template = Path(built['parent_build_report']).parent / 'check_imported_placement.inc'
    assert template.read_text() == probe.build.candidate.checker_template(old_template.read_text())
    assert (built_path.parent / 'himbaechel/uarch/xilinx/xilinx.cc').read_text() == probe.build.builder.checked_source(
        probe.build.builder.TAG_SOURCE.read_text(), template.read_text())
    assert (built_path.parent / 'frontend/json_frontend.cc').read_text() == probe.build.candidate.frontend_source(
        probe.build.candidate.FRONTEND.read_text())
    design49 = json.loads(BASE.read_text()); design50, _ = fixed.fixture(design49, actual_empty_lut())
    assert json.loads((path.parent / 'test-only-50.json').read_text()) == design50
    design286 = json.loads((base.checker.TRANSFER.parent / 'corrected-transfer-input.json').read_text())
    old_q = json.loads(base.checker.NATIVE.read_text())
    forced = next(c for c in old_q['commands'] if c['label'] == 'valid-forced')
    xdc49 = Path(next(v[4:] for v in forced['argv'] if v.startswith('xdc=')))
    for step in report['commands']:
        name = step['label']; text = Path(step['log']).read_text()
        if name not in REASONS and name not in POSITIVE: continue
        output = path.parent / (name + '-routed.json')
        profile = 'fixed-lut-v1' if name.startswith('v1_') else 'fixed-lut-v2'
        if name in base.small.REASONS:
            design = corrupt_checkpoint(design49, name); input_path = path.parent / (name + '.json')
            assert json.loads(input_path.read_text()) == design
        elif name in probe.NEW_REASONS:
            design = probe.new_corruption(design50, name); input_path = path.parent / (name + '.json')
            assert json.loads(input_path.read_text()) == design
        elif name == 'v2_286':
            design = design286; input_path = base.checker.TRANSFER.parent / 'corrected-transfer-input.json'
        elif name in ('v1_49', 'v2_49'): design = design49; input_path = BASE
        else: design = design50; input_path = path.parent / 'test-only-50.json'
        xdc = base.checker.TRANSFER.parent / 'literal.xdc' if name == 'v2_286' else xdc49
        argv = base.checker.checkpoint.resume_argv(report['executable']['path'], input_path, next(iter(design['modules'])), xdc, output, route=True)
        argv += ['-o', 'rknpu-check-imported-placement=' + profile]
        if name in POSITIVE:
            argv += ['-o', 'fasm=' + str(path.parent / (name + '.fasm')), '-o', 'placement=' + str(path.parent / (name + '-placement.json'))]
        assert step['argv'] == argv, 'Changed actual native v2 qualification invocation'
        if name in REASONS:
            probe.reject_log(step['returncode'], text, REASONS[name]); assert not output.exists()
            if name == 'v1_empty_output': check_rejection(step['returncode'], text)
            continue
        cells, pairs, roles, empty = POSITIVE[name]; base.check_full_scan(text, cells, pairs, roles)
        if empty is None: assert 'RKNPU empty-output import:' not in text
        else: assert text.count(f'RKNPU empty-output import: preserved {empty} literal disconnected LUT outputs; connected graph unchanged.') == 1
        original = next(iter(design['modules'].values())); exported = next(iter(json.loads(output.read_text())['modules'].values()))
        actual = probe.compare_route(original, exported); recorded = report['valid_routes'][name]
        assert all(recorded[key] == value for key, value in actual.items())
        if name == 'v2_50':
            assert exported['cells'][NAME]['connections']['O5'] == [] and exported['cells'][NAME]['port_directions']['O5'] == 'output'
        if name == 'v2_286':
            features, repeated = base.checker.checkpoint.parse_native_features((path.parent / (name + '.fasm')).read_text())
            selected = json.loads(base.checker.checkpoint.SELECTED.read_text())
            transfer = json.loads(base.checker.TRANSFER.read_text())
            originals = {n: selected[s] for n, s in transfer['control_origins'].items()}
            placements = json.loads((path.parent / (name + '-placement.json')).read_text())
            with base.SiteBELMap(base.DATABASE, base.CONSTIDS) as database:
                compared = base.checker.compare_selected(features, {n: placements[n] for n in originals}, originals,
                    {n: exported['cells'][n] for n in originals}, database.global_label)
            assert compared == recorded['primitive_features'] and len(features) == recorded['FASM_features']
            assert repeated == recorded['repeated_STEPDOWN_lines']
    return report, carry_build  # Same corrected-DSP base as the full placer.
