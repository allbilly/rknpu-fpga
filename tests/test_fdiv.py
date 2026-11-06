"""Bit-exact checks for the captured RK3588 FP16 three-guard-bit FDIV model."""
from __future__ import annotations
from fractions import Fraction
import json
from pathlib import Path
import unittest

from model.half import fdiv_bits

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / 'tests/fdiv_capture_vectors.json'


def finite_value(bits: int) -> Fraction:
    sign = -1 if bits >> 15 else 1
    exponent = (bits >> 10) & 0x1f
    fraction = bits & 0x3ff
    if exponent == 0:
        return Fraction(sign * fraction, 1 << 24)
    return Fraction(sign * (1024 + fraction)) * Fraction(2) ** (exponent - 25)


def exact_rne(a: int, b: int) -> int:
    """Infinite-precision quotient rounded once to binary16, ties-to-even."""
    sa, sb = a >> 15, b >> 15
    quotient = abs(finite_value(a)) / abs(finite_value(b))
    exponent = quotient.numerator.bit_length() - quotient.denominator.bit_length()
    if quotient < Fraction(2) ** exponent:
        exponent -= 1
    quantum = Fraction(2) ** max(exponent - 10, -24)
    scaled = quotient / quantum
    n = scaled.numerator // scaled.denominator
    fraction = scaled - n
    if fraction > Fraction(1, 2) or (fraction == Fraction(1, 2) and n & 1):
        n += 1
    if n == 2048:
        n = 1024
        exponent += 1
    if n == 1024 and exponent < -14:
        exponent = -14
    sign = (sa ^ sb) << 15
    if exponent < -14:
        return sign | (n & 0x3ff)
    if exponent > 15:
        return sign | 0x7c00
    return sign | ((exponent + 15) << 10) | (n & 0x3ff)


def finite_nonzero(a: int, b: int) -> bool:
    return ((a & 0x7fff) != 0 and (a & 0x7c00) != 0x7c00 and
            (b & 0x7fff) != 0 and (b & 0x7c00) != 0x7c00)


class FdivCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(CAPTURES.read_text())
        cls.lanes = cls.document['lanes']

    def test_capture_inventory(self):
        self.assertEqual(self.document['schema'], 'rk3588-fdiv-captures/v1')
        self.assertEqual(len(self.lanes), 1452)
        self.assertEqual(self.document['counts']['lanes'], 1452)
        self.assertEqual(self.document['counts']['finite_nonzero_lanes'], 1278)
        self.assertEqual(self.document['counts']['a_over_7_one_ulp_low_records'], 20)

    def test_all_captured_lanes_match(self):
        for lane in self.lanes:
            with self.subTest(source=lane['source'], index=lane['index']):
                self.assertEqual(fdiv_bits(lane['a'], lane['b']), lane['y'])

    def test_exact_rne_differs_only_in_captured_false_tie_window(self):
        finite = [lane for lane in self.lanes
                  if finite_nonzero(lane['a'], lane['b'])]
        self.assertEqual(len(finite), 1278)
        mismatches = [lane for lane in finite
                      if exact_rne(lane['a'], lane['b']) != lane['y']]
        self.assertEqual(len(mismatches), 20)
        for lane in mismatches:
            self.assertEqual(lane['b'], 0x4700)
            self.assertEqual(fdiv_bits(lane['a'], lane['b']), lane['y'])
            self.assertEqual(exact_rne(lane['a'], lane['b']), lane['y'] + 1)

    def test_a_over_7_records(self):
        a_values = {0x4c80, 0x5240, 0x5340, 0x5810, 0x59d0, 0x5c48, 0x5d28,
                    0x5e08, 0x5ee8, 0x5f08, 0x5fe8, 0x6064, 0x60d4, 0x6144,
                    0x61b4, 0x6224, 0x6294, 0x6324, 0x6394}
        records = [lane for lane in self.lanes
                   if lane['b'] == 0x4700 and lane['a'] in a_values]
        self.assertEqual(len(records), 20)
        self.assertEqual(len({lane['a'] for lane in records}), 19)
        for lane in records:
            self.assertEqual(fdiv_bits(lane['a'], lane['b']), lane['y'])
            self.assertEqual(lane['y'] + 1, exact_rne(lane['a'], lane['b']))

    def test_three_guard_bits_are_required(self):
        # 18/7 is the smallest captured false-tie-window case. Two guards would
        # round it up; four guards, or exact RNE, also round it up.
        self.assertEqual(fdiv_bits(0x4c80, 0x4700), 0x4124)
        self.assertEqual(exact_rne(0x4c80, 0x4700), 0x4125)

    def test_targeted_finite_rounding(self):
        cases = {
            (0x3c00, 0x4200): 0x3555,  # 1/3: below half an ULP
            (0x4000, 0x4200): 0x3955,  # 2/3: above half an ULP
            (0x3c00, 0x4900): 0x2e66,  # 1/10
            (0x7bff, 0x4900): 0x6e66,  # 65504/10: window, odd n rounds up
            (0x0001, 0x4000): 0x0000,  # exact 2^-25 tie rounds to even zero
            (0x0003, 0x4000): 0x0002,  # exact subnormal tie rounds to even
            (0x0005, 0x4000): 0x0002,  # exact subnormal tie rounds to even
            (0x0401, 0x4000): 0x0200,  # subnormal tie into min normal
            (0x7bff, 0x0400): 0x7c00,  # gross finite overflow
            (0x0001, 0x7bff): 0x0000,  # gross finite underflow
            (0xbc00, 0x4000): 0xb800,  # finite sign is sa^sb
            (0x8001, 0x4000): 0x8000,  # negative underflow tie to -0
        }
        for (a, b), expected in cases.items():
            with self.subTest(a=hex(a), b=hex(b)):
                self.assertEqual(fdiv_bits(a, b), expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
