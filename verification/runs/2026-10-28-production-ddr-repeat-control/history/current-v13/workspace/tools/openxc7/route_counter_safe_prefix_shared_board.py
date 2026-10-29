#!/usr/bin/env python3
"""Prepared full counter-safe HeAP checkpoint scan/route, not FPGA signoff.

Admit only this engine's completed full shared placement and fresh native
qualification. Retain the unchanged qualified v2 imported-checkpoint scanner,
normal router connectivity, complete cell/BEL/logical identity, clock fanout
and all 515-DSP/six-BRAM comparisons. Recheck the one-expression build and its
exact parent chain before sharing the same corrected-DSP routing base. Never
repack/replace the circuit, execute a comparison view or waive physical gates.
No standalone SHA256SUMS or FPGA access; preparation is not a routed result.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_prefix_shared_board as previous
import place_counter_safe_prefix_shared_board as placement
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_heap_route_control.py'
PLACED = placement.PLACED
ROUTED = 'ROUTED_FULL_C32K16_SHARED_PREFIX_COUNTER_SAFE_HEAP_V2_SCAN_AND_CONNECTIVITY_NOT_PHYSICAL_SIGNOFF'
COUNTS, CELLS = previous.COUNTS, previous.CELLS
PACKED_REPORT = previous.PACKED_REPORT
original = previous.original


def verify_counter_safe_binding(report):
    assert report['native_source_or_executable_changed'] is True
    assert report['only_HeAP_limit_expression_changed'] is True
    assert report['old_native_result_inherited'] is False
    path = Path(report['qualification']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('counter-safe-heap-qualification-')
    qualified = json.loads(path.read_text())
    placement.qualification.verify_metadata(qualified)
    assert report['executable'] == qualified['executable']
    assert report['qualified_parent_executable'] == qualified['qualified_parent_executable']
    assert report['counter_safe_engine_build_report'] == qualified['build_report']
    checks = report['counter_safe_attempt_limit_and_packed_checksum']
    assert checks == dict(actual_packed_checksum='0x0f489b2b', actual_full_packed_cells=523410,
                         actual_logged_maximum_attempts_per_cell=2147483646,
                         finite_counter_rejection_preserved=True, physical_fit_verified=False)


OLD_QUALIFICATION = "    assert Path(report['qualification']).resolve(strict=True) == shared.HEAP_QUALIFICATION.resolve(strict=True)\n"
NEW_QUALIFICATION = '    verify_counter_safe_binding(report)\n'
METADATA_SOURCE = source_shaped(inspect.getsource(previous.verify_placed_metadata),
                               ((OLD_QUALIFICATION, NEW_QUALIFICATION),))
METADATA_NAMESPACE = dict(previous.__dict__, PLACED=PLACED,
                          verify_counter_safe_binding=verify_counter_safe_binding)
exec(compile(METADATA_SOURCE, __file__ + ':same-full-target-placement-admission', 'exec'), METADATA_NAMESPACE)
verify_placed_metadata = METADATA_NAMESPACE['verify_placed_metadata']

# Normalize only this producer's own artifact paths; bind the actual report
# bytes. The old binder and both old placement enumerations remain untouched.
BIND_NAMESPACE = dict(previous.__dict__, PLACED=PLACED)
exec(compile(inspect.getsource(previous.bind_report), __file__ + ':unchanged-own-artifact-confinement', 'exec'), BIND_NAMESPACE)
bind_report = BIND_NAMESPACE['bind_report']

OLD_LOG = "    shared.check_heap_log(command['returncode'], log.read_text())\n"
NEW_LOG = """    placement.check_heap_log(command['returncode'], log.read_text())
    assert report['counter_safe_attempt_limit_and_packed_checksum'] == placement.full_log_checks(log.read_text())
"""
EVIDENCE_SOURCE = source_shaped(inspect.getsource(previous.verify_placed_native_evidence), ((OLD_LOG, NEW_LOG),))
EVIDENCE_NAMESPACE = dict(previous.__dict__, placement=placement)
exec(compile(EVIDENCE_SOURCE, __file__ + ':actual-full-log-limit-and-checksum', 'exec'), EVIDENCE_NAMESPACE)
verify_placed_native_evidence = EVIDENCE_NAMESPACE['verify_placed_native_evidence']


def placement_build(candidate, before):
    """Recheck the new object, then expose its unchanged parent for base equality."""
    path = Path(candidate['build_report']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('counter-safe-heap-engine-')
    assert str(path) in before and original.digest(path) == before[str(path)]
    built = json.loads(path.read_text())
    placement.qualification.build.verify_metadata(built)
    assert built['executable'] == candidate['executable']
    assert built['parent_executable'] == candidate['qualified_parent_executable']
    assert built['production_source_after'] == candidate['production_source_after']
    source = path.parent / 'common/place/placer_heap.cc'
    assert str(source) in before and original.digest(source) == before[str(source)] == built['generated_source_sha256']
    placement.qualification.build.candidate.verify_source_transition(
        placement.qualification.build.candidate.SOURCE.read_text(), source.read_text())
    parent_path = Path(built['parent_build_report']).resolve(strict=True)
    assert str(parent_path) in before and original.digest(parent_path) == before[str(parent_path)]
    parent = json.loads(parent_path.read_text())
    placement.qualification.build.parent_build.verify_build_metadata(parent)
    assert parent['executable'] == built['parent_executable']
    assert parent['production_source_after'] == built['production_source_after']
    # The original route procedure compares this parent's corrected-DSP base
    # with the independently qualified v2 scanner's base. Its engine never
    # executes placement while importing/routing the full literal checkpoint.
    return parent


OLD_BUILD = '        placing_build = placement_build(candidate,before)\n'
NEW_BUILD = OLD_BUILD + """        report.update(counter_safe_placement_engine_build_report=candidate['build_report'],
                      counter_safe_placement_only_HeAP_limit_expression_changed=True,
                      corrected_DSP_route_base_parent_chain_revalidated=True)
"""
REPLACEMENTS = (
    ('full-prefix-shared-heap-literal-empty-v2-scan-route-', 'full-prefix-shared-counter-safe-heap-literal-empty-v2-scan-route-'),
    (OLD_BUILD, NEW_BUILD),
)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 PLACED=PLACED, ROUTED=ROUTED, MAIN_SOURCE=MAIN_SOURCE,
                 verify_placed_metadata=verify_placed_metadata,
                 verify_placed_native_evidence=verify_placed_native_evidence,
                 bind_report=bind_report, placement_build=placement_build,
                 verify_placement_engine=placement.qualification.verify_qualification)
exec(compile(MAIN_SOURCE, __file__ + ':same-full-native-v2-scan-route-gates', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
