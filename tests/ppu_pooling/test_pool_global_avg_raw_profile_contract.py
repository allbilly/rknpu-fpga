# SPDX-License-Identifier: MIT
"""Pinned provenance and strict raw-command profile contract for global avg."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

from tools.ppu.run_pool_avg_global3x5 import (
    CASE, DONOR, FILES, FIXTURE, MANIFEST, load_contract,
)

ROOT = Path(__file__).resolve().parents[2]


class PoolGlobalAverageRawProfileContractTests(unittest.TestCase):
    def test_capture_and_raw_qwords_are_pinned(self) -> None:
        manifest, job, patched = load_contract()
        raw = (FIXTURE / 'regcmd.bin').read_bytes()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual(manifest['status'], 'READY_CAPTURE_BOUNDED_CANDIDATE')
        self.assertEqual(len(raw), 28 * 8)
        self.assertEqual(job['patches'], [
            {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 15},
            {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 22},
        ])
        changed = [i for i in range(28)
                   if raw[i * 8:i * 8 + 8] != patched[i * 8:i * 8 + 8]]
        self.assertEqual(changed, [15, 22])
        self.assertEqual(manifest['device_capture']['status'], 'OK')
        self.assertEqual(manifest['comparison']['source_expected_equals_device_output'], True)
        self.assertEqual(hashlib.sha256(DONOR.read_bytes()).hexdigest(),
                         manifest['source']['example_sha256'])
        for name in FILES:
            entry = manifest['files'][name]
            self.assertEqual((FIXTURE / name).stat().st_size, entry['bytes'])
            self.assertEqual(hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest(),
                             entry['sha256'])

    def test_numerical_shape_and_complete_output_bo_contract(self) -> None:
        manifest, _job, _patched = load_contract()
        self.assertEqual(manifest['ppu'], {
            'dtype': 'float16', 'method': 'average', 'method_selector': 0,
            'channels': 8, 'kernel': [3, 5], 'stride': [3, 5],
            'padding': [0, 0, 0, 0], 'index_en': False, 'use_cnt': 0,
            'in_shape': [3, 5], 'out_shape': [1, 1],
            'recip_kernel_width': '0x7266', 'recip_kernel_height': '0x7555',
        })
        inp = (FIXTURE / 'in.bin').read_bytes()
        expected = (FIXTURE / 'expected.bin').read_bytes()
        device = (FIXTURE / 'device_out.bin').read_bytes()
        init = (FIXTURE / 'out_init.bin').read_bytes()
        self.assertEqual(len(inp), 4096)
        self.assertEqual(len(expected), 4096)
        self.assertEqual(expected, device)
        self.assertEqual(expected[16:], init[16:])
        lanes = struct.unpack('<8e', expected[:16])
        self.assertEqual(len(lanes), 8)
        self.assertEqual(manifest['comparison']['tail_start'], 16)
        self.assertEqual(manifest['comparison']['logical_value_lanes_fp16'], 8)

    def test_dma_has_separate_profile_and_fixed_frame_contract(self) -> None:
        dma = (ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        profile = (ROOT / 'rtl/ppu/rk_ppu_pool_global_avg_raw_profile.sv').read_text()
        leaf = (ROOT / 'rtl/ppu/rk_ppu_pool_avg_global3x5_c8_fp16_capture.sv').read_text()
        self.assertIn('rk_ppu_pool_global_avg_raw_profile global_avg_profile_gate', dma)
        self.assertIn('rk_ppu_pool_avg_global3x5_c8_fp16_capture global_avg_pool_leaf', dma)
        self.assertIn("profile_input_bytes != 32'd240", dma)
        self.assertIn("profile_output_bytes != 32'd16", dma)
        self.assertIn("input_atom_q == 8'd14", dma)
        self.assertIn('bad_global_avg_input', dma)
        self.assertIn("word_index_q == 5'd15 || word_index_q == 5'd22", profile)
        self.assertIn("cmd_last !== (word_index_q == 5'd27)", profile)
        self.assertIn("rdma_transfer_bytes = 32'd240", profile)
        self.assertIn("output_write_bytes = 32'd16", profile)
        self.assertIn("atom_count_q == 4'd14", leaf)
        self.assertIn("fp16_positive_to_units", leaf)
        self.assertIn('Device differential coverage is only the pinned finite fixture', leaf)


if __name__ == '__main__':
    unittest.main()
