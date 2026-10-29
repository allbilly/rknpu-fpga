import hashlib
import json
from pathlib import Path
import struct
import unittest

from model.dma import DMAEmulator
from model.profile import ProfileError
from model.sim import Memory
from tools.dma_demo_fixture import WINDOWS, fixture


class DMADemoTests(unittest.TestCase):
    def test_fixture_and_verbatim_command_hashes(self):
        f = fixture()
        self.assertEqual(json.loads(json.dumps(f)), json.loads(Path('tests/dma_demo_fixture.json').read_text()))
        data = dict(f['init'])
        for address, amount, digest in zip((0x100e0000, 0x100e0120), (35, 22), f['task_sha256']):
            raw = b''.join(struct.pack('<H', data[a]) for a in range(address, address+8*amount, 2))
            self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
        self.assertEqual(len(data), 336)

    def test_limited_map_executes_complete_chain(self):
        f = fixture()
        data = dict(f['init'])
        memory = Memory()
        for address, _, size in WINDOWS:
            memory.map(address, b''.join(struct.pack('<H', data[a]) for a in range(address, address+size, 2)))
        emu = DMAEmulator(memory)
        emu.submit_dma(f['start_address'], f['start_amount'])
        self.assertEqual((emu.completed, emu.command_reads, emu.memory_transactions), (2, 228, 96))
        self.assertEqual([memory.read16(a) for a, _ in f['init']], f['expected'])

    def test_aperture_bounds_and_nonaliasing(self):
        physical = set()
        memory = Memory()
        for address, offset, size in WINDOWS:
            self.assertFalse(physical.intersection(range(offset, offset+size)))
            physical.update(range(offset, offset+size))
            memory.map(address, bytes(size))
        self.assertLessEqual(max(physical), 4095)
        for address, _, size in WINDOWS:
            for bad in (address-2, address+1, address+size):
                with self.subTest(address=hex(bad)), self.assertRaises(ProfileError) as error:
                    memory.read16(bad)
                self.assertEqual(error.exception.code, 5)
