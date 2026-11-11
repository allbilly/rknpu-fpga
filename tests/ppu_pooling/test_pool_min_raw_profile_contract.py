# SPDX-License-Identifier: MIT
"""Fixture and strict-profile contract for captured minimum pooling."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from tools.ppu.run_pool_min_raw_profile import CASE, load_contract


class MinRawProfileContractTests(unittest.TestCase):
    def test_capture_is_exactly_the_two_address_relocation_profile(self) -> None:
        manifest, job, capture, raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual((len(raw), len(patched)), (208, 208))
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [13, 20])
        self.assertEqual(capture['addresses']['buffers'], {'in': 4096, 'out': 8192})
        self.assertEqual([i for i in range(26)
                          if raw[i*8:i*8+8] != patched[i*8:i*8+8]], [13, 20])

    def test_minimum_operation_signature_is_not_valid_maximum(self) -> None:
        _manifest, _job, _capture, raw, _patched = load_contract()
        words = struct.unpack('<26Q', raw)
        max_words = struct.unpack('<26Q', Path(
            'tests/ppu_pooling/fixtures/fp16_max_k2s1_valid_c8_h4w4/regcmd.bin'
        ).read_bytes())
        self.assertEqual(words[2], max_words[2])
        self.assertEqual(words[8], 0x4001000000126024)
        self.assertEqual(max_words[8], 0x4001000000116024)
        self.assertEqual(words[10:13], max_words[10:13])
        self.assertEqual(words[16], max_words[16])

    def test_capture_and_finite_input_contract_remain_pinned(self) -> None:
        manifest, _job, _capture, _raw, _patched = load_contract()
        fixture = Path('tests/ppu_pooling/fixtures') / CASE
        device = (fixture/'device_out.bin').read_bytes()
        initial = (fixture/'out_init.bin').read_bytes()
        self.assertEqual(len(device), 4096)
        self.assertEqual(device[144:], initial[144:])
        self.assertEqual(manifest['comparison']['device_output_sha256'],
                         'bca82f92970dbcd7ad4a31a89d3f1e0868276c16b25185b8081e8e3234bd4d6a')
        words = struct.unpack('<128H', (fixture/'in.bin').read_bytes()[:256])
        self.assertEqual(sum(((word >> 10) & 0x1f) != 0x1f for word in words), 128)
        self.assertEqual(words.count(0), 1)
        self.assertEqual(words.count(0x8000), 0)

    def test_validator_rejects_changed_pool_method_and_reserved_fields(self) -> None:
        rtl = Path('rtl/ppu/rk_ppu_pool_min_raw_profile.sv').read_text()
        self.assertIn("5'd8: value_for = 32'h00000012", rtl)
        self.assertIn("5'd9: value_for = 32'h00000101", rtl)
        self.assertIn("word_index_q == 5'd13 || word_index_q == 5'd20", rtl)
        self.assertIn("cmd_data[19:16] !== 4'd0", rtl)
        self.assertIn("src_end = {1'b0, src_base_q} + 33'd256", rtl)
        self.assertIn("dst_end = {1'b0, dst_base_q} + 33'd144", rtl)


if __name__ == '__main__':
    unittest.main()
