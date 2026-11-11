# SPDX-License-Identifier: MIT
"""Capture, relocation and domain contract for padded C8 raw PPU profile."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from tools.ppu.run_pool_pad1_raw_profile import CASE, load_contract, sha_bytes


class Pad1RawProfileContractTests(unittest.TestCase):
    def test_raw_profile_is_distinct_and_only_two_addresses_relocate(self) -> None:
        manifest, job, capture, raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual(len(raw), 26 * 8)
        self.assertEqual(sha_bytes(raw),
                         '2dda5674abe0ffe92df36d2a004b6972f551e49cd2fb89387b28b9f1de665334')
        self.assertEqual(sha_bytes(patched),
                         '70c6b4e1412f451da2193a6a56fcb1994aec4dee43ed82f5dd24d0fb56ae771d')
        self.assertEqual([patch['regcmd_index'] for patch in job['patches']], [13, 20])
        self.assertEqual(capture['addresses']['buffers'], {'in': 4096, 'out': 8192})
        raw_words, patched_words = struct.unpack('<26Q', raw), struct.unpack('<26Q', patched)
        self.assertEqual([index for index, pair in enumerate(zip(raw_words, patched_words))
                          if pair[0] != pair[1]], [13, 20])
        self.assertEqual(patched_words[25], 0x0081000000600008)

        c3 = struct.unpack('<26Q', Path(
            'tests/ppu_pooling/fixtures/fp16_max_k2s2_c3_tail_h2w2/regcmd.bin').read_bytes())
        c8 = struct.unpack('<26Q', Path(
            'tests/ppu_pooling/fixtures/fp16_max_k2s1_valid_c8_h4w4/regcmd.bin').read_bytes())
        self.assertEqual(raw_words[2], c3[2])
        self.assertEqual(raw_words[5], 0x4001000000026018)
        self.assertEqual(c3[5], 0x4001000000006018)
        self.assertNotEqual(raw_words, c8)

    def test_shape_layout_padding_and_negative_input_domain_are_pinned(self) -> None:
        manifest, _job, _capture, _raw, _patched = load_contract()
        self.assertEqual(manifest['ppu']['channels'], 8)
        self.assertEqual(manifest['ppu']['padding'], [1, 1, 1, 1])
        self.assertEqual(manifest['ppu']['padding_value_fp16_bits'], 'fc00')
        self.assertEqual(manifest['layout']['input']['logical_bytes'], 64)
        self.assertEqual(manifest['layout']['output']['value_bytes'], 144)
        self.assertEqual(manifest['layout']['output']['buffer_bytes'], 4096)
        input_bo = Path('tests/ppu_pooling/fixtures')/CASE/'in.bin'
        words = struct.unpack('<32H', input_bo.read_bytes()[:64])
        self.assertTrue(all(word & 0x8000 for word in words))
        self.assertTrue(all((word & 0x7fff) != 0 for word in words))
        self.assertTrue(all(((word >> 10) & 0x1f) != 0x1f for word in words))

    def test_complete_device_output_tail_is_initialization(self) -> None:
        manifest, _job, _capture, _raw, _patched = load_contract()
        fixture = Path('tests/ppu_pooling/fixtures') / CASE
        device = (fixture/'device_out.bin').read_bytes()
        initial = (fixture/'out_init.bin').read_bytes()
        self.assertEqual(len(device), 4096)
        self.assertEqual(device[144:], initial[144:])
        self.assertEqual(manifest['comparison']['device_output_sha256'], sha_bytes(device))


if __name__ == '__main__':
    unittest.main()
