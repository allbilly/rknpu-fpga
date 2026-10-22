"""Shared full-board replay input controls; not numerical/FPGA acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/cmac'),
                str(Path(__file__).resolve().parents[2] / 'tools/openxc7')]
import prepare_prefix_shared_replay as new
import test_dsp_prefix_observed_mapped_board_control as previous

ExistingDSPReplayGuards = previous.PrefixObservedMappedBoardControls


def fixture():
    design = previous.dsp_fixture()
    design['modules'][new.PRIVATE] = design['modules'].pop('kernel')
    for cell in design['modules'][new.TOP]['cells'].values():
        if cell['type'] == 'kernel':
            cell['type'] = new.PRIVATE
    design['modules'][new.SHARED] = dict(cells={'comb': dict(type='LUT2')})
    design['modules'][new.TOP]['cells']['shared'] = dict(type=new.SHARED)
    return design


class SharedReplayInputs(unittest.TestCase):
    def test_complete_three_module_configuration_without_mutation(self):
        design = fixture()
        before = deepcopy(design)
        report, kinds = new.configuration(design)
        self.assertEqual(report['total_physical_dsps'], 515)
        self.assertEqual(report['physical_cmac_dsps'], 512)
        self.assertEqual(report['shared_combinational_cells'], 1)
        self.assertFalse(report['shared_module_omitted_from_execution'])
        self.assertEqual(kinds, {'DSP48E1', 'LUT2'})
        self.assertEqual(design, before)
        with self.assertRaises(AssertionError):
            new.models.verify_configurations(design, new.TOP, new.PRIVATE)

    def test_missing_extra_or_unmodeled_module_refused(self):
        for name in (new.TOP, new.PRIVATE, new.SHARED):
            design = fixture()
            del design['modules'][name]
            with self.assertRaises(AssertionError):
                new.configuration(design)
        design = fixture()
        design['modules']['extra'] = dict(cells={})
        with self.assertRaises(AssertionError):
            new.configuration(design)

    def test_shared_state_dsp_empty_or_nested_hardware_refused(self):
        for kind in ('FDCE', 'FDRE', 'DSP48E1', new.PRIVATE, 'unknown'):
            design = fixture()
            design['modules'][new.SHARED]['cells']['comb']['type'] = kind
            with self.subTest(kind=kind), self.assertRaises(AssertionError):
                new.configuration(design)
        design = fixture()
        design['modules'][new.SHARED]['cells'] = {}
        with self.assertRaises(AssertionError):
            new.configuration(design)

    def test_shared_missing_duplicate_or_parameter_override_refused(self):
        for action in ('missing', 'duplicate', 'override'):
            design = fixture()
            cells = design['modules'][new.TOP]['cells']
            if action == 'missing':
                del cells['shared']
            elif action == 'duplicate':
                cells['shared2'] = dict(type=new.SHARED)
            else:
                cells['shared']['parameters'] = {'override': '1'}
            with self.subTest(action=action), self.assertRaises(AssertionError):
                new.configuration(design)

    def test_kernel_loss_or_unqualified_DSP_settings_remain_failures(self):
        for action in ('kernel', 'DSP', 'bias', 'register', 'pin', 'unknown'):
            design = fixture()
            private = design['modules'][new.PRIVATE]['cells']
            if action == 'kernel':
                del design['modules'][new.TOP]['cells']['kernel_0']
            elif action == 'DSP':
                private.pop('0')
            elif action == 'bias':
                private['0']['connections']['C'][0] = '1'
            elif action == 'register':
                private['0']['parameters']['AREG'] = '0' * 31 + '1'
            elif action == 'pin':
                del private['0']['connections']['OPMODE']
            else:
                design['modules'][new.TOP]['cells']['extra'] = dict(type='unsupported')
            with self.subTest(action=action), self.assertRaises(AssertionError):
                new.configuration(design)

    def test_literal_actual_export_requires_every_byte(self):
        design = dict(modules={'tiny_control': dict(ports={}, cells={'literal': dict(type='INV',
            parameters={}, connections={'I': [2], 'O': [3]}, port_directions={'I': 'input', 'O': 'output'})})})
        text = new.structural_board_verilog(design)
        new.exact_export(design, text)
        for changed in (text[:-1], text + '// changed\n', text.replace('n_2)', 'n_3)')):
            with self.assertRaises(AssertionError):
                new.exact_export(design, changed)

    def test_manifest_conflicts_invalid_digests_and_missing_paths_refused(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-shared-replay-bindings-') as directory:
            path = Path(directory) / 'fixture.bin'
            path.write_bytes(b'host source-binding fixture')
            sha = new.digest(path)
            before = {}
            new.merge(before, {str(path): sha})
            self.assertEqual(before, {str(path): sha})
            with self.assertRaises(AssertionError):
                new.merge(before, {str(path): '0' * 64})
            with self.assertRaises(AssertionError):
                new.merge({}, {str(path): 'not a hash'})
            with self.assertRaises(FileNotFoundError):
                new.merge({}, {str(path.parent / 'absent'): sha})


if __name__ == '__main__':
    unittest.main()
