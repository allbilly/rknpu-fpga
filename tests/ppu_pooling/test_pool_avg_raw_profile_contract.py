# SPDX-License-Identifier: MIT
"""Fixture and strict-command contract for captured C8 average pooling."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from tools.ppu.run_pool_avg_raw_profile import CASE, load_contract


class PoolAverageRawProfileContractTests(unittest.TestCase):
    def test_only_declared_address_qwords_relocate(self) -> None:
        manifest, job, capture, raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual((len(raw), len(patched)), (224, 224))
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [15, 22])
        self.assertEqual(capture['addresses']['buffers'], {'in': 4096, 'out': 8192})
        self.assertEqual([i for i in range(28)
                          if raw[i*8:i*8+8] != patched[i*8:i*8+8]], [15, 22])

    def test_average_signature_and_reciprocals_are_exact(self) -> None:
        _manifest, _job, _capture, raw, _patched = load_contract()
        words = struct.unpack('<28Q', raw)
        self.assertEqual(words[8], 0x4001000000106024)
        self.assertEqual(words[9], 0x4001000001016034)
        self.assertEqual(words[10], 0x4001000078006038)
        self.assertEqual(words[11], 0x400100007800603c)
        self.assertEqual(words[27], 0x0081000000600008)

    def test_capture_is_finite_and_complete_bo_tail_is_untouched(self) -> None:
        manifest, _job, _capture, _raw, _patched = load_contract()
        fixture = Path('tests/ppu_pooling/fixtures') / CASE
        words = struct.unpack('<128H', (fixture/'in.bin').read_bytes()[:256])
        self.assertEqual(sum(((word >> 10) & 0x1f) == 0x1f for word in words), 0)
        self.assertEqual(sum((word & 0x7fff) == 0 for word in words), 1)
        values = struct.unpack('<128e', (fixture/'in.bin').read_bytes()[:256])
        self.assertEqual((min(values), max(values)), (-4.0, 11.875))
        self.assertTrue(all(((word >> 10) & 0x1f) != 0 or
                            (word & 0x7fff) == 0 for word in words))
        device = (fixture/'device_out.bin').read_bytes()
        init = (fixture/'out_init.bin').read_bytes()
        self.assertEqual(len(device), 4096)
        self.assertEqual(device[144:], init[144:])
        self.assertEqual(manifest['comparison']['device_output_sha256'],
                         'bea3f03feb736de6e310172765cdfc560bcbd8bb81e90d6ff9e7f0ba45fb7545')

    def test_gate_checks_all_non_address_values_and_geometry(self) -> None:
        rtl = Path('rtl/ppu/rk_ppu_pool_avg_raw_profile.sv').read_text()
        self.assertIn("5'd8: value_for = 32'h00000010", rtl)
        self.assertIn("5'd10, 5'd11: value_for = 32'h00007800", rtl)
        self.assertIn("word_index_q == 5'd15 || word_index_q == 5'd22", rtl)
        self.assertIn("cmd_data[19:16] !== 4'd0", rtl)
        self.assertIn("src_end = {1'b0, src_base_q} + 33'd256", rtl)
        self.assertIn("dst_end = {1'b0, dst_base_q} + 33'd144", rtl)


if __name__ == '__main__':
    unittest.main()
