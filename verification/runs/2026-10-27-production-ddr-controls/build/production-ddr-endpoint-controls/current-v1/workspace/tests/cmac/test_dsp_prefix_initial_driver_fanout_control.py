"""Initial-warning capture controls; not numerical or FPGA acceptance."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import capture_dsp_prefix_initial_driver_fanout as capture


class InitialDriverFanoutControl(unittest.TestCase):
    def fixture(self, consumer=False, output=False):
        body = {'ports': {}, 'netnames': {'temporary': {'bits': [10]}}, 'cells': {}}
        if output:
            body['ports']['result'] = {'direction': 'output', 'bits': [10]}
        if consumer:
            body['cells']['live'] = {'type': '$not', 'connections': {'A': [10], 'Y': [11]},
                                     'port_directions': {'A': 'input', 'Y': 'output'}}
        return {'modules': {'m': body}}

    def test_actual_script_stops_before_arithmetic_mapping(self):
        original = (ROOT / capture.normalization.PARENT).parent
        text = (original / 'mapping.ys').read_text()
        result = capture.frontend_capture_script(text, ROOT / 'build/control-not-executed')
        marker = f'synth_xilinx {capture.normalization.FLAGS} -run begin:coarse;\n'
        self.assertTrue(result.startswith(text.split(marker)[0]))
        self.assertIn('-run begin:prepare;\nproc;', result)
        self.assertEqual(result.count('write_json '), 2)
        self.assertNotIn('map_memory', result)
        self.assertNotIn('share;', result)

    def test_missing_or_repeated_endpoint_fails(self):
        original = (ROOT / capture.normalization.PARENT).parent
        text = (original / 'mapping.ys').read_text()
        marker = f'synth_xilinx {capture.normalization.FLAGS} -run begin:coarse;\n'
        for bad in (text.replace(marker, ''), text + marker):
            with self.assertRaises(AssertionError):
                capture.frontend_capture_script(bad, ROOT / 'build/control-not-executed')

    def test_disconnected_bit_has_zero_consumers(self):
        line = 'Warning: Wire m.temporary is used but has no driver.'
        result = capture.fanout_inventory(self.fixture(), capture.driver_notices(line))
        self.assertEqual(result[0]['direct_consumer_count'], 0)

    def test_actual_cell_and_output_consumers_are_not_hidden(self):
        line = 'Warning: Wire m.temporary is used but has no driver.'
        for consumer, output, expected in ((True, False, 1), (False, True, 1), (True, True, 2)):
            result = capture.fanout_inventory(self.fixture(consumer, output), capture.driver_notices(line))
            self.assertEqual(result[0]['direct_consumer_count'], expected)

    def test_unknown_pin_direction_and_duplicate_notice_fail(self):
        line = 'Warning: Wire m.temporary is used but has no driver.'
        design = self.fixture(True)
        del design['modules']['m']['cells']['live']['port_directions']['A']
        with self.assertRaises(AssertionError):
            capture.fanout_inventory(design, capture.driver_notices(line))
        with self.assertRaises(AssertionError):
            capture.fanout_inventory(self.fixture(), capture.driver_notices(line + '\n' + line))

    def test_escaped_scalar_and_upto_vector_indices(self):
        design = self.fixture()
        self.assertEqual(capture.notice_bit(design, 'Warning: Wire m.\\temporary is used but has no driver.'),
                         ('m', 'temporary', 0, 10))
        design['modules']['m']['netnames']['vector'] = {'bits': [20, 21, 22, 23], 'offset': 4, 'upto': 1}
        self.assertEqual(capture.notice_bit(design, 'Warning: Wire m.vector [5] is used but has no driver.'),
                         ('m', 'vector', 2, 22))


if __name__ == '__main__':
    unittest.main()
