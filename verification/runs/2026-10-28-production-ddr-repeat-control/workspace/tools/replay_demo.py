#!/usr/bin/env python3
"""Run the fixed FPGA ROM workload in the standalone software emulator."""
from pathlib import Path
import json
import struct
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from model.sim import Memory,RKEmulator
from model.dma import DMAEmulator
from model.half import from_bits
f=json.loads((ROOT/'tests/demo_fixture.json').read_text())
m=Memory()
m.map(0x10000000,bytes(4096))
for addr,words in ((f['a'],f['input_a_bits']),(f['b'],f['input_b_bits'])):
    for i,w in enumerate(words): m.write16(addr+2*i,w)
sim=RKEmulator(m)
for j,op in enumerate(('ADD','SUB','MUL')):
    words=[int(s,16) for s in f['commands'][22*j:22*(j+1)]]
    sim.submit(struct.pack('<22Q',*words))
    got=[m.read16(f['dst']+2*i) for i in range(8)]
    assert got==f['expected_bits'][8*j:8*(j+1)]
    print(f'{op}: {[from_bits(v) for v in got]} (software reference PASS)')
print(f'{sim.completed} tasks, {sim.memory_transactions} halfword memory transactions; no RTL/hardware executed.')
f=json.loads((ROOT/'tests/dma_demo_fixture.json').read_text())
m=Memory()
for address, _, size in f['windows']: m.map(address, bytes(size))
for address, value in f['init']: m.write16(address, value)
sim=DMAEmulator(m)
sim.submit_dma(f['start_address'], f['start_amount'])
assert [m.read16(address) for address, _ in f['init']]==f['expected']
assert (sim.completed, sim.command_reads, sim.memory_transactions)==(2,228,96)
print('DMA board ROM: unchanged production SUB(9), 2 tasks, 228 command reads, 96 data transactions, 336 memory checks (software only PASS).')
