# SPDX-License-Identifier: MIT
"""Static controls for indexed MAX integration into the owned raw DMA."""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PoolIndexRawDmaContractTests(unittest.TestCase):
    def test_shared_dma_selects_distinct_index_profile_and_leaf(self) -> None:
        dma = (ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        self.assertIn("command_qword[8] == 64'h4001400000116024", dma)
        self.assertIn('rk_ppu_pool_index_raw_profile index_profile_gate', dma)
        self.assertIn('rk_ppu_pool_max2x2s2_index_c8_h2w2 index_pool_leaf', dma)
        self.assertIn("profile_output_bytes != 32'd48", dma)
        self.assertIn("index_pool_unique !== 8'hff", dma)

    def test_dma_buffers_before_split_value_index_writes(self) -> None:
        dma = (ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        self.assertIn("32'd32 + {24'd0, (output_halfword_q - 7'd8), 1'b0}", dma)
        self.assertIn("output_halfword_q == 7'd15", dma)
        self.assertIn('index_value_atom_q <= index_pool_value_atom', dma)
        self.assertIn('index_index_atom_q <= index_pool_index_atom', dma)
        self.assertIn("(index_selected_q || global_selected_q || global_avg_selected_q) &&", dma)
        self.assertIn("c8_output_count_q == 4\'d1", dma)

    def test_input_domain_and_unique_control_reject_without_writes(self) -> None:
        dma = (ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        self.assertIn('bad_index_input', dma)
        self.assertIn('state_q == ST_C8_INPUT_RESPONSE && bad_index_input', dma)
        runner = (ROOT / 'tools/ppu/run_pool_index_raw_dma.py').read_text()
        self.assertIn("'output_halfword_writes': 16", runner)
        self.assertIn("'writes_before_all_inputs_and_unique_max_validation': 0", runner)
        self.assertIn("'tied_maximum_per_channel'", runner)

    def test_framework_source_manifests_bind_new_strict_gate(self) -> None:
        import json
        for profile in ('framework', 'framework_factored'):
            manifest = json.loads((ROOT / f'rtl/ddr/{profile}/sources.json').read_text())
            rows = [row for row in manifest['sources']
                    if row['path'] == 'rtl/ppu/rk_ppu_pool_index_raw_profile.sv']
            self.assertEqual(len(rows), 1)


if __name__ == '__main__':
    unittest.main()
