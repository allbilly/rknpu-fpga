"""Portable production BOs plus explicitly synthetic PC DMA protocol tests."""
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.dma import DMAEmulator, TAIL_KEYS
from model.profile import ProfileError, decode, encode, make_commands
from model.sim import Memory

BASE, A, B, D, C = 0x10000000, 0x10001000, 0x10020000, 0x10040000, 0x100e0000


class FaultMemory(Memory):
    def __init__(self, bus_error_at=0, drop_at=0, stall_at=0):
        super().__init__()
        self.transactions = 0
        self.bus_error_at, self.drop_at, self.stall_at = bus_error_at, drop_at, stall_at

    def access(self):
        if self.transactions+1 == self.stall_at:
            raise ProfileError(8, 'test adapter request timeout')
        self.transactions += 1
        if self.transactions == self.bus_error_at:
            raise ProfileError(5, 'test adapter bus error')
        if self.transactions == self.drop_at:
            raise ProfileError(8, 'test adapter response timeout')

    def read16(self, address):
        self.access()
        return super().read16(address)

    def write16(self, address, value):
        self.access()
        super().write16(address, value)


def production_cases():
    capture = json.loads((ROOT/'tests/backend_ew_captures.json').read_text())
    cases = []
    for c in capture['cases']:
        regions = {}
        for r in c['regions']:
            data = zlib.decompress(base64.b64decode(r['zlib_base64'], validate=True))
            assert len(data) == r['size'] and hashlib.sha256(data).hexdigest() == r['sha256']
            regions[r['address']] = data
        for t in c['tasks']:
            d = t['descriptor']
            addr, size = d['regcmd_addr'], d['regcfg_amount']*8
            raw = next(data[addr-base:addr-base+size] for base, data in regions.items()
                       if base <= addr and addr+size <= base+len(data))
            assert hashlib.sha256(raw).hexdigest() == t['sha256']
        first = c['tasks'][0]['descriptor']
        cases.append(dict(name='capture_'+c['name'], regions=regions, address=first['regcmd_addr'],
                          amount=first['regcfg_amount'], error=0, tasks=len(c['tasks']), repeats=1,
                          production=c))
    return cases


def packed(words):
    return b''.join(struct.pack('<Q', word) for word in words)


def synthetic_words(next_address=0, next_amount=0, dst=D):
    body = [word for (word,) in struct.iter_unpack('<Q', make_commands('ADD', 8, A, B, dst))
            if decode(word)[:2] not in TAIL_KEYS]
    return body + [encode(*TAIL_KEYS[0], next_address), encode(*TAIL_KEYS[1], next_amount),
                   encode(*TAIL_KEYS[2], 0), encode(*TAIL_KEYS[3], 0x18)]


def all_cases():
    cases = production_cases()
    data = {A: bytes.fromhex('003c00bc003800b8004000c000000080'),
            B: bytes.fromhex('003c003c003c003c003c003c003c003c'), D: b'\xad\xde'*8}

    def add(name, words=None, error=0, tasks=1, **kwargs):
        words = synthetic_words() if words is None else words
        regions = data | {C: packed(words)} | kwargs.pop('extra_regions', {})
        cases.append(dict(name='dma_'+name, regions=regions, address=C, amount=len(words),
                          error=error, tasks=tasks, repeats=1) | kwargs)

    add('terminal')
    add('unmapped_guard', synthetic_words(C+0x1000))
    add('inplace', synthetic_words(dst=A))
    add('restart', repeats=2)
    add('reset_during_fetch', reset_at=1)
    add('reset_during_data_read', reset_at=89)
    add('restart_after_partial_write_fault', fault_before_restart=95)
    add('noncontiguous_chain', synthetic_words(C+0x2000, 18), tasks=2,
        extra_regions={C+0x2000: packed(synthetic_words())})
    add('three_tasks', synthetic_words(C+0x2000, 18), tasks=3,
        extra_regions={C+0x2000: packed(synthetic_words(C+0x4000, 18)),
                       C+0x4000: packed(synthetic_words())})
    add('cycle_limit', synthetic_words(C, 18), error=7, tasks=4)
    for name, overrides in [('misaligned_start', {'address': C+2}), ('zero_amount', {'amount': 0}),
                            ('short_amount', {'amount': 3}), ('long_amount', {'amount': 65540}),
                            ('start_overflow', {'address': 0xfffffff0})]:
        add(name, error=7, tasks=0, **overrides)
    add('unmapped_start', address=C+0x1000, error=5, tasks=0)
    add('next_overflow', synthetic_words(0xfffffff0, 18), error=7, tasks=1)
    add('next_unmapped', synthetic_words(C+0x1000, 18), error=5, tasks=1)
    add('next_unaligned', synthetic_words(C+2, 18), error=7, tasks=0)
    add('next_null', synthetic_words(0, 18), error=7, tasks=0)
    add('next_amount_limit', synthetic_words(C, 65536), error=7, tasks=0)
    add('unknown', [encode(0x1001, 0x4074, 0)]+synthetic_words(), error=1, tasks=0)
    add('missing_register', synthetic_words()[1:], error=3, tasks=0)
    add('early_enable', [encode(0x0081, 8, 0x18)]+synthetic_words(), error=3, tasks=0)
    add('missing_enable', synthetic_words()[:-1]+[encode(0x0041, 0, 0)], error=3, tasks=0)
    w = synthetic_words()
    add('swapped_tail', w[:-4]+[w[-3], w[-4]]+w[-2:], error=3, tasks=0)
    add('body_tail', [w[-4]]+w, error=3, tasks=0)
    add('bad_enable', w[:-1]+[encode(0x0081, 8, 0)], error=2, tasks=0)
    # 22 QWORDs * four reads, then 8 * (read A, read B, write D).
    for at in (1, 2, 3, 4, 5, 85, 88, 89, 90, 91, 92, 112):
        add(f'bus_error_{at}', error=5, tasks=0, bus_error_at=at)
    for kind in ('drop_at', 'stall_at'):
        for at in (1, 4, 88, 89, 91, 112):
            add(f'{kind}_{at}', error=8, tasks=0, **{kind: at})
    add('second_fetch_error', synthetic_words(C+0x2000, 18), error=5, tasks=1,
        extra_regions={C+0x2000: packed(synthetic_words())}, bus_error_at=113)
    return cases


def replay(case):
    mem = FaultMemory(**{k: case.get(k, 0) for k in ('bus_error_at', 'drop_at', 'stall_at')})
    for address, data in case['regions'].items():
        mem.map(address, data)
    emu = DMAEmulator(mem, max_tasks=4)
    error = 0
    try:
        for _ in range(case['repeats']):
            emu.submit_dma(case['address'], case['amount'])
    except ProfileError as exc:
        error = exc.code
    assert error == case['error'], (case['name'], error, case['error'])
    assert emu.completed == case['tasks']*case['repeats'], (case['name'], emu.completed)
    assert emu.jobs == (0 if error else case['repeats'])
    if c := case.get('production'):
        buf, off = mem.locate(c['expected_address'], c['logical_count']*2)
        assert bytes(buf[off:off+c['logical_count']*2]).hex() == c['expected_logical_hex']
        assert emu.command_reads == 4*sum(t['descriptor']['regcfg_amount'] for t in c['tasks'])
        assert emu.memory_transactions == 3*((c['logical_count']+7)//8*8)*len(c['tasks'])
    return mem, emu


def generate():
    out = ROOT/'build/dma_vectors'
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for c in all_cases():
        path = out/c['name']
        path.mkdir(exist_ok=True)
        mem, emu = replay(c)
        (path/'input.hex').write_text(''.join(f'@{(addr-BASE)//2:x}\n'+
            ''.join(f'{v:04x}\n' for (v,) in struct.iter_unpack('<H', data))
            for addr, data in sorted(c['regions'].items())))
        (path/'mapped.hex').write_text(''.join(f'@{(addr-BASE)//2:x}\n'+'1\n'*(len(data)//2)
            for addr, data in sorted(c['regions'].items())))
        (path/'check.txt').write_text(''.join(f'{addr+2*i:08x} {v:04x}\n'
            for addr, data in sorted(mem.regions.items()) for i, (v,) in enumerate(struct.iter_unpack('<H', data))))
        manifest.append({k: v for k, v in c.items() if k not in ('regions', 'production')} |
                        {'transactions': mem.transactions, 'jobs': emu.jobs,
                         'checks': sum(len(data)//2 for data in mem.regions.values()),
                         'production_capture': 'production' in c})
    (out/'cases.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Generated {len(manifest)} DMA cases, including nine verbatim production BO captures')


if __name__ == '__main__':
    generate()
