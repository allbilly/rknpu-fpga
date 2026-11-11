# SPDX-License-Identifier: MIT
"""Capture and explicit-zero-frame contract for the 3x3 C4 padded case."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASE = 'conv_3x3_pad1_zero_frame_c4_h9_w9_oc4'
FIXTURE = ROOT / 'tests/conv/fixtures' / CASE
VALID = ROOT / 'tests/conv/fixtures/conv_3x3_valid_c4_h9_w9_oc4'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Conv3x3Pad1C4ContractTests(unittest.TestCase):
    def test_capture_provenance_and_single_task_fixture_are_pinned(self) -> None:
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        job = json.loads((FIXTURE / 'job.json').read_text())
        provenance = json.loads((FIXTURE / 'provenance.json').read_text())
        capture = json.loads((FIXTURE / 'device_capture.json').read_text())
        self.assertEqual(manifest['case'], CASE)
        self.assertEqual(manifest['status'], 'READY_CAPTURE_BOUNDED_CANDIDATE')
        self.assertEqual(capture['status'], 'OK')
        self.assertEqual(capture['submit_ret'], 0)
        self.assertEqual(job['tasks'], [{'regcmd_offset_words': 0, 'regcmd_words': 54}])
        self.assertEqual([p['regcmd_index'] for p in job['patches']], [21, 27, 35])
        self.assertEqual(manifest['source']['sha256'], provenance['source_sha256'])
        self.assertEqual(manifest['source']['sha256'],
                         'f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51')
        self.assertEqual(provenance['shape']['padded_zero_frame'], True)
        self.assertEqual(provenance['shape']['effective_input_h'], 11)
        self.assertEqual(provenance['shape']['effective_input_w'], 11)
        self.assertEqual(provenance['shape']['out_h'], 9)
        self.assertEqual(provenance['shape']['out_w'], 9)
        for name, record in manifest['files'].items():
            path = FIXTURE / name
            self.assertEqual(path.stat().st_size, record['bytes'], name)
            self.assertEqual(sha(path), record['sha256'], name)
        self.assertEqual(capture['hashes']['outputs']['out']['sha256'],
                         manifest['numeric']['device_output_bo_sha256'])

    def test_exact_qword_delta_is_not_stride2_or_valid_profile(self) -> None:
        valid = struct.unpack('<54Q', (VALID / 'regcmd.bin').read_bytes())
        padded = struct.unpack('<54Q', (FIXTURE / 'regcmd.bin').read_bytes())
        values = {
            5: 0x000000e0, 7: 0x000b000b, 9: 0x00000009,
            10: 0x00000051, 15: 0x00000006, 23: 0x0000002c,
            24: 0x0000004d, 25: 0x000b000b, 30: 0x00080008,
            36: 0x00000540, 37: 0x00000008, 38: 0x00000008,
            44: 0x00080008, 49: 0x00000a80,
        }
        self.assertEqual([i for i, pair in enumerate(zip(valid, padded))
                          if pair[0] != pair[1]], list(values))
        for i, (old, new) in enumerate(zip(valid, padded)):
            self.assertEqual((old >> 48, old & 0xffff), (new >> 48, new & 0xffff), i)
            if i in values:
                self.assertEqual((new >> 16) & 0xffffffff, values[i], i)

        job = json.loads((FIXTURE / 'job.json').read_text())
        capture = json.loads((FIXTURE / 'device_capture.json').read_text())
        stream = bytearray((FIXTURE / 'regcmd.bin').read_bytes())
        for patch in job['patches']:
            qword, = struct.unpack_from('<Q', stream, patch['regcmd_index'] * 8)
            address = {'a': 0x1000, 'w': 0x2000, 'out': 0x3000}[patch['buffer']]
            struct.pack_into('<Q', stream, patch['regcmd_index'] * 8,
                             (qword & ~(0xffffffff << 16)) | (address << 16))
        self.assertEqual(hashlib.sha256(stream).hexdigest(),
                         capture['hashes']['command_stream']['sha256'])
        # The RTL replay's 16-byte-aligned output base must actually overflow
        # the padded profile's 5,376-byte output allocation.
        self.assertEqual(0xffffeb10 & 0xf, 0)
        self.assertGreater(0xffffeb10 + 5376, 1 << 32)

    def test_packed_bo_contains_the_source_zero_frame_and_exact_outputs(self) -> None:
        packed = struct.unpack('<1936H', (FIXTURE / 'a.bin').read_bytes())
        source = struct.unpack('<324H', (FIXTURE / 'source_input_nchw.bin').read_bytes())
        for y in range(11):
            for x in range(11):
                pixel = y * 11 + x
                for c in range(8):
                    if c >= 4 or y in (0, 10) or x in (0, 10):
                        expected = 0
                    else:
                        expected = source[c * 81 + (y - 1) * 9 + x - 1]
                    self.assertEqual(packed[pixel * 8 + c], expected, (y, x, c))
                    self.assertEqual(packed[968 + pixel * 8 + c], 0,
                                     (y, x, 'second C1 plane', c))

        weights = struct.unpack('<576H', (FIXTURE / 'w.bin').read_bytes())
        source_weights = struct.unpack('<144H', (FIXTURE / 'source_weight_nchw.bin').read_bytes())
        for tap in range(9):
            for oc in range(4):
                for ic in range(16):
                    expected = source_weights[(oc * 4 + ic) * 9 + tap] if ic < 4 else 0
                    self.assertEqual(weights[tap * 64 + oc * 16 + ic], expected,
                                     (tap, oc, ic))

        logical = struct.unpack('<324H', (FIXTURE / 'expected.bin').read_bytes())
        captured = struct.unpack('<2688H', (FIXTURE / 'device_out.bin').read_bytes())
        for atom in range(81):
            for channel in range(4):
                self.assertEqual(captured[atom * 8 + channel],
                                 logical[channel * 81 + atom], (atom, channel))
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        self.assertTrue(manifest['numeric']['defined_elements_exact'])
        self.assertTrue(manifest['numeric']['padding_is_not_numerical_oracle'])

    def test_rtl_consumes_explicit_zero_frame_under_exact_padded_profile(self) -> None:
        profile = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_profile.sv').read_text()
        front = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_front.sv').read_text()
        core = (ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_core.sv').read_text()
        wrapper = (ROOT / 'rtl/cmac/rk_conv_3x3_pad1_zero_frame_c4_core.sv').read_text()
        self.assertIn("parameter bit PAD1_ZERO_FRAME = 1'b0", profile)
        for index, value in {
            9: "PAD1_ZERO_FRAME ? 32'h00000009",
            10: "PAD1_ZERO_FRAME ? 32'h00000051",
            30: "PAD1_ZERO_FRAME ? 32'h00080008",
            36: "PAD1_ZERO_FRAME ? 32'h00000540",
            37: "PAD1_ZERO_FRAME ? 32'h00000008",
            38: "PAD1_ZERO_FRAME ? 32'h00000008",
            44: "PAD1_ZERO_FRAME ? 32'h00080008",
            49: "PAD1_ZERO_FRAME ? 32'h00000a80",
        }.items():
            self.assertIn(f"{index}: begin", profile)
            self.assertIn(value, profile)
        self.assertIn('INPUT_H != (OUTPUT_H - 1) * STRIDE + KH', front)
        self.assertIn('INPUT_W != (OUTPUT_W - 1) * STRIDE + KW', front)
        # A 3x3 elaboration must still reproduce the captured geometry.
        self.assertIn('parameter int unsigned KH = 3', front)
        self.assertIn('parameter int unsigned KW = 3', front)
        # The atom counter spans the whole BO, which for a single C1 block
        # equals the pixel count. Both spellings are the same quantity.
        self.assertIn("localparam int unsigned TOTAL_ATOMS = BLOCK_STRIDE * C1_BLOCKS",
                      front)
        self.assertIn("32'(output_atom) == TOTAL_ATOMS-1", front)
        self.assertIn("logic [ATOM_BITS-1:0] output_atom", front)
        # The atom counter spans every C1 block; with one block it reduces to
        # the padded pixel count.
        self.assertIn("ATOM_BITS = $clog2(TOTAL_ATOMS + 1)", front)
        self.assertIn(".INPUT_H(DEPTHWISE_C3 ? 11 :", core)
        self.assertIn(".OUTPUT_H(DEPTHWISE_C3 ? 9 :", core)
        self.assertIn(".PAD1_ZERO_FRAME(PAD1_ZERO_FRAME)", core)
        self.assertIn(".GROUPED_C2(GROUPED_C2)", core)
        self.assertIn(".PAD1_ZERO_FRAME(1'b1)", wrapper)
        self.assertIn("consuming its explicit packed 11x11 zero BO", wrapper)


if __name__ == '__main__':
    unittest.main()
