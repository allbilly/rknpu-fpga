#!/usr/bin/env python3
"""Check a trained raw tile on an already audited, exclusively owned bridge.

Static test expectations never provide a hardware result. There is no model
arithmetic, layout repair, programming, fabric reset or retry in this worker.
"""
from pathlib import Path
import argparse
import dataclasses
import datetime
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.tinystories.native_trace import RecordedNativeLink
from tools.tinystories.prepare import require
from tools.tinystories.transport import DualRawTransport


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lines(path):
    result = {}
    for row in Path(path).read_text().splitlines():
        address, value = row.split()
        address = int(address, 16)
        require(address % 64 == 0 and address not in result and len(value) == 128,
                'Invalid static BO line')
        require(0x10000000 <= address < 0x10100000, 'Static BO outside shared RAM')
        result[address] = int(value, 16).to_bytes(64, 'little')
    require(bool(result), 'Missing static BO lines')
    return result


def regions(values):
    result = []
    for address, data in sorted(values.items()):
        if result and address == result[-1][0]+len(result[-1][1]):
            result[-1][1].extend(data)
        else:
            result.append((address, bytearray(data)))
    return [(a, bytes(d)) for a, d in result]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vectors', type=Path, required=True)
    parser.add_argument('--vectors-sha256', required=True)
    parser.add_argument('--port', type=int, default=3741)
    parser.add_argument('--quit-bridge', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    vector = args.vectors.resolve()
    require(sha(vector/'report.json') == args.vectors_sha256, 'Audited vector report changed')
    source = json.loads((vector/'report.json').read_text())
    require(source['status'] == 'STATIC_TRAINED_TILE_JOINED_TEST_VECTORS' and
            (source['lines'], source['cmac_amount'], source['ew_amount']) == (1408, 45, 22),
            'Wrong trained raw tile contract')
    for name, digest in source['files'].items():
        require(Path(name).name == name and sha(vector/name) == digest, 'Static expectation changed')
    initial = lines(vector/'initial.txt')
    expected = {name: regions(lines(vector/(name+'_expected.txt'))) for name in ('cmac', 'ew', 'repeat')}
    ew_delta, repeat_delta = lines(vector/'ew_delta.txt'), lines(vector/'repeat_delta.txt')
    require(len(initial) == 1408 and len(ew_delta) == 9 and len(repeat_delta) == 11,
            'Static owned BO inventory changed')
    for value in expected.values():
        require([(a, len(d)) for a, d in value] == [(a, len(d)) for a, d in regions(initial)],
                'Expectation changes owned BO extents')
    out = args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh local run directory required')
    out.mkdir(parents=True)
    record = dict(status='RUNNING', vectors_report_sha256=args.vectors_sha256,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), jobs=[],
                  hardware_access_attempted=False, hardware_accessed=False, flash_written=False,
                  cpu_dense_fallback=False, scope='BOS Wq0 first32 outputs, two raw CMAC jobs and two linked EW compactions; not full model')
    def save():
        (out/'report.json').write_text(json.dumps(record, indent=2)+'\n')
    save()
    link = transport = None
    try:
        record['hardware_access_attempted'] = True
        save()
        with (out/'native-scans.jsonl').open('x') as wire:
            try:
                link = RecordedNativeLink(wire, '127.0.0.1', args.port)
                record['hardware_accessed'] = True
                transport = DualRawTransport(link.host, link.port, link=link)
                record['identities'] = {}
                for profile in ('ew', 'cmac'):
                    transport.select_profile(profile)
                    record['identities'][profile] = dict(id=transport.reg_read(0), abi=transport.reg_read(4), status=transport.reg_read(8))
                    require(record['identities'][profile]['status'] == 0x10, 'Fresh idle endpoint required')
                for address, data in regions(initial):
                    transport.mem_write(address, data)
                    require(transport.mem_read(address, len(data)) == data, 'Initial complete BO readback mismatch')
                record['initial_bytes_uploaded_and_verified'] = sum(len(d) for _, d in regions(initial))
                save()
                for index, (profile, golden, delta) in enumerate((
                    ('cmac', 'cmac', {}), ('ew', 'ew', ew_delta),
                    ('cmac', 'repeat', repeat_delta), ('ew', 'ew', ew_delta))):
                    transport.select_profile(profile)
                    for address, data in regions(delta):
                        transport.mem_write(address, data)
                        require(transport.mem_read(address, len(data)) == data, 'Complete BO byte delta mismatch')
                    tag = 0x26000001+index
                    job = dict(profile=profile, tag=tag, expected=golden, status='RUNNING', regions=[])
                    record['jobs'].append(job)
                    save()
                    transport.submit(0x100e0000, 45 if profile == 'cmac' else 22, tag)
                    completion = transport.poll_result(timeout=30)
                    job['completion'] = dataclasses.asdict(completion)
                    require(completion.tag == tag and completion.completed_tasks == (1 if profile == 'cmac' else 2)
                            and completion.error_code == 0, 'Unexpected raw completion')
                    actual_bytes = bytearray()
                    for address, data in expected[golden]:
                        actual = transport.mem_read(address, len(data))
                        actual_bytes.extend(actual)
                        job['regions'].append(dict(address=address, bytes=len(actual), matches=actual == data,
                            sha256=hashlib.sha256(actual).hexdigest(), expected_sha256=hashlib.sha256(data).hexdigest()))
                        # Preserve actual bytes before reporting a mismatch.
                        (out/('job'+str(index)+'-readback.bin')).write_bytes(actual_bytes)
                        save()
                        require(actual == data, 'Whole BO numerical/guard mismatch at '+hex(address))
                    transport.ack_success()
                    job.update(status='PASS', bytes_checked=len(actual_bytes), ack_after_complete_readback=True)
                    save()
                    print('PASS_TRAINED_RAW_JOB', index, profile, len(actual_bytes), flush=True)
                require(len(record['jobs']) == 4, 'Incomplete repeated job lifecycle')
                record['status'] = 'PASS_PHYSICAL_TRAINED_TILE_COMPACTION_AND_REARM_REQUIRES_AUDIT'
            finally:
                if link is not None and args.quit_bridge:
                    link.shutdown_bridge()
                    record['bridge_quit_ack'] = True
                if transport is not None:
                    transport.close()
                elif link is not None:
                    link.close()
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()
    print(record['status'], out/'report.json', flush=True)


if __name__ == '__main__':
    main()
