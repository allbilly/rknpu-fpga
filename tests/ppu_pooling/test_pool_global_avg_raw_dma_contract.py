# SPDX-License-Identifier: MIT
"""Serialized-DMA traffic and whole-BO contract for captured global average."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from tools.ppu.run_pool_avg_global3x5 import (
    CASE, FIXTURE, load_contract,
)

ROOT = Path(__file__).resolve().parents[2]


class PoolGlobalAverageRawDmaContractTests(unittest.TestCase):
    def test_capture_relocations_and_transfer_accounting(self) -> None:
        manifest, job, patched = load_contract()
        raw = (FIXTURE / 'regcmd.bin').read_bytes()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual((len(raw), len(patched)), (224, 224))
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [15, 22])
        changed = [index for index in range(28)
                   if raw[index * 8:index * 8 + 8] != patched[index * 8:index * 8 + 8]]
        self.assertEqual(changed, [15, 22])
        command_reads = 28 * 4
        input_reads = manifest['layout']['input']['logical_bytes'] // 2
        output_writes = manifest['layout']['output']['value_bytes'] // 2
        self.assertEqual((command_reads, input_reads, output_writes), (112, 120, 8))
        self.assertEqual(command_reads + input_reads + output_writes, 240)
        self.assertEqual((224, 240, 16, 480),
                         (command_reads * 2, input_reads * 2,
                          output_writes * 2, (command_reads + input_reads + output_writes) * 2))

    def test_runner_and_dma_keep_invalid_cases_write_free(self) -> None:
        dma = (ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv').read_text()
        runner = (ROOT / 'tools/ppu/run_pool_global_avg_raw_dma.py').read_text()
        bench = (ROOT / 'tests/ppu_pooling/tb_ppu_pool_c8_raw_dma.sv').read_text()
        self.assertIn('rk_ppu_pool_global_avg_raw_profile global_avg_profile_gate', dma)
        self.assertIn('rk_ppu_pool_avg_global3x5_c8_fp16_capture global_avg_pool_leaf', dma)
        self.assertIn("GLOBAL_AVG_INPUT_BYTES = 33'd240", dma)
        self.assertIn("profile_output_bytes != 32'd16", dma)
        self.assertIn("input_atom_q == 8'd14", dma)
        self.assertIn("output_halfword_q == 7'd7", dma)
        self.assertIn("output_writes=0", runner)
        self.assertIn("'+GLOBAL_AVG_CASE=1'", runner)
        self.assertIn('global_avg_case != 0', bench)
        self.assertIn('output_write_count_q != 0', bench)
        self.assertIn('whole_output_bo_compared', runner)

    def test_framework_source_manifests_bind_both_new_modules_and_dma(self) -> None:
        expected_paths = (
            'rtl/ppu/rk_ppu_pool_global_avg_raw_profile.sv',
            'rtl/ppu/rk_ppu_pool_avg_global3x5_c8_fp16_capture.sv',
            'rtl/ppu/rk_ppu_pool_raw_dma.sv',
        )
        for profile_name in ('framework', 'framework_factored'):
            source_manifest = json.loads(
                (ROOT / f'rtl/ddr/{profile_name}/sources.json').read_text())
            paths = [row['path'] for row in source_manifest['sources']]
            for path in expected_paths:
                self.assertEqual(paths.count(path), 1, (profile_name, path))
                row = next(row for row in source_manifest['sources'] if row['path'] == path)
                self.assertEqual(row['sha256'], hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), path)


if __name__ == '__main__':
    unittest.main()
