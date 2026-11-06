import random
import struct
import unittest
from model.half import alu, to_bits
from model.profile import (Decoder, ENABLE, OPS, PROFILE_FIELDS, REGISTERS,
                           ProfileError, decode, encode, make_commands)
from model.sim import Memory, RKEmulator

A, B, D = 0x10000000, 0x10020000, 0x10040000

def words(raw):
    return [x for (x,) in struct.iter_unpack('<Q', raw)]

def change(raw, name, value):
    out = words(raw)
    idx = next(i for i, (_, _, n, _) in enumerate(REGISTERS) if n == name)
    target, address, *_ = REGISTERS[idx]
    out[idx] = encode(target, address, value)
    return struct.pack('<' + 'Q' * len(out), *out)

class ProfileTests(unittest.TestCase):
    def test_qword_format(self):
        self.assertEqual(encode(0x1001, 0x4070, 0x108202c0), 0x1001108202c04070)
        self.assertEqual(decode(0x1001108202c04070), (0x1001, 0x4070, 0x108202c0))
        self.assertEqual(encode(*ENABLE, 0x18), 0x0081000000180008)

    def test_all_profiles(self):
        for op in OPS:
            for n in (1, 7, 8, 9, 31, 32, 33, 63, 64, 65, 64000):
                with self.subTest(op=op, n=n):
                    dec = Decoder()
                    results = [dec.feed(w) for w in words(make_commands(op, n, A, B, D))]
                    self.assertTrue(all(x is None for x in results[:-1]))
                    self.assertEqual(results[-1].op, op)
                    self.assertEqual(results[-1].count, (n + 7) // 8 * 8)

    def assert_rejected(self, raw, code):
        m = Memory()
        destination = m.map(D, b'\x55\xaa' * 64)
        before = bytes(destination)
        emu = RKEmulator(m)
        with self.assertRaises(ProfileError) as ctx:
            emu.submit(raw)
        self.assertEqual(ctx.exception.code, code)
        self.assertEqual(before, bytes(destination))
        self.assertEqual(emu.memory_transactions, 0)

    def test_unknown_register(self):
        self.assert_rejected(struct.pack('<Q', encode(0x1001, 0x4074, 0)), 1)

    def test_wrong_target(self):
        self.assert_rejected(struct.pack('<Q', encode(0x0201, 0x4070, OPS['ADD'])), 1)

    def test_all_fixed_fields_reject_mutations(self):
        base = make_commands('ADD', 8, A, B, D)
        for _, _, name, value in REGISTERS:
            if value is not None:
                with self.subTest(register=name):
                    self.assert_rejected(change(base, name, value ^ 1), 7 if name.startswith('next_') else 2)

    def test_profile_dependent_fields(self):
        # out_convert and rdma_mode are only valid with the matching operation.
        for op in OPS:
            base = make_commands(op, 8, A, B, D)
            for name, value in PROFILE_FIELDS[op].items():
                with self.subTest(op=op, register=name):
                    self.assert_rejected(change(base, name, value ^ 1), 2)
        fdiv = make_commands('FDIV', 8, A, B, D)
        add = make_commands('ADD', 8, A, B, D)
        self.assert_rejected(change(fdiv, 'out_convert', PROFILE_FIELDS['ADD']['out_convert']), 2)
        self.assert_rejected(change(fdiv, 'rdma_mode', PROFILE_FIELDS['ADD']['rdma_mode']), 2)
        self.assert_rejected(change(add, 'out_convert', PROFILE_FIELDS['FDIV']['out_convert']), 2)
        self.assert_rejected(change(add, 'rdma_mode', PROFILE_FIELDS['FDIV']['rdma_mode']), 2)

    def test_missing_each_register(self):
        base = words(make_commands('ADD', 8, A, B, D))
        for i in range(len(REGISTERS)):
            with self.subTest(register=REGISTERS[i][2]):
                w = base[:i] + base[i + 1:]
                self.assert_rejected(struct.pack('<' + 'Q' * len(w), *w), 3)

    def test_bad_enable(self):
        base = words(make_commands('ADD', 8, A, B, D))
        base[-1] = encode(*ENABLE, 0x1d)
        self.assert_rejected(struct.pack('<' + 'Q' * len(base), *base), 2)

    def test_unsupported_precision_and_op(self):
        base = make_commands('ADD', 8, A, B, D)
        self.assert_rejected(change(base, 'data_format', 0xa8000002), 2)
        # FDIV is supported, but only with its own fixed field values.
        self.assert_rejected(change(base, 'ew_config', OPS['FDIV']), 2)
        self.assert_rejected(change(base, 'ew_config', 0x108503c0), 2)
        fdiv = make_commands('FDIV', 8, A, B, D)
        dec = Decoder()
        results = [dec.feed(w) for w in words(fdiv)]
        self.assertTrue(all(x is None for x in results[:-1]))
        self.assertEqual(results[-1].op, 'FDIV')

    def test_max_special_values(self):
        # +0 wins over -0; equal signs choose the larger value.
        self.assertEqual(alu(0x8000, 0x0000, 'MAX'), 0x0000)
        self.assertEqual(alu(0x0000, 0x8000, 'MAX'), 0x0000)
        self.assertEqual(alu(0x8000, 0x8000, 'MAX'), 0x8000)
        self.assertEqual(alu(0xbc00, 0xc000, 'MAX'), 0xbc00)
        self.assertEqual(alu(0xc000, 0xbc00, 'MAX'), 0xbc00)
        self.assertEqual(alu(0xfc00, 0x7bff, 'MAX'), 0x7bff)
        self.assertEqual(alu(0x7e00, 0x3c00, 'MAX'), 0x7c01)

    def test_captured_rk_special_values(self):
        # Real RK3588 Rocket captures: NaN results use 0x7c01, exact
        # ADD/SUB cancellation is +0, and SUB has a non-IEEE infinity quirk.
        for op in ('ADD', 'SUB', 'MUL', 'MAX'):
            with self.subTest(op=op):
                self.assertEqual(alu(0x7e00, 0x3c00, op), 0x7c01)
        self.assertEqual(alu(0x8000, 0x8000, 'ADD'), 0x0000)
        self.assertEqual(alu(0x8000, 0x0000, 'SUB'), 0x0000)
        self.assertEqual(alu(0xfc00, 0xfc00, 'SUB'), 0x7c00)
        self.assertEqual(alu(0x7c00, 0xfc00, 'SUB'), 0x7c01)
        self.assertEqual(alu(0xfc00, 0x0000, 'MUL'), 0x7c01)

    def test_fdiv_captured_special_values(self):
        # Real 4x4 zero/infinity matrix and the special-path sign(a) rule.
        self.assertEqual(alu(0x0000, 0x0000, 'FDIV'), 0x7c01)
        self.assertEqual(alu(0x0000, 0x8000, 'FDIV'), 0x7c00)
        self.assertEqual(alu(0x8000, 0x0000, 'FDIV'), 0xfc00)
        self.assertEqual(alu(0x8000, 0x8000, 'FDIV'), 0xfc00)
        self.assertEqual(alu(0x0000, 0x7c00, 'FDIV'), 0x0000)
        self.assertEqual(alu(0x8000, 0x7c00, 'FDIV'), 0x8000)
        self.assertEqual(alu(0x7c00, 0x7c00, 'FDIV'), 0x7c00)
        self.assertEqual(alu(0xfc00, 0x7c00, 'FDIV'), 0xfc00)
        self.assertEqual(alu(0x3c00, 0x8000, 'FDIV'), 0x7c00)
        self.assertEqual(alu(0xbc00, 0x8000, 'FDIV'), 0xfc00)
        self.assertEqual(alu(0x3c00, 0xfc00, 'FDIV'), 0x0000)
        self.assertEqual(alu(0xbc00, 0xfc00, 'FDIV'), 0x8000)
        self.assertEqual(alu(0x7e00, 0x3c00, 'FDIV'), 0x7c01)
        self.assertEqual(alu(0x3c00, 0x7c01, 'FDIV'), 0x7c01)
        # Finite overflow/underflow use sign(a)^sign(b), unlike special paths.
        self.assertEqual(alu(0x7bff, 0xb800, 'FDIV'), 0xfc00)
        self.assertEqual(alu(0x0001, 0xc000, 'FDIV'), 0x8000)

    def test_dimension_errors(self):
        base = make_commands('ADD', 16, A, B, D)
        self.assert_rejected(change(base, 'rdma_width', 0), 6)
        self.assert_rejected(change(base, 'width', 8000), 2)
        self.assert_rejected(change(base, 'width', 0x10000000), 2)

    def test_address_errors(self):
        base = make_commands('ADD', 32, A, B, D)
        for name in ('src_a', 'src_b', 'dst'):
            with self.subTest(name=name):
                self.assert_rejected(change(base, name, 0x10000002), 4)
                self.assert_rejected(change(base, name, 0xfffffff0), 4)
        self.assert_rejected(change(base, 'dst', A + 16), 4)
        self.assert_rejected(change(base, 'dst', B - 16), 4)

    def test_32bit_endpoint(self):
        d = Decoder()
        for w in words(make_commands('ADD', 8, 0xfffffff0, B, D)):
            cfg = d.feed(w)
        self.assertEqual(cfg.src_a, 0xfffffff0)

    def test_last_write_wins(self):
        w = words(make_commands('ADD', 8, A, B, D))
        w.insert(-1, encode(0x1001, 0x4070, OPS['MUL']))
        d = Decoder()
        for x in w:
            cfg = d.feed(x)
        self.assertEqual(cfg.op, 'MUL')

    def test_fault_sticky(self):
        d = Decoder()
        with self.assertRaises(ProfileError):
            d.feed(0)
        with self.assertRaises(ProfileError) as c:
            d.feed(words(make_commands('ADD', 8, A, B, D))[0])
        self.assertEqual(c.exception.code, 1)

    def test_framing(self):
        with self.assertRaises(ValueError):
            RKEmulator(Memory()).submit(b'\x00')
        self.assert_rejected(make_commands('ADD', 8, A, B, D)[:-8], 3)

class ExecutionTests(unittest.TestCase):
    def run_case(self, op, n, inplace=False):
        rng = random.Random(n)
        padded = (n + 7) // 8 * 8
        av = [rng.randrange(65536) for _ in range(n)] + [0] * (padded - n)
        bv = [rng.randrange(65536) for _ in range(n)] + [0] * (padded - n)
        a = struct.pack('<' + 'H' * padded, *av)
        b = struct.pack('<' + 'H' * padded, *bv)
        m = Memory()
        m.map(A, a + b'\xa5\x5a' * 8)
        m.map(B, b + b'\xa5\x5a' * 8)
        if not inplace:
            m.map(D, b'\xad\xde' * padded + b'\xa5\x5a' * 8)
        emu = RKEmulator(m)
        dst = A if inplace else D
        emu.submit(make_commands(op, n, A, B, dst))
        for i, (x, y) in enumerate(zip(av, bv)):
            self.assertEqual(m.read16(dst + 2*i), alu(x, y, op))
        for i in range(8):
            self.assertEqual(m.read16(dst + padded*2 + i*2), 0x5aa5)
        self.assertEqual(emu.completed, 1)
        self.assertEqual(emu.memory_transactions, padded*3)
        self.assertEqual(m.regions[B][:len(b)], b)
        if not inplace:
            self.assertEqual(m.regions[A][:len(a)], a)

    def test_arithmetic_end_to_end(self):
        for op in OPS:
            for n in (1, 2, 7, 8, 9, 31, 32, 33, 63, 64, 65, 257, 4096, 64000):
                with self.subTest(op=op, n=n): self.run_case(op, n)

    def test_inplace(self):
        for op in OPS:
            with self.subTest(op=op): self.run_case(op, 33, True)

    def test_back_to_back_tasks(self):
        m = Memory()
        m.map(A, struct.pack('<8H', *([to_bits(1)]*8)))
        m.map(B, struct.pack('<8H', *([to_bits(2)]*8)))
        m.map(D, b'\0'*16)
        emu = RKEmulator(m)
        emu.submit(make_commands('ADD', 8, A, B, D) + make_commands('MUL', 8, D, B, A))
        self.assertEqual(emu.completed, 2)
        self.assertEqual(m.read16(A), to_bits(6))

    def test_memory_fault(self):
        m = Memory()
        m.map(A, b'\0'*16)
        emu = RKEmulator(m)
        with self.assertRaises(ProfileError) as c:
            emu.submit(make_commands('ADD', 8, A, B, D))
        self.assertEqual(c.exception.code, 5)
        with self.assertRaises(ProfileError):
            emu.submit(make_commands('ADD', 8, A, B, D))

    def test_memory_mapping(self):
        m = Memory()
        m.map(0, b'\0'*16)
        with self.assertRaises(ValueError): m.map(8, b'\0'*16)
        with self.assertRaises(ValueError): m.map(0xffffffff, b'\0'*16)
        with self.assertRaises(ProfileError): m.read16(1)

if __name__ == '__main__':
    unittest.main(verbosity=2)
