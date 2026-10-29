"""Complete full placement gates plus actual-new-pack checksum/census controls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import place_recursive_mux_prefix_shared_board as placement
from test_recursive_mux_full_pack_control import RecursiveMuxFullPackControls, SharedPackAdmission, PinnedNativeReader


class RecursiveMuxFullPlaceControls(unittest.TestCase):
    def test_same_full_native_placement_guards_and_no_old_census_mutation(self):
        text = placement.MAIN_SOURCE
        for old, new in reversed(placement.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        self.assertEqual(text, placement.previous.MAIN_SOURCE)
        for name in ('placement_argv', 'verify_full_argv', 'compare_placement', 'verify_corrected_packed', 'verify_clock_admission'):
            self.assertIs(placement.NAMESPACE[name], placement.previous.NAMESPACE[name])
        self.assertEqual(placement.NATIVE_TIMEOUT, 43200)
        self.assertIs(placement.NAMESPACE['validate_pack'], placement.packer.validate_pack)
        self.assertIn("assert pack['executable'] == preflight['executable']", placement.MAIN_SOURCE)
        self.assertNotIn('523410', placement.full_log_checks.__code__.co_consts)

    def test_incomplete_or_small_probe_does_not_admit_native_full_placement(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-full-mux-place-admission-control-') as directory:
            root = Path(directory)
            path = root / 'build/openxc7/recursive-mux-feedthrough-qualification-control/report.json'
            path.parent.mkdir(parents=True)
            with patch.object(placement, 'ROOT', root), patch.object(placement.qualification, 'verify_qualification') as native:
                for status in ('RUNNING', 'FAIL_RECURSIVE_MUX_FEEDTHROUGH_QUALIFICATION',
                               'PASS_SMALL_RECURSIVE_MUX_NATIVE_PLACEMENT_NOT_FULL_BACKEND_QUALIFICATION_OR_FIT'):
                    path.write_text(json.dumps({'status': status}))
                    with self.subTest(status=status), self.assertRaises(AssertionError): placement.admit_qualification(path)
                    native.assert_not_called()

    def test_new_bound_checksum_cell_census_and_finite_limit_all_required(self):
        # Comparison-only metadata/log fixtures, not native execution or a new actual census.
        old = json.loads((ROOT / 'build/openxc7/full-prefix-shared-native-pack-1791474646490498829/report.json').read_text())
        for count, checksum in ((523410, '0x12345678'), (523522, '0xabcdef01')):
            with tempfile.TemporaryDirectory(prefix='rknpu-new-pack-log-control-') as directory:
                packed = deepcopy(old)
                packed.update(status=placement.packer.PACKED,
                    only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent=True,
                    legacy_full_encoder_result_inherited_as_new_pack=False,
                    legacy_DSP_encoder_qualification='test-only-baseline-reference')
                extra = count - packed['native_census']['cells']
                packed['native_census']['cells'] = count
                packed['native_census']['primitive_counts']['SLICE_LUTX'] += extra
                packed['LUT_sharing_bound']['lut_cells'] += extra
                log = Path(directory) / 'native-pack.log'; log.write_text('Info: Checksum: ' + checksum + '\n')
                packed['commands'][-1]['log'] = str(log)
                text = ('Info: Checksum: ' + checksum + '\nInfo: Creating initial analytic placement for ' + str(count) +
                        ' cells, random placement wirelen = 1.\nInfo: Running main analytical placer, max placement attempts per cell = 2147483646.\n')
                result = placement.full_log_checks(text, packed)
                self.assertEqual(result['actual_full_packed_cells'], count)
                self.assertEqual(result['actual_packed_checksum'], checksum)
                self.assertFalse(result['old_fixed_packed_census_or_checksum_inherited'])
                for changed in (text.replace(checksum, '0x00000000'), text.replace(str(count), str(count + 1)),
                                text.replace('2147483646', '10000'), text + 'Info: Checksum: ' + checksum + '\n' + text,
                                text.replace('Creating initial analytic placement for ', 'Other placer for ')):
                    with self.subTest(count=count, changed=changed[-70:]), self.assertRaises(AssertionError):
                        placement.full_log_checks(changed, packed)


if __name__ == '__main__':
    unittest.main()
