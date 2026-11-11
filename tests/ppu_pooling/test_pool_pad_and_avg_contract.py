#!/usr/bin/env python3
"""Contract checks for the four leaves added in this increment.

  rk_ppu_pool_int_avg              Q16 integer average (4 captured profiles)
  rk_ppu_pool_max_k1s1_i8_c32      1x1 C32 identity
  rk_ppu_pool_max3x3s2_pad1_c8_h4w4   padded 3x3/stride-2 maximum
  rk_ppu_pool_avg2x2s1_pad1_c8_h1w1   padded 2x2/stride-1 average
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/ppu_pooling/fixtures'
AVG_CORE = ROOT / 'rtl/ppu/rk_ppu_pool_int_avg.sv'
AVG_WRAPPERS = (
    ROOT / 'rtl/ppu/rk_ppu_pool_avg_q16_i8_c16_k2s2.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg_q16_i8_c16_k3x3.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg_q16_i16_c8_k2s2.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg_q16_i16_c8_k3x3.sv',
)
IDENTITY = ROOT / 'rtl/ppu/rk_ppu_pool_max_k1s1_i8_c32.sv'
PAD_MAX = ROOT / 'rtl/ppu/rk_ppu_pool_max3x3s2_pad1_c8_h4w4.sv'
PAD_AVG = ROOT / 'rtl/ppu/rk_ppu_pool_avg2x2s1_pad1_c8_h1w1.sv'


def code_only(path: Path) -> str:
    return '\n'.join(line.split('//', 1)[0] for line in path.read_text().splitlines())


class IntegerAverageContractTests(unittest.TestCase):
    def test_divisor_is_signed(self) -> None:
        """Verilog makes `/` unsigned if either operand is unsigned.

        The first version divided by `SUM_W'(AREA)`, which is unsigned, so a
        sum of -144 divided by 9 produced 0xB7 instead of -16. The signed
        constant is the fix and this test pins it.
        """
        code = code_only(AVG_CORE)
        self.assertIn('localparam logic signed [SUM_W-1:0] AREA_SIGNED', code)
        self.assertIn('total / AREA_SIGNED', code)
        # The unsigned spelling must not come back.
        self.assertNotIn("total / SUM_W'(AREA)", code)

    def test_parameters_are_validated_at_elaboration(self) -> None:
        code = code_only(AVG_CORE)
        self.assertIn('ELEM_W != 8 && ELEM_W != 16', code)
        self.assertIn('LANES != 128 / ELEM_W', code)
        self.assertIn('ATOMS < 1 || ATOMS > 64', code)

    def test_wrappers_select_the_captured_geometry(self) -> None:
        expected = {
            AVG_WRAPPERS[0]: '#(.ELEM_W(8), .LANES(16), .KH(2), .KW(2))',
            AVG_WRAPPERS[1]: '#(.ELEM_W(8), .LANES(16), .KH(3), .KW(3))',
            AVG_WRAPPERS[2]: '#(.ELEM_W(16), .LANES(8), .KH(2), .KW(2))',
            AVG_WRAPPERS[3]: '#(.ELEM_W(16), .LANES(8), .KH(3), .KW(3))',
        }
        for path, parameters in expected.items():
            self.assertIn(parameters, path.read_text(), path.name)

    def test_fixture_sums_are_exact_multiples_of_the_area(self) -> None:
        """This is why the captures cannot distinguish truncation from floor.

        If a future capture has a non-exact sum, this test fails and the
        rounding rule must be re-derived rather than assumed.
        """
        import struct
        cases = {
            'int8_avg_q16_k2s2_valid_c16_h2w2': (16, 4, 8, 2, 2),
            'int8_avg_q16_k3x3_valid_c16_h3w3': (16, 9, 8, 3, 3),
            'int16_avg_q16_k2s2_valid_c8_h2w2': (8, 4, 16, 2, 2),
            'int16_avg_q16_k3x3_valid_c8_h3w3': (8, 9, 16, 3, 3),
        }

        def signed8(value: int) -> int:
            return value - 256 if value > 127 else value

        for case, (channels, area, width, kh, kw) in cases.items():
            fixture = FIXTURES / case
            raw = (fixture / 'in.bin').read_bytes()
            pixels = kh * kw
            if width == 8:
                values = [signed8(v) for v in raw[:pixels * channels]]
            else:
                values = list(struct.unpack(f'<{pixels * channels}h',
                                            raw[:pixels * channels * 2]))
            for channel in range(channels):
                total = sum(values[p * channels + channel] for p in range(pixels))
                self.assertEqual(total % area, 0,
                                 f'{case} channel {channel}: sum {total} is not a '
                                 f'multiple of area {area}; the captured rounding '
                                 f'rule must be re-derived')

    def test_leaf_records_the_candidate_rounding_rule(self) -> None:
        text = AVG_CORE.read_text()
        self.assertIn('candidate', text.lower())
        self.assertIn('truncation toward zero', text.lower())
        # The rejected reciprocal form must not appear in the datapath.
        code = code_only(AVG_CORE)
        self.assertNotIn('recip', code.lower())


class IdentityProfileContractTests(unittest.TestCase):
    def test_c32_identity_is_two_atoms_in_two_atoms_out(self) -> None:
        code = code_only(IDENTITY)
        self.assertIn('beat_q < 2', code.replace("'d", ''))
        self.assertIn('out_last', code)
        # 1x1 must not silently produce a non-identity result.
        self.assertNotIn('max', code.lower().replace('rk_ppu_pool_max', ''))

    def test_captured_c32_output_equals_input_prefix(self) -> None:
        fixture = FIXTURES / 'int8_max_k1s1_valid_c32_h1w1'
        data_in = (fixture / 'in.bin').read_bytes()
        device = (fixture / 'device_out.bin').read_bytes()
        self.assertEqual(data_in[:32], device[:32])
        self.assertFalse(any(data_in[32:]))
        self.assertFalse(any(device[32:]))


class PaddedMaximumContractTests(unittest.TestCase):
    def test_padding_is_the_captured_negative_infinity(self) -> None:
        code = code_only(PAD_MAX)
        self.assertIn("NEG_INF = 16'hfc00", code)
        # Out-of-window taps must not become zero or a neighbour.
        self.assertIn('candidate = NEG_INF', code)
        self.assertIn('y >= 0 && y < H && x >= 0 && x < W', code)

    def test_window_is_3x3_with_stride_2(self) -> None:
        code = code_only(PAD_MAX)
        self.assertIn('for (integer ky = 0; ky < 3; ky = ky + 1)', code)
        self.assertIn('oy * 2 - 1 + ky', code)

    def test_nan_is_an_explicit_fault_not_an_ordering(self) -> None:
        text = PAD_MAX.read_text()
        self.assertIn('NaN', text)
        code = code_only(PAD_MAX)
        self.assertIn("5'h1f", code)
        self.assertIn("16'hxxxx", code)

    def test_frozen_capture_reproduces_a_python_maximum(self) -> None:
        import struct
        import sys
        sys.path.insert(0, str(ROOT))
        from model.half import from_bits
        fixture = FIXTURES / 'fp16_max_k3s2_pad1_c8_h4w4'
        values = [from_bits(v) for v in
                  struct.unpack('<2048H', (fixture / 'in.bin').read_bytes())]
        device = [from_bits(v) for v in
                  struct.unpack('<2048H', (fixture / 'device_out.bin').read_bytes())]
        channels, height, width = 8, 4, 4
        negative_infinity = float('-inf')

        def pixel(y: int, x: int) -> list[float]:
            if y < 0 or y >= height or x < 0 or x >= width:
                return [negative_infinity] * channels
            base = (y * width + x) * channels
            return values[base:base + channels]

        computed = []
        for oy in range(2):
            for ox in range(2):
                for lane in range(channels):
                    best = negative_infinity
                    for ky in range(3):
                        for kx in range(3):
                            value = pixel(oy * 2 - 1 + ky, ox * 2 - 1 + kx)[lane]
                            best = max(best, value)
                    computed.append(best)
        self.assertEqual(len(computed), 32)
        for index, (mine, captured) in enumerate(zip(computed, device[:32])):
            self.assertAlmostEqual(mine, captured, places=6,
                                   msg=f'output {index} differs')


class PaddedAverageContractTests(unittest.TestCase):
    def test_padding_is_zero_and_division_is_by_four(self) -> None:
        code = code_only(PAD_AVG)
        self.assertIn('fp16_div4', code)
        self.assertIn("exponent - 5'd2", code)

    def test_both_use_cnt_profiles_share_one_leaf(self) -> None:
        # USE_CNT has no effect in these captures; the leaf must not branch on it.
        text = PAD_AVG.read_text().lower()
        self.assertIn('use_cnt', text)
        self.assertIn('implements no count-driven', text)

    def test_captured_values_are_exactly_v_over_four(self) -> None:
        import struct
        import sys
        sys.path.insert(0, str(ROOT))
        from model.half import from_bits
        for case in ('fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1',
                     'fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1'):
            fixture = FIXTURES / case
            source = [from_bits(v) for v in
                      struct.unpack('<2048H', (fixture / 'in.bin').read_bytes())]
            device = [from_bits(v) for v in
                      struct.unpack('<2048H', (fixture / 'device_out.bin').read_bytes())]
            self.assertEqual(source[0], 8.0, case)
            for atom in range(4):
                for lane in range(8):
                    self.assertEqual(device[atom * 8 + lane], 2.0, case)
            self.assertFalse(any(device[32:]), case)
            for lane in range(8):
                self.assertEqual(source[lane] / 4, 2.0, case)


if __name__ == '__main__':
    unittest.main()
