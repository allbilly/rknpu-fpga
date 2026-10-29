"""Actual full-pack empty LUT output plus small/synthetic comparison controls."""
from copy import deepcopy
import json
import mmap
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from compare_full_imported_export import comparison_port_source, full_export_view
from compare_imported_carry_export import carry_export_view
from audit_corrected_full_pack_identity import cell_value
from probe_imported_placement_checker import NATIVE, checkpoint


def actual_cell():
    path = NATIVE.parent / 'full-packed.json'
    marker = b'        "rk_mapped_cell_85079$split$xorcy0": {'
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        start = data.find(marker); assert start >= 0
        end = data.find(b'\n        }', start) + len(b'\n        }'); assert end > start
        return cell_value(data[start:end])


def fixture():
    before = {'cells': {'actual-disconnected-XORCY-LUT2': actual_cell()}, 'ports': {}}
    after = deepcopy(before)
    del after['cells']['actual-disconnected-XORCY-LUT2']['connections']['O6']
    del after['cells']['actual-disconnected-XORCY-LUT2']['port_directions']['O6']
    return before, after


class FullImportedExport(unittest.TestCase):
    def test_actual_full_packed_LUT2_empty_O6_contract_and_no_input_mutation(self):
        before, after = fixture(); a, b = deepcopy(before), deepcopy(after)
        source = before['cells']['actual-disconnected-XORCY-LUT2']
        self.assertEqual(source['attributes']['X_ORIG_TYPE'], 'LUT2')
        self.assertEqual(source['connections']['O6'], [])
        self.assertEqual(source['attributes']['X_ORIG_PORT_O6'], 'O')
        view, meta = full_export_view(comparison_port_source(before), after)
        self.assertEqual(view['cells']['actual-disconnected-XORCY-LUT2']['connections']['O6'], [])
        self.assertEqual(meta['restored_empty_plain_LUT_outputs'], 1)
        self.assertFalse(meta['comparison_view_used_for_execution'])
        self.assertEqual((before, after), (a, b))

    def test_old_plain_LUT_proof_still_fails_missing_output(self):
        before, after = fixture()
        old, _ = carry_export_view(comparison_port_source(before), after)
        with self.assertRaises(AssertionError): checkpoint.proof_module(old)

    def test_changed_kind_INIT_mapping_unknown_output_or_multiple_outputs_fail(self):
        for kind in ('wrong_kind', 'wrong_INIT', 'wrong_mapping', 'unknown_pin', 'multiple_outputs'):
            before, after = fixture(); source = before['cells']['actual-disconnected-XORCY-LUT2']; target = after['cells']['actual-disconnected-XORCY-LUT2']
            if kind == 'wrong_kind': target['attributes']['X_ORIG_TYPE'] = 'SRL16E'
            elif kind == 'wrong_INIT': target['parameters']['INIT'] = '1'
            elif kind == 'wrong_mapping': target['attributes']['X_ORIG_PORT_O6'] = 'different'
            elif kind == 'unknown_pin':
                source['connections']['unknown'] = source['connections'].pop('O6'); source['port_directions']['unknown'] = source['port_directions'].pop('O6')
            else: source['connections']['O5'] = []; source['port_directions']['O5'] = 'output'
            with self.subTest(kind=kind), self.assertRaises(AssertionError): full_export_view(comparison_port_source(before), after)

    def test_source_memory_kind_or_bad_literal_or_non_O_annotation_fails(self):
        for key, value in [('kind', 'SRL16E'), ('INIT', 'unknown'), ('mapping', 'not_O')]:
            before, after = fixture(); source = before['cells']['actual-disconnected-XORCY-LUT2']
            if key == 'kind': source['attributes']['X_ORIG_TYPE'] = value
            elif key == 'INIT': source['parameters']['INIT'] = value
            else: source['attributes']['X_ORIG_PORT_O6'] = value
            with self.assertRaises(AssertionError): full_export_view(comparison_port_source(before), after)

    def test_connected_original_output_cannot_be_reconstructed(self):
        before, after = fixture(); source = before['cells']['actual-disconnected-XORCY-LUT2']
        source['connections']['O6'] = [42]
        view, meta = full_export_view(comparison_port_source(before), after)
        self.assertEqual(meta['restored_empty_plain_LUT_outputs'], 0)
        self.assertNotIn('O6', view['cells']['actual-disconnected-XORCY-LUT2']['connections'])
        with self.assertRaises(AssertionError): checkpoint.proof_module(view)

    def test_existing_port_direction_or_connected_output_never_repaired(self):
        before, after = fixture(); target = after['cells']['actual-disconnected-XORCY-LUT2']
        target['connections']['O6'] = [42]; target['port_directions']['O6'] = 'input'
        view, meta = full_export_view(comparison_port_source(before), after)
        self.assertEqual(meta['restored_empty_plain_LUT_outputs'], 0)
        self.assertEqual(view['cells']['actual-disconnected-XORCY-LUT2']['connections']['O6'], [42])
        with self.assertRaises(AssertionError): checkpoint.proof_module(view)

    def test_complete_synthetic_50_cell_proof_preserves_dead_output_function(self):
        # Test-only extra disconnected output, not a modified native execution input.
        before = next(iter(json.loads((NATIVE.parent / 'valid-forced-placed.json').read_text())['modules'].values()))
        parent = NATIVE.parents[1] / 'imported-placement-checker-qualification-1791426415757842131/fixed_49-routed.json'
        after = next(iter(json.loads(parent.read_text())['modules'].values()))
        name = next(n for n, c in before['cells'].items() if c['type'] == 'SLICE_LUTX' and c['connections'].get('O6'))
        original = deepcopy(before['cells'][name])
        original['connections']['O6'] = []
        before['cells']['test-only-disconnected-output'] = original
        # Preserve the actual native LUT pin permutation/wire renumbering in
        # the routed half of this synthetic pair; do not copy pre-route IDs.
        imported = deepcopy(after['cells'][name]); del imported['connections']['O6']; del imported['port_directions']['O6']
        after['cells']['test-only-disconnected-output'] = imported
        view, meta = full_export_view(comparison_port_source(before), after)
        identity = checkpoint.assert_circuit_identity(checkpoint.proof_module(before), checkpoint.proof_module(view, before['ports']))
        self.assertEqual(identity['logical_board']['cells'], 50)
        self.assertEqual(meta['restored_empty_plain_LUT_outputs'], 1)
        bad = deepcopy(after); c = bad['cells']['test-only-disconnected-output']; c['parameters']['INIT'] = '1'
        with self.assertRaises(AssertionError): full_export_view(comparison_port_source(before), bad)

    def test_memory_or_SRL_mode_annotations_are_not_plain_LUTs(self):
        for owner in ('original', 'exported'):
            for marker in ('X_LUT_AS_DRAM', 'X_LUT_AS_SRL'):
                before, after = fixture()
                cells = before['cells'] if owner == 'original' else after['cells']
                cells['actual-disconnected-XORCY-LUT2']['attributes'][marker] = '1'
                with self.subTest(owner=owner, marker=marker), self.assertRaises(AssertionError):
                    full_export_view(comparison_port_source(before), after)


if __name__ == '__main__': unittest.main()
