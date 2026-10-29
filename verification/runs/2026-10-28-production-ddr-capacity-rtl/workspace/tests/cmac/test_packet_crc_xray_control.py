"""Unchanged source-distributed normal-bitstream CRC checks and real negatives.

The normal fixture declares Vivado2016.3/7a50tfgg484. It is an offline CRC
algorithm corpus, not the K480 board design or RK3588/hardware captures.
Corruptions are in memory only; original inputs are never modified.
"""
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import verify_packet_crc as checked

NORMAL = Path('/home/fedora/tiny-gpu/build/ypcb/prjxray/lib/test_data/configuration_test.bit')
NORMAL_SHA = 'ede657295c11a5cc2b6b1984ab98507c20bd90aa46e38b5acc15fb75f2be7169'
SMALL = Path('/home/fedora/rknpu-fpga/build/openxc7/small-native-heap-bit-encoding-1791491349869461344/small-control.NOT_FOR_PROGRAMMING.unverified.bit')
SMALL_SHA = '35f6459a5d2a082d815cfb1e8586fd29517e25020868d8b8dfb038d4075e9519'
PART = '7a50tfgg484'
IDCODE = 0x0362c093


def pinned(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Changed literal corpus input')
    return raw


class XrayPacketCrcControl(unittest.TestCase):
    def test_unchanged_normal_fixture_two_crc_checks(self):
        result = checked.verify(pinned(NORMAL, NORMAL_SHA), PART, IDCODE)
        self.assertEqual(result['fdri_words'], 547420)
        self.assertEqual(result['checked_register_words'], 547437)
        self.assertEqual([(c['payload_word'], c['expected'], c['covered_words']) for c in result['crc_checks']],
                         [(547479, 1310965884, 547431), (547597, 3819798181, 6)])
        self.assertFalse(result['test_ready_bitstream'])
        self.assertFalse(result['physical_configuration_crc_verified'])
        self.assertFalse(result['full_target_acceptance'])
        self.assertEqual(hashlib.sha256(NORMAL.read_bytes()).hexdigest(), NORMAL_SHA)

    def corrupt_first_packet_word(self, register):
        raw = pinned(NORMAL, NORMAL_SHA)
        _, data = checked.payload(raw, PART)
        offset = next(offset for offset, reg, values in checked.packets(data)
                      if reg == register and len(values) > 0)
        broken = bytearray(raw)
        location = len(raw) - len(data) + (offset + 1) * 4 + 3
        broken[location] ^= 1
        self.assertNotEqual(hashlib.sha256(broken).hexdigest(), NORMAL_SHA)
        return bytes(broken)

    def test_actual_fdri_word_one_bit_corruption_rejected(self):
        with self.assertRaisesRegex(ValueError, 'CRC mismatch at payload word 547479'):
            checked.verify(self.corrupt_first_packet_word(2), PART, IDCODE)
        self.assertEqual(hashlib.sha256(NORMAL.read_bytes()).hexdigest(), NORMAL_SHA)

    def test_actual_crc_word_one_bit_corruption_rejected(self):
        with self.assertRaisesRegex(ValueError, 'CRC mismatch at payload word 547479'):
            checked.verify(self.corrupt_first_packet_word(0), PART, IDCODE)
        self.assertEqual(hashlib.sha256(NORMAL.read_bytes()).hexdigest(), NORMAL_SHA)

    def test_saved_k480_packet_without_crc_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'CRC reset discards unchecked'):
            checked.verify(pinned(SMALL, SMALL_SHA))
        self.assertEqual(hashlib.sha256(SMALL.read_bytes()).hexdigest(), SMALL_SHA)


if __name__ == '__main__':
    unittest.main()
