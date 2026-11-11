# SPDX-License-Identifier: MIT
"""Capture-boundary tests for the indexed MAX raw-command profile."""
from __future__ import annotations

import json
import unittest

from tools.ppu.run_pool_index import FIXTURE, MANIFEST, fixture_check
from tools.ppu.run_pool_index_raw_profile import RTL, load_contract


class PoolIndexRawProfileContractTests(unittest.TestCase):
    def test_pinned_capture_relocations_and_geometry(self) -> None:
        manifest, job, capture, raw, patched = load_contract()
        self.assertEqual(len(raw), 26 * 8)
        self.assertEqual(job['patches'], [
            {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 13},
            {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 20},
        ])
        self.assertEqual(capture['addresses']['buffers'], {'in': 4096, 'out': 8192})
        self.assertEqual([i for i in range(26)
                          if raw[i*8:i*8+8] != patched[i*8:i*8+8]], [13, 20])
        self.assertEqual(manifest['layout']['output']['index_offset'], 32)
        self.assertEqual(manifest['layout']['output']['logical_bytes'], 48)

    def test_complete_fixture_and_numeric_admission_are_pinned(self) -> None:
        fixture = fixture_check()
        manifest = fixture['manifest']
        self.assertEqual(manifest['input_value_contract']['finite_lanes'], 32)
        self.assertEqual(manifest['input_value_contract']['positive_zero_lanes'], 24)
        self.assertTrue(manifest['input_value_contract']['unique_maximum_per_channel'])
        self.assertEqual(manifest['layout']['output']['index_offset'], 32)
        self.assertEqual((FIXTURE / 'expected.bin').read_bytes(),
                         (FIXTURE / 'device_out.bin').read_bytes())

    def test_gate_is_strict_and_reserves_the_gap_without_relocating_other_words(self) -> None:
        text = RTL.read_text()
        self.assertIn("word_index_q == 5'd13 || word_index_q == 5'd20", text)
        self.assertIn("cmd_last !== (word_index_q == 5'd25)", text)
        self.assertIn("src_end = {1'b0, src_base_q} + 33'd64", text)
        self.assertIn("dst_end = {1'b0, dst_base_q} + 33'd48", text)
        self.assertIn("rdma_transfer_bytes = 32'd64", text)
        self.assertIn("output_write_bytes = 32'd48", text)

    def test_unique_flag_is_exported_and_stable_with_the_paired_outputs(self) -> None:
        leaf = (FIXTURE.parents[3] / 'rtl/ppu/rk_ppu_pool_max2x2s2_index_c8_h2w2.sv').read_text()
        self.assertIn('output logic [7:0]   out_unique', leaf)
        self.assertIn('unique_mask_q <= unique_mask_next', leaf)
        bench = (FIXTURE.parents[3] / 'tests/ppu_pooling/tb_ppu_pool_max2x2s2_index_c8_h2w2.sv').read_text()
        self.assertIn("out_unique !== 8'hff", bench)
        self.assertIn('out_unique !== held_unique', bench)


if __name__ == '__main__':
    unittest.main()
