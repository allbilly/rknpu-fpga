#!/usr/bin/env python3
"""Contract checks for the captured depthwise C3 3x3 case."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASE = 'conv_depthwise_3x3_c3_h11_w28_oc3'
FIXTURE = ROOT / 'tests/conv/fixtures' / CASE
PARENT = ROOT / 'build/rk3588-example-captures/conv-fp16/cases' / CASE


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ConvDepthwiseC3ContractTests(unittest.TestCase):
    def test_fixture_and_capture_provenance_are_pinned(self) -> None:
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        job = json.loads((FIXTURE / 'job.json').read_text())
        provenance = json.loads((FIXTURE / 'provenance.json').read_text())
        capture = json.loads((FIXTURE / 'device_capture.json').read_text())
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual(manifest['status'], 'READY_CAPTURE_BOUNDED_CANDIDATE')
        self.assertEqual(capture['status'], 'OK')
        self.assertEqual(capture['submit_ret'], 0)
        self.assertEqual(capture['tasks'][0]['regcmd_words'], 54)
        self.assertEqual(job['tasks'],
                         [{'regcmd_offset_words': 0, 'regcmd_words': 54}])
        self.assertEqual([row['regcmd_index'] for row in job['patches']],
                         [21, 27, 35])
        self.assertEqual(provenance['shape']['in_c'], 3)
        self.assertEqual(provenance['shape']['out_c'], 3)
        self.assertEqual(provenance['shape']['groups'], 3)
        self.assertEqual(provenance['shape']['out_h'], 9)
        self.assertEqual(provenance['shape']['out_w'], 26)
        self.assertEqual(manifest['source']['sha256'],
                         provenance['source_sha256'])
        for name, record in manifest['files'].items():
            payload = (FIXTURE / name).read_bytes()
            self.assertEqual(len(payload), record['bytes'], name)
            self.assertEqual(sha(FIXTURE / name), record['sha256'], name)

    def test_command_stream_matches_the_device_capture(self) -> None:
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        capture = json.loads((FIXTURE / 'device_capture.json').read_text())
        raw = (FIXTURE / 'regcmd.bin').read_bytes()
        self.assertEqual(len(raw), 54 * 8)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         manifest['command']['template_sha256'])
        addresses = manifest['command']['addresses']
        patched = bytearray(raw)
        for index, name in ((21, 'a'), (27, 'w'), (35, 'out')):
            qword, = struct.unpack_from('<Q', patched, index * 8)
            qword = (qword & ~(0xffffffff << 16)) | (addresses[name] << 16)
            struct.pack_into('<Q', patched, index * 8, qword)
        self.assertEqual(hashlib.sha256(bytes(patched)).hexdigest(),
                         manifest['command']['captured_patched_sha256'])
        self.assertEqual(hashlib.sha256(bytes(patched)).hexdigest(),
                         capture['hashes']['command_stream']['sha256'])
        differ = [i for i in range(54)
                  if struct.unpack_from('<Q', raw, i * 8)[0] !=
                  struct.unpack_from('<Q', patched, i * 8)[0]]
        self.assertEqual(differ, [21, 27, 35])
        # The capture placed its weight/output BOs at 0x3000/0x4000, not the
        # sequential default 0x2000/0x3000 every other conv capture used.
        self.assertEqual(addresses, {'a': 0x1000, 'w': 0x3000, 'out': 0x4000})

    def test_depthwise_packed_operands_and_defined_outputs(self) -> None:
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        packed = struct.unpack('<2464H', (FIXTURE / 'a.bin').read_bytes())
        weights = struct.unpack('<72H', (FIXTURE / 'w.bin').read_bytes())
        expected = struct.unpack('<702H', (FIXTURE / 'expected.bin').read_bytes())
        device_bytes = (FIXTURE / 'device_out.bin').read_bytes()
        device = struct.unpack(f'<{len(device_bytes)//2}H', device_bytes)
        source_input = struct.unpack('<924H',
                                     (FIXTURE / 'source_input_nchw.bin').read_bytes())
        source_weight = struct.unpack('<27H',
                                      (FIXTURE / 'source_weight_nchw.bin').read_bytes())
        self.assertEqual(manifest['layout']['input_pixel_stride_bytes'], 16)
        self.assertEqual(manifest['layout']['weight_bytes'], 144)
        self.assertEqual(len(device_bytes), 15104)
        # One C1 plane of 11x28 pixels: real C0..C2, five zero lanes.
        for pixel in range(11 * 28):
            for lane in range(3):
                self.assertEqual(packed[pixel * 8 + lane],
                                 source_input[lane * 308 + pixel], (pixel, lane))
            for lane in range(3, 8):
                self.assertEqual(packed[pixel * 8 + lane], 0, (pixel, lane))
        # depthwise_spatial_major [ky][kx][c2_out=8]; real lanes 0..2 only.
        for tap in range(9):
            for lane in range(8):
                want = source_weight[lane * 9 + tap] if lane < 3 else 0
                self.assertEqual(weights[tap * 8 + lane], want, (tap, lane))
        # Output: 236 atoms per plane, three real OC lanes, width stride 26.
        for channel in range(3):
            for atom in range(9 * 26):
                self.assertEqual(device[atom * 8 + channel],
                                 expected[channel * 234 + atom], (channel, atom))
        for halfword in range(3, 8):
            self.assertEqual(device[halfword], 0, halfword)
        self.assertTrue(manifest['numeric']['defined_elements_exact'])
        self.assertTrue(manifest['numeric']['padding_is_not_numerical_oracle'])

    def test_parent_source_case_is_the_single_task_form(self) -> None:
        parent_job = json.loads((PARENT / 'job.json').read_text())
        self.assertEqual(parent_job['tasks'],
                         [{'regcmd_offset_words': 0, 'regcmd_words': 54}])
        family = json.loads((ROOT / 'build/rk3588-example-captures/conv-fp16' /
                             'manifest.json').read_text())
        rows = {row['case']: row for row in family['cases']}
        self.assertEqual(rows[CASE]['status'], 'READY')

    def test_rtl_selects_a_diagonal_depthwise_profile(self) -> None:
        profile = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_profile.sv').read_text()
        front = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_front.sv').read_text()
        core = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_core.sv').read_text()
        wrapper = (ROOT / 'rtl/cmac/rk_conv_3x3_depthwise_c3_core.sv').read_text()
        generator = (ROOT / 'tools/conv/gen_conv_profiles.py').read_text()
        header = (ROOT / 'rtl/cmac/rk_conv_3x3_profiles.svh').read_text()
        self.assertIn("parameter bit DEPTHWISE_C3 = 1'b0", profile)
        for index, value in {
            4: "DEPTHWISE_C3 ? 32'h00000123",
            5: "DEPTHWISE_C3 ? 32'h000000d0",
            7: "DEPTHWISE_C3 ? 32'h001c000b",
            8: "DEPTHWISE_C3 ? 32'h00020008",
            9: "DEPTHWISE_C3 ? 32'h0000001a",
            10: "DEPTHWISE_C3 ? 32'h000000ea",
            11: "DEPTHWISE_C3 ? 32'h00000090",
            12: "DEPTHWISE_C3 ? 32'h00000090",
            13: "DEPTHWISE_C3 ? 32'h03030001",
            14: "DEPTHWISE_C3 ? 32'h0000001b",
            15: "DEPTHWISE_C3 ? 32'h00000007",
            23: "DEPTHWISE_C3 ? 32'h00000070",
            24: "DEPTHWISE_C3 ? 32'h000000c4",
            25: "DEPTHWISE_C3 ? 32'h001c000b",
            26: "DEPTHWISE_C3 ? 32'h00000008",
            28: "DEPTHWISE_C3 ? 32'h00000007",
            29: "DEPTHWISE_C3 ? 32'h00000203",
            30: "DEPTHWISE_C3 ? 32'h00080019",
            33: "DEPTHWISE_C3 ? 32'h000001fc",
            36: "DEPTHWISE_C3 ? 32'h00000ec0",
            37: "DEPTHWISE_C3 ? 32'h00000019",
            38: "DEPTHWISE_C3 ? 32'h00000008",
            40: "DEPTHWISE_C3 ? 32'h0002001f",
            42: "DEPTHWISE_C3 ? 32'h0000036e",
            44: "DEPTHWISE_C3 ? 32'h00080019",
            49: "DEPTHWISE_C3 ? 32'h00001d80",
        }.items():
            self.assertIn(f"{index}: begin", profile)
            self.assertIn(value, profile)
        self.assertIn("weight_bytes = DEPTHWISE_C3 ? 33'd144", profile)
        self.assertIn("(DEPTHWISE_C3 ? 33'd11776 : 33'd0)", profile)
        self.assertIn("parameter bit DEPTHWISE = 1'b0", front)
                # The depthwise weight group is indexed by aligned channel count, not
        # by the 16-byte atom width; using PACK_C2 aliased the next tap.
        self.assertIn("localparam int unsigned WEIGHT_LANES = DEPTHWISE ? ALIGN_C :",
                      front)
        self.assertIn("must fit one aligned weight group", front)
        self.assertIn("32'd1 << kernel_lane", front)
        self.assertIn(".DEPTHWISE_C3(DEPTHWISE_C3)", core)
        self.assertIn(".INPUT_CHANNELS(DEPTHWISE_C3 ? 3 :", core)
        self.assertIn(".ALIGN_C(DEPTHWISE_C3 ? 8 : 16)", core)
        self.assertIn(".DEPTHWISE_C3(1'b1)", wrapper)
        self.assertIn("depthwise_spatial_major", wrapper)
        self.assertIn("'DEPTHWISE_C3'", generator)
        self.assertIn("CONV_PROFILE_DEPTHWISE_C3 = 7", header)


if __name__ == '__main__':
    unittest.main()
