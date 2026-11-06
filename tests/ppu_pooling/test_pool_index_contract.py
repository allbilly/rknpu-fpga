# SPDX-License-Identifier: MIT
"""Strict negative controls for the single captured FP16 MAX+INDEX case."""
from __future__ import annotations

import copy
import json
import unittest

from tools.ppu.run_pool_index import (
    FIXTURE_FILES,
    MANIFEST,
    fixture_check,
    source_oracle,
    validate_contract,
)


class PoolIndexCaptureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text())

    def test_pinned_capture_and_source_oracle(self) -> None:
        validate_contract(self.manifest)
        fixture = fixture_check()
        self.assertEqual(set(fixture['files']), set(FIXTURE_FILES))
        self.assertEqual(fixture['files']['device_out.bin']['bytes'], 4096)
        values, indices = source_oracle((MANIFEST.parent / 'in.bin').read_bytes())
        expected = (MANIFEST.parent / 'expected.bin').read_bytes()
        self.assertEqual(expected[:16], values)
        self.assertEqual(expected[32:48], indices)

    def test_rejects_mode_geometry_and_index_layout_drift(self) -> None:
        mutations = (
            (('ppu', 'method'), 'minimum'),
            (('ppu', 'stride'), [1, 1]),
            (('ppu', 'in_shape'), [4, 4]),
            (('ppu', 'index_en'), False),
            (('ppu', 'use_cnt'), 7),
            (('layout', 'output', 'index_offset'), 16),
            (('layout', 'output', 'index_bytes'), 0),
            (('comparison', 'logical_output_bytes'), 32),
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

    def test_oracle_refuses_nonfinite_negative_zero_and_tied_maxima(self) -> None:
        fixture = bytearray((MANIFEST.parent / 'in.bin').read_bytes())
        nonfinite = bytearray(fixture)
        nonfinite[:2] = (0x7c00).to_bytes(2, 'little')
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            source_oracle(bytes(nonfinite))
        negative_zero = bytearray(fixture)
        negative_zero[:2] = (0x8000).to_bytes(2, 'little')
        with self.assertRaisesRegex(ValueError, 'negative zero'):
            source_oracle(bytes(negative_zero))
        tied = bytearray(fixture)
        # Channel 0's maximum is 100 at position 0; make position 1 equal.
        tied[16:18] = tied[0:2]
        with self.assertRaisesRegex(ValueError, 'unique maximum'):
            source_oracle(bytes(tied))


if __name__ == '__main__':
    unittest.main()
