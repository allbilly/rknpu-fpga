import unittest

from model.dma import DMAEmulator
from model.profile import ProfileError
from model.sim import Memory
from tools.dma_fixtures import all_cases, production_cases, replay


class DMATests(unittest.TestCase):
    def test_production_capture_integrity_and_outputs(self):
        cases = production_cases()
        self.assertEqual(len(cases), 9)
        for case in cases:
            with self.subTest(case=case['name']):
                replay(case)

    def test_protocol_and_partial_writes(self):
        for case in all_cases():
            with self.subTest(case=case['name']):
                mem, emu = replay(case)
                if case['error']:
                    before = {a: bytes(d) for a, d in mem.regions.items()}
                    transactions = mem.transactions
                    with self.assertRaises(ProfileError) as error:
                        emu.submit_dma(case['address'], case['amount'])
                    self.assertEqual(error.exception.code, case['error'])
                    self.assertEqual(mem.transactions, transactions)
                    self.assertEqual(mem.regions, before)

    def test_entry_contract(self):
        for limit in (0, 4096):
            with self.assertRaises(ValueError):
                DMAEmulator(Memory(), limit)
        with self.assertRaises(TypeError):
            DMAEmulator(Memory()).submit(b'')
