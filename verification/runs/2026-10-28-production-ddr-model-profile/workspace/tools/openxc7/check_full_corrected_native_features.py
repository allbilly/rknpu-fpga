"""Prepared full-target feature comparator for the isolated corrected encoder.

Reuse exact native readers and the strict 515-DSP/six-BRAM census, but retain
the corrected encoder's separately evidenced 39-tie DSP policy. The old
31-tie gate is unchanged. A caller must independently admit a completed
corrected placement/route and prove all BELs and logical wiring unchanged.
This comparator does not admit placement transfer, timing, DRC or a bitstream.
"""
from pathlib import Path

from check_full_native_features import full_inventory, routed_primitives, placed_primitives
from check_corrected_dsp_features import compare_corrected_dsp
from check_prefix_native_features import compare_bram
from probe_prefix_native_config import parse_native_features
from pack_prefix_board import DATABASE, CONSTIDS
from himbaechel_site_bels import SiteBELMap


def compare_selected(features, placements, selected, packed, global_label):
    """Generic comparison only; small saved controls cannot pass the census."""
    assert set(placements) == set(selected) == set(packed), 'Incomplete/extra selected primitive membership'
    bels = [placements[name]['nextpnr_bel'] for name in selected]
    assert len(set(bels)) == len(bels), 'Aliased selected DSP/BRAM BEL'
    checks = {}
    for name, original in selected.items():
        placement, native = placements[name], packed[name]
        assert global_label(placement['nextpnr_bel']) == native['attributes']['NEXTPNR_BEL'], 'Native placement differs from routed BEL'
        if original['type'] == 'DSP48E1':
            checks[name] = compare_corrected_dsp(features, placement, original, native)
        else:
            assert original['type'] == 'RAMB36E1' and native['type'] == 'RAMB36E1_RAMB36E1', 'Unmodeled selected primitive'
            checks[name] = compare_bram(features, placement, original)
    return checks


def verify_full_features(fasm_path, placement_path, routed_path, selected, expected_groups):
    packed = routed_primitives(routed_path, selected)
    groups = full_inventory(selected, packed)
    assert groups == expected_groups, 'Changed full kernel DSP grouping'
    placed = placed_primitives(placement_path, selected)
    features, repeated = parse_native_features(Path(fasm_path).read_text())
    with SiteBELMap(DATABASE, CONSTIDS) as database:
        checks = compare_selected(features, placed, selected, packed, database.global_label)
    dsp = [checks[name] for name, original in selected.items() if original['type'] == 'DSP48E1']
    assert len(dsp) == 515 and all(check['dedicated_constant_pins_compared'] == 39 for check in dsp)
    assert sum(check['extra_tile_only_pins_compared'] for check in dsp) == 4120
    return dict(status='COMPARED_ALL_515_CORRECTED_DSP_AND_6_BRAM_SOURCE_DEFINED_FEATURES_NOT_ROUTE_ADMISSION_OR_SIGNOFF',
        kernel_dsps=groups, selected_primitives_compared=len(checks), primitive_checks=checks,
        corrected_DSP_tile_pins_compared=4120, native_FASM_features=len(features),
        repeated_idempotent_STEPDOWN_lines=repeated, old_31_tie_gate_modified=False,
        full_route_source_and_circuit_identity_admitted=False, placement_transfer_admitted=False,
        USE_MULT_physical_default_verified=False, ordinary_constant_net_routing_verified=False,
        observable_BRAM_startup_reset_independence_proved=False, numerical_acceptance=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)
