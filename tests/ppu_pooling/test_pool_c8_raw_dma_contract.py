# SPDX-License-Identifier: MIT
"""Fixture and serialized-traffic contract for the integrated C8 PPU route."""
from __future__ import annotations

import unittest
from pathlib import Path

from tools.ppu.run_pool_c8_raw_profile import CASE, load_contract


class PoolC8RawDmaContractTests(unittest.TestCase):
    def test_capture_geometry_requires_exactly_304_transactions(self) -> None:
        manifest, job, capture, _raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual(len(patched), 26 * 8)
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [13, 20])
        self.assertEqual(capture['addresses']['buffers'], {'in': 4096, 'out': 8192})
        command_reads = 26 * 4
        input_reads = manifest['layout']['input']['logical_bytes'] // 2
        output_writes = manifest['layout']['output']['value_bytes'] // 2
        self.assertEqual((command_reads, input_reads, output_writes), (104, 128, 72))
        self.assertEqual(command_reads + input_reads + output_writes, 304)
        self.assertEqual(manifest['layout']['input']['buffer_bytes'], 4096)
        self.assertEqual(manifest['layout']['output']['buffer_bytes'], 4096)

    def test_output_contract_is_complete_device_bo_with_untouched_tail(self) -> None:
        manifest, _job, _capture, _raw, _patched = load_contract()
        fixture = Path('tests/ppu_pooling/fixtures') / CASE
        device = (fixture / 'device_out.bin').read_bytes()
        initial = (fixture / 'out_init.bin').read_bytes()
        self.assertEqual(len(device), 4096)
        self.assertEqual(manifest['comparison']['device_output_sha256'],
                         manifest['comparison']['source_expected_sha256'])
        self.assertEqual(device[144:], initial[144:])

    def test_dma_validates_entire_c8_input_before_first_device_write(self) -> None:
        rtl = Path('rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        bench = Path('tests/ppu_pooling/tb_ppu_pool_c8_raw_dma.sv').read_text()
        self.assertIn("mem_rsp_rdata[14:10] == 5'h1f", rtl)
        self.assertIn("mem_rsp_rdata[15]", rtl)
        self.assertIn('c8_output_atoms[c8_output_count_q] <= pool_out_atom', rtl)
        self.assertIn("(!index_selected_q && !global_selected_q && !global_avg_selected_q &&", rtl)
        self.assertIn("c8_output_count_q == 4'd9))", rtl)
        self.assertIn("((index_selected_q || global_selected_q || global_avg_selected_q) &&", rtl)
        self.assertIn("c8_output_count_q == 4'd1)", rtl)
        self.assertIn('ST_C8_OUTPUT_REQUEST', rtl)
        self.assertIn('mode == 6 || mode == 7 || mode == 8', bench)
        self.assertIn('input_read_count_q != 101', bench)
        self.assertIn('input_read_count_q != 128', bench)


if __name__ == '__main__':
    unittest.main()
