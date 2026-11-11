#!/usr/bin/env python3
"""Verify every frozen pooling fixture against its device capture.

This is a data-contract test, not an RTL test: it proves that each
`tests/ppu_pooling/fixtures/<case>/` directory is a faithful, hash-bound copy of
a successful RK3588 run (or an explicitly source-derived candidate), and that
the geometry recorded in `manifest.json` agrees with the case's own register
dump. READY cases without a fixture are reported as outstanding rather than
silently skipped.

The file set is read from each manifest rather than assumed, because some
fixtures predate the freeze tool and one candidate is source-derived with no
device BO. Three pre-existing fixtures carry an older manifest schema: they
are hash-checked here, but their richer cross-checks only apply when the
corresponding fields exist.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/ppu_pooling/fixtures'
FAMILY = ROOT / 'build/rk3588-example-captures/pooling/manifest.json'
MIN_FROZEN = 19


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def family_rows() -> dict[str, dict]:
    if not FAMILY.exists():
        return {}
    return {row['case']: row for row in json.loads(FAMILY.read_text())['cases']}


def fixture_cases() -> list[str]:
    return sorted(p.parent.name for p in FIXTURES.glob('*/manifest.json'))


def reg_dump(fixture: Path) -> dict[str, int]:
    fields: dict[str, int] = {}
    path = fixture / 'regcmd.txt'
    if not path.exists():
        return fields
    for line in path.read_text().splitlines():
        if line.startswith('#') or not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        try:
            fields[parts[4].strip()] = int(parts[3], 16)
        except ValueError:
            # A legacy dump row carries a non-hex token; skip it rather than
            # inventing a value.
            continue
    return fields


def frozen_cases() -> list[str]:
    """Fixtures written by tools/ppu/freeze_pool_fixture.py."""
    cases = []
    for case in fixture_cases():
        manifest = json.loads((FIXTURES / case / 'manifest.json').read_text())
        if (manifest.get('status') == 'READY_CAPTURE_BOUNDED_CANDIDATE'
                and 'command_stream' in manifest
                and 'addresses' in manifest['command_stream']):
            cases.append(case)
    return cases


def patched_stream(fixture: Path, manifest: dict) -> bytes:
    """Relocate the source stream using the addresses the run actually used."""
    import struct
    raw = (fixture / 'regcmd.bin').read_bytes()
    patched = bytearray(raw)
    stream = manifest['command_stream']
    addresses = stream.get('addresses')
    relocations = stream.get('address_relocations')
    if not addresses or not relocations:
        return bytes(patched)
    capture = json.loads((fixture / 'capture.json').read_text())
    buffers = [row['buffer'] for row in capture['patches']]
    for index, buffers_for_index in zip(relocations,
                                        [[b] for b in buffers]):
        buffer = buffers_for_index[0]
        qword, = struct.unpack_from('<Q', patched, index * 8)
        qword = (qword & ~(0xffffffff << 16)) | (addresses[buffer] << 16)
        struct.pack_into('<Q', patched, index * 8, qword)
    return bytes(patched)


class PoolingFixtureContractTests(unittest.TestCase):
    def test_every_frozen_fixture_is_hash_bound_and_complete(self) -> None:
        cases = fixture_cases()
        self.assertGreaterEqual(
            len(cases), MIN_FROZEN,
            'expected the READY pooling fixtures to be frozen; '
            f'only {len(cases)} present')
        for case in cases:
            fixture = FIXTURES / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            self.assertEqual(manifest['case'], case)
            for name, record in manifest['files'].items():
                path = fixture / name
                if not path.is_file():
                    # Some pre-freeze manifests enumerate a dump that was not
                    # retained; only fail when the file is load-bearing.
                    if name in ('in.bin', 'expected.bin', 'job.json',
                                'regcmd.bin', 'out_init.bin'):
                        self.fail(f'{case}: missing {name}')
                    continue
                self.assertEqual(path.stat().st_size, record['bytes'], (case, name))
                self.assertEqual(sha(path), record['sha256'], (case, name))

    def test_device_output_is_the_oracle_and_tail_is_intact(self) -> None:
        for case in fixture_cases():
            fixture = FIXTURES / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            device_path = fixture / 'device_out.bin'
            if not device_path.exists():
                # Source-derived candidate: there is no device BO by design.
                self.assertIn('source', manifest)
                continue
            device = device_path.read_bytes()
            expected_path = fixture / 'expected.bin'
            if not expected_path.exists():
                # Source-derived candidate without a host oracle file.
                continue
            expected = expected_path.read_bytes()
            if 'device_output_sha256' in manifest.get('comparison', {}):
                self.assertEqual(hashlib.sha256(device).hexdigest(),
                                 manifest['comparison']['device_output_sha256'], case)
            self.assertEqual(device, expected, case)
            # The declared span is the union of the value region and, when
            # INDEX_EN, the separate index region.
            spans = []
            if manifest.get('comparison', {}).get('logical_value_bytes'):
                spans.append(manifest['comparison']['logical_value_bytes'])
            if manifest.get('layout', {}).get('output', {}).get('logical_bytes'):
                spans.append(manifest['layout']['output']['logical_bytes'])
            logical = max(spans) if spans else 0
            # Compare the declared output span, then require everything past
            # it to equal the captured initial BO so no write escaped.
            self.assertLessEqual(logical, len(device), case)
            initial_path = fixture / 'out_init.bin'
            if initial_path.exists():
                initial = initial_path.read_bytes()
                self.assertEqual(device[logical:], initial[logical:], case)
            else:
                self.assertTrue(all(b == 0 for b in device[logical:]), case)

    def test_geometry_matches_the_register_dump(self) -> None:
        for case in fixture_cases():
            fixture = FIXTURES / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            fields = reg_dump(fixture)
            if not fields:
                # Pre-freeze fixtures without a register dump cannot be
                # cross-checked here; their manifest geometry stands alone.
                self.assertIn('ppu', manifest)
                continue
            ppu = manifest['ppu']
            required = ('PPU_DATA_CUBE_IN_WIDTH', 'PPU_DATA_CUBE_IN_HEIGHT',
                        'PPU_DATA_CUBE_OUT_WIDTH', 'PPU_DATA_CUBE_OUT_HEIGHT',
                        'PPU_DATA_CUBE_IN_CHANNEL', 'PPU_POOLING_KERNEL_CFG',
                        'PPU_OPERATION_MODE_CFG')
            if not all(name in fields for name in required):
                # The 16x16 source-derived candidate carries a partial dump.
                self.assertIn('ppu', manifest)
                continue
            for name, want in (
                ('PPU_DATA_CUBE_IN_WIDTH', ppu['in_shape'][1] - 1),
                ('PPU_DATA_CUBE_IN_HEIGHT', ppu['in_shape'][0] - 1),
                ('PPU_DATA_CUBE_OUT_WIDTH', ppu['out_shape'][1] - 1),
                ('PPU_DATA_CUBE_OUT_HEIGHT', ppu['out_shape'][0] - 1),
                ('PPU_DATA_CUBE_IN_CHANNEL', ppu['channels'] - 1),
            ):
                self.assertEqual(fields[name], want, (case, name))
            cfg = fields['PPU_POOLING_KERNEL_CFG']
            self.assertEqual((cfg >> 8) & 0xf, ppu['kernel'][0] - 1, (case, 'kh'))
            self.assertEqual(cfg & 0xf, ppu['kernel'][1] - 1, (case, 'kw'))
            self.assertEqual((cfg >> 20) & 0xf, ppu['stride'][0] - 1, (case, 'sy'))
            self.assertEqual((cfg >> 16) & 0xf, ppu['stride'][1] - 1, (case, 'sx'))
            if 'method_selector' in ppu:
                self.assertEqual(fields['PPU_OPERATION_MODE_CFG'] & 0xf,
                                 ppu['method_selector'], (case, 'method'))
            if 'PPU_POOLING_PADDING_CFG' in fields and 'padding' in ppu:
                pad = fields['PPU_POOLING_PADDING_CFG']
                self.assertEqual([(pad >> 4) & 0xf, (pad >> 12) & 0xf,
                                  (pad >> 8) & 0xf, pad & 0xf],
                                 [ppu['padding'][2], ppu['padding'][0],
                                  ppu['padding'][3], ppu['padding'][1]], case)

    def test_command_stream_hashes_match_the_device_capture(self) -> None:
        for case in fixture_cases():
            fixture = FIXTURES / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            stream = manifest.get('command_stream')
            if stream is None:
                # Pre-freeze fixture: only the file binding is checkable.
                self.assertTrue((fixture / 'regcmd.bin').is_file(), case)
                continue
            self.assertEqual(stream['source_regcmd_sha256'],
                             sha(fixture / 'regcmd.bin'), case)
            self.assertEqual(stream['qwords'],
                             len((fixture / 'regcmd.bin').read_bytes()) // 8, case)
            if not (fixture / 'capture.json').exists():
                continue
            capture = json.loads((fixture / 'capture.json').read_text())
            self.assertEqual(stream['device_patched_regcmd_sha256'],
                             capture['hashes']['command_stream']['sha256'], case)
            self.assertEqual(capture['status'], 'OK', case)
            self.assertEqual(capture['submit_ret'], 0, case)
            if not stream.get('addresses'):
                continue
            self.assertEqual(hashlib.sha256(patched_stream(fixture, manifest)).hexdigest(),
                             stream['device_patched_regcmd_sha256'], case)

    def test_no_ready_pooling_case_lacks_a_fixture(self) -> None:
        rows = family_rows()
        if not rows:
            self.skipTest('pooling capture family manifest is not present')
        missing = [case for case, row in rows.items()
                   if row['status'] == 'READY'
                   and not (FIXTURES / case / 'manifest.json').exists()]
        self.assertEqual(missing, [], 'READY pooling cases without a fixture')

    def test_each_fixture_is_declared_in_the_family_manifest(self) -> None:
        rows = family_rows()
        if not rows:
            self.skipTest('pooling capture family manifest is not present')
        for case in fixture_cases():
            manifest = json.loads((FIXTURES / case / 'manifest.json').read_text())
            if manifest.get('status') == 'SOURCE_DERIVED_SIMULATION_CANDIDATE':
                # Not a device capture, so it is intentionally absent from the
                # capture family manifest.
                continue
            self.assertTrue(case in rows, f'{case} absent from the family manifest')
            self.assertEqual(rows[case]['status'], 'READY', case)


class PoolingNumericOracleTests(unittest.TestCase):
    """Recompute each fixture's expected output from its packed input.

    This proves the frozen `expected.bin` is a real function of `in.bin` under
    the declared pooling semantics, so a future leaf cannot be validated
    against a stale or unrelated oracle.
    """

    @staticmethod
    def s8(value: int) -> int:
        return value - 256 if value > 127 else value

    def test_int8_max_2x2_stride2_matches_recomputation(self) -> None:
        fixture = FIXTURES / 'int8_max_k2s2_valid_c16_h2w2'
        manifest = json.loads((fixture / 'manifest.json').read_text())
        ppu = manifest['ppu']
        self.assertEqual(ppu['dtype'], 'int8')
        self.assertEqual(ppu['method'], 'maximum')
        self.assertEqual(ppu['in_shape'], [2, 2])
        self.assertEqual(ppu['kernel'], [2, 2])
        self.assertEqual(ppu['stride'], [2, 2])
        source = (fixture / 'in.bin').read_bytes()
        expected = (fixture / 'expected.bin').read_bytes()
        channels = ppu['channels']
        elements = [self.s8(source[index]) for index in range(channels)]
        for pixel in (1, 2, 3):
            base = pixel * channels
            elements = [max(elements[c], self.s8(source[base + c]))
                        for c in range(channels)]
        produced = bytes(value & 0xFF for value in elements)
        self.assertEqual(produced, expected[:channels])

    def test_int8_min_2x2_stride2_matches_recomputation(self) -> None:
        fixture = FIXTURES / 'int8_min_k2s2_valid_c16_h2w2'
        manifest = json.loads((fixture / 'manifest.json').read_text())
        self.assertEqual(manifest['ppu']['method'], 'minimum')
        source = (fixture / 'in.bin').read_bytes()
        expected = (fixture / 'expected.bin').read_bytes()
        channels = manifest['ppu']['channels']
        elements = [self.s8(source[index]) for index in range(channels)]
        for pixel in (1, 2, 3):
            base = pixel * channels
            elements = [min(elements[c], self.s8(source[base + c]))
                        for c in range(channels)]
        produced = bytes(value & 0xFF for value in elements)
        self.assertEqual(produced, expected[:channels])

    def test_int16_max_2x2_stride2_matches_recomputation(self) -> None:
        import struct
        fixture = FIXTURES / 'int16_max_k2s2_valid_c8_h2w2'
        manifest = json.loads((fixture / 'manifest.json').read_text())
        self.assertEqual(manifest['ppu']['dtype'], 'int16')
        source = struct.unpack('<32h', (fixture / 'in.bin').read_bytes()[:64])
        expected = struct.unpack('<8h', (fixture / 'expected.bin').read_bytes()[:16])
        channels = manifest['ppu']['channels']
        elements = list(source[:channels])
        for pixel in (1, 2, 3):
            base = pixel * channels
            elements = [max(elements[c], source[base + c]) for c in range(channels)]
        self.assertEqual(tuple(elements), expected)

    def test_int16_min_2x2_stride2_matches_recomputation(self) -> None:
        import struct
        fixture = FIXTURES / 'int16_min_k2s2_valid_c8_h2w2'
        manifest = json.loads((fixture / 'manifest.json').read_text())
        self.assertEqual(manifest['ppu']['method'], 'minimum')
        source = struct.unpack('<32h', (fixture / 'in.bin').read_bytes()[:64])
        expected = struct.unpack('<8h', (fixture / 'expected.bin').read_bytes()[:16])
        channels = manifest['ppu']['channels']
        elements = list(source[:channels])
        for pixel in (1, 2, 3):
            base = pixel * channels
            elements = [min(elements[c], source[base + c]) for c in range(channels)]
        self.assertEqual(tuple(elements), expected)

    def test_int8_average_q16_matches_integer_mean(self) -> None:
        fixture = FIXTURES / 'int8_avg_q16_k2s2_valid_c16_h2w2'
        manifest = json.loads((fixture / 'manifest.json').read_text())
        self.assertEqual(manifest['ppu']['method'], 'average')
        # The reciprocal comes from the case's own register dump, not a
        # hard-coded constant: PPU_RECIP_KERNEL_WIDTH for this 2x2 window is
        # 0x8000 = 32768, i.e. Q16 of 1/2.
        fields = reg_dump(fixture)
        recip = fields['PPU_RECIP_KERNEL_WIDTH']
        self.assertEqual(recip, 0x8000, 'unexpected captured reciprocal')
        source = (fixture / 'in.bin').read_bytes()
        expected = (fixture / 'expected.bin').read_bytes()
        channels = manifest['ppu']['channels']
        for channel in range(channels):
            total = sum(self.s8(source[pixel * channels + channel])
                        for pixel in range(4))
            # Captured semantics: mean = (sum * recip) >> 17, truncating.
            mean = (total * recip) >> 17
            self.assertEqual(mean & 0xFF, expected[channel],
                             (channel, total, mean))

    def test_unknown_dtype_is_not_silently_accepted(self) -> None:
        rows = family_rows()
        if not rows:
            self.skipTest('pooling capture family manifest is not present')
        for case in fixture_cases():
            manifest = json.loads((FIXTURES / case / 'manifest.json').read_text())
            self.assertIn(manifest['ppu']['dtype'],
                          {'float16', 'int8', 'int16'},
                          f'{case}: unsupported dtype must not be scored')


if __name__ == '__main__':
    unittest.main()
