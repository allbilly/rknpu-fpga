"""Fail-closed continuation admission against the actual failed parent."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from resume_imported_carry_checker import PARENT, FLAGS, verify_parent_metadata


class ImportedCarryCheckerResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.parent = json.loads(PARENT.read_text())

    def test_actual_parent_is_completed_native_work_but_still_failed(self):
        verify_parent_metadata(self.parent)
        self.assertEqual(self.parent['status'], 'FAIL')

    def test_different_failure_or_nonterminal_parent_fails(self):
        for key, value in (('status', 'RUNNING'), ('stage', 'admission'), ('finished_utc', None),
                           ('error', "AssertionError('different failure')"), ('native_corruption_rejections', 7)):
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_parent_metadata({**self.parent, key: value})

    def test_no_missing_failed_or_relabelled_native_step_is_admitted(self):
        for change in ('missing', 'status', 'returncode', 'label'):
            bad = deepcopy(self.parent)
            if change == 'missing': bad['commands'].pop()
            elif change == 'status': bad['commands'][-1]['status'] = 'RUNNING'
            elif change == 'returncode': bad['commands'][-1]['returncode'] = 125
            else: bad['commands'][-1]['label'] = 'different'
            with self.subTest(change=change), self.assertRaises(AssertionError): verify_parent_metadata(bad)

    def test_small_parent_cannot_grant_full_or_physical_acceptance(self):
        for key in FLAGS:
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_parent_metadata({**self.parent, key: True})


if __name__ == '__main__':
    unittest.main()
