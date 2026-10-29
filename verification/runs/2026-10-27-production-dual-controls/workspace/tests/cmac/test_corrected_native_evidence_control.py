"""Metadata corruption controls; complete evidence is checked by the caller."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import verify_corrected_native_evidence as verify


class CorrectedNativeEvidenceControl(unittest.TestCase):
    def reports(self):
        return json.loads(verify.NATIVE.read_text()), json.loads(verify.IDENTITY.read_text())

    def test_actual_completed_metadata(self):
        verify.verify_metadata(*self.reports())

    def test_pending_or_reduced_scope_rejected(self):
        for key, value in [('status', 'RUNNING'), ('full_target_parallel_products', 32)]:
            native, identity = self.reports()
            native[key] = value
            with self.assertRaises(AssertionError): verify.verify_metadata(native, identity)

    def test_changed_command_or_failure_rejected(self):
        native, identity = self.reports()
        native['commands'][-1]['returncode'] = 1
        with self.assertRaises(AssertionError): verify.verify_metadata(native, identity)

    def test_unproved_placement_transfer_or_signoff_rejected(self):
        for key in ('old_full_placement_reuse_admitted', 'timing_signoff', 'hardware_programmed'):
            native, identity = self.reports()
            native[key] = True
            with self.assertRaises(AssertionError): verify.verify_metadata(native, identity)

    def test_incomplete_full_identity_rejected(self):
        native, identity = self.reports()
        identity['comparison']['cells_compared'] = 286
        with self.assertRaises(AssertionError): verify.verify_metadata(native, identity)


if __name__ == '__main__':
    unittest.main()
