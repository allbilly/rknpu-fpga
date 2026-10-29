"""Independent fixed scratch replay for an admitted dual-DDR USER2 image.

This reads a saved scan trace only. It does not admit an image, access hardware,
or establish full capacity, injected ECC behavior, recovery or numerical work.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import sys

ROOT = Path('/home/fedora/rknpu-fpga')
sys.path.insert(0, str(ROOT))
from tools.tinystories.audit_scans import commands

ADDRESSES = (0x40, 0x1000, 0x1800, 0x200040, 0x1000040, 0x7fffffc0)
IDENTITIES = {0: 0x524b4144, 0x100: 0x524b4344}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def expected_memory():
    result = []
    for trial in range(2):
        values = {
            address: int.from_bytes(bytes((byte * 37 + index * 19 + trial * 83) % 256
                for byte in range(64)), 'little')
            for index, address in enumerate(ADDRESSES)
        }
        order = ADDRESSES if trial == 0 else tuple(reversed(ADDRESSES))
        result.extend((4, address, values[address]) for address in order)
        result.extend((3, address, values[address]) for address in ADDRESSES)
    return result


def replay(wire):
    """Consume every decoded command and require both final idle witnesses."""
    expected = expected_memory()
    identities = set()
    abis = set()
    ready = set()
    last_status_at = {}
    checked = 0
    count = 0
    for command in wire:
        count += 1
        op, address, data, response = (command[k] for k in ('op', 'address', 'data', 'response'))
        require(all(type(x) is int and x >= 0 for x in (op, address, data, response)),
                'Malformed decoded command')
        if op == 1:
            require(data == 0 and address in (0, 4, 8, 0x100, 0x104, 0x108),
                    'Unmodeled scratch CSR read')
            base = address & ~0xff
            offset = address - base
            if offset == 0:
                require(response == IDENTITIES[base], 'Wrong DDR namespace identity')
                identities.add(base)
            elif offset == 4:
                require(base in identities and response == 0x10000, 'Wrong DDR namespace ABI')
                abis.add(base)
            else:
                require(base in abis, 'Status precedes namespace identity/ABI')
                require(response in (0, 16), 'Busy, faulted or unknown scratch status')
                require(response == 16 or (checked == 0 and base not in ready),
                        'Initialized DDR lost readiness')
                if response == 16:
                    ready.add(base)
                    last_status_at[base] = checked
            continue
        require(op in (3, 4), 'Scratch contains a CSR write or unknown operation')
        require(identities == abis == ready == {0, 0x100},
                'Scratch memory precedes both initialized namespace admissions')
        require(checked < len(expected), 'Extra scratch memory operation')
        require((op != 3 or data == 0) and (op != 4 or response == 0),
                'Malformed scratch memory payload/response')
        wanted_op, wanted_address, wanted = expected[checked]
        actual = data if op == 4 else response
        require((op, address, actual) == (wanted_op, wanted_address, wanted),
                'Scratch order, address or complete line bytes differ')
        checked += 1
    require(checked == 24 and all(last_status_at.get(base) == checked for base in IDENTITIES),
            'Incomplete scratch or missing both post-read healthy status witnesses')
    return dict(status='PASS_FIXED_DUAL_DDR_SCRATCH_WIRE_REPLAY_ONLY',
        decoded_commands=count, memory_commands=checked, write_commands=12,
        read_commands=12, checked_bytes=768, addresses=list(ADDRESSES),
        both_namespaces_initialized_before_memory=True,
        both_namespaces_healthy_after_memory=True,
        full_capacity_qualified=False, ecc_injection_qualified=False,
        recovery_qualified=False, numerical_execution_qualified=False,
        image_target_route_qualified=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), 'Fresh scratch audit receipt required')
    before = sha(args.trace)
    stats = {}
    result = replay(commands(args.trace, stats))
    require(sha(args.trace) == before, 'Scratch trace changed during audit')
    result.update(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  native_scan_sha256=before, wire=stats)
    with args.out.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(result['status'])


if __name__ == '__main__':
    main()
