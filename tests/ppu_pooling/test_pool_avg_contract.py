# SPDX-License-Identifier: MIT
"""Strict negative controls for the single capture-bounded average fixture."""
from __future__ import annotations

import copy
import json
import unittest

from tools.ppu.run_pool_avg import MANIFEST, fixture_check, validate_contract


class PoolAverageCaptureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text())

    def test_pinned_fixture_and_contract(self) -> None:
        validate_contract(self.manifest)
        fixture = fixture_check()
        self.assertEqual(fixture['files']['device_out.bin']['bytes'], 4096)
        self.assertEqual(fixture['files']['in.bin']['bytes'], 4096)

    def test_rejects_mode_shape_and_rounding_drift(self) -> None:
        mutations = (
            (('ppu', 'method'), 'maximum'),
            (('ppu', 'in_shape'), [2, 2]),
            (('ppu', 'out_shape'), [4, 4]),
            (('ppu', 'padding'), [1, 1, 1, 1]),
            (('ppu', 'index_en'), True),
            (('ppu', 'use_cnt'), 7),
            (('layout', 'output', 'line_stride_bytes'), 64),
            (('source', 'tolerance_abs'), 0.0),
        )
        for path, value in mutations:
            with self.subTest(path=path):
                altered = copy.deepcopy(self.manifest)
                target = altered
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValueError):
                    validate_contract(altered)


if __name__ == '__main__':
    unittest.main()
