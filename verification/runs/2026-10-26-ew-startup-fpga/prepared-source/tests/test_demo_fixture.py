import json
from pathlib import Path
import struct
import unittest
from model.half import to_bits
from model.profile import decode
from model.sim import Memory, RKEmulator

class DemoFixtureTest(unittest.TestCase):
    def test_rom_workload_three_ops(self):
        data=json.loads((Path(__file__).parent/'demo_fixture.json').read_text())
        m=Memory()
        m.map(0x10000000,bytes(4096))
        for addr, vals in ((data['a'],data['input_a_bits']),(data['b'],data['input_b_bits'])):
            for i,v in enumerate(vals): m.write16(addr+2*i,v)
        sim=RKEmulator(m)
        for j in range(3):
            words=[int(s,16) for s in data['commands'][22*j:22*(j+1)]]
            self.assertEqual(decode(words[-1]),(0x81,8,0x18))
            sim.submit(struct.pack('<22Q',*words))
            self.assertEqual([m.read16(data['dst']+2*i) for i in range(8)],data['expected_bits'][8*j:8*(j+1)])
        self.assertEqual(sim.completed,3)
        # Independently readable, exact expected results for the first ADD run.
        self.assertEqual(data['expected_bits'][:8],[to_bits(v) for v in (3,5,7,-3,0,2**-13,0.75,0)])

if __name__=='__main__': unittest.main()
