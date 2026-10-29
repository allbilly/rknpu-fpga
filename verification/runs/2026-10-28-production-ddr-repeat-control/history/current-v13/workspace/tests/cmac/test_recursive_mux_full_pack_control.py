"""Full recursive-mux pack preparation guards, not an executed full native pack."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import pack_recursive_mux_prefix_shared_board as pack
from test_prefix_shared_pack_control import SharedPackAdmission, PinnedNativeReader


class RecursiveMuxFullPackControls(unittest.TestCase):
    def test_same_full_pack_procedure_except_explicit_new_engine_admission(self):
        text = pack.MAIN_SOURCE
        for old, new in reversed(pack.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        self.assertEqual(text, inspect.getsource(pack.previous.main))
        for name in ('validate_prepared', 'native_census', 'verify_corrected_packed', 'verify_clock_admission', 'LUTInputs'):
            self.assertIs(pack.NAMESPACE[name], getattr(pack.previous, name))
        for marker in ('verify_corrected_packed(cell, packed[name])', 'DSP_configurations_compared=515',
                       'extra_tile_only_ties_compared=4120', "'--freq', '50', '--seed', '3588'",
                       "'--Werror', '--debug'", 'physical_positions(log,', 'native_census(output, selected,'):
            self.assertIn(marker, pack.MAIN_SOURCE)

    def test_incomplete_failed_or_small_probe_only_cannot_admit_full_pack(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-full-mux-pack-admission-control-') as directory:
            root = Path(directory)
            path = root / 'build/openxc7/recursive-mux-feedthrough-qualification-control/report.json'
            path.parent.mkdir(parents=True)
            with patch.object(pack, 'ROOT', root), patch.object(pack.qualification, 'verify_qualification') as native, \
                    patch.object(pack.previous, 'validate_qualification') as legacy:
                for status in ('RUNNING', 'FAIL_RECURSIVE_MUX_FEEDTHROUGH_QUALIFICATION',
                               'PASS_SMALL_RECURSIVE_MUX_NATIVE_PLACEMENT_NOT_FULL_BACKEND_QUALIFICATION_OR_FIT',
                               'BUILT_ISOLATED_RECURSIVE_MUX_FEEDTHROUGH_PACK_PROBED_NOT_PNR_QUALIFIED_OR_FULL_FIT'):
                    path.write_text(json.dumps({'status': status}))
                    with self.subTest(status=status), self.assertRaises(AssertionError): pack.admit_qualification(path)
                    native.assert_not_called(); legacy.assert_not_called()

    def test_complete_full_pack_gate_not_weakened_or_old_status_relabelled(self):
        old = json.loads((ROOT / 'build/openxc7/full-prefix-shared-native-pack-1791474646490498829/report.json').read_text())
        # Comparison-only metadata control; this is not a new engine/full native result.
        value = deepcopy(old)
        value.update(status=pack.PACKED, only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent=True,
                     legacy_full_encoder_result_inherited_as_new_pack=False,
                     legacy_DSP_encoder_qualification='test-only-baseline-reference')
        pack.validate_pack(value)
        self.assertNotEqual(old['status'], value['status'])
        for key, changed in (('status', old['status']), ('channels', 16), ('kernels', 8),
                             ('parallel_products', 256), ('retained_cmac_dsps', 256),
                             ('retained_shell_dsps', 0), ('intended_clock_period_ns', 40),
                             ('legacy_full_encoder_result_inherited_as_new_pack', True),
                             ('only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent', False)):
            control = deepcopy(value); control[key] = changed
            with self.subTest(key=key), self.assertRaises(AssertionError): pack.validate_pack(control)
        for primitive, count in (('DSP48E1_DSP48E1', 514), ('RAMB36E1_RAMB36E1', 5), ('SLICE_FFX', 17518)):
            control = deepcopy(value); control['native_census']['primitive_counts'][primitive] = count
            with self.subTest(primitive=primitive), self.assertRaises(AssertionError): pack.validate_pack(control)


if __name__ == '__main__':
    unittest.main()
