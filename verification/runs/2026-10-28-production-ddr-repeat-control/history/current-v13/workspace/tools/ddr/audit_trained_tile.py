#!/usr/bin/env python3
"""Read-only DDR trained-tile wire audit; image/target admission is separate.

Consumes successful decoded USER2 commands and compares original static BOs.
No transport, arithmetic oracle, programming API or execution fallback is used.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr.interface import require
from tools.tinystories.audit_scans import commands

IDENTITIES = {0: 0x524B4144, 256: 0x524B4344}
PHASES = (('cmac', 'cmac', 45, 1), ('ew', 'ew', 22, 2),
          ('cmac', 'repeat', 45, 1), ('ew', 'ew', 22, 2))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def lines(path):
    result = {}
    previous = -1
    for row in Path(path).read_text().splitlines():
        require(re.fullmatch(r'[0-9a-fA-F]{8} [0-9a-fA-F]{128}', row),
                'Malformed original DDR BO line')
        address, value = (int(word, 16) for word in row.split())
        require(address % 64 == 0 and previous < address < 0x10100000 and
                address >= 0x10000000, 'Unordered/unmapped original DDR BO')
        result[address] = value
        previous = address
    require(result, 'Empty original DDR BO')
    return result


def replay(wire, initial, expected, deltas):
    """Audit four fixed jobs; callers separately bind the original vectors."""
    require(set(expected) == {'cmac', 'ew', 'repeat'} and
            set(deltas) == {'ew', 'repeat'}, 'Incomplete trained phases')
    addresses = set(initial)
    require(addresses and all(set(image) == addresses for image in expected.values()) and
            all(set(delta) <= addresses for delta in deltas.values()),
            'Changed trained BO extents')
    memory = {}
    unverified = set()
    identities = set()
    idle = set()
    staged = {}
    active = None
    released = None
    finished = 0
    checked = 0
    writes = 0
    before = dict(initial)
    for command in wire:
        op, address, value, response = (command[k] for k in ('op', 'address', 'data', 'response'))
        if op in (2, 4):
            require(response == 0, 'Failed trained write command')
        if op in (3, 4):
            require(finished < len(PHASES) and address in addresses,
                    'Trained memory access escaped original BOs/workload')
            if op == 4:
                require(active is None and not staged and released is None and
                        identities == {0, 4, 256, 260} and idle == {0, 256},
                        'DDR upload before identities/readiness or during ownership')
                require(value == before[address], 'Upload differs from original trained BO/delta')
                memory[address] = value
                unverified.add(address)
                writes += 1
            elif active is None:
                require(not staged and memory.get(address) == response,
                        'Uploaded trained line was not verified')
                unverified.discard(address)
            else:
                require(active['complete'] and address not in active['reads'],
                        'Output read before completion or repeated line')
                require(response == expected[active['golden']][address],
                        'Actual trained output/guard differs from static expectation')
                active['reads'][address] = response
            continue
        require(op in (1, 2) and 0 <= address < 0x200, 'Unmodeled trained opcode/CSR')
        base = 256 if address >= 256 else 0
        offset = address - base
        if op == 1:
            require(offset in (0, 4, 8, 28, 32, 36), 'Unmodeled trained CSR read')
            if offset in (0, 4):
                require(active is None and not staged and
                        response == (IDENTITIES[base] if offset == 0 else 0x10000),
                        'Wrong DDR identity/ABI or identity read during ownership')
                if offset == 4:
                    require(base in identities, 'DDR ABI observed before identity')
                identities.add(address)
            elif offset == 8:
                require(not response & ~0x77F and not response & (8 | 32),
                        'Faulted or unmodeled DDR status')
                if active is None and not staged:
                    require(response == 0x10, 'DDR idle/ACK did not restore memory readiness')
                    idle.add(base)
                    if released is not None:
                        require(released == base, 'ACK health checked in wrong namespace')
                        released = None
                elif active is not None:
                    require(active['base'] == base, 'Peer status read during owned job')
                    if response & 4:
                        require(not response & (2 | 64), 'Invalid DDR completion status')
                        active['complete'] = True
            else:
                require(active is not None and active['base'] == base and active['complete'],
                        'Completion registers observed outside successful owner')
                required = {28: active['tag'], 32: active['tasks'], 36: 0}[offset]
                require(response == required, 'Wrong DDR completion tag/tasks/code')
                active['regs'].add(offset)
            continue
        require(offset in (12, 16, 20, 24), 'Unmodeled trained CSR write')
        if offset != 12:
            require(active is None and released is None and finished < len(PHASES) and
                    (not staged or staged['base'] == base) and offset not in staged,
                    'Descriptor namespace/ownership overlap')
            staged['base'] = base
            staged[offset] = value
        elif value == 1:
            require(active is None and released is None and not unverified and
                    set(staged) == {'base', 16, 20, 24} and staged['base'] == base and
                    finished < len(PHASES), 'Incomplete or overlapping trained submit')
            profile, golden, amount, tasks = PHASES[finished]
            tag = 0x26000001 + finished
            require((base, staged[16], staged[20], staged[24]) ==
                    (256 if profile == 'cmac' else 0, 0x100E0000, amount, tag),
                    'Changed original trained descriptor')
            require(memory == before, 'Incomplete or altered original trained command/operand BO')
            active = dict(base=base, tag=tag, tasks=tasks, golden=golden,
                          reads={}, regs=set(), complete=False)
            staged = {}
        elif value == 2:
            require(active is not None and active['base'] == base and active['complete'] and
                    active['regs'] == {28, 32, 36} and set(active['reads']) == addresses,
                    'ACK before successful completion and complete trained BO readback')
            memory = dict(active['reads'])
            checked += 64 * len(addresses)
            finished += 1
            before = dict(memory)
            if finished < len(PHASES):
                before.update(deltas['repeat' if finished == 2 else 'ew'])
            active = None
            released = base
        else:
            raise ValueError('Unmodeled trained doorbell')
    require(finished == 4 and active is None and not staged and not unverified and released is None,
            'Incomplete trained command/ACK history')
    return dict(raw_jobs=finished, tasks=6, complete_bo_bytes=checked,
                upload_line_commands=writes, complete_readback_before_each_ack=True)


def audit(worker, vectors, expected_vectors_sha256):
    worker, vectors = Path(worker).resolve(), Path(vectors).resolve()
    require(re.fullmatch(r'[0-9a-f]{64}', expected_vectors_sha256) and
            sha(vectors / 'report.json') == expected_vectors_sha256,
            'Original vector report differs from externally reviewed digest')
    child = json.loads((worker / 'report.json').read_text())
    source = json.loads((vectors / 'report.json').read_text())
    require(child['status'] == 'PASS_PHYSICAL_TRAINED_TILE_COMPACTION_AND_REARM_REQUIRES_AUDIT' and
            child['memory_profile'] == 'ddr' and child['hardware_accessed'] is True and
            child['flash_written'] is False and child['cpu_dense_fallback'] is False,
            'Completed explicit DDR worker required')
    require(child['vectors_report_sha256'] == sha(vectors / 'report.json') and
            source['status'] == 'STATIC_TRAINED_TILE_JOINED_TEST_VECTORS' and
            (source['lines'], source['cmac_amount'], source['ew_amount']) == (1408, 45, 22),
            'Wrong or changed original trained vector contract')
    require({'initial.txt', 'cmac_expected.txt', 'ew_expected.txt', 'repeat_expected.txt',
             'ew_delta.txt', 'repeat_delta.txt'} <= set(source['files']),
            'Missing original trained vector file hashes')
    for name, digest in source['files'].items():
        require(Path(name).name == name and sha(vectors / name) == digest,
                'Changed original trained vector file')
    require({'native-scans.jsonl'} | {'job' + str(i) + '-readback.bin' for i in range(4)}
            <= set(child['artifacts']), 'Missing actual scan/capture artifact hashes')
    for name, digest in child['artifacts'].items():
        path = (worker / name).resolve()
        require(path.is_relative_to(worker) and sha(path) == digest, 'Changed DDR worker artifact')
    initial = lines(vectors / 'initial.txt')
    expected = {name: lines(vectors / (name + '_expected.txt')) for name in ('cmac', 'ew', 'repeat')}
    deltas = {name: lines(vectors / (name + '_delta.txt')) for name in ('ew', 'repeat')}
    require(len(initial) == 1408 and len(deltas['ew']) == 9 and len(deltas['repeat']) == 11,
            'Changed trained vector inventory')
    stats = {}
    result = replay(commands(worker / 'native-scans.jsonl', stats), initial, expected, deltas)
    require(len(child['jobs']) == 4, 'Missing trained worker jobs')
    for index, (profile, golden, amount, tasks) in enumerate(PHASES):
        job = child['jobs'][index]
        raw = b''.join(value.to_bytes(64, 'little') for _, value in sorted(expected[golden].items()))
        require(job['status'] == 'PASS' and job['profile'] == profile and job['tag'] == 0x26000001 + index and
                job['bytes_checked'] == len(raw) and job['ack_after_complete_readback'] is True and
                (worker / ('job' + str(index) + '-readback.bin')).read_bytes() == raw,
                'Worker capture disagrees with static expected BO')
    return dict(status='PASS_INDEPENDENT_DDR_TRAINED_TILE_RAW_WIRE_AUDIT_ONLY',
                scope='Actual USER2 commands/complete trained BO bytes only; exact image, target, route and physical DDR admission require separate reviewed receipts',
                utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                worker_report_sha256=sha(worker / 'report.json'),
                vector_report_sha256=sha(vectors / 'report.json'),
                native_scan_sha256=sha(worker / 'native-scans.jsonl'), wire=stats,
                image_target_route_qualified_by_this_audit=False, **result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    parser.add_argument('--vectors', type=Path, required=True)
    parser.add_argument('--vectors-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), 'Fresh trained audit output required')
    result = audit(args.worker, args.vectors, args.vectors_sha256)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'], args.out)


if __name__ == '__main__':
    main()
