#!/usr/bin/env python3
"""Contract checks for the promoted split-OC C16 3x3 captures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASES = ('conv_splitoc_3x3_c16_h9_w9_oc16_task0',
         'conv_splitoc_3x3_c16_h9_w9_oc16_task1')
ADDRESSES = {'a': 0x1000, 'w': 0x2000, 'out': 0x3000}
PARENT = ROOT / 'build/rk3588-example-captures/conv-fp16/cases'
FAMILY = ROOT / 'build/rk3588-example-captures/conv-fp16/manifest.json'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patched_command(raw: bytes) -> bytes:
    patched = bytearray(raw)
    for index, value in ((21, ADDRESSES['a']), (27, ADDRESSES['w']),
                         (35, ADDRESSES['out'])):
        qword, = struct.unpack_from('<Q', patched, index * 8)
        qword = (qword & ~(0xffffffff << 16)) | (value << 16)
        struct.pack_into('<Q', patched, index * 8, qword)
    return bytes(patched)


class ConvSplitOcC16ContractTests(unittest.TestCase):
    def test_fixture_and_capture_provenance_are_pinned(self) -> None:
        for case in CASES:
            fixture = ROOT / 'tests/conv/fixtures' / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            job = json.loads((fixture / 'job.json').read_text())
            provenance = json.loads((fixture / 'provenance.json').read_text())
            capture = json.loads((fixture / 'device_capture.json').read_text())
            self.assertEqual(manifest['case'], case)
            self.assertEqual(manifest['status'], 'READY_CAPTURE_BOUNDED_CANDIDATE')
            self.assertEqual(capture['status'], 'OK')
            self.assertEqual(capture['submit_ret'], 0)
            self.assertEqual(capture['tasks'][0]['regcmd_words'], 54)
            self.assertEqual(job['tasks'],
                             [{'regcmd_offset_words': 0, 'regcmd_words': 54}])
            self.assertEqual([row['regcmd_index'] for row in job['patches']],
                             [21, 27, 35])
            self.assertEqual(provenance['shape']['in_c'], 16)
            self.assertEqual(provenance['shape']['out_c'], 8)
            self.assertEqual(provenance['shape']['out_h'], 7)
            self.assertEqual(provenance['shape']['out_w'], 7)
            self.assertEqual(provenance['shape']['groups'], 1)
            self.assertEqual(provenance['shape']['parent_case'],
                             'conv_splitoc_3x3_c16_h9_w9_oc16')
            self.assertEqual(manifest['source']['sha256'],
                             provenance['source_sha256'])
            for name, record in manifest['files'].items():
                payload = (fixture / name).read_bytes()
                self.assertEqual(len(payload), record['bytes'], name)
                self.assertEqual(sha(fixture / name), record['sha256'], name)

    def test_command_stream_matches_the_promoted_capture(self) -> None:
        for case in CASES:
            fixture = ROOT / 'tests/conv/fixtures' / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            capture = json.loads((fixture / 'device_capture.json').read_text())
            raw = (fixture / 'regcmd.bin').read_bytes()
            self.assertEqual(len(raw), 54 * 8)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),
                             manifest['command']['template_sha256'])
            self.assertEqual(manifest['command']['template_sha256'],
                             'a60a4448d096c069a35f941e9718391964f4809aa227ae3d63784c860224e9db')
            relocated = patched_command(raw)
            self.assertEqual(hashlib.sha256(relocated).hexdigest(),
                             manifest['command']['captured_patched_sha256'])
            self.assertEqual(hashlib.sha256(relocated).hexdigest(),
                             capture['hashes']['command_stream']['sha256'])
            self.assertEqual(hashlib.sha256(relocated).hexdigest(),
                             '8c95d0fa8d9e14ad0b6689872fe7e14b1ce08552b4aaba69bb59605dd2f3ee57')
            differ = [i for i in range(54)
                      if struct.unpack_from('<Q', raw, i * 8)[0] !=
                      struct.unpack_from('<Q', relocated, i * 8)[0]]
            self.assertEqual(differ, [21, 27, 35])

    def test_packed_c16_operands_and_defined_outputs_match_oracle(self) -> None:
        for group, case in enumerate(CASES):
            fixture = ROOT / 'tests/conv/fixtures' / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            packed = struct.unpack('<1296H', (fixture / 'a.bin').read_bytes())
            weights = struct.unpack('<1152H', (fixture / 'w.bin').read_bytes())
            expected = struct.unpack('<392H', (fixture / 'expected.bin').read_bytes())
            device_bytes = (fixture / 'device_out.bin').read_bytes()
            device = struct.unpack(f'<{len(device_bytes)//2}H', device_bytes)
            source_input = struct.unpack('<1296H',
                                         (fixture / 'source_input_nchw.bin').read_bytes())
            source_weight = struct.unpack('<2304H',
                                          (fixture / 'source_weight_nchw.bin').read_bytes())
            self.assertEqual(manifest['layout']['input_pixel_stride_bytes'], 16)
            self.assertEqual(manifest['layout']['output_logical_elements'], 392)
            self.assertEqual(manifest['layout']['input_c1_plane_stride_bytes'], 1296)
            # Two C1 planes of 81 pixels; lane l of plane p is C(p*8+l).
            for pixel in range(81):
                for lane in range(8):
                    self.assertEqual(packed[pixel * 8 + lane],
                                     source_input[lane * 81 + pixel],
                                     ('plane0', pixel, lane))
                    self.assertEqual(packed[648 + pixel * 8 + lane],
                                     source_input[(8 + lane) * 81 + pixel],
                                     ('plane1', pixel, lane))
            # kh-major [tap][OC][align_C=16]; each group task selects OC8 half.
            for tap in range(9):
                for oc in range(8):
                    for ic in range(16):
                        want = source_weight[((group * 8 + oc) * 16 + ic) * 9 + tap]
                        self.assertEqual(weights[tap * 128 + oc * 16 + ic], want,
                                         (tap, oc, ic))
            for atom in range(49):
                for channel in range(8):
                    self.assertEqual(device[atom * 8 + channel],
                                     expected[channel * 49 + atom], (atom, channel))
            # The remaining BO bytes are not a numerical oracle; the capture
            # retains prior-job content there.
            self.assertTrue(manifest['numeric']['defined_elements_exact'])
            self.assertTrue(manifest['numeric']['padding_is_not_numerical_oracle'])

    def test_parent_two_task_case_stays_blocked(self) -> None:
        parent = json.loads((PARENT / 'conv_splitoc_3x3_c16_h9_w9_oc16' /
                             'job.json').read_text())
        self.assertEqual(len(parent['tasks']), 2)
        rows = {row['case']: row for row in
                json.loads(FAMILY.read_text())['cases']}
        for case in CASES:
            self.assertEqual(rows[case]['status'], 'READY')
        self.assertEqual(rows['conv_splitoc_3x3_c16_h9_w9_oc16']['status'],
                         'BLOCKED')

    def test_rtl_selects_a_parameterized_split_oc_profile(self) -> None:
        profile = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_profile.sv').read_text()
        front = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_front.sv').read_text()
        core = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_core.sv').read_text()
        wrapper = (ROOT / 'rtl/cmac/rk_conv_3x3_splitoc_c16_core.sv').read_text()
        self.assertIn("parameter bit SPLIT_OC_C16 = 1'b0", profile)
        for index, value in {
            8: "SPLIT_OC_C16 ? 32'h000f0010",
            11: "SPLIT_OC_C16 ? 32'h00000900",
            13: "SPLIT_OC_C16 ? 32'h03030008",
            14: "SPLIT_OC_C16 ? 32'h0000001b",
            40: "SPLIT_OC_C16 ? 32'h0007001f",
        }.items():
            self.assertIn(f"{index}: begin", profile)
            self.assertIn(value, profile)
        self.assertIn("SPLIT_OC_C16 ? 33'd2304 : 33'd1152", profile)
        self.assertIn("weight_bytes = DEPTHWISE_C3 ? 33'd144 :", profile)
        self.assertIn("parameter int unsigned INPUT_CHANNELS = 4", front)
        self.assertIn("parameter int unsigned KERNELS = 4", front)
        self.assertIn("PLANES = (INPUT_CHANNELS + PACK_C2 - 1) / PACK_C2", front)
        # The weight store is a single-read-port RAM; the tap group base is
        # computed by weight_group_address rather than a literal index.
        self.assertIn('localparam int unsigned WEIGHT_HALFWORDS = TAPS * WEIGHT_LANES * CHUNKS', front)
        self.assertIn('chunk_f * TAPS * WEIGHT_LANES + tap * WEIGHT_LANES +', front)
        self.assertIn('assign weight_raddr = weight_read_address_w[WEIGHT_BITS-1:0]', front)
        self.assertIn(".INPUT_CHANNELS(DEPTHWISE_C3 ? 3 : SPLIT_OC_C16 ? 16 : GROUPED_C2 ? 2 : 4)", core)
        self.assertIn(".KERNELS(DEPTHWISE_C3 ? 3 : SPLIT_OC_C16 ? 8 : 4)", core)
        self.assertIn(".SPLIT_OC_C16(SPLIT_OC_C16)", core)
        self.assertIn(".SPLIT_OC_C16(1'b1)", wrapper)


if __name__ == '__main__':
    unittest.main()
