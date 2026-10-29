#!/usr/bin/env python3
"""Prepared reviewed-full-checkpoint routing; no placement or FPGA acceptance.

Require a completed independent all-cell/BEL/DSP/clock review, its unchanged
zero-code native producer and source-bound analytic-subset audit. Preserve the
original failed wrapper rather than relabel its commands. Execute only the
literal native checkpoint with all existing qualified v2 scanner/router,
identity, clock, 515-DSP/six-BRAM and feature guards. No repacking, comparison
view execution, timing/electrical/DRC waiver, bitstream or FPGA/flash access.
No standalone checksum manifest is written.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_recursive_mux_prefix_shared_board as previous
import review_valid_pack_recursive_mux_completed_placement as prepared_review
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_reviewed_recursive_mux_full_route_control.py'
review = prepared_review.previous
PLACED = review.REVIEWED
ROUTED = 'ROUTED_REVIEWED_FULL_C32K16_RECURSIVE_MUX_V2_SCAN_AND_CONNECTIVITY_NOT_PHYSICAL_SIGNOFF'
original = previous.original


def producer_path(report, field, prefix):
    path = Path(report[field]).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith(prefix), 'Wrong actual producer'
    assert report['source'][str(path)] == original.digest(path), 'Changed actual producer report'
    return path


def require_contained_bindings(report, parent, path):
    """Every original source/artifact must already be in the review binding."""
    seen = set()
    for manifest, own in ((parent['source'], False), (parent['artifacts'], True)):
        for name, sha in manifest.items():
            item = (ROOT / name).resolve(strict=True)
            assert re.fullmatch('[0-9a-f]{64}', sha)
            if own:
                assert item.is_relative_to(path.parent), 'Artifact outside actual producer'
                assert str(item) not in seen, 'Duplicate normalized producer artifact'
                seen.add(str(item))
            assert report['source'][str(item)] == sha, 'Original evidence missing from reviewed chain'


def original_execution(report):
    path = producer_path(report, 'native_execution_report', 'full-prefix-shared-recursive-mux-heap-place-')
    native = json.loads(path.read_text())
    command = review.verify_parent_metadata(native)
    assert report['original_native_commands'] == native['commands'], 'Changed original command history'
    assert not Path(f'/proc/{command["pid"]}').exists(), 'Original native worker still live'
    assert not Path(f'/proc/{native["supervisor_pid"]}').exists(), 'Original producer still live'
    require_contained_bindings(report, native, path)
    for key in ('executable', 'native_version', 'packed_report', 'prepared_report', 'execution_input',
                'constraint_translation', 'production_source_before'):
        assert report[key] == native[key], 'Changed original execution identity: ' + key
    return path, native


def own_pack(report):
    return previous.own_pack(original_execution(report)[1])


def qualification_path(report):
    return Path(original_execution(report)[1]['qualification'])


def verify_review_metadata(report):
    assert report['status'] == PLACED and report['stage'] == 'complete' and report['finished_utc']
    assert all(report[k] is True for k in ('original_full_output_guards_retained',
        'full_placed_cell_membership_verified', 'source_proven_analytic_subset_contract_used'))
    assert all(report[k] is False for k in ('fresh_native_placement_executed', 'original_failed_report_relabelled',
        'original_native_output_modified', 'hardware_execution_input_changed', 'native_routing_executed',
        'numerical_netlist_acceptance', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
        'drc_signoff', 'bitstream_emitted', 'hardware_programmed'))
    assert [c['label'] for c in report['commands']] == ['software_controls', 'generated_check']
    assert all(c['status'] == 'PASS_SOFTWARE_CONTROL_ONLY' and c['returncode'] == 0
               and c['timeout_seconds'] == 120 and c['cwd'] == str(ROOT) for c in report['commands'])
    assert report['commands'][0]['argv'] == [report['commands'][0]['argv'][0], '-B', '-W', 'error', '-m',
        'unittest', 'discover', '-s', 'tests/cmac', '-p', prepared_review.CONTROL.name, '-v']
    python = Path(report['commands'][0]['argv'][0]).resolve(strict=True)
    assert report['source'][str(python)] == original.digest(python)
    assert report['commands'][1]['argv'] == ['make', 'generated-check']
    for path in (Path(prepared_review.__file__).resolve(), prepared_review.CONTROL, Path(review.__file__).resolve()):
        assert report['source'][str(path)] == original.digest(path), 'Changed reviewed admission/full-output guards'


def scope_report(report, native, path):
    sp = producer_path(report, 'source_scope_report', 'recursive-mux-analytic-scope-typed-')
    scope = json.loads(sp.read_text())
    review.verify_scope_metadata(scope, native, path)
    require_contained_bindings(report, scope, sp)
    source = Path(scope['compiled_HeAP_source']).resolve(strict=True)
    assert report['source'][str(source)] == original.digest(source)
    assert review.scope_audit.previous.source_contract(source.read_text()) == scope['native_source_scope_contract']
    return scope


def verify_native_lineage(report):
    path, native = original_execution(report)
    qualified_path = qualification_path(report).resolve(strict=True)
    assert qualified_path.is_relative_to(ROOT / 'build/openxc7') and qualified_path.name == 'report.json'
    assert qualified_path.parent.name.startswith('recursive-mux-feedthrough-qualification-')
    qualified = json.loads(qualified_path.read_text())
    previous.placement.qualification.verify_metadata(qualified)
    assert native['executable'] == qualified['executable']
    assert native['qualified_parent_executable'] == qualified['qualified_parent_executable']
    assert native['recursive_mux_engine_build_report'] == qualified['build_report']
    scope = scope_report(report, native, path)
    log = Path(native['commands'][-1]['log']).resolve(strict=True)
    assert log.is_relative_to(path.parent)
    checks = review.fresh_log_checks(log.read_text(), own_pack(report), scope)
    assert report['reviewed_native_log_characterization'] == checks


# Preserve all original target/count/unique-BEL/DSP/tie/clock/source gates.
# Only original execution facts come from the explicitly preserved producer,
# rather than pretending the two fresh review commands ran native placement.
METADATA_REPLACEMENTS = (
    ("    assert report['status'] == PLACED and report['stage'] == 'complete' and report['finished_utc']\n",
     "    verify_review_metadata(report)\n    native = original_execution(report)[1]\n"),
    ("all(report[k] is False for k in ('native_routing_executed'", "all(native[k] is False for k in ('native_routing_executed'"),
    ("all(report[k] is True for k in ('native_packing_executed'", "all(native[k] is True for k in ('native_packing_executed'"),
    ("    assert [c['label'] for c in report['commands']] == labels\n",
     "    assert [c['label'] for c in report['original_native_commands']] == labels\n"),
    ("    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0 for c in report['commands'])\n",
     "    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0 for c in report['original_native_commands'])\n"),
    ('    verify_recursive_binding(report)\n', '    verify_native_lineage(report)\n'),
    ("report['host_native_timeout_seconds']", "native['host_native_timeout_seconds']"),
)
METADATA_SOURCE = source_shaped(previous.METADATA_SOURCE, METADATA_REPLACEMENTS)
METADATA_NAMESPACE = dict(previous.METADATA_NAMESPACE, PLACED=PLACED, own_pack=own_pack,
    original_execution=original_execution, verify_review_metadata=verify_review_metadata,
    verify_native_lineage=verify_native_lineage)
exec(compile(METADATA_SOURCE, __file__ + ':preserved-all-full-placement-guards-separated-history', 'exec'), METADATA_NAMESPACE)
verify_placed_metadata = METADATA_NAMESPACE['verify_placed_metadata']

BIND_NAMESPACE = dict(previous.BIND_NAMESPACE, PLACED=PLACED)
exec(compile(inspect.getsource(previous.shared.bind_report), __file__ + ':same-own-artifact-confinement', 'exec'), BIND_NAMESPACE)
bind_report = BIND_NAMESPACE['bind_report']


def verify_review_snapshots(report, path):
    assert path.parent.name.startswith('full-recursive-mux-valid-pack-completed-placement-review-')
    expected = {'executed_source.py': Path(prepared_review.__file__).read_text(),
                'executed_prepared_main.py': prepared_review.MAIN_SOURCE,
                'executed_post_native_checks.py': review.POST_SOURCE}
    for name, text in expected.items():
        item = path.parent / name
        assert report['artifacts'][str(item)] == original.digest(item) and item.read_text() == text
    for command in report['commands']:
        log = Path(command['log']).resolve(strict=True)
        assert log.is_relative_to(path.parent) and report['artifacts'][str(log)] == original.digest(log)


def verify_placed_native_evidence(report, path):
    verify_review_snapshots(report, path)
    owner, native = original_execution(report)
    pack = own_pack(report)
    assert str(previous.own_pack_path(native)) in report['source']
    command = native['commands'][-1]
    previous.shared.shared.verify_full_argv(command['argv'])
    assert command['argv'][0] == report['executable']['path']
    output = (ROOT / report['placed_design']).resolve(strict=True)
    log = Path(command['log']).resolve(strict=True)
    assert output == owner.parent / 'placed.json' and log.is_relative_to(owner.parent)
    assert report['source'][str(output)] == original.digest(output)
    assert report['source'][str(log)] == original.digest(log)
    assert command['argv'][command['argv'].index('--write') + 1] == str(output)
    assert command['argv'][command['argv'].index('--json') + 1] == pack['execution_input']
    scope = scope_report(report, native, owner)
    previous.placement.NAMESPACE['verify_clock_admission'](log.read_text(), report['constraint_translation'])
    assert report['reviewed_native_log_characterization'] == review.fresh_log_checks(log.read_text(), pack, scope)


def shared_packed_path(placed, before):
    return previous.shared_packed_path(original_execution(placed)[1], before)


def selected_inputs(placed, before):
    native = original_execution(placed)[1]
    return previous.selected_inputs(dict(native, placement_checks=placed['placement_checks']), before)


REPLACEMENTS = (
    ('full-prefix-shared-recursive-mux-heap-literal-empty-v2-scan-route-',
     'full-reviewed-recursive-mux-literal-empty-v2-scan-route-'),
    ("assert design_path.is_relative_to(placed_path.parent) and str(design_path) in before",
     "assert design_path == original_execution(placed)[0].parent / 'placed.json' and str(design_path) in before"),
    ("        qualification = Path(placed['qualification']); candidate, before = verify_placement_engine(qualification)\n",
     """        qualification = qualification_path(placed); candidate, before = verify_placement_engine(qualification)
        report.update(independent_full_placement_review_report=str(placed_path),
            original_failed_native_execution_report=placed['native_execution_report'],
            original_failed_native_report_relabelled=False, original_native_output_modified=False,
            analytic_subset_marker_used_as_full_census=False)
"""),
)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
    PLACED=PLACED, ROUTED=ROUTED, MAIN_SOURCE=MAIN_SOURCE,
    verify_placed_metadata=verify_placed_metadata, verify_placed_native_evidence=verify_placed_native_evidence,
    qualification_path=qualification_path, original_execution=original_execution, bind_report=bind_report,
    shared_packed_path=shared_packed_path, selected_inputs=selected_inputs)
exec(compile(MAIN_SOURCE, __file__ + ':unchanged-full-native-v2-route-and-feature-gates', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
