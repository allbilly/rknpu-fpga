"""Supplemental tag-only controls; inherited first-checker gates unchanged."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_imported_placement_checker_build as old_tests
from build_imported_carry_checker import BASE_TEMPLATE, ROLE_BLOCK, ROLE_LOG, extended_template, local_carry_roles
from build_imported_placement_checker import TAG_SOURCE, checked_source
from probe_imported_placement_checker import NATIVE


class ImportedCarryCheckerBuild(old_tests.ImportedPlacementCheckerBuild):
    @classmethod
    def setUpClass(cls):
        cls.old = TAG_SOURCE.read_text()
        cls.block = extended_template(BASE_TEMPLATE.read_text())

    def test_supplement_removes_exactly_to_frozen_base_template(self):
        reverted = self.block.replace('checked_pairs = 0, checked_carry_feeds = 0;', 'checked_pairs = 0;').replace(ROLE_BLOCK, '').replace(ROLE_LOG, '')
        self.assertEqual(reverted, BASE_TEMPLATE.read_text())
        self.assertIn('sink.port != di || local_carry->getPort(di) != di_feed', ROLE_BLOCK)
        self.assertIn('di_feed->users.entries() == 1', ROLE_BLOCK)
        self.assertIn('l5.only_drives_carry = true;', ROLE_BLOCK)
        self.assertIn('cell_tags.swap(saved)', self.block)
        checked_source(self.old, self.block)

    def test_actual_eight_roles_and_wrong_DI_and_additional_user(self):
        module = next(iter(json.loads((NATIVE.parent / 'valid-forced-placed.json').read_text())['modules'].values()))
        roles = local_carry_roles(module)
        self.assertEqual(len(roles), 8)
        bad = deepcopy(module); role = roles[0]; carry = bad['cells'][role['carry']]
        other = 'DI' + str((int(role['di'][-1]) + 1) % 4)
        carry['connections'][role['di']], carry['connections'][other] = carry['connections'][other], carry['connections'][role['di']]
        with self.assertRaisesRegex(AssertionError, 'wrong local carry DI role'): local_carry_roles(bad)
        bad = deepcopy(module)
        ff = next(c for c in bad['cells'].values() if c['type'] == 'SLICE_FFX')
        ff['connections']['D'] = [role['net']]
        self.assertEqual(len(local_carry_roles(bad)), 7)
        self.assertEqual(len(local_carry_roles(module)), 8)


if __name__ == '__main__':
    unittest.main()
