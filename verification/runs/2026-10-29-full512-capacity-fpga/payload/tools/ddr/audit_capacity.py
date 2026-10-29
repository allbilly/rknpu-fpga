"""Read-only audit of the RKMT capacity session's actual USER2 scans.

This proves the exact management protocol and terminal device witnesses.
The caller must separately qualify the BIST RTL, image/load/target and lease;
the management trace does not contain every internally compared DDR byte.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.tinystories.audit_scans import commands


def require(ok, message):
    if not ok:
        raise ValueError(message)


def replay(wire, seed=0x3588c350):
    """Consume a complete, dedicated, full-window management session."""
    require(type(seed) is int and 0 <= seed < 1 << 32, 'Seed must be uint32')
    stream = iter(wire)
    command_count = 0

    def take(op, address, *, data=0, response=None):
        nonlocal command_count
        try:
            row = next(stream)
        except StopIteration:
            raise ValueError('Truncated capacity protocol') from None
        require(isinstance(row, dict) and
                all(type(row.get(k)) is int and row[k] >= 0
                    for k in ('op', 'address', 'data', 'response')),
                'Malformed decoded capacity command')
        require((row['op'], row['address'], row['data']) == (op, address, data),
                'Unexpected capacity command/order/payload')
        require(row['response'] < 1 << 32 and
                (response is None or row['response'] == response),
                'Wrong capacity response')
        command_count += 1
        return row['response']

    # A fresh DualDdrRawTransport validates both original namespaces first.
    for address, value in ((0, 0x524b4144), (4, 0x10000),
                           (0x100, 0x524b4344), (0x104, 0x10000)):
        take(1, address, response=value)
    while True:
        status = take(1, 8)
        require(status in (0, 0x10), 'Faulted or owned memory at admission')
        if status == 0x10:
            break
    for address, value in ((0x200, 0x524b4d54), (0x204, 0x10000),
                           (0x214, 1 << 31), (0x218, 0),
                           (0x21c, 0x00020040), (8, 0x10), (0x108, 0x10),
                           (0x208, 1)):
        take(1, address, response=value)
    take(2, 0x210, data=seed, response=0)
    take(1, 0x210, response=seed)
    take(2, 0x20c, data=1, response=0)

    previous = (0, 0)
    snapshots = 0
    expected = 1 << 26  # Two trials of 2 GiB / 64 bytes in each direction.
    while True:
        status = take(1, 0x208)
        counts = (take(1, 0x220), take(1, 0x224))
        take(1, 0x228, response=0)
        take(1, 0x22c, response=0)
        require(not status & ~0x7f and status & 0x40 and not status & 0x10,
                'Faulted, unknown or lost diagnostic ownership')
        require(all(old <= now <= expected for old, now in zip(previous, counts)),
                'Regressing or out-of-window capacity counters')
        previous = counts
        snapshots += 1
        if status & 8:
            require(status == 0x68 and counts == (expected, expected),
                    'Completion without exact full-span counts/ownership')
            break
    take(1, 0x208, response=0x68)
    sentinel = object()
    require(next(stream, sentinel) is sentinel, 'Extra command after terminal health witness')
    return dict(base=0, size=1 << 31, seed=seed, trials=2,
                lines_per_trial=1 << 25, completed_writes=previous[0],
                completed_reads=previous[1], device_status=0x68,
                snapshots=snapshots, decoded_commands=command_count,
                memory_payloads_observed_on_jtag=False,
                four_retirement_witnesses_require_source_bound_bist=True)


def audit(trace, seed=0x3588c350):
    trace = Path(trace)
    def digest():
        with trace.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    before = digest()
    stats = {}
    result = replay(commands(trace, stats), seed)
    after = digest()
    require(before == after, 'Actual scan trace changed during audit')
    require(stats['commands'] == result['decoded_commands'], 'Incomplete decoded trace')
    return dict(status='PASS_INDEPENDENT_FULL_WINDOW_RKMT_WIRE_WITNESSES_ONLY',
                trace_sha256=before, scan_statistics=stats, **result,
                physical_capacity_qualified=False, hardware_accessed=False,
                scope='Management witnesses only; exact image/BIST/target/load and recovery review required')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--seed', type=lambda x: int(x, 0), default=0x3588c350)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    require(not args.out.exists(), 'Fresh audit output path required')
    result = audit(args.trace, args.seed)
    with args.out.open('x') as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
