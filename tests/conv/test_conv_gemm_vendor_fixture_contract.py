#!/usr/bin/env python3
"""Contract checks for the frozen conv-gemm-vendor fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/conv/fixtures'
FREEZER = ROOT / 'tools/conv/freeze_vendor_fixtures.py'
FAMILY = ROOT / 'build/rk3588-example-captures/conv-gemm-vendor/manifest.json'
FROZEN_GEMM = ('gemm_m2_n2_k1', 'gemm_m1_n16_k32', 'gemm_m2_n16_k32',
               'gemm_m4_n32_k64')
FROZEN_CONV = ('conv_1x1_c1_oc6_h4w4', 'conv_grouped_3x3_c4_oc4_g2_h5w5',
               'conv_legacy_3x3_c4_oc4_h9w9')
REJECTED = ('conv_depthwise_3x3_c3_oc3_h11w28_task0',
            'conv_depthwise_3x3_c3_oc3_h11w28_task1',
            'conv_py_3x3_c32_oc128_h14w14_fullsetup')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ConvGemmVendorFixtureContractTests(unittest.TestCase):
    def test_every_ready_case_is_either_frozen_or_rejected(self) -> None:
        family = json.loads(FAMILY.read_text())['cases']
        ready = [row['case'] for row in family if row['status'] == 'READY']
        frozen = [case for case in ready
                  if (FIXTURES / case / 'manifest.json').is_file()]
        rejected = [case for case in ready if case not in frozen]
        # Nothing may be silently missing: every READY case falls into exactly
        # one of the two buckets.
        self.assertEqual(len(frozen) + len(rejected), len(ready))
        self.assertEqual(set(frozen), set(FROZEN_GEMM + FROZEN_CONV))
        self.assertEqual(set(rejected), set(REJECTED))

    def test_frozen_fixtures_are_hash_bound(self) -> None:
        for case in FROZEN_GEMM + FROZEN_CONV:
            manifest = json.loads((FIXTURES / case / 'manifest.json').read_text())
            self.assertEqual(manifest['case'], case)
            self.assertEqual(manifest['status'], 'READY_CAPTURE_BOUNDED_CANDIDATE')
            self.assertEqual(manifest['device_capture']['submit_ret'], 0)
            self.assertEqual(manifest['device_capture']['errors'], [])
            for name, record in manifest['files'].items():
                path = FIXTURES / case / name
                self.assertEqual(path.stat().st_size, record['bytes'], name)
                self.assertEqual(sha(path), record['sha256'], name)

    def test_gemm_oracle_is_recomputed_not_merely_repacked(self) -> None:
        for case in FROZEN_GEMM:
            manifest = json.loads((FIXTURES / case / 'manifest.json').read_text())
            self.assertEqual(manifest['oracle_kind'], 'gemm')
            self.assertIn('recomputed_sha256', manifest['output'])
            recomputed = (FIXTURES / case / 'oracle_recomputed.bin').read_bytes()
            device = (FIXTURES / case / 'device_out.bin').read_bytes()
            comparison = manifest['comparison']
            if comparison['mode'] == 'exact':
                self.assertEqual(recomputed, device[:len(recomputed)], case)
            else:
                self.assertLessEqual(comparison['max_abs_diff'],
                                     comparison['tolerance'], case)

    def test_conv_oracle_provenance_is_stated(self) -> None:
        for case in FROZEN_CONV:
            manifest = json.loads((FIXTURES / case / 'manifest.json').read_text())
            if manifest['oracle_kind'] == 'conv_host_oracle_repack':
                self.assertIn('provenance', manifest['oracle_contract'])
                self.assertIn('not recomputed', manifest['oracle_contract']['provenance'])

    def test_rejections_are_quantified(self) -> None:
        """The rejected cases must have a measured reason recorded in the doc."""
        doc = (ROOT / 'docs/CONV_GEMM_VENDOR_FIXTURES.md').read_text()
        for case in REJECTED:
            self.assertFalse((FIXTURES / case / 'manifest.json').exists(), case)
            self.assertIn(case, doc, case)
        # The depthwise pair shares a device hash: a different failure than a
        # numeric disagreement, and worth stating exactly.
        results = ROOT / 'build/rk3588-example-captures/results/conv-gemm-vendor-20261105T214000Z/conv-gemm-vendor'
        first = sha(results / REJECTED[0] / 'output.bin')
        second = sha(results / REJECTED[1] / 'output.bin')
        self.assertEqual(first, second,
                         'depthwise task0/task1 device BOs must still be identical')
        self.assertIn('23762b45', doc)

    def test_freezer_recomputes_a_gemm_surface(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location('freezer', FREEZER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        family = json.loads(FAMILY.read_text())['cases']
        row = next(r for r in family if r['case'] == 'gemm_m1_n16_k32')
        bundle = ROOT / 'build/rk3588-example-captures/conv-gemm-vendor/cases' / row['case']
        recomputed, facts = module.oracle(row['case'], row, bundle)
        self.assertEqual(facts['kind'], 'gemm')
        device = (ROOT / 'build/rk3588-example-captures/results/'
                  'conv-gemm-vendor-20261105T214000Z/conv-gemm-vendor/gemm_m1_n16_k32/'
                  'output.bin').read_bytes()
        self.assertEqual(recomputed, device[:len(recomputed)])

    def test_no_gemm_or_conv_leaf_claims_these_fixtures_yet(self) -> None:
        """Fixtures are the precondition; no RTL executes them, and the table says so."""
        table = (ROOT / 'docs/PROGRESS_TABLE.md').read_text()
        self.assertIn('conv-gemm-vendor', table)
        # No source file may reference a vendor-gemm fixture by name.
        for path in (ROOT / 'rtl').rglob('*.sv'):
            text = path.read_text()
            for case in FROZEN_GEMM + FROZEN_CONV:
                self.assertNotIn(case, text, f'{path.name} names {case}')


if __name__ == '__main__':
    unittest.main()
