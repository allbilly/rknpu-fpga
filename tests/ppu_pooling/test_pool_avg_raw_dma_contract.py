# SPDX-License-Identifier: MIT
"""Fixture and serialized-traffic contract for average-pool raw DMA."""
from __future__ import annotations

import struct
import unittest
from pathlib import Path

from tools.ppu.run_pool_avg_raw_profile import CASE, load_contract


class PoolAverageRawDmaContractTests(unittest.TestCase):
    def test_28_qword_capture_has_exact_serialized_transfer_cost(self) -> None:
        manifest, job, _capture, raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual((len(raw), len(patched)), (224, 224))
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [15, 22])
        command_reads = 28 * 4
        input_reads = manifest['layout']['input']['logical_bytes'] // 2
        output_writes = manifest['layout']['output']['value_bytes'] // 2
        self.assertEqual((command_reads, input_reads, output_writes), (112, 128, 72))
        self.assertEqual(command_reads + input_reads + output_writes, 312)

    def test_capture_input_domain_and_whole_bo_contract(self) -> None:
        fixture = Path('tests/ppu_pooling/fixtures') / CASE
        words = struct.unpack('<128H', (fixture/'in.bin').read_bytes()[:256])
        self.assertEqual(sum(((word >> 10) & 0x1f) == 0x1f for word in words), 0)
        self.assertEqual(sum((word & 0x7fff) == 0 for word in words), 1)
        values = struct.unpack('<128e', (fixture/'in.bin').read_bytes()[:256])
        self.assertEqual((min(values), max(values)), (-4.0, 11.875))
        device = (fixture/'device_out.bin').read_bytes()
        init = (fixture/'out_init.bin').read_bytes()
        self.assertEqual(len(device), 4096)
        self.assertEqual(device[144:], init[144:])

    def test_shared_dma_fetches_two_closed_command_lengths_and_validates_before_write(self) -> None:
        rtl = Path('rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        bench = Path('tests/ppu_pooling/tb_ppu_pool_c8_raw_dma.sv').read_text()
        self.assertIn("COMMAND_26_BYTES = 33'd208", rtl)
        self.assertIn("COMMAND_28_BYTES = 33'd224", rtl)
        self.assertIn('logic [63:0] command_qword [0:27]', rtl)
        self.assertIn("command_qwords_q == 6'd28", rtl)
        self.assertIn("command_qword[8] == 64'h4001000000106024", rtl)
        self.assertIn('rk_ppu_pool_avg_raw_profile avg_profile_gate', rtl)
        self.assertIn('rk_ppu_pool_avg2x2s1_fp16_capture avg_pool_leaf', rtl)
        self.assertIn('avg_selected_q && state_q == ST_C8_INPUT_SEND', rtl)
        self.assertIn('avg_case != 0 && ((mode >= 6 && mode <= 9) || mode == 15 || mode == 16)', bench)
        self.assertIn('avg_case != 0 && mode >= 10 && mode <= 14', bench)
        self.assertIn("mem_rsp_rdata == 16'h8000", rtl)
        self.assertIn("mem_rsp_rdata[14:0] > 15'h4400", rtl)
        self.assertIn("mem_rsp_rdata > 16'h49f0", rtl)


if __name__ == '__main__':
    unittest.main()
