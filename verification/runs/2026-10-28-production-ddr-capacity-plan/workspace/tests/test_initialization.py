import struct
import unittest

from model.profile import Decoder, ProfileError, decode, encode, make_commands
from model.sim import Memory, RKEmulator
from tools.ew_initialization import initialization_words, initialized_commands

A, B, D = 0x10001000, 0x10020000, 0x10040000


def decode_all(raw, decoder=None):
    decoder = decoder or Decoder()
    result = None
    for (word,) in struct.iter_unpack('<Q', raw):
        result = decoder.feed(word)
    return result


class InitializationTests(unittest.TestCase):
    def reject(self, raw, code):
        memory = Memory()
        before = b'\xad\xde' * 40
        output = memory.map(D, before)
        emulator = RKEmulator(memory)
        with self.assertRaises(ProfileError) as ctx:
            emulator.submit(raw)
        self.assertEqual(ctx.exception.code, code)
        self.assertEqual(emulator.completed, 0)
        self.assertEqual(emulator.memory_transactions, 0)
        self.assertEqual(bytes(output), before)

    def test_complete_profiles(self):
        for op in ('ADD', 'SUB', 'MUL'):
            for count in (1, 7, 8, 9, 33, 63999, 64000):
                with self.subTest(op=op, count=count):
                    cfg = decode_all(initialized_commands(op, count, A, B, D))
                    self.assertEqual((cfg.op, cfg.count), (op, (count+7)//8*8))

    def test_every_initialization_field_required_if_any_present(self):
        init = initialization_words(33)
        for i in range(len(init)):
            with self.subTest(register=hex(init[i] & 0xffff)):
                self.reject(initialized_commands('ADD', 33, A, B, D, init[:i]+init[i+1:]), 3)
                self.reject(initialized_commands('ADD', 33, A, B, D, [init[i]]), 3)

    def test_every_fixed_bit_rejected(self):
        init = initialization_words(33)
        for i, word in enumerate(init):
            target, address, value = decode(word)
            if address == 0x405c:
                continue
            for bit in range(32):
                with self.subTest(register=hex(address), bit=bit):
                    bad = init.copy()
                    bad[i] = encode(target, address, value ^ (1 << bit))
                    self.reject(initialized_commands('ADD', 33, A, B, D, bad), 2)

    def test_wdma_dimension_and_reserved_bits(self):
        for value, code in ((0, 6), (8000, 2), (0x2000, 2), (0x10000, 2), (0x80000004, 2)):
            init = initialization_words(33)
            init[6] = encode(0x1001, 0x405c, value)
            self.reject(initialized_commands('ADD', 33, A, B, D, init), code)

    def test_state_does_not_leak_between_tasks(self):
        d = Decoder()
        for raw in (initialized_commands('ADD', 33, A, B, D), make_commands('MUL', 8, A, B, D),
                    initialized_commands('SUB', 9, A, B, D)):
            self.assertIsNotNone(decode_all(raw, d))
        init = initialization_words(9)
        with self.assertRaises(ProfileError) as ctx:
            decode_all(initialized_commands('ADD', 9, A, B, D, init[1:]), d)
        self.assertEqual(ctx.exception.code, 3)

    def test_last_valid_write_and_sticky_invalid_write(self):
        init = initialization_words(33)
        wrong_shape = encode(0x1001, 0x405c, 0)
        self.assertEqual(decode_all(initialized_commands('ADD', 33, A, B, D, [wrong_shape]+init)).count, 40)
        invalid = encode(0x1001, 0x4040, 0x52)
        d = Decoder()
        with self.assertRaises(ProfileError) as ctx:
            d.feed(invalid)
        self.assertEqual(ctx.exception.code, 2)
        with self.assertRaises(ProfileError) as ctx:
            decode_all(initialized_commands('ADD', 33, A, B, D), d)
        self.assertEqual(ctx.exception.code, 2)

    def test_wrong_target_remains_unknown(self):
        for word in initialization_words(8):
            _, address, value = decode(word)
            self.reject(struct.pack('<Q', encode(0x2001, address, value)), 1)

    def test_nonzero_pc_tail_still_rejected(self):
        raw = initialized_commands('ADD', 8, A, B, D)
        words = [x for (x,) in struct.iter_unpack('<Q', raw)]
        i = next(i for i, x in enumerate(words) if decode(x)[:2] == (0x0101, 0x10))
        words[i] = encode(0x0101, 0x10, 0x100e0120)
        self.reject(struct.pack('<'+'Q'*len(words), *words), 7)
