#!/usr/bin/env python3
"""Fresh v2 qualification with explicit strength on the unused test LUT.

Preserve/recheck the actual 2026-10-08 failed qualification and its original
resource-property rejection. BaseCtx's effective missing-strength default is
USER=6; only a newly generated test-only 50-cell fixture declares that same
value. Re-execute every original native command/gate, including the unexecuted
286-cell DSP/BRAM control. No old input/report, native engine, RTL, comparator,
error expectation, full input, SHA256SUMS manifest or FPGA is changed.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_empty_output_checker as probe
import fixed_empty_output_fixture as fixed
from probe_imported_empty_lut import BASE, NAME, actual_empty_lut, fixture as old_fixture
from place_prefix_board import bind_report, verify_bindings

FAILED = probe.ROOT / 'build/openxc7/empty-output-checker-qualification-1791433199135092252/report.json'
CONTROL = probe.ROOT / 'tests/cmac/test_fixed_empty_output_fixture.py'
PASS = 'QUALIFIED_SMALL_NATIVE_LITERAL_EMPTY_OUTPUT_V2_WITH_EXPLICIT_TEST_STRENGTH_NOT_FULL_ROUTE_NUMERICAL_OR_PHYSICAL_SIGNOFF'
OLD_VERIFY = probe.support.verify_small_evidence


def verify_failed(before):
    report = json.loads(FAILED.read_text())
    assert report['status'] == 'FAIL' and report['stage'] == 'native_positive_routes' and report['finished_utc']
    assert report['error'] == "AssertionError('Changed resource properties: test_only_declared_empty_XORCY_LUT2')"
    labels = ['software_controls', 'generated_check', 'version', 'v1_empty_output',
              *probe.support.small.REASONS, *probe.NEW_REASONS, 'v1_49', 'v2_49', 'v2_50']
    assert [c['label'] for c in report['commands']] == labels
    assert report['fresh_old_corruption_rejections'] == report['fresh_literal_corruption_rejections'] == 8
    assert set(report['valid_routes']) == {'v1_49', 'v2_49'}
    assert report['full_target_parallel_products'] == 512 and all(report[key] is False for key in probe.FLAGS)
    bind_report(FAILED, report, before); verify_bindings(before)
    for path in (Path(__file__).resolve(), CONTROL, fixed.BASE_CTX, fixed.BASE_TYPES):
        sha = probe.support.digest(path); assert str(path) not in before or before[str(path)] == sha; before[str(path)] = sha
    original, _ = old_fixture(json.loads(BASE.read_text()), actual_empty_lut())
    assert json.loads((FAILED.parent / 'test-only-50.json').read_text()) == original
    before50 = next(iter(original['modules'].values()))
    after50 = next(iter(json.loads((FAILED.parent / 'v2_50-routed.json').read_text())['modules'].values()))
    assert 'BEL_STRENGTH' not in before50['cells'][NAME]['attributes']
    assert after50['cells'][NAME]['attributes']['BEL_STRENGTH'] == fixed.USER_STRENGTH
    try: probe.compare_route(before50, after50)
    except AssertionError as error:
        assert str(error) == 'Changed resource properties: ' + NAME
    else: raise AssertionError('The original failed resource-property gate no longer rejects')
    fixed.verify_strength_source()
    expected, _ = fixed.fixture(json.loads(BASE.read_text()), actual_empty_lut())
    diagnostic = probe.compare_route(next(iter(expected['modules'].values())), after50)
    assert diagnostic['footprint']['unchanged_physical_bel_assignments'] == diagnostic['logical_identity']['logical_board']['cells'] == 50
    assert diagnostic['comparison_only_port_annotations']['restored_empty_plain_LUT_outputs'] == 0
    for step in report['commands']:
        name = step['label']; text = Path(step['log']).read_text()
        expected_code = 125 if name in {'v1_empty_output', *probe.support.small.REASONS, *probe.NEW_REASONS} else 0
        assert step['returncode'] == step['expected_returncode'] == expected_code
        assert step['status'] == ('PASS_EXPECTED_REJECTION_ONLY' if expected_code else 'PASS_TOOL_EXECUTION_ONLY')
        if name == 'v1_empty_output': probe.check_rejection(step['returncode'], text)
        elif name in probe.support.small.REASONS:
            probe.reject_log(step['returncode'], text, 'RKNPU imported placement scan: ' + probe.support.small.REASONS[name])
        elif name in probe.NEW_REASONS: probe.reject_log(step['returncode'], text, probe.NEW_REASONS[name])
        elif name in ('v1_49', 'v2_49', 'v2_50'):
            cells, pairs = (50, 10) if name == 'v2_50' else (49, 9)
            probe.support.check_full_scan(text, cells, pairs, 8)
    return report


def verify_extension_evidence(before):
    parent, built = OLD_VERIFY(before)
    failure = verify_failed(before)
    assert failure['native_version'] == parent['native_version']
    child_build = json.loads(Path(failure['candidate_build_report']).read_text()); probe.verify_build(child_build)
    assert child_build['parent_executable'] == parent['executable'] and child_build['executable'] == failure['executable']
    return parent, built


def main():
    # Configure only this process's frozen procedure. Bindings include this
    # entrypoint, the old FAIL and exact fixture/native strength primary source.
    probe.support.verify_small_evidence = verify_extension_evidence
    probe.fixture = fixed.fixture
    probe.CONTROL = CONTROL
    probe.PASS = PASS
    probe.__doc__ = __doc__
    probe.main()


if __name__ == '__main__': main()
