"""Supplemental corruption/log controls; original eight methods retained."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_imported_placement_checker_probe as old_tests
from build_imported_carry_checker import local_carry_roles
from probe_imported_carry_checker import corrupt_checkpoint, scan_log, EXTRA_REASONS


class ImportedCarryCheckerProbe(old_tests.ImportedPlacementCheckerProbe):
    def test_new_corruptions_do_not_mutate_the_saved_positive(self):
        saved = deepcopy(self.original)
        for kind in EXTRA_REASONS:
            bad = corrupt_checkpoint(self.original, kind)
            self.assertNotEqual(bad, self.original)
            self.assertEqual(self.original, saved)
        with self.assertRaisesRegex(AssertionError, 'wrong local carry DI role'):
            local_carry_roles(next(iter(corrupt_checkpoint(self.original, 'wrong_local_carry_DI')['modules'].values())))
        module = next(iter(corrupt_checkpoint(self.original, 'local_carry_extra_user')['modules'].values()))
        self.assertEqual(len(local_carry_roles(module)), 7)

    def test_native_role_count_is_additional_to_every_old_success_gate(self):
        marker = 'Info: RKNPU imported placement scan: verified 8 local carry DI roles.\n'
        good = self.good_log().replace('Info: RKNPU imported placement scan: passed', marker + 'Info: RKNPU imported placement scan: passed')
        scan_log(0, good, 49, 9)
        for bad in (self.good_log(), good.replace('verified 8', 'verified 7'), good + marker):
            with self.assertRaises(AssertionError): scan_log(0, bad, 49, 9)
        for reason in EXTRA_REASONS.values():
            failed = 'Info: RKNPU imported placement scan: begin before clock/general routing.\nERROR: RKNPU imported placement scan: ' + reason + '.\n'
            scan_log(125, failed, rejection=reason)
            with self.assertRaises(AssertionError): scan_log(125, failed + 'Info: Running router2...\n', rejection=reason)


if __name__ == '__main__':
    unittest.main()
