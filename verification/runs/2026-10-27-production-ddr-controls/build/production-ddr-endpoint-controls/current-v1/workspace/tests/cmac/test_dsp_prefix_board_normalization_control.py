"""Diagnostic capture controls, not full-board or FPGA acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import capture_dsp_prefix_board_normalization as capture


class NormalizationControl(unittest.TestCase):
    def test_actual_script_is_only_additive_capture_and_output_paths(self):
        old = ROOT / capture.PARENT
        text = (old.parent / 'mapping.ys').read_text()
        new = capture.capture_script(text, capture.FLAGS, old.parent, ROOT / 'build/control-not-executed')
        self.assertIn('-run map_memory:check;\ndesign -save ', new)
        self.assertIn('blackbox =A:whitebox;\nwrite_json ', new)
        self.assertIn('design -load rk_normalization_capture;\nsynth_xilinx ', new)
        self.assertEqual(new.count('-run check:'), 1)
        self.assertEqual(new.count('share;'), 0)

    def test_missing_repeated_or_different_stage_fails(self):
        old = ROOT / capture.PARENT
        text = (old.parent / 'mapping.ys').read_text()
        marker = f'synth_xilinx {capture.FLAGS} -run map_memory:'
        for bad in (text.replace(marker, marker + 'fine'), text + marker + ';\n', text.replace('mapped.v', 'other.v')):
            with self.assertRaises(AssertionError):
                capture.capture_script(bad, capture.FLAGS, old.parent, ROOT / 'build/control-not-executed')

    def fixture(self, pin, direction, bits, final, write_width=0):
        cell = dict(type='RAMB36E1', parameters={'WRITE_WIDTH_A': f'{write_width:032b}'},
                    port_directions={pin: direction}, connections={pin: bits})
        pre = {'modules': {'top': {'ports': {}, 'cells': {'ram': cell}}}}
        pre['modules']['top']['netnames'] = {f'wire_{bit}': {'bits': [bit]} for bit in bits if type(bit) is int}
        post = deepcopy(pre)
        post['modules']['top']['cells']['ram']['connections'][pin] = final
        post['modules']['RAMB36E1'] = {'ports': {pin: {'bits': list(range(len(final)))}}}
        return pre, post, {('ram', pin): (len(bits), len(final))}

    def test_zero_extension_preserves_all_enable_bits(self):
        pre, post, notices = self.fixture('WEBWE', 'input', [1, 2, 3, 4], [1, 2, 3, 4, '0', '0', '0', '0'])
        self.assertEqual(len(capture.audit_normalization(pre, post, 'top', notices)), 1)
        post['modules']['top']['cells']['ram']['connections']['WEBWE'][-1] = '1'
        with self.assertRaises(AssertionError):
            capture.audit_normalization(pre, post, 'top', notices)

    def test_live_discarded_input_and_unknown_active_input_fail(self):
        for lost, width in (([99], 0), (['x'], 36), (['1'], 0)):
            pre, post, notices = self.fixture('DIADI', 'input', ['0'] + lost, ['0'], width)
            with self.assertRaises(AssertionError):
                capture.audit_normalization(pre, post, 'top', notices)

    def test_disabled_unknown_input_and_zero_padding_pass(self):
        for lost, width in ((['x'], 0), (['0'], 36)):
            pre, post, notices = self.fixture('DIADI', 'input', ['0'] + lost, ['0'], width)
            self.assertEqual(len(capture.audit_normalization(pre, post, 'top', notices)), 1)

    def test_discarded_output_must_have_no_consumer_or_retained_alias(self):
        pre, post, notices = self.fixture('DOADO', 'output', [1, 2], [1])
        self.assertEqual(len(capture.audit_normalization(pre, post, 'top', notices)), 1)
        for changed in ('consumer', 'alias'):
            left, right = deepcopy(pre), deepcopy(post)
            if changed == 'consumer':
                left['modules']['top']['ports']['result'] = {'direction': 'output', 'bits': [2]}
                right['modules']['top']['ports'] = deepcopy(left['modules']['top']['ports'])
            else:
                left['modules']['top']['cells']['ram']['connections']['DOADO'] = [1, 1]
            with self.assertRaises(AssertionError):
                capture.audit_normalization(left, right, 'top', notices)

    def test_unreported_rewiring_and_extra_notice_fail(self):
        pre, post, notices = self.fixture('DOADO', 'output', [1, 2], [1])
        for bad in ({}, dict(notices, other=(1, 2))):
            with self.assertRaises(AssertionError):
                capture.audit_normalization(pre, post, 'top', bad)

    def test_export_wire_renumbering_and_dead_zero_aliases(self):
        pre, post, notices = self.fixture('DOADO', 'output', [1, 2], [1])
        post['modules']['top']['netnames']['wire_1']['bits'] = [10]
        post['modules']['top']['netnames']['wire_2']['bits'] = ['0']
        post['modules']['top']['cells']['ram']['connections']['DOADO'] = [10]
        self.assertEqual(len(capture.audit_normalization(pre, post, 'top', notices)), 1)
        post['modules']['top']['netnames']['wire_2']['bits'] = [10]
        with self.assertRaises(AssertionError):
            capture.audit_normalization(pre, post, 'top', notices)

    def test_silent_constant_input_resize_is_still_audited(self):
        pre, post, notices = self.fixture('DIADI', 'input', ['x', '0'], ['x'])
        result = capture.audit_normalization(pre, post, 'top', {})
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]['resize_notice_present'])

    def test_real_notice_inventory_is_exactly_32(self):
        old = ROOT / capture.PARENT
        notices = capture.resize_notices((old.parent / 'mapping.log').read_text(), 'ypcb_cmac_array_top')
        self.assertEqual(len(notices), 32)
        self.assertEqual(len({name for name, pin in notices}), 6)


if __name__ == '__main__':
    unittest.main()
