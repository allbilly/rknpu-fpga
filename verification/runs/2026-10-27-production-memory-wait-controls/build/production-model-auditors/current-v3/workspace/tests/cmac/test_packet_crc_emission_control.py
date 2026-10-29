"""CRC-only byte-transform controls; small in-memory fixtures are not FPGA proof."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import add_packet_crc_candidate as emitted
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_packet_crc_control import packet, wrap


def native(data=(0, 1, 0xdeadbeef)):
    words = []
    for reg, value in emitted.PROFILE:
        if value == 'EMPTY':
            words += packet(2, [])
        elif value == 'DATA':
            words += [(2 << 29) | (2 << 27) | len(data), *data]
        else:
            words += packet(reg, [value])
        # Native type-2 ownership must stay immediate.
        if value != 'EMPTY':
            words += [0x20000000]
    return words


class PacketCrcEmissionControl(unittest.TestCase):
    def test_only_two_packets_and_payload_length_added(self):
        raw = wrap(native())
        result, evidence = emitted.inject(raw, 3)
        self.assertEqual(len(result), len(raw) + 16)
        self.assertEqual(len(evidence['crc_insertions']), 2)
        self.assertTrue(evidence['original_payload_projection_byte_identical'])
        self.assertTrue(evidence['original_header_except_length_byte_identical'])
        self.assertEqual(evidence['crc_verification']['fdri_words'], 3)
        self.assertFalse(evidence['crc_verification']['test_ready_bitstream'])

    def test_real_new_crc_and_data_corruptions_rejected(self):
        result, _ = emitted.inject(wrap(native()), 3)
        _, data = emitted.reader.payload(result, emitted.reader.PART)
        for desired in (0, 2):
            position = next(offset for offset, reg, values in emitted.reader.packets(data)
                            if reg == desired and values)
            broken = bytearray(result)
            broken[len(result) - len(data) + (position + 1) * 4 + 3] ^= 1
            with self.subTest(register=desired), self.assertRaisesRegex(ValueError, 'CRC mismatch'):
                emitted.reader.verify(bytes(broken))

    def test_all_native_scalar_fields_checked(self):
        original = native()
        position = 0
        for reg, value in emitted.PROFILE:
            if value == 'EMPTY':
                position += 1
            elif value == 'DATA':
                position += 5  # Header, three words, NOP.
            else:
                broken = original.copy()
                broken[position + 1] ^= 1
                with self.subTest(register=reg, value=value), self.assertRaises(ValueError):
                    emitted.inject(wrap(broken), 3)
                position += 3

    def test_crc_present_or_extra_write_not_ignored(self):
        for extra in (packet(0, [0]), packet(13, [0])):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'profile'):
                emitted.inject(wrap(extra + native()), 3)

    def test_different_frame_data_length_rejected(self):
        with self.assertRaisesRegex(ValueError, 'FDRI length'):
            emitted.inject(wrap(native()), 4)

    def test_input_is_not_mutated(self):
        original = wrap(native())
        saved = bytes(original)
        emitted.inject(original, 3)
        self.assertEqual(original, saved)

    def test_default_requires_complete_k480_frame_extent(self):
        with self.assertRaisesRegex(ValueError, 'FDRI length'):
            emitted.inject(wrap(native()))

    def test_wrong_part_or_changed_preamble_rejected(self):
        raw = wrap(native())
        for broken in (wrap(native(), '7a50tfgg484'), raw.replace(b'\x11\x22\x00\x44', b'\0\0\0\0', 1)):
            with self.subTest(length=len(broken)), self.assertRaises(ValueError):
                emitted.inject(broken, 3)


if __name__ == '__main__':
    unittest.main()
