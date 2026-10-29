"""Read-only admission of the completed corrected engine and full pack proof.

Revalidate content bindings, exact two-object/source changes, original native
legality probes, complete DSP census and actual small FASM comparisons. The
separate full packed proof remains a logical comparison, not placement
transfer, full routing or physical signoff. Existing accepted files stay intact.
"""
import json
from pathlib import Path
import re

from pack_prefix_board import ROOT, digest
from place_prefix_board import bind_report, verify_bindings
from qualify_dsp_constant_candidate import QUALIFIED, COMMANDS, verify_build_metadata, check_native_log
from qualify_static_exp_candidate import LABELS, probe_argv, check_log, validate_placed
from build_dsp_constant_candidate import checked_source, link_argv, UPSTREAM_DIGESTS
from check_full_native_features import full_inventory, routed_primitives
from check_corrected_dsp_features import verify_corrected_packed, compare_corrected_dsp
from check_prefix_native_features import compare_bram
from probe_prefix_native_config import SELECTED, parse_native_features, verify_clock_admission, verify_fixture

NATIVE = ROOT / 'build/openxc7/dsp-constant-qualification-1791414657664905509/report.json'
IDENTITY = ROOT / 'build/openxc7/corrected-full-pack-identity-1791415739115873319/report.json'
IDENTIFIED = 'PASS_FULL_PACKED_LOGICAL_IDENTITY_EXCEPT_EXACT_DSP_TILE_CONSTANT_REPRESENTATION_NOT_PLACEMENT_TRANSFER_OR_SIGNOFF'


def verify_metadata(q, identity):
    assert q['status'] == QUALIFIED and q['stage'] == 'complete' and q['finished_utc']
    assert q['part'] == 'xc7k480tffg1156-2' and q['full_target_parallel_products'] == 512
    assert (q['native_positive_placements'], q['lut_output_comparisons'], q['full_packed_DSPs_compared'],
            q['full_packed_extra_tile_only_ties_compared']) == (3, 1024, 515, 4120)
    assert q['illegal_pair_rejected_before_postPlace'] is True
    assert [step['label'] for step in q['commands']] == COMMANDS
    for step in q['commands']:
        expected = 125 if step['label'] == 'invalid-forced' else 0
        assert step['returncode'] == step['expected_returncode'] == expected
        assert step['status'] == ('PASS_EXPECTED_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY')
    for key in ('full_board_native_placement_executed', 'full_board_native_routing_executed', 'full_board_native_FASM_executed',
                'full_circuit_equivalence_claimed', 'full_board_numerical_acceptance', 'expected_vectors_used_for_execution',
                'old_full_placement_reuse_admitted', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
                'drc_signoff', 'bitstream_emitted', 'hardware_programmed', 'ordinary_constant_net_routing_verified',
                'USE_MULT_physical_default_verified'):
        assert q[key] is False, 'Unsupported corrected-engine acceptance: ' + key
    assert identity['status'] == IDENTIFIED and identity['finished_utc'] and identity['full_parallel_products'] == 512
    result = identity['comparison']
    assert (result['cells_compared'], result['unchanged_non_DSP_cell_records'], result['changed_DSP_records'],
            result['source_defined_tile_pin_disconnections_compared']) == (538118, 537603, 515, 4120)
    for key in ('complete_named_wire_table_byte_identical', 'public_ports_and_packing_settings_byte_identical',
                'ordinary_pin_wire_ids_unchanged', 'literal_DSP_parameters_and_non_tie_attributes_unchanged'):
        assert result[key] is True
    assert result['disconnected_pin_normalization_used'] is result['comparison_view_executed'] is False
    for key in ('full_native_qualification_acceptance_claimed', 'old_full_placement_transfer_admitted',
                'native_placement_executed', 'native_routing_executed', 'numerical_acceptance', 'physical_fit_verified',
                'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert identity[key] is False, 'Unsupported packed-identity acceptance: ' + key
    assert q['production_source_before'] == q['production_source_after'] == identity['production_source_after']


def verify_corrected_evidence(native_path=NATIVE, identity_path=IDENTITY):
    native_path, identity_path = Path(native_path).resolve(strict=True), Path(identity_path).resolve(strict=True)
    q, identity = json.loads(native_path.read_text()), json.loads(identity_path.read_text())
    verify_metadata(q, identity)
    before = {}
    bind_report(native_path, q, before)
    bind_report(identity_path, identity, before)
    verify_bindings(before)
    built_path = Path(q['candidate_build_report'])
    assert str(built_path) in before
    built = json.loads(built_path.read_text())
    verify_build_metadata(built)
    assert built['executable'] == q['executable'] and digest(q['executable']['path']) == q['executable']['sha256']
    for name, sha in {**built['inputs'], **built['artifacts']}.items():
        assert str(Path(name).resolve()) in before and before[str(Path(name).resolve())] == sha
    parent = json.loads(Path(built['parent_build_report']).read_text())
    original_link = next(step['argv'] for step in parent['commands'] if step['label'] == 'link_precision_candidate')
    current_link = next(step['argv'] for step in built['commands'] if step['label'] == 'link_DSP_constant_candidate')
    replacements = {}
    for filename in UPSTREAM_DIGESTS:
        objects = [Path(item) for item in original_link if item.endswith('/uarch/xilinx/' + filename + '.o')]
        assert len(objects) == 1
        replacements[objects[0]] = built_path.parent / (filename + '.o')
        checked_source(filename, (built_path.parent / ('original-' + filename)).read_text(),
                       (built_path.parent / 'himbaechel/uarch/xilinx' / filename).read_text())
    assert current_link == link_argv(original_link, q['executable']['path'], replacements), 'Unadmitted native object/link change'
    selected = json.loads(SELECTED.read_text())
    for step in q['commands']:
        log = Path(step['log']).read_text()
        if step['label'] in LABELS:
            check_log(step['returncode'], log, step['expected_returncode'])
            xdc = next(item.removeprefix('xdc=') for item in step['argv'] if item.startswith('xdc='))
            assert step['argv'] == probe_argv(q['executable']['path'], step['fixture'], xdc, step['output'])
            if step['label'] == 'invalid-forced': assert not Path(step['output']).exists()
            else:
                result = validate_placed(step['output'], 47 if step['label'] == 'counter' else 49,
                                         None if step['label'] == 'counter' else step['fixture'])
                assert result == step['placement_checks']
        elif step['label'] in ('full_native_pack', 'native_clock_admission'):
            verify_clock_admission(log, q['constraint_translation'])
            assert 'Program finished normally.' in log
        elif step['label'] == 'small_native_PNR_FASM': check_native_log(log)
        else:
            assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', log), 'Changed successful control log'
    full = native_path.parent / 'full-packed.json'
    assert identity['corrected_pack_path'] == str(full)
    assert before[str(full)] == q['artifacts'][str(full.relative_to(ROOT))]
    packed = routed_primitives(full, selected)
    assert full_inventory(selected, packed) == q['full_packed_kernel_inventory']
    for name, cell in selected.items():
        if cell['type'] == 'DSP48E1': verify_corrected_packed(cell, packed[name])
    origins = q['control_origins']
    fixture = ROOT / q['execution_input']
    verify_fixture(json.loads(fixture.read_text()), origins, selected)
    features, repeated = parse_native_features((native_path.parent / 'control.fasm').read_text())
    assert len(features) == q['native_FASM_features'] and repeated == q['native_FASM_repeated_idempotent_STEPDOWN_lines']
    placements = json.loads((native_path.parent / 'placement.json').read_text())
    routed = next(iter(json.loads((native_path.parent / 'routed.json').read_text())['modules'].values()))
    dsps = {name: compare_corrected_dsp(features, placements[name], selected[source], routed['cells'][name])
            for name, source in origins.items() if selected[source]['type'] == 'DSP48E1'}
    brams = {name: compare_bram(features, placements[name], selected[source])
             for name, source in origins.items() if selected[source]['type'] == 'RAMB36E1'}
    assert dsps == q['DSP_feature_comparison'] and brams == q['BRAM_feature_comparison']
    verify_bindings(before)
    return q, before
