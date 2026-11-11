# SPDX-License-Identifier: MIT
"""Fixture and serialized-traffic contract for the C3 raw DMA engine."""
from __future__ import annotations

import unittest
from pathlib import Path

from tools.ppu.run_pool_c3_raw_profile import CASE, load_contract


class PoolC3RawDmaContractTests(unittest.TestCase):
    def test_fixture_geometry_is_exactly_144_halfword_transactions(self) -> None:
        manifest, job, capture, _raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual(len(patched), 26 * 8)
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [13, 20])
        self.assertEqual(capture['addresses']['buffers'], {'in': 4096, 'out': 8192})

        command_reads = (26 * 8) // 2
        input_reads = manifest['layout']['input']['logical_bytes'] // 2
        output_writes = manifest['layout']['output']['value_bytes'] // 2
        self.assertEqual((command_reads, input_reads, output_writes), (104, 32, 8))
        self.assertEqual(command_reads + input_reads + output_writes, 144)
        self.assertEqual(manifest['layout']['input']['buffer_bytes'], 4096)
        self.assertEqual(manifest['layout']['output']['buffer_bytes'], 4096)

    def test_full_output_comparison_is_the_pinned_device_capture(self) -> None:
        manifest, _job, _capture, _raw, _patched = load_contract()
        comparison = manifest['comparison']
        self.assertEqual(comparison['scope'], 'complete 4096-byte output BO including physical output tail')
        self.assertEqual(comparison['mismatches_expected'], 0)
        self.assertEqual(comparison['tolerance'], 0.0)
        self.assertEqual(comparison['device_output_sha256'],
                         comparison['source_expected_sha256'])
        self.assertTrue(Path('tests/ppu_pooling/tb_ppu_pool_c3_raw_dma.sv').is_file())

    def test_single_frame_leaf_is_rearmed_between_jobs(self) -> None:
        rtl = Path('rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        bench = Path('tests/ppu_pooling/tb_ppu_pool_c3_raw_dma.sv').read_text()
        self.assertIn('pool_leaf_rst_n_q <= 1\'b0', rtl)
        self.assertIn('.rst_n(pool_leaf_rst_n)', rtl)
        self.assertIn('profile_gate_rst_n_q <= 1\'b0', rtl)
        self.assertIn('.rst_n(profile_gate_rst_n_q && rst_n)', rtl)
        self.assertIn('if (mode == 5)', bench)
        self.assertIn('same-epoch PPU job timed out', bench)


if __name__ == '__main__':
    unittest.main()
