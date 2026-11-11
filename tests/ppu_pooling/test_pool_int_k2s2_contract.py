#!/usr/bin/env python3
"""Contract checks for the shared signed-integer 2x2/stride-2 reducer."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/ppu_pooling/fixtures'
CORE = ROOT / 'rtl/ppu/rk_ppu_pool_int_k2s2.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_int_k2s2.sv'
RUNNER = ROOT / 'tools/ppu/run_pool_int_k2s2.py'
CASES = {
    'int8_max_k2s2_valid_c16_h2w2': {'elem_w': 8, 'lanes': 16, 'method': 0, 'name': 'maximum'},
    'int8_min_k2s2_valid_c16_h2w2': {'elem_w': 8, 'lanes': 16, 'method': 1, 'name': 'minimum'},
    'int16_max_k2s2_valid_c8_h2w2': {'elem_w': 16, 'lanes': 8, 'method': 0, 'name': 'maximum'},
    'int16_min_k2s2_valid_c8_h2w2': {'elem_w': 16, 'lanes': 8, 'method': 1, 'name': 'minimum'},
}
WRAPPERS = {
    'int8_max_k2s2_valid_c16_h2w2': ROOT / 'rtl/ppu/rk_ppu_pool_max_k2s2_i8_c16_h2w2.sv',
    'int8_min_k2s2_valid_c16_h2w2': ROOT / 'rtl/ppu/rk_ppu_pool_min_k2s2_i8_c16_h2w2.sv',
    'int16_max_k2s2_valid_c8_h2w2': ROOT / 'rtl/ppu/rk_ppu_pool_max_k2s2_i16_c8_h2w2.sv',
    'int16_min_k2s2_valid_c8_h2w2': ROOT / 'rtl/ppu/rk_ppu_pool_min_k2s2_i16_c8_h2w2.sv',
}


def code_only(path: Path) -> str:
    return '\n'.join(line.split('//', 1)[0] for line in path.read_text().splitlines())


class PoolIntK2s2ContractTests(unittest.TestCase):
    def test_core_is_signed_integer_only_with_validated_parameters(self) -> None:
        core = code_only(CORE)
        self.assertIn('parameter integer ELEM_W = 8', core)
        self.assertIn('parameter integer LANES = 16', core)
        self.assertIn('parameter int unsigned METHOD = 0', core)
        self.assertIn('logic signed [ELEM_W-1:0] sa, sb', core)
        self.assertIn('(METHOD == 0) ? ((sa >= sb) ? a : b) : ((sa <= sb) ? a : b)',
                      core)
        self.assertIn('ELEM_W != 8 && ELEM_W != 16', core)
        self.assertIn('LANES != 128 / ELEM_W', core)
        self.assertIn('METHOD != 0 && METHOD != 1', core)
        for forbidden in ('fp16', "16'h", 'nan', 'pad'):
            self.assertNotIn(forbidden, core.lower())

    def test_core_seeds_from_the_first_atom(self) -> None:
        core = code_only(CORE)
        # A zero seed would bias positive-only MAX and negative-only MIN lanes.
        self.assertIn('acc_q <= in_atom', core)
        self.assertIn("count_q == 2'd0", core)

    def test_wrappers_instantiate_the_shared_core_with_expected_parameters(self) -> None:
        for case, spec in CASES.items():
            wrapper = WRAPPERS[case].read_text()
            self.assertIn('rk_ppu_pool_int_k2s2', wrapper)
            self.assertIn(f'.ELEM_W({spec["elem_w"]})', wrapper)
            self.assertIn(f'.LANES({spec["lanes"]})', wrapper)
            self.assertIn(f'.METHOD({spec["method"]})', wrapper)
            self.assertIn('minimum' if spec['method'] else 'maximum',
                          wrapper.lower())

    def test_fixtures_are_the_four_captured_integer_profiles(self) -> None:
        for case, spec in CASES.items():
            manifest = json.loads((FIXTURES / case / 'manifest.json').read_text())
            ppu = manifest['ppu']
            self.assertEqual(manifest['case'], case)
            self.assertEqual(ppu['dtype'],
                             'int8' if spec['elem_w'] == 8 else 'int16')
            self.assertEqual(ppu['method'], spec['name'])
            self.assertEqual(ppu['channels'], spec['lanes'])
            self.assertEqual(ppu['in_shape'], [2, 2])
            self.assertEqual(ppu['out_shape'], [1, 1])
            self.assertEqual(ppu['kernel'], [2, 2])
            self.assertEqual(ppu['stride'], [2, 2])
            self.assertEqual(ppu['padding'], [0, 0, 0, 0])
            self.assertEqual(manifest['comparison']['tolerance'], 0.0)

    def test_replay_covers_the_complete_output_bo_for_all_four_profiles(self) -> None:
        bench = TB.read_text()
        self.assertIn('parameter integer ELEM_W = 8', bench)
        self.assertIn('localparam int unsigned BO_BYTES = 4096', bench)
        self.assertIn('whole-BO mismatch', bench)
        self.assertIn('unsupported integer pooling replay geometry', bench)
        compact = bench.replace(' ', '')
        for spec in CASES.values():
            self.assertIn(f'ELEM_W={spec["elem_w"]}', compact)
            self.assertIn(f'LANES={spec["lanes"]}', compact)
            self.assertIn(f'METHOD={spec["method"]}', compact)
        runner = RUNNER.read_text()
        self.assertIn("counts != (spec['elem_w'], spec['lanes'], spec['method'], 4, 4096)",
                      runner)
        self.assertIn('hardware_accessed', runner)


if __name__ == '__main__':
    unittest.main()
