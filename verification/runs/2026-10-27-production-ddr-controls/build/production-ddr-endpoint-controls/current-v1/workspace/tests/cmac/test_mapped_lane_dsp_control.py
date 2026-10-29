"""Mapped-lane admission/bench controls, not numerical or FPGA evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_mapped_lane_dsp as runner


def parent():
    return dict(status='PASS_ISOLATED_LANE_DSP_XC7_AREA_ONLY', commands=[
        dict(log=name + '.log', status='PASS', returncode=0)
        for name in ('version', 'reference_xc7_mapping', 'actual_xc7_mapping')],
        mapped_cells={'reference': {'LUT6': 2}, 'actual': {'LUT6': 1, 'DSP48E1': 1}},
        mapped_lut_primitives={'reference': 2, 'actual': 1},
        **{n: False for n in ('numerical_equivalence_acceptance', 'mapped_numerical_acceptance',
            'full_array_numerical_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


class MappedLaneDspControls(unittest.TestCase):
    def test_only_completed_strict_area_parent_is_admitted(self):
        report = parent(); before = deepcopy(report); runner.validate_parent_metadata(report); self.assertEqual(report, before)
        for mutation in ('status', 'command', 'returncode', 'counts', 'dsp', 'numeric', 'physical', 'bitstream'):
            changed = deepcopy(report)
            if mutation == 'status': changed['status'] = 'RUNNING'
            elif mutation == 'command': changed['commands'].pop()
            elif mutation == 'returncode': changed['commands'][1]['returncode'] = 1
            elif mutation == 'counts': changed['mapped_lut_primitives']['actual'] = 2
            elif mutation == 'dsp': changed['mapped_cells']['actual']['DSP48E1'] = 0
            elif mutation == 'numeric': changed['mapped_numerical_acceptance'] = True
            elif mutation == 'physical': changed['physical_fit_verified'] = True
            else: changed['bitstream_emitted'] = True
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.validate_parent_metadata(changed)

    def test_adapter_only_rebinds_actual_candidate_and_restores_original_literally(self):
        text = runner.SOURCES[-1].read_text(); mapped = runner.mapped_miter(text)
        self.assertEqual(mapped.replace(runner.MAPPED_TOP + ' candidate (', 'rk_cmac_fp16_lane_dsp candidate ('), text)
        self.assertIn('rk_cmac_fp16_rows reference_rows (', mapped)
        self.assertNotIn('rk_cmac_fp16_lane_dsp candidate (', mapped)
        with self.assertRaises(AssertionError): runner.mapped_miter(text + text)
        with self.assertRaises(AssertionError): runner.mapped_miter(mapped)

    def test_exact_positive_marker_and_real_negative_exit_are_required(self):
        runner.validate_result(runner.MARKER, 0, False)
        runner.validate_result('FATAL: LANE_DSP_MISMATCH a=0000', 1, True)
        for text, code, negative in [(runner.MARKER, 1, False), (runner.MARKER + '\n' + runner.MARKER, 0, False),
                (runner.MARKER.replace('135680', '1'), 0, False), ('compiler crash', 1, True),
                ('LANE_DSP_MISMATCH', 2, True), ('LANE_DSP_MISMATCH\nPASS other', 1, True),
                (runner.MARKER + '\nwarning: primitive', 0, False)]:
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.validate_result(text, code, negative)

    def test_native_state_unknown_cells_and_missing_dsp_are_not_mapped_acceptance(self):
        design = dict(modules={runner.MAPPED_TOP: dict(cells={
            'a': {'type': 'DSP48E1'}, 'b': {'type': 'LUT6'}})})
        self.assertEqual(runner.verify_export_domain(design), {'DSP48E1': 1, 'LUT6': 1})
        for kind in ('rk_cmac_fp16_lane_dsp', '$mul', 'FDCE', 'unknown'):
            changed = deepcopy(design); changed['modules'][runner.MAPPED_TOP]['cells']['c'] = {'type': kind}
            with self.subTest(kind=kind), self.assertRaises(AssertionError): runner.verify_export_domain(changed)
        changed = deepcopy(design); del changed['modules'][runner.MAPPED_TOP]['cells']['a']
        with self.assertRaises(AssertionError): runner.verify_export_domain(changed)


if __name__ == '__main__': unittest.main()
