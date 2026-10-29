"""Offline CRC-reader controls, not RTL, physical CRC or FPGA evidence."""
import random
import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import verify_packet_crc as checked


def bit_reference(address, data, previous):
    value = (address << 32) | data
    state = previous
    polynomial = checked.POLY << 1
    for _ in range(37):
        if (value & 1) != (state & 1):
            state ^= polynomial
        value >>= 1
        state >>= 1
    return state


def packet(reg, values):
    return [(1 << 29) | (2 << 27) | (reg << 13) | len(values), *values]


def wrap(words, part=checked.PART):
    fields = dict(a='offline-crc-fixture', b=part, c='2026/10/09', d='00:00:00')
    raw = bytes.fromhex('00090ff00ff00ff00ff0000001')
    for name, value in fields.items():
        text = value.encode('ascii') + b'\0'
        raw += name.encode('ascii') + struct.pack('>H', len(text)) + text
    preamble = [0xffffffff] * 8 + [0xbb, 0x11220044, 0xffffffff, 0xffffffff, 0xaa995566]
    data = struct.pack('>' + 'I' * (len(preamble) + len(words)), *preamble, *words)
    return raw + b'e' + struct.pack('>I', len(data)) + data


def fixture(with_checks=True, data=(0, 1, 0xdeadbeef)):
    before = [(19, 0), (9, 0x02003fe5), (14, 0), (12, checked.IDCODE), (1, 0), (4, 1)]
    after = [(4, 10), (4, 3), (4, 5), (1, 0x03be0000), (6, 0x501), (5, 0x501)]
    result = packet(17, [0]) + packet(16, [0]) + packet(4, [0]) + packet(4, [7])
    state = 0
    for reg, value in before:
        result += packet(reg, [value])
        state = bit_reference(reg, value, state)
    result += packet(2, []) + [(2 << 29) | (2 << 27) | len(data), *data]
    for value in data:
        state = bit_reference(2, value, state)
    if with_checks:
        result += packet(0, [state])
    result += packet(4, [7])
    state = 0
    for reg, value in after:
        result += packet(reg, [value])
        state = bit_reference(reg, value, state)
    if with_checks:
        result += packet(0, [state])
    result += packet(4, [7]) + packet(4, [13]) + [0x20000000]
    return result


class PacketCrcControl(unittest.TestCase):
    def test_pinned_upstream_known_values(self):
        for address, data, previous, expected in (
                (0, 0, 0, 0), (16, 0, 0, 0x82f63b78),
                (31, 0xffffffff, 0, 0xbf86d4df), (0, 0, 0xffffffff, 0xc631e365)):
            with self.subTest(address=address, data=data, previous=previous):
                self.assertEqual(checked.update(address, data, previous), expected)

    def test_table_matches_37_bit_reference_seed3588(self):
        rng = random.Random(3588)
        for _ in range(4096):
            address, data, previous = rng.randrange(32), rng.getrandbits(32), rng.getrandbits(32)
            self.assertEqual(checked.update(address, data, previous), bit_reference(address, data, previous))

    def test_invalid_crc_arguments_rejected(self):
        for args in ((32, 0, 0), (-1, 0, 0), (False, 0, 0), (0, -1, 0),
                     (0, 1 << 32, 0), (0, 0, 1 << 32), (0, 0, True)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                checked.update(*args)

    def test_complete_control_is_software_only(self):
        result = checked.verify(wrap(fixture()))
        self.assertEqual(len(result['crc_checks']), 2)
        self.assertEqual(result['fdri_words'], 3)
        self.assertEqual(result['crc_resets'], 3)
        self.assertEqual(result['pre_reset_zero_prologue_words'], 3)
        for field in ('physical_configuration_crc_verified', 'timing_signoff', 'electrical_verified',
                      'drc_signoff', 'numerical_acceptance', 'full_target_acceptance',
                      'test_ready_bitstream', 'hardware_accessed', 'input_modified'):
            self.assertIs(result[field], False)

    def test_missing_checks_not_replaced_by_resets(self):
        with self.assertRaisesRegex(ValueError, 'reset discards unchecked'):
            checked.verify(wrap(fixture(False)))

    def test_actual_data_bit_corruption_rejected(self):
        words = fixture()
        location = words.index(0xdeadbeef)
        words[location] ^= 1
        with self.assertRaisesRegex(ValueError, 'CRC mismatch'):
            checked.verify(wrap(words))

    def test_actual_crc_word_corruption_rejected(self):
        words = fixture()
        location = words.index(packet(0, [0])[0]) + 1
        words[location] ^= 1
        with self.assertRaisesRegex(ValueError, 'CRC mismatch'):
            checked.verify(wrap(words))

    def test_wrong_exact_part_and_id_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Wrong exact'):
            checked.verify(wrap(fixture(), 'xc7a50tfgg484-1'))
        with self.assertRaisesRegex(ValueError, 'IDCODE'):
            checked.verify(wrap(fixture()), expected_idcode=0x23751093)

    def test_unsupported_packet_fields_rejected(self):
        for words, error in ((packet(8, [0]), 'Unsupported register'),
                             ([0x28004001, 0], 'read/reserved'),
                             ([0], 'packet type/debug'),
                             ([0x30004000, 0x20000000, 0x50000001, 0], 'immediate'),
                             ([0x50000001, 0], 'FDRI owner'),
                             ([0x30004000], 'Unfulfilled'),
                             ([0x30000002, 0, 0], 'scalar word count')):
            with self.subTest(words=words), self.assertRaisesRegex(ValueError, error):
                list(checked.packets(checked.payload(wrap(words), checked.PART)[1]))

    def test_unchecked_prologue_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unchecked pre-reset'):
            checked.verify(wrap(packet(9, [0]) + fixture()))

    def test_truncation_trailing_and_bad_preamble_rejected(self):
        raw = wrap(fixture())
        for broken in (raw[:-1], raw + b'\0', raw.replace(b'\x11\x22\x00\x44', b'\0\0\0\0', 1)):
            with self.subTest(length=len(broken)), self.assertRaises(ValueError):
                checked.verify(broken)

    def test_write_after_desync_rejected(self):
        with self.assertRaisesRegex(ValueError, 'after DESYNC'):
            checked.verify(wrap(fixture() + packet(1, [0])))


if __name__ == '__main__':
    unittest.main()
