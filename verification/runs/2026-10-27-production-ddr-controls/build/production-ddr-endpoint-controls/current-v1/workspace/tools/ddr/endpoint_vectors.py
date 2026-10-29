"""Raw captured BOs and independent software test oracles, never a device fallback."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import re
import zlib

from model.dma import DMAEmulator
from model.sim import Memory
from tools.ddr.interface import load_json, require

ROOT = Path(__file__).resolve().parents[2]
BASE = 0x10000000
BYTES = 1048576
LOCAL = ('tools/ddr/endpoint_vectors.py', 'tools/ddr/interface.py',
         'tests/backend_ew_captures.json', 'model/__init__.py', 'model/dma.py',
         'model/sim.py', 'model/profile.py', 'model/half.py')
CASE_NAMES = {f'{op}_{count}' for op in ('add', 'sub', 'mul') for count in (8, 9, 33)}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def captured_cases():
    capture = load_json(ROOT/'tests/backend_ew_captures.json')
    require(capture['backend_commit'] == '078eee94d8f1912bb63ce786c250d2c24984844a', 'Wrong backend encoder pin')
    names = [c['name'] for c in capture['cases']]
    require(len(names) == len(CASE_NAMES) and set(names) == CASE_NAMES, 'Capture inventory differs')
    cases = []
    for case in capture['cases']:
        regions = {}
        for region in case['regions']:
            address, size = region['address'], region['size']
            require(type(address) is type(size) is int and address % 64 == size % 64 == 0 and
                    size > 0 and BASE <= address and address+size <= BASE+BYTES, 'Unsafe physical BO extent')
            require(address not in regions, 'Duplicate BO base')
            data = zlib.decompress(base64.b64decode(region['zlib_base64'], validate=True))
            require(len(data) == size and sha(data) == region['sha256'], 'Captured BO identity differs')
            require(all(not (address < other+len(buf) and other < address+size)
                        for other, buf in regions.items()), 'Overlapping capture BOs')
            regions[address] = data
        tasks = case['tasks']
        require(tasks and len(tasks) <= 4, 'Task inventory differs')
        for task in tasks:
            descriptor = task['descriptor']; address = descriptor['regcmd_addr']; amount = descriptor['regcfg_amount']
            fixed = dict(flags=0, op_idx=4, enable_mask=0x18, int_mask=0x300,
                         int_clear=0x1ffff, int_status=0, regcfg_offset=0)
            require(set(descriptor) == set(fixed) | {'regcmd_addr', 'regcfg_amount'} and
                    all(type(descriptor[name]) is int and descriptor[name] == value
                        for name, value in fixed.items()), 'Unmodeled captured task descriptor field')
            require(type(address) is type(amount) is int and address % 16 == 0 and 4 <= amount <= 65539,
                    'Invalid captured descriptor')
            spans = [data[address-base:address-base+8*amount] for base, data in regions.items()
                     if base <= address and address+8*amount <= base+len(data)]
            require(len(spans) == 1 and sha(spans[0]) == task['sha256'], 'Final command QWORDs changed')
        first = tasks[0]['descriptor']
        cases.append(dict(name='capture_'+case['name'], address=first['regcmd_addr'],
                          amount=first['regcfg_amount'], tasks=len(tasks), regions=regions, production=case))
    return cases


def lines(regions):
    return ''.join(f'{base+offset:08x} {int.from_bytes(data[offset:offset+64], "little"):0128x}\n'
                   for base, data in sorted(regions.items()) for offset in range(0, len(data), 64))


def vector_contents():
    files, specs = {}, []
    for case in captured_cases():
        memory = Memory()
        for base, data in case['regions'].items():
            memory.map(base, data)
        engine = DMAEmulator(memory, max_tasks=4)
        engine.submit_dma(case['address'], case['amount'])
        source = case['production']
        buf, offset = memory.locate(source['expected_address'], source['logical_count']*2)
        require(bytes(buf[offset:offset+source['logical_count']*2]).hex() == source['expected_logical_hex'],
                'Independent numerical oracle differs from captured expected result')
        require(engine.completed == case['tasks'] and engine.jobs == 1 and
                engine.command_reads == 4*sum(t['descriptor']['regcfg_amount'] for t in source['tasks']) and
                engine.memory_transactions == 3*((source['logical_count']+7)//8*8)*case['tasks'],
                'Raw replay task/shape contract differs')
        upload = lines(case['regions']); expected = lines(memory.regions)
        files[case['name']+'/upload.txt'] = upload
        files[case['name']+'/expected.txt'] = expected
        count = sum(len(data)//64 for data in case['regions'].values())
        require(len(upload.splitlines()) == len(expected.splitlines()) == count, 'BO line inventory differs')
        specs.append(dict(name=case['name'], case=case['name'], address=case['address'], amount=case['amount'],
                          tasks=case['tasks'], lines=count, jobs=1, negative=0, reset_recovery=0))
        if case['name'] == 'capture_sub_9':
            engine.submit_dma(case['address'], case['amount'])
            require(lines(memory.regions) == expected, 'Repeated raw SUB9 changed the complete expected BOs')
    sub = next(c for c in specs if c['name'] == 'capture_sub_9')
    specs.append(dict(sub, name='repeat_sub_9', jobs=2))
    for mode, name in [(1, 'unknown_command'), (2, 'rmw_ue'), (3, 'dropped_return'),
                       (4, 'phy_write_stall'), (5, 'calibration_loss'), (6, 'queued_fault_after_success'),
                       (7, 'ecc_control_timeout'), (8, 'late_pending_result_fault'),
                       (9, 'host_memory_timeout')]:
        specs.append(dict(sub, name=name, negative=mode, jobs=2 if mode == 6 else 1))
    specs.append(dict(sub, name='joint_reset_recovery', negative=2, reset_recovery=1))
    return files, specs


def generate(directory):
    files, specs = vector_contents()
    directory = Path(directory)
    require(not directory.exists(), 'Use a fresh vector directory')
    for name, text in files.items():
        path = directory/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return specs


def verify_vectors(directory):
    files, specs = vector_contents()
    directory = Path(directory)
    found = {str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()}
    require(found == set(files), 'Missing or extra vector file')
    for name, expected in files.items():
        path = directory/name
        require(not path.is_symlink() and path.read_text() == expected and
                all(re.fullmatch(r'[0-9a-f]{8} [0-9a-f]{128}', row) for row in expected.splitlines()),
                'BO stimulus/oracle bytes changed: '+name)
    return specs
