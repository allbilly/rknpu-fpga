# SPDX-License-Identifier: MIT
"""Pinned capture, exact register delta and layout contract for stride-2 C4."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASE = 'conv_3x3_stride2_c4_h11_w11_oc4'
FIXTURE = ROOT / 'tests/conv/fixtures' / CASE
VALID = ROOT / 'tests/conv/fixtures/conv_3x3_valid_c4_h9_w9_oc4'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Conv3x3Stride2C4ContractTests(unittest.TestCase):
    def test_fixture_and_source_provenance_bind_one_successful_task(self) -> None:
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        job = json.loads((FIXTURE / 'job.json').read_text())
        provenance = json.loads((FIXTURE / 'provenance.json').read_text())
        capture = json.loads((FIXTURE / 'device_capture.json').read_text())
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual(manifest['status'], 'READY_CAPTURE_BOUNDED_CANDIDATE')
        self.assertEqual(capture['status'], 'OK')
        self.assertEqual(capture['submit_ret'], 0)
        self.assertEqual(capture['tasks'][0]['regcmd_words'], 54)
        self.assertEqual(job['tasks'], [{'regcmd_offset_words': 0, 'regcmd_words': 54}])
        self.assertEqual([p['regcmd_index'] for p in job['patches']], [21, 27, 35])
        self.assertEqual(manifest['source']['sha256'], provenance['source_sha256'])
        self.assertEqual(manifest['source']['sha256'],
                         'f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51')
        self.assertEqual(provenance['shape'], {
            'batch': 1, 'in_c': 4, 'in_h': 11, 'in_w': 11, 'out_c': 4,
            'kh': 3, 'kw': 3, 'stride': 2, 'groups': 1,
            'padded_zero_frame': False, 'effective_input_h': 11,
            'effective_input_w': 11, 'out_h': 5, 'out_w': 5,
        })
        for name, record in manifest['files'].items():
            path = FIXTURE / name
            self.assertEqual(path.stat().st_size, record['bytes'], name)
            self.assertEqual(sha(path), record['sha256'], name)
        self.assertEqual(capture['hashes']['outputs']['out']['sha256'],
                         manifest['numeric']['device_output_bo_sha256'])

    def test_only_three_relocations_and_pinned_stride_fields_differ(self) -> None:
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        job = json.loads((FIXTURE / 'job.json').read_text())
        capture = json.loads((FIXTURE / 'device_capture.json').read_text())
        raw = bytearray((FIXTURE / 'regcmd.bin').read_bytes())
        original = bytes(raw)
        addresses = {'a': 0x1000, 'w': 0x2000, 'out': 0x3000}
        for patch in job['patches']:
            qword, = struct.unpack_from('<Q', raw, patch['regcmd_index'] * 8)
            qword = (qword & ~(0xffffffff << 16)) | (addresses[patch['buffer']] << 16)
            struct.pack_into('<Q', raw, patch['regcmd_index'] * 8, qword)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         capture['hashes']['command_stream']['sha256'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         manifest['command']['captured_patched_sha256'])
        self.assertEqual([i for i in range(54)
                          if raw[i*8:i*8+8] != original[i*8:i*8+8]], [21, 27, 35])

        valid = struct.unpack('<54Q', (VALID / 'regcmd.bin').read_bytes())
        stride2 = struct.unpack('<54Q', original)
        expected_values = {
            5: 0x000000e0, 6: 0x00000012, 7: 0x000b000b,
            9: 0x00000005, 10: 0x00000019, 15: 0x00000006,
            23: 0x0000002c, 24: 0x0000004d, 25: 0x000b000b,
            30: 0x00040004, 36: 0x000001c0, 37: 0x00000004,
            38: 0x00000004, 44: 0x00040004, 49: 0x00000380,
        }
        self.assertEqual([i for i, pair in enumerate(zip(valid, stride2))
                          if pair[0] != pair[1]], list(expected_values))
        for i, (old, new) in enumerate(zip(valid, stride2)):
            self.assertEqual((old >> 48, old & 0xffff), (new >> 48, new & 0xffff), i)
            if i in expected_values:
                self.assertEqual((new >> 16) & 0xffffffff, expected_values[i], i)

    def test_packed_operands_and_defined_capture_values_follow_stride2_layout(self) -> None:
        packed_input = struct.unpack('<1936H', (FIXTURE / 'a.bin').read_bytes())
        source_input = struct.unpack('<484H', (FIXTURE / 'source_input_nchw.bin').read_bytes())
        for y in range(11):
            for x in range(11):
                pixel = y * 11 + x
                for channel in range(8):
                    actual = packed_input[pixel * 8 + channel]
                    expected = source_input[channel * 121 + pixel] if channel < 4 else 0
                    self.assertEqual(actual, expected, (y, x, channel))
                    self.assertEqual(packed_input[968 + pixel * 8 + channel], 0,
                                     (y, x, 'second C1 plane', channel))

        packed_weight = struct.unpack('<576H', (FIXTURE / 'w.bin').read_bytes())
        source_weight = struct.unpack('<144H', (FIXTURE / 'source_weight_nchw.bin').read_bytes())
        for tap in range(9):
            for oc in range(4):
                for ic in range(16):
                    actual = packed_weight[tap * 64 + oc * 16 + ic]
                    expected = source_weight[(oc * 4 + ic) * 9 + tap] if ic < 4 else 0
                    self.assertEqual(actual, expected, (tap, oc, ic))

        expected = struct.unpack('<100H', (FIXTURE / 'expected.bin').read_bytes())
        device = struct.unpack('<896H', (FIXTURE / 'device_out.bin').read_bytes())
        for y in range(5):
            for x in range(5):
                atom = y * 5 + x
                for channel in range(4):
                    self.assertEqual(device[atom * 8 + channel],
                                     expected[channel * 25 + atom], (channel, y, x))
        self.assertTrue(manifest_is_exact(FIXTURE))

    def test_rtl_selects_only_the_two_explicit_geometries(self) -> None:
        profile = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_profile.sv').read_text()
        front = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_front.sv').read_text()
        core = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_core.sv').read_text()
        wrapper = (ROOT / 'rtl/cmac/rk_conv_3x3_stride2_c4_core.sv').read_text()
        self.assertIn("parameter bit STRIDE2 = 1'b0", profile)
        self.assertIn("input_bytes = (GROUPED_C2 ? 33'd800 : 33'd2592)", profile)
        self.assertIn("((STRIDE2 || PAD1_ZERO_FRAME) ? 33'd1280 : 33'd0)", profile)
        self.assertIn("output_bytes = (GROUPED_C2 ? 33'd768 : 33'd3328)", profile)
        self.assertIn("(PAD1_ZERO_FRAME ? 33'd2048 : 33'd0)", profile)
        self.assertIn("(STRIDE2 ? 33'd1536 : 33'd0)", profile)
        self.assertIn('INPUT_H != (OUTPUT_H - 1) * STRIDE + KH', front)
        self.assertIn('INPUT_W != (OUTPUT_W - 1) * STRIDE + KW', front)
        # A 3x3 elaboration must still reproduce the captured geometry.
        self.assertIn('parameter int unsigned KH = 3', front)
        self.assertIn('parameter int unsigned KW = 3', front)
        self.assertIn('input_pixel = (output_y * STRIDE + tap_y) * INPUT_W +', front)
        self.assertIn('output_x * STRIDE + tap_x', front)
        self.assertIn('.STRIDE2(STRIDE2)', core)
        self.assertIn('.STRIDE(STRIDE2 ? 2 : 1)', core)
        self.assertIn('.STRIDE2(1\'b1)', wrapper)


def manifest_is_exact(fixture: Path) -> bool:
    manifest = json.loads((fixture / 'manifest.json').read_text())
    return (manifest['numeric']['defined_elements_exact'] is True and
            manifest['numeric']['padding_is_not_numerical_oracle'] is True)


if __name__ == '__main__':
    unittest.main()
