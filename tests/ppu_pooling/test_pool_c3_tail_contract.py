# SPDX-License-Identifier: MIT
"""Strict fixture and input-contract controls for the captured C3 tail case."""
from __future__ import annotations

import copy
import json
import struct
import unittest

from tools.ppu.run_pool_c3_tail import (
    FIXTURE_FILES,
    MANIFEST,
    fixture_check,
    source_oracle,
    validate_contract,
)


class PoolC3TailCaptureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text())

    def test_pinned_capture_and_source_tail_oracle(self) -> None:
        validate_contract(self.manifest)
        fixture = fixture_check()
        self.assertEqual(set(fixture['files']), set(FIXTURE_FILES))
        self.assertEqual(fixture['files']['device_out.bin']['bytes'], 4096)
        output = source_oracle((MANIFEST.parent / 'in.bin').read_bytes())
        self.assertEqual(struct.unpack('<8e', output),
                         (20.0, 50.0, 60.0, -99.0, -99.0, -99.0, -99.0, -99.0))

    def test_rejects_mode_shape_tail_and_layout_drift(self) -> None:
        mutations = (
            (('ppu', 'method'), 'minimum'),
            (('ppu', 'channels'), 8),
            (('ppu', 'stride'), [1, 1]),
            (('ppu', 'in_shape'), [4, 4]),
            (('ppu', 'index_en'), True),
            (('ppu', 'use_cnt'), 7),
            (('layout', 'input', 'tail_lanes_per_atom'), 0),
            (('layout', 'input', 'tail_value_fp16'), 0.0),
            (('layout', 'output', 'value_bytes'), 6),
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

    def test_oracle_refuses_nonfinite_zero_and_modified_tail(self) -> None:
        fixture = bytearray((MANIFEST.parent / 'in.bin').read_bytes())
        nonfinite = bytearray(fixture)
        nonfinite[:2] = (0x7c00).to_bytes(2, 'little')
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            source_oracle(bytes(nonfinite))
        zero = bytearray(fixture)
        zero[:2] = (0).to_bytes(2, 'little')
        with self.assertRaisesRegex(ValueError, 'zero values'):
            source_oracle(bytes(zero))
        changed_tail = bytearray(fixture)
        changed_tail[6:8] = (0x3c00).to_bytes(2, 'little')
        with self.assertRaisesRegex(ValueError, 'tail'):
            source_oracle(bytes(changed_tail))


if __name__ == '__main__':
    unittest.main()
