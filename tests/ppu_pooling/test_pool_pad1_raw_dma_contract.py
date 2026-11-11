# SPDX-License-Identifier: MIT
"""Fixture, routing and serialized-traffic contract for padded C8 PPU DMA."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from tools.ppu.run_pool_pad1_raw_profile import CASE, load_contract


class Pad1RawDmaContractTests(unittest.TestCase):
    def test_capture_geometry_requires_exactly_208_serial_transactions(self) -> None:
        manifest, job, capture, raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual((len(raw), len(patched)), (208, 208))
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [13, 20])
        self.assertEqual(capture['addresses']['buffers'], {'in': 4096, 'out': 8192})
        command_reads = 26 * 4
        input_reads = manifest['layout']['input']['logical_bytes'] // 2
        output_writes = manifest['layout']['output']['value_bytes'] // 2
        self.assertEqual((command_reads, input_reads, output_writes), (104, 32, 72))
        self.assertEqual(command_reads + input_reads + output_writes, 208)
        self.assertEqual(manifest['layout']['input']['logical_bytes'], 64)
        self.assertEqual(manifest['layout']['output']['value_bytes'], 144)

    def test_signature_keeps_padded_c8_distinct_from_c3_and_valid_c8(self) -> None:
        _manifest, _job, _capture, raw, _patched = load_contract()
        words = struct.unpack('<26Q', raw)
        c3 = struct.unpack('<26Q', Path(
            'tests/ppu_pooling/fixtures/fp16_max_k2s2_c3_tail_h2w2/regcmd.bin').read_bytes())
        c8 = struct.unpack('<26Q', Path(
            'tests/ppu_pooling/fixtures/fp16_max_k2s1_valid_c8_h4w4/regcmd.bin').read_bytes())
        self.assertEqual((words[2], words[5]), (c3[2], 0x4001000000026018))
        self.assertEqual(c3[5], 0x4001000000006018)
        self.assertEqual(words[2], 0x400100000001600c)
        self.assertEqual(c8[2], 0x400100000003600c)

    def test_complete_device_bo_tail_is_untouched_and_input_is_strict(self) -> None:
        manifest, _job, _capture, _raw, _patched = load_contract()
        fixture = Path('tests/ppu_pooling/fixtures') / CASE
        device = (fixture/'device_out.bin').read_bytes()
        initial = (fixture/'out_init.bin').read_bytes()
        words = struct.unpack('<32H', (fixture/'in.bin').read_bytes()[:64])
        self.assertEqual(len(device), 4096)
        self.assertEqual(device[144:], initial[144:])
        self.assertEqual(manifest['comparison']['device_output_sha256'],
                         'a18647840e9e8c3abb2f004ee47e6d629d735755b8dbdd5e5b340e314f03411e')
        self.assertTrue(all((word & 0x8000) and (word & 0x7fff) != 0 and
                            ((word >> 10) & 0x1f) not in (0, 0x1f) for word in words))

    def test_dma_uses_dedicated_padded_profile_and_delays_all_writes(self) -> None:
        rtl = Path('rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        bench = Path('tests/ppu_pooling/tb_ppu_pool_c8_raw_dma.sv').read_text()
        self.assertIn('rk_ppu_pool_pad1_raw_profile pad1_profile_gate', rtl)
        self.assertIn('rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2 pad1_pool_leaf', rtl)
        self.assertIn('command_qword[5][47:16] == 32\'h00000002', rtl)
        self.assertIn('bad_pad1_input', rtl)
        self.assertIn('c8_output_atoms[c8_output_count_q] <= pool_out_atom', rtl)
        self.assertIn("(!index_selected_q && !global_selected_q && !global_avg_selected_q &&\n                                 c8_output_count_q == 4'd9)", rtl)
        self.assertIn("((index_selected_q || global_selected_q || global_avg_selected_q) &&\n                                  c8_output_count_q == 4'd1)", rtl)
        self.assertIn("if (pad1_case != 0 && mode >= 6 && mode <= 10", bench)
        self.assertIn('input_read_count_q != 0', bench)


if __name__ == '__main__':
    unittest.main()
