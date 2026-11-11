# SPDX-License-Identifier: MIT
"""Source-provenance and strict-contract checks for the global MAX candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

from tools.ppu.run_pool_global_raw_dma import (
    CASE, FIXTURE, MANIFEST, load_contract,
)

ROOT = Path(__file__).resolve().parents[2]


class PoolGlobalRawDmaContractTests(unittest.TestCase):
    def test_fixture_is_source_emitted_and_explicitly_not_a_device_capture(self) -> None:
        manifest, job, raw, patched = load_contract()
        self.assertEqual(manifest['status'], 'SOURCE_DERIVED_SIMULATION_CANDIDATE')
        self.assertIsNone(manifest['device_capture'])
        self.assertEqual(len(raw), 26 * 8)
        self.assertEqual(job['patches'], [
            {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 13},
            {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 20},
        ])
        self.assertEqual([i for i in range(26)
                          if raw[i * 8:i * 8 + 8] != patched[i * 8:i * 8 + 8]],
                         [13, 20])
        self.assertEqual(manifest['command_stream']['qwords'], 26)
        self.assertIn('not a device capture',
                      manifest['command_stream']['provenance'].lower())

    def test_exact_source_numerics_and_complete_bo_are_pinned(self) -> None:
        manifest, _job, _raw, _patched = load_contract()
        self.assertEqual(manifest['ppu'], {
            'dtype': 'float16', 'method': 'maximum', 'method_selector': 1,
            'channels': 8, 'kernel': [16, 16], 'stride': [16, 16],
            'padding': [0, 0, 0, 0], 'index_en': False, 'use_cnt': 0,
            'in_shape': [16, 16], 'out_shape': [1, 1],
        })
        self.assertEqual((FIXTURE / 'in.bin').stat().st_size, 4096)
        values = struct.unpack('<2048e', (FIXTURE / 'in.bin').read_bytes())
        self.assertEqual(values, tuple(float(value) for value in range(2048)))
        output_init = (FIXTURE / 'out_init.bin').read_bytes()
        expected = (FIXTURE / 'expected.bin').read_bytes()
        self.assertEqual(expected[:16], struct.pack('<8e', *range(2040, 2048)))
        self.assertEqual(expected[16:], output_init[16:])
        self.assertEqual(len(expected), 4096)
        self.assertEqual(hashlib.sha256(expected).hexdigest(),
                         manifest['comparison']['expected_output_sha256'])

    def test_dma_admits_only_bounded_profile_and_domain(self) -> None:
        dma = (ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        profile = (ROOT / 'rtl/ppu/rk_ppu_pool_global_raw_profile.sv').read_text()
        leaf = (ROOT / 'rtl/ppu/rk_ppu_pool_max16x16s16_c8.sv').read_text()
        self.assertIn('rk_ppu_pool_global_raw_profile global_profile_gate', dma)
        self.assertIn('rk_ppu_pool_max16x16s16_c8 global_pool_leaf', dma)
        self.assertIn("profile_input_bytes != 32'd4096", dma)
        self.assertIn("profile_output_bytes != 32'd16", dma)
        self.assertIn("input_atom_q == 8'd255", dma)
        self.assertIn("bad_global_input", dma)
        self.assertIn("word_index_q == 5'd13 || word_index_q == 5'd20", profile)
        self.assertIn("cmd_last !== (word_index_q == 5'd25)", profile)
        self.assertIn("rdma_transfer_bytes = 32'd4096", profile)
        self.assertIn("output_write_bytes = 32'd16", profile)
        self.assertIn("atom_count_q == 8'd255", leaf)

    def test_framework_manifests_bind_both_new_rtl_modules(self) -> None:
        for profile_name in ('framework', 'framework_factored'):
            source_manifest = json.loads(
                (ROOT / f'rtl/ddr/{profile_name}/sources.json').read_text())
            paths = [row['path'] for row in source_manifest['sources']]
            self.assertEqual(paths.count('rtl/ppu/rk_ppu_pool_global_raw_profile.sv'), 1)
            self.assertEqual(paths.count('rtl/ppu/rk_ppu_pool_max16x16s16_c8.sv'), 1)
            for path in ('rtl/ppu/rk_ppu_pool_global_raw_profile.sv',
                         'rtl/ppu/rk_ppu_pool_max16x16s16_c8.sv',
                         'rtl/ppu/rk_ppu_pool_raw_dma.sv'):
                row = next(row for row in source_manifest['sources'] if row['path'] == path)
                actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                self.assertEqual(actual, row['sha256'], path)


if __name__ == '__main__':
    unittest.main()
