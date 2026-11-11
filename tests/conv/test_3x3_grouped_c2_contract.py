#!/usr/bin/env python3
"""Contract checks for the promoted grouped-task C2 3x3 captures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASES = ('conv_grouped_3x3_c4_h5_w5_oc8_g2_task0',
         'conv_grouped_3x3_c4_h5_w5_oc8_g2_task1')
ADDRESSES = {'a': 0x1000, 'w': 0x2000, 'out': 0x3000}
PARENT = ROOT / 'build/rk3588-example-captures/conv-fp16/cases'


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


class ConvGroupedC2ContractTests(unittest.TestCase):
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
            self.assertEqual(provenance['shape']['in_c'], 2)
            self.assertEqual(provenance['shape']['out_c'], 4)
            self.assertEqual(provenance['shape']['in_h'], 5)
            self.assertEqual(provenance['shape']['in_w'], 5)
            self.assertEqual(provenance['shape']['out_h'], 3)
            self.assertEqual(provenance['shape']['out_w'], 3)
            self.assertEqual(provenance['shape']['groups'], 1)
            self.assertEqual(provenance['shape']['parent_case'],
                             'conv_grouped_3x3_c4_h5_w5_oc8_g2')
            self.assertEqual(manifest['source']['sha256'],
                             provenance['source_sha256'])
            for name, record in manifest['files'].items():
                payload = (fixture / name).read_bytes()
                self.assertEqual(len(payload), record['bytes'], name)
                self.assertEqual(sha(fixture / name), record['sha256'], name)

    def test_command_stream_is_the_promoted_host_tuple(self) -> None:
        for case in CASES:
            fixture = ROOT / 'tests/conv/fixtures' / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            capture = json.loads((fixture / 'device_capture.json').read_text())
            raw = (fixture / 'regcmd.bin').read_bytes()
            self.assertEqual(len(raw), 54 * 8)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),
                             manifest['command']['template_sha256'])
            relocated = patched_command(raw)
            self.assertEqual(hashlib.sha256(relocated).hexdigest(),
                             manifest['command']['captured_patched_sha256'])
            self.assertEqual(hashlib.sha256(relocated).hexdigest(),
                             capture['hashes']['command_stream']['sha256'])
            # Only the three declared value-32 relocations differ.
            differ = [i for i in range(54)
                      if struct.unpack_from('<Q', raw, i * 8)[0] !=
                      struct.unpack_from('<Q', relocated, i * 8)[0]]
            self.assertEqual(differ, [21, 27, 35])
            # The promoted task 0 and task 1 command streams are identical:
            # only the packed input/weight/output BOs differ per group.
            self.assertEqual(hashlib.sha256(raw).hexdigest(),
                             '29b60f0bc2baa4b802823dacba0770c7d36e46f0c4b7bf1994eba762ee55a08f')

    def test_packed_c2_operands_and_defined_outputs_match_oracle(self) -> None:
        for group, case in enumerate(CASES):
            fixture = ROOT / 'tests/conv/fixtures' / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            packed = struct.unpack('<400H', (fixture / 'a.bin').read_bytes())
            weights = struct.unpack('<576H', (fixture / 'w.bin').read_bytes())
            expected = struct.unpack('<36H', (fixture / 'expected.bin').read_bytes())
            device = struct.unpack('<384H', (fixture / 'device_out.bin').read_bytes())
            source_input = struct.unpack('<100H',
                                         (fixture / 'source_input_nchw.bin').read_bytes())
            source_weight = struct.unpack('<144H',
                                          (fixture / 'source_weight_nchw.bin').read_bytes())
            self.assertEqual(manifest['layout']['input_pixel_stride_bytes'], 16)
            self.assertEqual(manifest['layout']['output_logical_elements'], 36)
            # Two C1 planes of 25 pixels, each pixel a 16-byte C2=8 atom.
            self.assertEqual(manifest['layout']['input_c1_plane_stride_bytes'], 400)
            # The parent NCHW source holds all four grouped input channels;
            # the promoted task carries its own two-channel group slice.
            for pixel in range(25):
                for channel in range(2):
                    self.assertEqual(packed[pixel * 8 + channel],
                                     source_input[(group * 2 + channel) * 25 + pixel],
                                     (pixel, channel))
                for channel in range(2, 8):
                    self.assertEqual(packed[pixel * 8 + channel], 0, (pixel, channel))
            for halfword in range(200, 400):
                self.assertEqual(packed[halfword], 0, halfword)
            # kh-major [tap][OC][align_C=16]; real IC=0,1 and OC=0..3.
            # The parent NCHW weight file stores both groups back-to-back
            # (72 halfwords per group).
            for tap in range(9):
                for oc in range(4):
                    for ic in range(16):
                        want = (source_weight[group * 72 + (oc * 2 + ic) * 9 + tap]
                                if ic < 2 else 0)
                        self.assertEqual(weights[tap * 64 + oc * 16 + ic], want,
                                         (tap, oc, ic))
            for atom in range(9):
                for channel in range(4):
                    self.assertEqual(device[atom * 8 + channel],
                                     expected[channel * 9 + atom], (atom, channel))
            # The padded OC4..OC7 lanes and the rest of the 768-byte BO are not
            # a numerical oracle; the capture retains prior-job bytes there.
            # Only the BO size and the declared non-oracle policy are asserted.
            self.assertEqual(len(device), 384)
            self.assertTrue(manifest['numeric']['padding_is_not_numerical_oracle'])
            self.assertTrue(manifest['numeric']['defined_elements_exact'])
            self.assertTrue(manifest['numeric']['padding_is_not_numerical_oracle'])

    def test_promoted_replays_keep_the_parent_two_task_case_blocked(self) -> None:
        parent = json.loads((PARENT / 'conv_grouped_3x3_c4_h5_w5_oc8_g2' /
                             'job.json').read_text())
        self.assertEqual(len(parent['tasks']), 2)
        family = json.loads((ROOT / 'build/rk3588-example-captures/conv-fp16' /
                             'manifest.json').read_text())
        rows = {row['case']: row for row in family['cases']}
        for case in CASES:
            self.assertEqual(rows[case]['status'], 'READY')
        self.assertEqual(rows['conv_grouped_3x3_c4_h5_w5_oc8_g2']['status'],
                         'BLOCKED')

    def test_rtl_selects_a_parameterized_grouped_c2_profile(self) -> None:
        profile = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_profile.sv').read_text()
        front = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_front.sv').read_text()
        core = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_core.sv').read_text()
        wrapper = (ROOT / 'rtl/cmac/rk_conv_3x3_grouped_c2_core.sv').read_text()
        self.assertIn("parameter bit GROUPED_C2 = 1'b0", profile)
        for index, value in {
            5: "GROUPED_C2 ? 32'h00000080",
            7: "GROUPED_C2 ? 32'h00050005",
            8: "GROUPED_C2 ? 32'h00010010",
            9: "GROUPED_C2 ? 32'h00000003",
            10: "GROUPED_C2 ? 32'h00000009",
            15: "GROUPED_C2 ? 32'h00000003",
            23: "GROUPED_C2 ? 32'h00000014",
            24: "GROUPED_C2 ? 32'h00000005",
            25: "GROUPED_C2 ? 32'h00050005",
            30: "GROUPED_C2 ? 32'h00020002",
            36: "GROUPED_C2 ? 32'h000000c0",
            37: "GROUPED_C2 ? 32'h00000002",
            38: "GROUPED_C2 ? 32'h00000002",
            44: "GROUPED_C2 ? 32'h00020002",
            49: "GROUPED_C2 ? 32'h00000180",
        }.items():
            self.assertIn(f"{index}: begin", profile)
            self.assertIn(value, profile)
        self.assertIn("input_bytes = (GROUPED_C2 ? 33'd800 : 33'd2592)", profile)
        self.assertIn("output_bytes = (GROUPED_C2 ? 33'd768 : 33'd3328)", profile)
        self.assertIn("parameter int unsigned INPUT_CHANNELS = 4", front)
        # Real channels are walked one per cycle; padded BO lanes stay
        # masked. The group base is derived, not a literal index chain.
        self.assertIn("lane_of_slot = slot / int'(INPUT_CHANNELS)", front)
        self.assertIn("channel_of_slot = slot % int'(INPUT_CHANNELS)", front)
        self.assertIn("weight_group_address(", front)
        self.assertIn("32'(output_atom), 32'(tap_index) + 32'd1", front)
        self.assertIn('chunk_f * TAPS * WEIGHT_LANES', front)
        self.assertIn("frame_data_mask = REAL_MASK", front)
        self.assertIn(".GROUPED_C2(GROUPED_C2)", core)
        self.assertIn(".INPUT_CHANNELS(DEPTHWISE_C3 ? 3 : SPLIT_OC_C16 ? 16 : GROUPED_C2 ? 2 : 4)", core)
        self.assertIn(".OUTPUT_H(DEPTHWISE_C3 ? 9 :", core)
        self.assertIn(".GROUPED_C2(1'b1)", wrapper)
        self.assertIn("padded lanes are masked", wrapper)


if __name__ == '__main__':
    unittest.main()
