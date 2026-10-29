"""Exact structural correction controls; native transfer is a separate run."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import correct_placed_dsp_constants as fix
from probe_corrected_dsp_checkpoint import ROOT, SELECTED, NATIVE


class CorrectedPlacementTransferControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        q = json.loads(NATIVE.read_text())
        originals = json.loads(SELECTED.read_text())
        origins = q['control_origins']
        cls.selected = {name: originals[source] for name, source in origins.items() if originals[source]['type'] == 'DSP48E1'}
        # Software-only old-representation fixture derived from an actual
        # corrected placement, NOT claimed as old-engine native placement.
        path = ROOT / 'build/openxc7/corrected-dsp-checkpoint-control-1791417172851071744/placed.json'
        cls.fixture = next(iter(json.loads(path.read_text())['modules'].values()))
        vcc = fix.constant_drivers(cls.fixture)['VCC']
        for name, original in cls.selected.items():
            cell = cls.fixture['cells'][name]
            baseline = fix.dsp_expectations(original)['dedicated_constant_pins']
            extra = set(fix.corrected_expectations(original)['packed_tile_constant_nets']) - set(baseline)
            for pin in extra: cell['connections'][pin] = [vcc]
            for level in ('GND', 'VCC'):
                cell['attributes']['DSP_' + level + '_PINS'] = ' '.join(sorted(pin for pin, value in baseline.items() if value == level))
        cls.name = next(iter(cls.selected))

    def test_exact_32_pin_change_preserves_all_286_cells_and_input(self):
        before = deepcopy(self.fixture)
        result, record = fix.correct_placement(self.fixture, self.selected)
        self.assertEqual(self.fixture, before)
        self.assertEqual(record['cells_compared'], 286)
        self.assertEqual(record['DSPs_corrected'], 4)
        self.assertEqual(record['tile_pin_disconnections_compared'], 32)
        self.assertFalse(record['native_transfer_legality_admitted'])
        self.assertTrue(record['all_physical_BELs_unchanged'])

    def test_already_corrected_input_is_not_silently_reused(self):
        corrected, _ = fix.correct_placement(self.fixture, self.selected)
        with self.assertRaisesRegex(AssertionError, '31-tie'): fix.correct_placement(corrected, self.selected)

    def test_routed_checkpoint_is_not_a_transfer_input(self):
        bad = deepcopy(self.fixture)
        bad['settings']['route'] = format(1, '032b')
        with self.assertRaisesRegex(AssertionError, 'routing'): fix.correct_placement(bad, self.selected)

    def test_wrong_old_tile_wire_rejected(self):
        bad = deepcopy(self.fixture)
        bad['cells'][self.name]['connections']['INMODE1'] = [fix.constant_drivers(bad)['GND']]
        with self.assertRaisesRegex(AssertionError, 'tile-only'): fix.correct_placement(bad, self.selected)

    def test_parameter_change_rejected(self):
        bad = deepcopy(self.fixture)
        bad['cells'][self.name]['parameters']['AREG'] = '1'
        with self.assertRaises(AssertionError): fix.correct_placement(bad, self.selected)

    def test_missing_dsp_inventory_rejected(self):
        selected = dict(self.selected)
        del selected[self.name]
        with self.assertRaisesRegex(AssertionError, 'inventory'): fix.correct_placement(self.fixture, selected)

    def test_changed_bel_rejected_by_complete_delta(self):
        corrected, _ = fix.correct_placement(self.fixture, self.selected)
        corrected['cells'][self.name]['attributes']['NEXTPNR_BEL'] = 'NOT_A_NATIVE_BEL'
        with self.assertRaisesRegex(AssertionError, 'BEL'): fix.verify_delta(self.fixture, corrected, self.selected)

    def test_changed_ordinary_wire_rejected_by_complete_delta(self):
        corrected, _ = fix.correct_placement(self.fixture, self.selected)
        corrected['cells'][self.name]['connections']['A0'] = [999999999]
        with self.assertRaisesRegex(AssertionError, 'ordinary'): fix.verify_delta(self.fixture, corrected, self.selected)

    def test_changed_non_dsp_cell_rejected_by_complete_delta(self):
        corrected, _ = fix.correct_placement(self.fixture, self.selected)
        # Replace only this comparison object's non-DSP cell, not shared input.
        name = next(name for name, cell in corrected['cells'].items() if cell['type'] == 'SLICE_LUTX')
        corrected['cells'][name] = dict(corrected['cells'][name], parameters={'INIT': '0'})
        with self.assertRaisesRegex(AssertionError, 'non-DSP'): fix.verify_delta(self.fixture, corrected, self.selected)

    def test_changed_named_wire_table_rejected_by_complete_delta(self):
        corrected, _ = fix.correct_placement(self.fixture, self.selected)
        corrected['netnames'] = dict(corrected['netnames'], UNMODELED={'bits': [999999999]})
        with self.assertRaisesRegex(AssertionError, 'named nets'): fix.verify_delta(self.fixture, corrected, self.selected)

    def test_changed_non_tie_attribute_rejected_by_complete_delta(self):
        corrected, _ = fix.correct_placement(self.fixture, self.selected)
        corrected['cells'][self.name]['attributes']['UNMODELED'] = '1'
        with self.assertRaisesRegex(AssertionError, 'non-tie'): fix.verify_delta(self.fixture, corrected, self.selected)

    def test_missing_constant_driver_rejected(self):
        bad = deepcopy(self.fixture)
        del bad['cells'][next(name for name, cell in bad['cells'].items() if cell['type'] == 'PSEUDO_VCC')]
        with self.assertRaisesRegex(AssertionError, 'constant driver'): fix.correct_placement(bad, self.selected)


if __name__ == '__main__':
    unittest.main()
