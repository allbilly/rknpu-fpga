# SPDX-License-Identifier: MIT
"""Capture provenance and exact relocation contract for the C8 raw profile."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from tools.ppu.run_pool_c8_raw_profile import CASE, FATAL_RE, load_contract, sha_bytes


class PoolC8RawProfileContractTests(unittest.TestCase):
    def test_raw_command_is_a_separate_profile_and_only_addresses_relocate(self) -> None:
        manifest, job, capture, raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual(len(raw), 26 * 8)
        self.assertEqual(sha_bytes(raw),
                         '75f7c70eb3eafc8345a634633f9c45df231dad1195f79ad1f9a2ea7038a4cebf')
        self.assertEqual(sha_bytes(patched),
                         '32a8fe3772f79dd74bc1ed6952055d5b2720ccdfbb4bdd11c516ada15142f649')
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [13, 20])
        self.assertEqual(capture['addresses']['buffers'], {'in': 4096, 'out': 8192})
        raw_words, patched_words = struct.unpack('<26Q', raw), struct.unpack('<26Q', patched)
        self.assertEqual([i for i, pair in enumerate(zip(raw_words, patched_words))
                          if pair[0] != pair[1]], [13, 20])
        self.assertEqual(patched_words[25], 0x0081000000600008)

        c3 = struct.unpack('<26Q', Path(
            'tests/ppu_pooling/fixtures/fp16_max_k2s2_c3_tail_h2w2/regcmd.bin').read_bytes())
        c8 = struct.unpack('<26Q', raw)
        self.assertEqual([i for i, pair in enumerate(zip(c3, c8)) if pair[0] != pair[1]],
                         [2, 3, 4, 5, 6, 7, 9, 14, 15, 17, 18, 19, 21, 22])

    def test_captured_shape_layout_and_input_value_domain_are_pinned(self) -> None:
        manifest, _job, _capture, _raw, _patched = load_contract()
        self.assertEqual(manifest['ppu'], {
            'dtype': 'float16', 'method': 'maximum', 'method_selector': 1,
            'channels': 8, 'kernel': [2, 2], 'stride': [1, 1],
            'padding': [0, 0, 0, 0], 'index_en': False, 'use_cnt': 0,
            'in_shape': [4, 4], 'out_shape': [3, 3],
        })
        self.assertEqual(manifest['layout']['input']['logical_bytes'], 256)
        self.assertEqual(manifest['layout']['output']['value_bytes'], 144)
        self.assertEqual(manifest['layout']['input']['buffer_bytes'], 4096)
        self.assertEqual(manifest['layout']['output']['buffer_bytes'], 4096)
        self.assertEqual(manifest['input_value_contract']['positive_zero_lanes'], 1)
        self.assertEqual(manifest['input_value_contract']['infinity_or_nan_lanes'], 0)

    def test_device_output_is_complete_and_tail_is_initialization(self) -> None:
        manifest, _job, capture, _raw, _patched = load_contract()
        fixture = Path('tests/ppu_pooling/fixtures') / CASE
        device = (fixture / 'device_out.bin').read_bytes()
        initial = (fixture / 'out_init.bin').read_bytes()
        self.assertEqual(len(device), 4096)
        self.assertEqual(len(initial), 4096)
        self.assertEqual(device[144:], initial[144:])
        self.assertEqual(sha_bytes(device), manifest['comparison']['device_output_sha256'])
        self.assertEqual(capture['hashes']['outputs']['out']['sha256'], sha_bytes(device))

    def test_runner_flags_simulator_fatal_output(self) -> None:
        for line in ('[460000] %Fatal: assertion failed',
                     'FATAL: testbench.sv: assertion failed',
                     'ERROR: $fatal was called'):
            with self.subTest(line=line):
                self.assertIsNotNone(FATAL_RE.search(line))


if __name__ == '__main__':
    unittest.main()
