# SPDX-License-Identifier: MIT
"""Provenance and relocation contract for the captured C3 raw PPU gate."""
from __future__ import annotations

import struct
import unittest

from tools.ppu.run_pool_c3_raw_profile import (
    CASE,
    FATAL_RE,
    load_contract,
    sha_bytes,
)


class PoolC3RawProfileContractTests(unittest.TestCase):
    def test_original_stream_and_only_two_job_relocations(self) -> None:
        manifest, job, capture, raw, patched = load_contract()
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual(len(raw), 26 * 8)
        self.assertEqual(len(patched), len(raw))
        self.assertEqual(sha_bytes(raw),
                         '9dc604e7342f0759b63222d24bbf4721cc50a6b6ec4becad1ffdb0c92205a55c')
        self.assertEqual(sha_bytes(patched),
                         '2aea54d33e144aaf796b6523f66a40f7567c9997d4b69edc73f989587f5c8178')
        self.assertEqual([patch['regcmd_index'] for patch in job['patches']], [13, 20])
        self.assertEqual(capture['addresses']['buffers'], {'in': 4096, 'out': 8192})

        raw_words = struct.unpack('<26Q', raw)
        patched_words = struct.unpack('<26Q', patched)
        self.assertEqual((raw_words[13] >> 48) & 0xffff, 0x4001)
        self.assertEqual(raw_words[13] & 0xffff, 0x6070)
        self.assertEqual((raw_words[20] >> 48) & 0xffff, 0x8001)
        self.assertEqual(raw_words[20] & 0xffff, 0x701c)
        changed = [index for index, (before, after)
                   in enumerate(zip(raw_words, patched_words)) if before != after]
        self.assertEqual(changed, [13, 20])
        self.assertEqual((patched_words[13] >> 16) & 0xffffffff, 8192)
        self.assertEqual((patched_words[20] >> 16) & 0xffffffff, 4096)
        self.assertEqual(patched_words[25], 0x0081000000600008)

    def test_contract_binds_source_layout_and_complete_bo_allocations(self) -> None:
        manifest, _job, _capture, _raw, _patched = load_contract()
        self.assertEqual(manifest['ppu']['dtype'], 'float16')
        self.assertEqual(manifest['ppu']['method'], 'maximum')
        self.assertEqual(manifest['ppu']['channels'], 3)
        self.assertEqual(manifest['layout']['input']['logical_bytes'], 64)
        self.assertEqual(manifest['layout']['output']['value_bytes'], 16)
        self.assertEqual(manifest['layout']['output']['buffer_bytes'], 4096)

    def test_runner_detects_fatal_output_even_if_simulator_returns_zero(self) -> None:
        for line in (
            '[460000] %Fatal: assertion failed',
            'FATAL: testbench.sv: assertion failed',
            'ERROR: $fatal was called',
        ):
            with self.subTest(line=line):
                self.assertIsNotNone(FATAL_RE.search(line))


if __name__ == '__main__':
    unittest.main()
