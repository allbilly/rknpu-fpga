# SPDX-License-Identifier: MIT
"""Pinned RK capture, register relocation and numerical/layout contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASE = 'conv_3x3_valid_c4_h9_w9_oc4'
FIXTURE = ROOT / 'tests/conv/fixtures' / CASE
def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Conv3x3ValidC4ContractTests(unittest.TestCase):
    def test_fixture_pins_source_provenance_and_single_task_capture(self) -> None:
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
        self.assertEqual([row['regcmd_index'] for row in job['patches']], [21, 27, 35])
        self.assertEqual(provenance['shape'], {
            'batch': 1, 'in_c': 4, 'in_h': 9, 'in_w': 9, 'out_c': 4,
            'kh': 3, 'kw': 3, 'stride': 1, 'groups': 1,
            'padded_zero_frame': False, 'effective_input_h': 9,
            'effective_input_w': 9, 'out_h': 7, 'out_w': 7,
        })
        self.assertEqual(manifest['source']['sha256'], provenance['source_sha256'])
        self.assertEqual(manifest['source']['sha256'],
                         'f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51')
        for name, record in manifest['files'].items():
            path = FIXTURE / name
            self.assertEqual(path.stat().st_size, record['bytes'], name)
            self.assertEqual(sha(path), record['sha256'], name)
        self.assertEqual(capture['hashes']['command_stream']['sha256'],
                         manifest['command']['captured_patched_sha256'])
        self.assertEqual(capture['hashes']['outputs']['out']['sha256'],
                         manifest['numeric']['device_output_bo_sha256'])

    def test_job_relocations_reproduce_captured_raw_qword_stream(self) -> None:
        job = json.loads((FIXTURE / 'job.json').read_text())
        capture = json.loads((FIXTURE / 'device_capture.json').read_text())
        raw = bytearray((FIXTURE / 'regcmd.bin').read_bytes())
        self.assertEqual(len(raw), 54 * 8)
        addresses = {'a': 0x1000, 'w': 0x2000, 'out': 0x3000}
        for patch in job['patches']:
            index = patch['regcmd_index']
            qword, = struct.unpack_from('<Q', raw, index * 8)
            qword = (qword & ~(0xffffffff << 16)) | (addresses[patch['buffer']] << 16)
            struct.pack_into('<Q', raw, index * 8, qword)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         capture['hashes']['command_stream']['sha256'])
        self.assertEqual([i for i in range(54)
                          if raw[i * 8:i * 8 + 8] != (FIXTURE / 'regcmd.bin').read_bytes()[i * 8:i * 8 + 8]],
                         [21, 27, 35])

    def test_packed_operands_and_defined_device_outputs_match_source_layout(self) -> None:
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        packed_input = struct.unpack('<1296H', (FIXTURE / 'a.bin').read_bytes())
        source_input = struct.unpack('<324H', (FIXTURE / 'source_input_nchw.bin').read_bytes())
        for y in range(9):
            for x in range(9):
                pixel = y * 9 + x
                for channel in range(8):
                    actual = packed_input[pixel * 8 + channel]
                    expected = source_input[channel * 81 + pixel] if channel < 4 else 0
                    self.assertEqual(actual, expected, (y, x, channel))
                for channel in range(8):
                    self.assertEqual(packed_input[648 + pixel * 8 + channel], 0,
                                     (y, x, 'second C1 plane', channel))

        packed_weight = struct.unpack('<576H', (FIXTURE / 'w.bin').read_bytes())
        source_weight = struct.unpack('<144H', (FIXTURE / 'source_weight_nchw.bin').read_bytes())
        for ky in range(3):
            for kx in range(3):
                tap = ky * 3 + kx
                for oc in range(4):
                    for ic in range(16):
                        actual = packed_weight[tap * 64 + oc * 16 + ic]
                        expected = source_weight[(oc * 4 + ic) * 9 + tap] if ic < 4 else 0
                        self.assertEqual(actual, expected, (ky, kx, oc, ic))

        expected = struct.unpack('<196H', (FIXTURE / 'expected.bin').read_bytes())
        device = struct.unpack('<1664H', (FIXTURE / 'device_out.bin').read_bytes())
        self.assertEqual(len(expected), manifest['shape']['output_channels'] * 49)
        for y in range(7):
            for x in range(7):
                atom = y * 7 + x
                for channel in range(4):
                    logical = expected[channel * 49 + atom]
                    captured = device[atom * 8 + channel]
                    self.assertEqual(logical, captured, (channel, y, x))
        self.assertEqual(manifest['numeric']['defined_elements_exact'], True)
        self.assertEqual(manifest['numeric']['padding_is_not_numerical_oracle'], True)

    def test_strict_profile_and_front_keep_the_supported_shape_fixed(self) -> None:
        profile = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_profile.sv').read_text()
        front = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_front.sv').read_text()
        core = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_core.sv').read_text()
        for fixed in ('32\'h00000120', '32\'h000000c0', '32\'h03030004',
                      '32\'h00000340', 'word_index == 6\'d53'):
            self.assertIn(fixed, profile)
        # BO sizes derive from each capture's own plane/atom allocation.
        self.assertIn("input_bytes = (GROUPED_C2 ? 33'd800 : 33'd2592)", profile)
        self.assertIn("((STRIDE2 || PAD1_ZERO_FRAME) ? 33'd1280 : 33'd0)", profile)
        self.assertIn("output_bytes = (GROUPED_C2 ? 33'd768 : 33'd3328)", profile)
        self.assertIn("(PAD1_ZERO_FRAME ? 33'd2048 : 33'd0)", profile)
        self.assertIn("(STRIDE2 ? 33'd1536 : 33'd0)", profile)
        self.assertIn("weight_bytes = DEPTHWISE_C3 ? 33'd144 :", profile)
        self.assertIn("SPLIT_OC_C16 ? 33'd2304 : 33'd1152", profile)
        self.assertIn("input_end = {1'b0, config_input_base} + input_bytes", profile)
        self.assertIn("output_end = {1'b0, config_output_base} + output_bytes", profile)
        # The front is geometry-parameterized rather than a literal C4 table.
        self.assertIn("parameter int unsigned INPUT_CHANNELS = 4", front)
        self.assertIn("parameter int unsigned KERNELS = 4", front)
        self.assertIn("parameter int unsigned ALIGN_C = 16", front)
        self.assertIn("parameter int unsigned PACK_C2 = 8", front)
        self.assertIn('localparam int unsigned WEIGHT_HALFWORDS = TAPS * WEIGHT_LANES * CHUNKS', front)
        self.assertIn('chunk_f * TAPS * WEIGHT_LANES + tap * WEIGHT_LANES +', front)
        self.assertIn("lane_of_slot = slot / int'(INPUT_CHANNELS)", front)
        self.assertIn("frame_data_mask = REAL_MASK", front)
        # The tap count is derived from the requested kernel, and the default
        # KH/KW of 3 must still yield the captured nine taps.
        self.assertIn("localparam int unsigned TAPS = KH * KW", front)
        self.assertIn("parameter int unsigned KH = 3", front)
        self.assertIn("parameter int unsigned KW = 3", front)
        self.assertIn("frame_first = tap_index == 6\'d0", front)
        self.assertIn("frame_last = tap_index == 6\'(TAPS - 1)", front)
        self.assertIn("if (tap_index == 6\'(TAPS - 1)) begin", front)
        self.assertIn("output_atom == OUTPUT_H*OUTPUT_W-1" in front or
                      "32'(output_atom) == TOTAL_ATOMS-1", front)
        self.assertIn('CACC requires a stable tag', front)
        self.assertIn('.INPUT_CHANNELS(DEPTHWISE_C3 ? 3 : SPLIT_OC_C16 ? 16 : GROUPED_C2 ? 2 : 4)', core)
        self.assertIn('.KERNELS(DEPTHWISE_C3 ? 3 : SPLIT_OC_C16 ? 8 : 4)', core)
        self.assertIn('rk_cmac_cacc_fp16_array', core)


if __name__ == '__main__':
    unittest.main()
