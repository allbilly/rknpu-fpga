# SPDX-License-Identifier: MIT
"""Fixture and serialized-traffic contract for minimum-pool raw DMA."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from tools.ppu.run_pool_min_raw_profile import CASE, load_contract


class MinRawDmaContractTests(unittest.TestCase):
    def test_capture_geometry_is_exactly_304_halfword_transactions(self) -> None:
        manifest, job, _capture, raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual((len(raw), len(patched)), (208, 208))
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [13, 20])
        command_reads = 26 * 4
        input_reads = manifest['layout']['input']['logical_bytes'] // 2
        output_writes = manifest['layout']['output']['value_bytes'] // 2
        self.assertEqual((command_reads, input_reads, output_writes), (104, 128, 72))
        self.assertEqual(command_reads + input_reads + output_writes, 304)

    def test_capture_input_has_only_admitted_finite_normal_and_positive_zero(self) -> None:
        fixture = Path('tests/ppu_pooling/fixtures') / CASE
        words = struct.unpack('<128H', (fixture/'in.bin').read_bytes()[:256])
        self.assertEqual(words.count(0), 1)
        self.assertNotIn(0x8000, words)
        self.assertTrue(all(((word >> 10) & 0x1f) not in (0, 0x1f)
                            for word in words if word != 0))
        device = (fixture/'device_out.bin').read_bytes()
        initial = (fixture/'out_init.bin').read_bytes()
        self.assertEqual(len(device), 4096)
        self.assertEqual(device[144:], initial[144:])

    def test_dma_selects_minimum_gate_and_buffers_before_writes(self) -> None:
        rtl = Path('rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        bench = Path('tests/ppu_pooling/tb_ppu_pool_c8_raw_dma.sv').read_text()
        self.assertIn('rk_ppu_pool_min_raw_profile min_profile_gate', rtl)
        self.assertIn('rk_ppu_pool_min2x2s1_fp16_capture min_pool_leaf', rtl)
        self.assertIn("command_qword[8] == 64'h4001000000126024", rtl)
        self.assertIn("profile_input_bytes != 32'd256", rtl)
        self.assertIn("profile_output_bytes != 32'd144", rtl)
        self.assertIn("mem_rsp_rdata == 16'h8000", rtl)
        self.assertIn("mem_rsp_rdata[14:10] == 5'd0 && mem_rsp_rdata[9:0] != 10'd0", rtl)
        self.assertIn('c8_output_atoms[c8_output_count_q] <= pool_out_atom', rtl)
        self.assertIn("(!index_selected_q && !global_selected_q && "
                      "!global_avg_selected_q &&", rtl)
        self.assertIn("c8_output_count_q == 4'd9", rtl)
        self.assertIn("c8_output_count_q == 4'd1", rtl)
        self.assertIn("index_selected_q || global_selected_q || "
                      "global_avg_selected_q", rtl)
        self.assertIn('min_case != 0 && mode >= 6 && mode <= 10', bench)
        self.assertIn('min_case != 0 && mode >= 11', bench)


if __name__ == '__main__':
    unittest.main()
