#!/usr/bin/env python3
"""Generate fixed deterministic corpus for the private capacity-pattern leaf bench."""
from __future__ import annotations
import hashlib, json, pathlib, random, struct

ROOT=pathlib.Path('/home/fedora/rknpu-fpga')
OUT=pathlib.Path(__file__).resolve().parent
RTL=ROOT/'build/ddr-capacity-bist-source-v1/rk_ddr_capacity_pattern.sv'
LINE=64;PHYSICAL=1<<31;RNG_SEED=0x3588b157
BOUNDARY=[0,64,0x1000,0x1fc0,0x2000,0xffc0,0x10000,0x100000,
          0x7fff0000,0x7fffff00,0x7fffffc0]
SEEDS=[0,0x3588c350,0xffffffff]
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def pattern(address,seed,trial):
    # Independent fixture formula: little-endian 32-bit words in lane-major order.
    index=address//LINE
    words=[(index ^ seed ^ ((lane*0x9e3779b9)&0xffffffff) ^ (0xffffffff if trial else 0))&0xffffffff
           for lane in range(16)]
    return struct.pack('<16I',*words)

def main():
    rows=[]
    for address in BOUNDARY:
        for seed in SEEDS:
            for trial in (0,1):rows.append((address,seed,trial))
    rng=random.Random(RNG_SEED)
    random_rows=[]
    for _ in range(4096):
        address=rng.randrange(PHYSICAL//LINE)*LINE
        seed=rng.getrandbits(32);trial=rng.getrandbits(1)
        random_rows.append((address,seed,trial))
    rows.extend(random_rows)
    vectors=OUT/'vectors.txt'
    with vectors.open('x') as f:
        for address,seed,trial in rows:
            data=pattern(address,seed,trial)
            f.write(f'{address:08x} {seed:08x} {trial:d} 1 {int.from_bytes(data,"little"):0128x}\n')
    manifest={'schema':'ddr-capacity-pattern-leaf-vectors-v1','rows':len(rows),
      'boundary_addresses':[f'0x{x:08x}' for x in BOUNDARY],'boundary_seeds':[f'0x{x:08x}' for x in SEEDS],
      'boundary_trials':[0,1],'random_rows':4096,'random_seed':'0x3588b157',
      'address_generation':'uniform deterministic aligned line indices in [0,2^31/64)',
      'random_seed_and_trial':'getrandbits(32), getrandbits(1) from Python random.Random(0x3588b157)',
      'golden_words':'test_pattern.py separately pins address-zero words and bytes',
      'vectors_path':str(vectors),'vectors_sha256':sha(vectors),'vectors_bytes':vectors.stat().st_size,
      'rtl_source_path':str(RTL),'rtl_source_sha256':sha(RTL),
      'expected_data':'independent little-endian 16-word formula; no import of tools.ddr.capacity_pattern',
      'hardware_executed':False,'physical_capacity_qualified':False}
    out=OUT/'vectors-manifest.json';out.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'rows':len(rows),'vectors_sha256':manifest['vectors_sha256'],'manifest':str(out)},sort_keys=True))
if __name__=='__main__':main()
