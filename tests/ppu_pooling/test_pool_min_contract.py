# SPDX-License-Identifier: MIT
"""Strict negative controls for the one captured FP16 minimum fixture."""
from __future__ import annotations

import copy
import json
import unittest

from tools.ppu.run_pool_min import (
    FIXTURE_FILES,
    MANIFEST,
    fixture_check,
    source_oracle,
    validate_contract,
)


class PoolMinimumCaptureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text())

    def test_pinned_fixture_and_independent_finite_oracle(self) -> None:
        validate_contract(self.manifest)
        fixture = fixture_check()
        self.assertEqual(set(fixture['files']), set(FIXTURE_FILES))
        self.assertEqual(fixture['files']['device_out.bin']['bytes'], 4096)
        self.assertEqual(fixture['files']['in.bin']['bytes'], 4096)

    def test_rejects_mode_shape_layout_and_numeric_drift(self) -> None:
        mutations = (
            (('ppu', 'method'), 'maximum'),
            (('ppu', 'method_selector'), 1),
            (('ppu', 'in_shape'), [2, 2]),
            (('ppu', 'out_shape'), [4, 4]),
            (('ppu', 'padding'), [1, 1, 1, 1]),
            (('ppu', 'index_en'), True),
            (('ppu', 'use_cnt'), 7),
            (('layout', 'output', 'line_stride_bytes'), 64),
            (('comparison', 'tolerance'), 0.0625),
        )
        for path, value in mutations:
            with self.subTest(path=path):
                mutated = copy.deepcopy(self.manifest)
                node = mutated
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = value
                with self.assertRaises(ValueError):
                    validate_contract(mutated)

    def test_oracle_refuses_nonfinite_and_negative_zero_inputs(self) -> None:
        fixture = (MANIFEST.parent / 'in.bin').read_bytes()
        nonfinite = bytearray(fixture)
        nonfinite[0:2] = (0x7c00).to_bytes(2, 'little')
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            source_oracle(bytes(nonfinite))
        negative_zero = bytearray(fixture)
        negative_zero[0:2] = (0x8000).to_bytes(2, 'little')
        with self.assertRaisesRegex(ValueError, 'negative zero'):
            source_oracle(bytes(negative_zero))


if __name__ == '__main__':
    unittest.main()
