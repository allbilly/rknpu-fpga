"""Offline contract for the EW aperture audit (task-21).

Runs tools/merged/ew_aperture_audit.py over the frozen capture bundles and pins
the verdict + bounds that docs/EW_APERTURE_AUDIT.md relies on. No Vivado, no
hardware.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.merged import ew_aperture_audit as audit  # noqa: E402


class EwApertureAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = audit.run(['ew-fp16', 'fdiv-systematic', 'simple_add'])
        cls.families = {family['family']: family for family in cls.result['families']}

    def test_audit_verdict_and_frozen_families(self):
        self.assertEqual(self.result['verdict'], 'PASS')
        self.assertEqual(self.result['problems'], [])
        self.assertIn('ew-fp16', self.families)
        self.assertIn('fdiv-systematic', self.families)
        self.assertIn('simple_add', self.families)

    def test_ew_fp16_all_cases_fit_the_six_banks(self):
        family = self.families['ew-fp16']
        self.assertEqual(family['cases'], 54)
        self.assertEqual(family['cases_with_problems'], 0)
        self.assertEqual(family['max_command_bytes'], 176)  # 22 QWORD words
        self.assertEqual(family['max_buffers'], 3)
        self.assertEqual(family['buffer_sizes'], [4096])
        self.assertLessEqual(family['max_region_count'], len(audit.EW_BANKS))
        # every case patches the three captured data pointers, value32 only
        for case in family['results']:
            self.assertEqual([p['buffer'] for p in case['patches']], ['out', 'a', 'b'])
            self.assertEqual({p['kind'] for p in case['patches']}, {'value32'})
            self.assertEqual({field['field'] for field in case['address_fields']},
                             {'dpu_dst', 'rdma_src_a', 'rdma_src_b', 'pc_next_address'})
            self.assertTrue(all(field['patched'] for field in case['address_fields']
                                if field['field'] != 'pc_next_address'))

    def test_fdiv_systematic_cases_fit_the_six_banks(self):
        family = self.families['fdiv-systematic']
        self.assertEqual(family['cases'], 8)
        self.assertEqual(family['cases_with_problems'], 0)
        self.assertEqual(family['max_command_bytes'], 176)
        self.assertEqual(family['buffer_sizes'], [64])
        self.assertLessEqual(family['max_region_count'], len(audit.EW_BANKS))

    def test_simple_add_has_no_separate_bundles_and_is_covered(self):
        family = self.families['simple_add']
        self.assertEqual(family['separate_bundles'], 0)
        self.assertEqual(family['audited_via'], 'ew-fp16')
        self.assertEqual(family['ew_fp16_cases_cross_checked'], 54)

    def test_bank_capacity_and_production_baseline(self):
        self.assertEqual(sum(size for _, size in audit.EW_BANKS.values()), 100 * 1024)
        production = self.result['production_baseline']
        self.assertEqual(production['cases'], 9)
        self.assertEqual(production['max_region_count'], 6)
        self.assertEqual(production['union_span'], [0x1000_1000, 0x100F_4000])
        # Staged bundle families use at most A/B/D + command; the production
        # layout adds scratch and task, i.e. exactly the measured six banks.
        self.assertEqual(len(audit.EW_BANKS), production['max_region_count'])


if __name__ == '__main__':
    unittest.main()
