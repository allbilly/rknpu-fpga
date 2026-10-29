#!/usr/bin/env python3
"""Prepared shared-prefix full C32/K16 checkpoint scan/route, not signoff.

Admit this candidate's own completed placement and measured packing, never
the original larger graph or a diagnostic LUT-group assignment. Derive the
unchanged qualified HeAP/v2 route procedure with reversible admission/path
changes only. Keep native all-BEL/pair/carry scans, router connectivity, exact
whole logical/physical identity and all 515-DSP/six-BRAM feature checks.
No numerical, timing/electrical/DRC, bitstream or programming acceptance follows.
No standalone SHA256SUMS file or altered original/live helper is used.
"""
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_native_heap_board as previous
import place_prefix_shared_board as shared
from audit_empty_output_pairs import source_shaped
from pack_prefix_shared_board import PREPARED

ROOT = shared.ROOT
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_route_control.py'
PACKED_REPORT = ROOT / 'build/openxc7/full-prefix-shared-native-pack-1791474646490498829/report.json'
PLACED = 'PLACED_FULL_C32K16_SHARED_PREFIX_NATIVE_HEAP_NORMAL_REFINEMENT_NOT_ROUTED_FIT_OR_SIGNOFF'
ROUTED = 'ROUTED_FULL_C32K16_SHARED_PREFIX_HEAP_V2_SCAN_AND_CONNECTIVITY_NOT_PHYSICAL_SIGNOFF'
COUNTS = dict(BUFGCTRL=1, CARRY4=8630, DSP48E1_DSP48E1=515, IOB33_INBUF_EN=2,
    IOB33_OUTBUF=3, PAD=5, PSEUDO_GND=1, PSEUDO_VCC=1, RAMB36E1_RAMB36E1=6,
    SELMUX2_1=8647, SLICE_FFX=17519, SLICE_LUTX=488080)
CELLS = sum(COUNTS.values())
original = previous.previous.original


def own_pack(report):
    path = Path(report['packed_report']).resolve(strict=True)
    assert path == PACKED_REPORT.resolve(strict=True), 'Different shared packed graph'
    pack = json.loads(path.read_text())
    shared.validate_pack(pack)
    assert pack['native_census']['primitive_counts'] == COUNTS
    assert pack['native_census']['cells'] == CELLS == 523410
    return pack


def verify_placed_metadata(report):
    # Reject incomplete placement before execution output or tool launch.
    assert report['status'] == PLACED and report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['retained_cmac_dsps'],
            report['retained_shell_dsps'], report['intended_part'], report['intended_clock_period_ns'], report['seed']) == (
                32, 16, 512, 512, 3, 'xc7k480tffg1156-2', 20, 3588)
    assert all(report[k] is False for k in ('native_routing_executed', 'packed_context_reloaded',
        'old_placement_reused', 'input_group_assignment_used', 'numerical_netlist_acceptance',
        'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff',
        'bitstream_emitted', 'hardware_programmed'))
    assert all(report[k] is True for k in ('native_packing_executed', 'native_placement_executed',
                                         'original_prepared_input_repacked'))
    labels = ['software_controls', 'native_heap_guard_controls', 'generated_check', 'version', 'native_place']
    assert [c['label'] for c in report['commands']] == labels
    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0 for c in report['commands'])
    assert (report['DSP_configurations_compared'], report['extra_tile_only_ties_compared']) == (515, 4120)
    checks = report['placement_checks']
    assert checks['primitive_counts'] == COUNTS
    assert checks['bound_cells'] == checks['unique_bel_slots'] == CELLS
    assert len(checks['retained_kernel_dsps']) == 16 and set(checks['retained_kernel_dsps'].values()) == {32}
    assert checks['full_placed_numerical_acceptance'] is False
    assert checks['native_legality_scope'] == 'QUALIFIED_HEAP_NORMAL_REFINEMENT_FINAL_BEL_VALIDITY_CHECK_NOT_COMPLETE_ARCHITECTURE_SIGNOFF'
    pack = own_pack(report)
    assert checks['retained_kernel_dsps'] == report['retained_kernel_dsps'] == pack['retained_kernel_dsps']
    assert report['production_source_before'] == report['production_source_after'] == pack['production_source_after']
    assert report['constraint_translation'] == pack['constraint_translation']
    assert report['constraint_translation']['target_period_ns'] == 20.0
    assert report['constraint_translation']['signoff_constraint_profile'] is False
    assert Path(report['qualification']).resolve(strict=True) == shared.HEAP_QUALIFICATION.resolve(strict=True)
    assert report['host_native_timeout_seconds'] == shared.NATIVE_TIMEOUT == 43200
    assert report['prepared_report'] == pack['prepared_report'] and report['execution_input'] == pack['execution_input']


def bind_report(path, report, before):
    """Normalize only this producer's absolute artifact paths for binding.

    The original relative-path binder and all its confinement/hash checks
    remain unchanged. This in-memory metadata view is never saved or executed;
    the original actual report bytes are what its report digest binds.
    """
    if report['status'] not in (PLACED, shared.PACKED, PREPARED):
        return original.bind_report(path, report, before)
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    artifacts = {}
    for name, sha in report['artifacts'].items():
        artifact = (ROOT / name).resolve(strict=True)
        assert artifact.is_relative_to(path.parent), 'Artifact outside actual shared attempt'
        relative = str(artifact.relative_to(ROOT))
        assert relative not in artifacts, 'Duplicate normalized artifact path'
        artifacts[relative] = sha
    original.bind_report(path, dict(report, artifacts=artifacts), before)


def verify_placed_native_evidence(report, path):
    pack = own_pack(report)
    assert str(PACKED_REPORT) in report['source']
    command = report['commands'][-1]
    shared.verify_full_argv(command['argv'])
    assert command['argv'][0] == report['executable']['path']
    output = Path(report['placed_design']).resolve(strict=True)
    log = Path(command['log']).resolve(strict=True)
    assert output.is_relative_to(path.parent) and log.is_relative_to(path.parent)
    assert command['argv'][command['argv'].index('--write') + 1] == str(output)
    assert command['argv'][command['argv'].index('--json') + 1] == pack['execution_input']
    shared.check_heap_log(command['returncode'], log.read_text())


def shared_packed_path(placed, before):
    path = Path(own_pack(placed)['packed_design']).resolve(strict=True)
    assert path.is_relative_to(PACKED_REPORT.parent) and str(path) in before
    assert original.digest(path) == before[str(path)], 'Changed measured shared packed graph'
    return path


def selected_inputs(placed, before):
    path = PACKED_REPORT.parent / 'actual-DSP-BRAM-input.json'
    assert str(path) in before and original.digest(path) == before[str(path)]
    selected = json.loads(path.read_text())
    assert len(selected) == 521 and Counter(c['type'] for c in selected.values()) == {'DSP48E1': 515, 'RAMB36E1': 6}
    groups = Counter(n.split('.')[0] for n, c in selected.items() if c['type'] == 'DSP48E1' and '.' in n)
    assert dict(groups) == placed['placement_checks']['retained_kernel_dsps']
    return selected


OLD_ADMISSION = "    assert placed_path.is_relative_to(ROOT / 'build/openxc7')\n"
NEW_ADMISSION = OLD_ADMISSION + """    verify_placed_metadata(json.loads(placed_path.read_text()))
    resource.setrlimit(resource.RLIMIT_AS, (12 * 1024**3, 12 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
"""
OLD_MODULE = "        verify_placed_module(module, placed['placement_checks']['primitive_counts'], placed['placement_checks']['retained_kernel_dsps'])\n"
NEW_MODULE = OLD_MODULE + """        assert set(module['cells']) == shared.packed_names(shared_packed_path(placed, before)), 'Changed full shared placed membership'
"""
REPLACEMENTS = (
    ('full-prefix-heap-literal-empty-v2-scan-route-', 'full-prefix-shared-heap-literal-empty-v2-scan-route-'),
    (OLD_ADMISSION, NEW_ADMISSION),
    ("qualification = Path(placed['qualified_engine_report'])", "qualification = Path(placed['qualification'])"),
    (OLD_MODULE, NEW_MODULE),
    ('        selected = json.loads(checker.checkpoint.SELECTED.read_text())', '        selected = selected_inputs(placed, before)'),
)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
    ROUTED=ROUTED, MAIN_SOURCE=MAIN_SOURCE, verify_placed_metadata=verify_placed_metadata,
    verify_placed_native_evidence=verify_placed_native_evidence, bind_report=bind_report,
    verify_packed_metadata=shared.validate_pack, verify_prepared_metadata=shared.validate_prepared,
    shared=shared, shared_packed_path=shared_packed_path, selected_inputs=selected_inputs)
exec(compile(MAIN_SOURCE, __file__ + ':same-full-HeAP-v2-scan-and-route-gates', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
