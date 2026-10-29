#!/usr/bin/env python3
"""Prepared corrected-mux full checkpoint route, not native or physical acceptance.

Require this engine's completed full pack, full placement and fresh original-
gates qualification. Use its actual bound census, checksum and selected DSP/
BRAM input. Keep the qualified v2 scanner/router, complete cell/BEL/logical
identity, clock fanout and all 515-DSP/six-BRAM feature gates. Revalidate both
isolated object transitions back to the unchanged corrected-DSP routing base.
Never repack or execute a comparison view. No physical/timing/electrical waiver,
old producer edit, checksum manifest, bitstream or FPGA/flash access occurs.
"""
import inspect
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_counter_safe_prefix_shared_board as previous
import place_recursive_mux_prefix_shared_board as placement
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_recursive_mux_full_route_control.py'
PLACED = placement.PLACED
ROUTED = 'ROUTED_FULL_C32K16_SHARED_PREFIX_RECURSIVE_MUX_V2_SCAN_AND_CONNECTIVITY_NOT_PHYSICAL_SIGNOFF'
original = previous.original
shared = previous.previous


def own_pack_path(report):
    path = Path(report['packed_report']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('full-prefix-shared-recursive-mux-native-pack-')
    return path


def own_pack(report):
    pack = json.loads(own_pack_path(report).read_text())
    placement.packer.validate_pack(pack)
    assert report['executable'] == pack['executable'], 'Different placement and full-pack engines'
    assert report['qualification'] == pack['encoder_qualification'], 'Different fresh native qualifications'
    return pack


def verify_recursive_binding(report):
    assert report['native_source_or_executable_changed'] is True
    assert report['only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent'] is True
    assert report['counter_safe_HeAP_parent_retained'] is True and report['old_native_result_inherited'] is False
    path = Path(report['qualification']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('recursive-mux-feedthrough-qualification-')
    qualified = json.loads(path.read_text())
    placement.qualification.verify_metadata(qualified)
    assert report['executable'] == qualified['executable']
    assert report['qualified_parent_executable'] == qualified['qualified_parent_executable']
    assert report['recursive_mux_engine_build_report'] == qualified['build_report']
    pack = own_pack(report)
    assert report['recursive_mux_attempt_limit_and_packed_checksum'] == packed_checks(pack)


def packed_checks(pack):
    """Metadata against actual pack log; never fabricate a native placement log."""
    placement.packer.validate_pack(pack)
    text = Path(pack['commands'][-1]['log']).read_text()
    checksums = re.findall(r'(?m)^Info: Checksum: (0x[0-9a-f]{8})$', text)
    assert len(checksums) == 1, 'Missing/ambiguous actual new full pack checksum'
    count = pack['native_census']['cells']
    limit = placement.previous.qualification.build.candidate.limit(count, 8)
    assert limit == 2147483646
    return dict(actual_packed_checksum=checksums[0], actual_full_packed_cells=count,
        actual_logged_maximum_attempts_per_cell=limit, finite_counter_rejection_preserved=True,
        old_fixed_packed_census_or_checksum_inherited=False, physical_fit_verified=False)


METADATA_REPLACEMENTS = (
    ("checks['primitive_counts'] == COUNTS", "checks['primitive_counts'] == own_pack(report)['native_census']['primitive_counts']"),
    ("checks['bound_cells'] == checks['unique_bel_slots'] == CELLS",
     "checks['bound_cells'] == checks['unique_bel_slots'] == own_pack(report)['native_census']['cells']"),
    (previous.OLD_QUALIFICATION, '    verify_recursive_binding(report)\n'),
)
METADATA_SOURCE = source_shaped(inspect.getsource(shared.verify_placed_metadata), METADATA_REPLACEMENTS)
METADATA_NAMESPACE = dict(shared.__dict__, PLACED=PLACED, own_pack=own_pack,
                          verify_recursive_binding=verify_recursive_binding)
exec(compile(METADATA_SOURCE, __file__ + ':unchanged-full-placement-gates-new-bound-profile', 'exec'), METADATA_NAMESPACE)
verify_placed_metadata = METADATA_NAMESPACE['verify_placed_metadata']

# Preserve every artifact confinement and duplicate/binding check; recognize
# only the new actual producer status, without changing frozen module globals.
BIND_NAMESPACE = dict(shared.__dict__, PLACED=PLACED,
                      shared=SimpleNamespace(PACKED=placement.packer.PACKED))
exec(compile(inspect.getsource(shared.bind_report), __file__ + ':same-own-artifact-confinement', 'exec'), BIND_NAMESPACE)
bind_report = BIND_NAMESPACE['bind_report']

EVIDENCE_REPLACEMENTS = (
    ("assert str(PACKED_REPORT) in report['source']", "assert str(own_pack_path(report)) in report['source']"),
    (previous.OLD_LOG, """    placement.check_heap_log(command['returncode'], log.read_text())
    assert report['recursive_mux_attempt_limit_and_packed_checksum'] == placement.full_log_checks(log.read_text(), pack)
"""),
)
EVIDENCE_SOURCE = source_shaped(inspect.getsource(shared.verify_placed_native_evidence), EVIDENCE_REPLACEMENTS)
EVIDENCE_NAMESPACE = dict(shared.__dict__, own_pack=own_pack, own_pack_path=own_pack_path, placement=placement)
exec(compile(EVIDENCE_SOURCE, __file__ + ':actual-full-placement-log-required', 'exec'), EVIDENCE_NAMESPACE)
verify_placed_native_evidence = EVIDENCE_NAMESPACE['verify_placed_native_evidence']


def shared_packed_path(placed, before):
    path = Path(own_pack(placed)['packed_design']).resolve(strict=True)
    assert path.is_relative_to(own_pack_path(placed).parent) and str(path) in before
    assert original.digest(path) == before[str(path)], 'Changed actual new full packed graph'
    return path


SELECTED_SOURCE = source_shaped(inspect.getsource(shared.selected_inputs),
    (('PACKED_REPORT.parent', 'own_pack_path(placed).parent'),))
SELECTED_NAMESPACE = dict(shared.__dict__, own_pack_path=own_pack_path)
exec(compile(SELECTED_SOURCE, __file__ + ':same-complete-own-DSP-BRAM-selection', 'exec'), SELECTED_NAMESPACE)
selected_inputs = SELECTED_NAMESPACE['selected_inputs']


def placement_build(candidate, before):
    path = Path(candidate['build_report']).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('recursive-mux-feedthrough-native-io-engine-')
    assert str(path) in before and original.digest(path) == before[str(path)]
    built = json.loads(path.read_text())
    build = placement.qualification.candidate
    build.verify_metadata(built)
    assert built['executable'] == candidate['executable']
    assert built['parent_executable'] == candidate['qualified_parent_executable']
    assert built['production_source_after'] == candidate['production_source_after']
    source = path.parent / 'himbaechel/uarch/xilinx/pack.cc'
    assert str(source) in before and original.digest(source) == before[str(source)] == built['generated_source_sha256']
    build.verify_source_transition(build.SOURCE.read_text(), source.read_text())
    counter_path = build.PARENT.resolve(strict=True)
    assert str(counter_path) in before and original.digest(counter_path) == before[str(counter_path)]
    counter = json.loads(counter_path.read_text())
    build.heap.verify_metadata(counter)
    assert counter['executable'] == built['parent_executable']
    parent_link = next(c for c in counter['commands'] if c['label'] == 'link_counter_safe_heap')
    link = next(c for c in built['commands'] if c['label'] == 'link_recursive_mux_feedthrough')
    assert link['argv'] == build.link_argv(parent_link['argv'], Path(built['executable']['path']),
                                         {build.OBJECT: path.parent / 'pack.cc.o'})
    assert link['cwd'] == parent_link['cwd']
    # Both changed objects are placement/packing-only; the independently
    # qualified v2 scanner/router imports the literal new placed checkpoint.
    return previous.placement_build(dict(build_report=str(counter_path), executable=counter['executable'],
        qualified_parent_executable=counter['parent_executable'],
        production_source_after=counter['production_source_after']), before)


REPLACEMENTS = (
    ('full-prefix-shared-counter-safe-heap-literal-empty-v2-scan-route-',
     'full-prefix-shared-recursive-mux-heap-literal-empty-v2-scan-route-'),
    ("counter_safe_placement_engine_build_report=candidate['build_report'],\n                      counter_safe_placement_only_HeAP_limit_expression_changed=True,",
     "recursive_mux_placement_engine_build_report=candidate['build_report'],\n                      recursive_mux_and_counter_safe_placement_parent_chain_revalidated=True,"),
)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
    PLACED=PLACED, ROUTED=ROUTED, MAIN_SOURCE=MAIN_SOURCE,
    verify_placed_metadata=verify_placed_metadata, verify_placed_native_evidence=verify_placed_native_evidence,
    bind_report=bind_report, placement_build=placement_build,
    verify_placement_engine=placement.qualification.verify_qualification,
    verify_packed_metadata=placement.packer.validate_pack,
    shared_packed_path=shared_packed_path, selected_inputs=selected_inputs)
exec(compile(MAIN_SOURCE, __file__ + ':same-full-v2-scan-route-feature-and-identity-gates', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
