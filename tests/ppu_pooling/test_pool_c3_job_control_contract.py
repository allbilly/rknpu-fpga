# SPDX-License-Identifier: MIT
"""Static compatibility checks for the isolated RKPP control page."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PoolC3JobControlContractTests(unittest.TestCase):
    def test_ppu_control_page_is_opt_in_and_distinct_from_layout(self) -> None:
        source = (ROOT / 'rtl/ddr/framework/rk_layout_job_control.sv').read_text()
        self.assertIn("parameter bit ENABLE_PPU = 1'b0", source)
        self.assertIn("page===24'h000003 && ENABLE_PPU", source)
        self.assertIn("32'h524b5050", source)
        self.assertIn("page===24'h000004", source)
        bench = (ROOT / 'tests/ppu_pooling/tb_ppu_c3_job_control.sv').read_text()
        self.assertIn("read_reg(32'h00000400, 32'h524b4c59", bench)
        self.assertIn("wire selected_layout=ui_start_kind===2'd2", (
            ROOT / 'rtl/ddr/framework_factored/rk_layout_compute_dispatch_ppu.sv').read_text())
        self.assertIn("wire selected_ppu=ui_start_kind===2'd3", (
            ROOT / 'rtl/ddr/framework_factored/rk_layout_compute_dispatch_ppu.sv').read_text())

    def test_selected_framework_profiles_bind_c3_rtl_sources(self) -> None:
        expected = {
            'rtl/ppu/rk_ppu_pool_c3_raw_profile.sv',
            'rtl/ppu/rk_ppu_pool_max2x2s2_c3_tail_h2w2.sv',
            'rtl/ppu/rk_ppu_pool_c8_raw_profile.sv',
            'rtl/ppu/rk_ppu_pool_max2x2s1_c8.sv',
            'rtl/ppu/rk_ppu_pool_pad1_raw_profile.sv',
            'rtl/ppu/rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2.sv',
            'rtl/ppu/rk_ppu_pool_min_raw_profile.sv',
            'rtl/ppu/rk_ppu_pool_min2x2s1_fp16_capture.sv',
            'rtl/ppu/rk_ppu_pool_avg_raw_profile.sv',
            'rtl/ppu/rk_ppu_pool_avg2x2s1_fp16_capture.sv',
            'rtl/ppu/rk_ppu_pool_raw_dma.sv',
        }
        for profile in ('framework', 'framework_factored'):
            with self.subTest(profile=profile):
                manifest = json.loads((ROOT / f'rtl/ddr/{profile}/sources.json').read_text())
                paths = {row['path'] for row in manifest['sources']}
                self.assertTrue(expected.issubset(paths))
                self.assertEqual(manifest['sources'][63]['path'],
                                 f'rtl/ddr/{profile}/rk_layout_compute_dispatch_ppu.sv')

        for profile in ('dual_host', 'dual_host_factored',
                        'dual_host_maintenance_fi', 'dual_host_shared_cacc'):
            with self.subTest(non_ppu_profile=profile):
                manifest = json.loads((ROOT / f'rtl/ddr/{profile}/sources.json').read_text())
                paths = {row['path'] for row in manifest['sources']}
                self.assertNotIn(f'rtl/ddr/{profile}/rk_layout_compute_dispatch_ppu.sv', paths)
                self.assertTrue(any(path.endswith('/rk_layout_compute_dispatch.sv')
                                    for path in paths))

    def test_control_simulation_covers_ready_fault_and_ack_ownership(self) -> None:
        bench = (ROOT / 'tests/ppu_pooling/tb_ppu_c3_job_control.sv').read_text()
        self.assertIn("write_reg(PPU_PAGE + 32'h0c, 32'd1, 2'b10)", bench)
        self.assertIn("last_start_kind !== 2'd3", bench)
        self.assertIn("write_reg(PPU_PAGE + 32'h0c, 32'd2, 2'b00)", bench)
        self.assertIn("write_reg(PPU_PAGE + 32'h0c, 32'd2, 2'b10)", bench)


if __name__ == '__main__':
    unittest.main()
