"""Actual-profile audit controls; no new native tool or physical proof."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import audit_upstream_dsp_constants as audit


class UpstreamDSPConstantAuditControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = json.loads(audit.SELECTED.read_text())
        cls.original = next(cell for cell in selected.values() if cell['type'] == 'DSP48E1')

    def packed(self):
        return dict(type='DSP48E1_DSP48E1', attributes={'DSP_GND_PINS': 'D0 RSTD', 'DSP_VCC_PINS': ''},
            parameters={f'IS_{bus}[{bit}]_INVERTED': '1' for bus, bit in audit.PINS})

    def test_actual_zero_profile_has_all_eight_requested_control_pins(self):
        self.assertEqual(set(audit.requirements(self.original)),
            {'INMODE0', 'INMODE1', 'INMODE2', 'INMODE3', 'INMODE4', 'ALUMODE2', 'ALUMODE3', 'OPMODE6'})
        changed = copy.deepcopy(self.original)
        changed['connections']['INMODE'][1] = '1'
        with self.assertRaises(AssertionError):
            audit.requirements(changed)

    def test_missing_tile_declarations_remain_findings_even_with_inversion_parameters(self):
        packed = self.packed()
        self.assertEqual(len(audit.packed_gap(self.original, packed)), 8)
        packed['attributes']['DSP_VCC_PINS'] = ' '.join(audit.requirements(self.original))
        self.assertEqual(audit.packed_gap(self.original, packed), {})
        # This checks declarations only. It is not corrected FASM acceptance.
        packed['parameters']['IS_INMODE[1]_INVERTED'] = '0'
        with self.assertRaises(AssertionError):
            audit.packed_gap(self.original, packed)

    def test_duplicate_conflicting_or_wrong_primitive_ties_fail(self):
        for attributes in ({'DSP_GND_PINS': 'D0 D0', 'DSP_VCC_PINS': ''},
                           {'DSP_GND_PINS': 'D0', 'DSP_VCC_PINS': 'D0'}):
            packed = self.packed()
            packed['attributes'] = attributes
            with self.assertRaises(AssertionError):
                audit.declared_ties(packed)
        packed = self.packed()
        packed['type'] = 'LUT6'
        with self.assertRaises(AssertionError):
            audit.declared_ties(packed)

    def test_native_feature_gap_keeps_tie_values_and_disabled_inverters_separate(self):
        placement = dict(type='DSP48E1_DSP48E1', site='DSP48_X0Y3', tile='DSP_R_X10Y20')
        gap = audit.sample_gap({}, placement, self.original)
        self.assertEqual(len(gap['absent_or_different_features']), 16)
        required = gap['required_features']
        self.assertIn('DSP_R_X10Y20.DSP_1_INMODE1.DSP_GND_R', required)
        self.assertIn('DSP_R_X10Y20.DSP48.DSP_1.ZIS_INMODE_INVERTED[1]', required)
        self.assertFalse(audit.sample_gap(required, placement, self.original)['absent_or_different_features'])
        changed = dict(required)
        changed['DSP_R_X10Y20.DSP_1_INMODE1.DSP_GND_R'] = '0'
        self.assertEqual(len(audit.sample_gap(changed, placement, self.original)['absent_or_different_features']), 1)

    def test_one_remaining_gap_cannot_be_classified_as_no_gap_or_pass(self):
        for full, small in ((1, 0), (0, 1), (4120, 64)):
            status = audit.finding_status(full, small)
            self.assertIn('GAP', status)
            self.assertNotIn('NO_GAP', status)
            self.assertNotIn('PASS', status)
        self.assertIn('NOT_ENCODER_OR_PHYSICAL_ACCEPTANCE', audit.finding_status(0, 0))
        with self.assertRaises(AssertionError):
            audit.finding_status(-1, 0)


if __name__ == '__main__':
    unittest.main()
