#!/usr/bin/env python3
"""Offline ew-int aperture audit for Image B page-form integration (task-23).

Reads the frozen ew-int capture bundles (15 READY, 3 BLOCKED) under
``build/rk3588-example-captures/ew-int/`` and answers the questions the Image B
integration needs before the sparse aperture is pinned:

* which command-QWORD fields carry a device memory address, and whether every
  one of them is host-patched at staging time (no captured absolute address is
  ever executed unpatched — including the layout-mode surface/stride registers,
  which are geometry, not pointers);
* the staged buffer/command footprint of every READY case under the page-form
  staging plan (A/B/D data banks + command bank inside a 16 KiB sparse
  aperture);
* the union span, per-case region count, maximum sizes and holes of the
  sparse map, versus the 1 MiB decoded aperture;
* that the BLOCKED cases stay excluded (no oracle, no staging requirement).

It reads only frozen files and RTL sources; it never writes under the capture
tree, never runs Vivado and never touches hardware. ``--json`` prints a machine
summary used by the contract tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from model.int_profile import (KNOWN_KEYS, OPERATION_ENABLE,  # noqa: E402
                               decode_regcmd, patch_value32)
from model.profile import decode  # noqa: E402

CAPTURES = ROOT / 'build/rk3588-example-captures/ew-int'
TOOL = 'tools/merged/ew_int_aperture_audit.py'

# Image B page-form staging plan (docs/EW_INT_APERTURE_AUDIT.md §2). Absolute
# device addresses: the decoded ew-int aperture is 0x1100_0000 + 1 MiB;
# physical banks are four 4 KiB entries at fixed offsets. The command BO lives
# in the fourth bank so the page needs exactly one memory master.
APERTURE_BASE = 0x1100_0000
APERTURE_BYTES = 1 << 20
INT_BANKS = {
    'A': (0x1100_1000, 4096, 'operand a (RDMA.SRC_BASE_ADDR)'),
    'B': (0x1100_2000, 4096, 'operand b (RDMA.EW_BASE_ADDR)'),
    'D': (0x1100_3000, 4096, 'output (DPU.DST_BASE_ADDR)'),
    'command': (0x1100_4000, 4096, 'raw command BO (page START_ADDRESS)'),
}
STAGING = {'a': 'A', 'b': 'B', 'out': 'D', 'command': 'command'}

# Address-bearing register fields of the three captured integer stream shapes.
# Evidence: docs/EW_INT.md §2 register map; every other captured register is a
# mode/geometry/value field (model/int_profile.KNOWN_KEYS covers the whole set).
ADDRESS_FIELDS = {
    (0x1001, 0x4020): 'dpu_dst',
    (0x2001, 0x5018): 'rdma_src_a',
    (0x2001, 0x5038): 'rdma_src_b',
    (0x0101, 0x0010): 'pc_next_address',
    (0x0101, 0x0014): 'pc_next_amount',
}
FIELD_PLACEHOLDER = {
    'dpu_dst': 0x20000000,
    'rdma_src_a': 0x10000000,
    'rdma_src_b': 0x10010000,
}
FIELD_BUFFER = {'dpu_dst': 'out', 'rdma_src_a': 'a', 'rdma_src_b': 'b'}
EXPECTED_COMMAND_QWORDS = {'simple': 18, 'layout': 44, 'regroup': 31}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_words(raw: bytes) -> list[tuple[int, int, int]]:
    words = [int.from_bytes(raw[i:i + 8], 'little') for i in range(0, len(raw), 8)]
    return [decode(word) for word in words]


def aperture_bank(address: int) -> str | None:
    for name, (base, size, _role) in INT_BANKS.items():
        if base <= address < base + size:
            return name
    return None


def audit_case(manifest_entry: dict) -> dict:
    bundle = CAPTURES / manifest_entry['bundle_dir']
    job = json.loads((bundle / 'job.json').read_text())
    regcmd = (bundle / 'regcmd.bin').read_bytes()
    fields = decode_words(regcmd)
    patches = {int(p['regcmd_index']): p for p in job.get('patches', [])}
    padding = int(job.get('regcmd_padding_words', 0))
    command_words = int(job['tasks'][0]['regcmd_words'])
    problems: list[str] = []
    if len(regcmd) != 8 * (command_words + padding):
        problems.append('regcmd.bin length does not match job regcmd_words')
    if (len(regcmd) % 8) or len(fields) != len(regcmd) // 8:
        problems.append('regcmd.bin is not an integral number of QWORDs')

    # Every decoded register key must be part of the reviewed integer map; the
    # only address-bearing keys are the three patched pointers plus the zero
    # single-task PC tail.
    unknown_keys = []
    for index, (target, offset, _value) in enumerate(fields):
        key = (target, offset)
        if key not in KNOWN_KEYS and key != OPERATION_ENABLE:
            unknown_keys.append(f'Q{index} {key} not in the reviewed integer map')
    problems += unknown_keys

    address_fields = []
    for index, (target, offset, value) in enumerate(fields):
        name = ADDRESS_FIELDS.get((target, offset))
        if name is None:
            continue
        patched = index in patches
        address_fields.append(dict(index=index, field=name, value=value,
                                   patched=patched,
                                   patch_buffer=patches[index]['buffer'] if patched else None))
        if name in ('pc_next_address', 'pc_next_amount'):
            # Single-task integer streams: the terminal PC chain must be zero
            # and must never be a patch target.
            if value != 0:
                problems.append(f'Q{index} {name} nonzero ({value:#x}); chained PC '
                                'tasks are not evidenced for ew-int')
            if patched:
                problems.append(f'Q{index} {name} must not be host-patched')
            continue
        if not patched:
            problems.append(f'Q{index} {name} is an address field but is not host-patched')
            continue
        if patches[index].get('kind') != 'value32':
            problems.append(f'Q{index} {name} patch kind is not value32')
        if patches[index].get('buffer') != FIELD_BUFFER[name]:
            problems.append(f'Q{index} {name} patch buffer '
                            f'{patches[index].get("buffer")} != {FIELD_BUFFER[name]}')
        if value != FIELD_PLACEHOLDER[name]:
            problems.append(f'Q{index} {name} value {value:#010x} is not the captured '
                            f'placeholder {FIELD_PLACEHOLDER[name]:#010x}')

    # Every patch must target one of the three data-pointer fields.
    for index, patch in patches.items():
        if index >= len(fields):
            problems.append(f'patch index {index} outside the command BO')
            continue
        target, offset, _ = fields[index]
        name = ADDRESS_FIELDS.get((target, offset))
        if name not in FIELD_BUFFER:
            problems.append(f'patch Q{index} targets {name or (target, offset)}, '
                            'not a data-pointer field')
        if patch.get('kind') != 'value32':
            problems.append(f'patch Q{index} kind is not value32')
        if patch.get('buffer') not in STAGING:
            problems.append(f'patch Q{index} buffer {patch.get("buffer")} has no bank')

    # Decode the captured stream with the integer decoder to get the stage
    # geometry and confirm the mode/counted shape. The three addresses must be
    # patched (to the page-form aperture bases) for the decoder contract.
    staged = patch_value32(regcmd, 0x1001, 0x4020, INT_BANKS['D'][0] + 0)
    staged = patch_value32(staged, 0x2001, 0x5018, INT_BANKS['A'][0] + 0)
    staged = patch_value32(staged, 0x2001, 0x5038, INT_BANKS['B'][0] + 0)
    try:
        configs = decode_regcmd(staged)
    except Exception as error:  # noqa: BLE001 - fail closed with the message
        problems.append(f'integer decoder rejects the staged stream: {error}')
        configs = []
    config = configs[0] if configs else None
    if config is not None:
        if command_words != EXPECTED_COMMAND_QWORDS[config.mode]:
            problems.append(f'{config.mode} stream has {command_words} QWORDs; '
                            f'captured shape is {EXPECTED_COMMAND_QWORDS[config.mode]}')

    # Staged regions: three 4096-byte BOs + the raw command BO in the fourth
    # bank. Buffer sizes come from job.json and must fit their bank exactly.
    buffers = []
    for buffer in job.get('buffers', []):
        bank = STAGING.get(buffer['name'])
        if bank is None:
            problems.append(f'buffer {buffer["name"]} has no planned aperture bank')
            continue
        base, size, _role = INT_BANKS[bank]
        if int(buffer['size']) > size:
            problems.append(f'buffer {buffer["name"]} size {buffer["size"]} > bank '
                            f'{bank} ({size})')
        buffers.append(dict(name=buffer['name'], size=int(buffer['size']),
                            direction=buffer['direction'], bank=bank, address=base,
                            bytes_required=int(buffer['size'])))
    command_base, command_bank_size, _role = INT_BANKS['command']
    if len(regcmd) > command_bank_size:
        problems.append(f'command BO {len(regcmd)} B > command bank {command_bank_size}')
    if not any(buffer['name'] == 'out' and buffer['direction'] == 'out'
               for buffer in buffers):
        problems.append('no output buffer in the bundle')
    regions = buffers + [dict(name='command', size=len(regcmd), direction='in',
                              bank='command', address=command_base,
                              bytes_required=len(regcmd))]

    # Union span of the required bytes, and the holes of the sparse map.
    required_span = [min(region['address'] for region in regions),
                     max(region['address'] + region['bytes_required']
                         for region in regions)]
    for region in regions:
        if aperture_bank(region['address']) != region['bank']:
            problems.append(f'{region["name"]} address does not decode to bank '
                            f'{region["bank"]}')
        if (region['address'] & 15) != 0:
            problems.append(f'{region["name"]} base not 16-byte aligned')
    # a/b/out must not overlap each other or the command bank (they sit in
    # disjoint banks by construction; check the absolute ranges anyway).
    ordered = sorted(regions, key=lambda region: region['address'])
    for left, right in zip(ordered, ordered[1:]):
        if left['address'] + left['bytes_required'] > right['address']:
            problems.append(f'{left["name"]} and {right["name"]} overlap')

    return dict(
        case=manifest_entry['case'],
        dtype=manifest_entry['dtype'],
        operation=manifest_entry['operation'],
        mode=config.mode if config else None,
        count=config.count if config else None,
        in_bytes=config.in_bytes if config else None,
        out_bytes=config.out_bytes if config else None,
        command_words=command_words,
        command_bytes=len(regcmd),
        padding_words=padding,
        buffers=[dict(name=b['name'], size=b['size'], direction=b['direction'])
                 for b in buffers],
        patches=[dict(index=index, buffer=patch['buffer'], kind=patch['kind'])
                 for index, patch in sorted(patches.items())],
        address_fields=address_fields,
        regions=[dict(name=r['name'], bank=r['bank'], address=r['address'],
                      size=r['size'], bytes_required=r['bytes_required'])
                 for r in regions],
        region_count=len(regions),
        required_span=required_span,
        problems=problems,
    )


def run() -> dict:
    manifest = json.loads((CAPTURES / 'manifest.json').read_text())
    ready = [entry for entry in manifest['cases'] if entry.get('status') == 'READY']
    blocked = [entry for entry in manifest['cases'] if entry.get('status') != 'READY']
    results = [audit_case(entry) for entry in ready]
    problems = [f'{result["case"]}: {problem}'
                for result in results for problem in result['problems']]

    # The 16 KiB sparse plan versus a dense 1 MiB decode.
    bank_total = sum(size for _base, size, _role in INT_BANKS.values())
    dense_tiles = APERTURE_BYTES // 4096
    sparse_tiles = bank_total // 4096
    bank_table = [dict(name=name, address=base, bytes=size, role=role,
                       bram36_tiles=size // 4096)
                  for name, (base, size, role) in INT_BANKS.items()]

    # The blocked cases need no aperture: no oracle and no staged expectation.
    blocked_audit = [dict(case=entry['case'], status=entry['status'],
                          oracle=entry.get('oracle'),
                          blocked_reason=entry.get('blocked_reason'))
                     for entry in blocked]

    # Sanity: no READY case needs a fifth region or a bank larger than 4 KiB.
    max_region_count = max(result['region_count'] for result in results)
    max_command_bytes = max(result['command_bytes'] for result in results)
    holes = [[APERTURE_BASE, INT_BANKS['A'][0]],
             [INT_BANKS['command'][0] + INT_BANKS['command'][1],
              APERTURE_BASE + APERTURE_BYTES]]
    buffer_sizes = sorted({buffer['size'] for result in results
                           for buffer in result['buffers']})
    union_span = [min(result['required_span'][0] for result in results),
                  max(result['required_span'][1] for result in results)]

    if len(ready) != 15 or len(blocked) != 3:
        problems.append(f'capture family counts changed: READY={len(ready)} '
                        f'BLOCKED={len(blocked)}')
    if max_region_count > 4:
        problems.append(f'max region count {max_region_count} exceeds the four-bank plan')
    if any(size > 4096 for size in buffer_sizes):
        problems.append(f'buffer sizes {buffer_sizes} exceed a 4 KiB bank')
    if max_command_bytes > 4096:
        problems.append('command BO exceeds a 4 KiB bank')

    return dict(
        schema='rk3588-ew-int-aperture-audit/v1',
        tool=TOOL,
        captures_root=str(CAPTURES.relative_to(ROOT)),
        capture_manifest_sha256=sha(CAPTURES / 'manifest.json'),
        aperture=dict(base=APERTURE_BASE, decoded_bytes=APERTURE_BYTES,
                      dense_bram36_tiles=dense_tiles,
                      physical_bytes=bank_total,
                      physical_bram36_tiles=sparse_tiles,
                      saved_bram36_tiles=dense_tiles - sparse_tiles,
                      staging='page-form: a/b/out/command in four 4 KiB banks; '
                              'START_ADDRESS points at the command bank'),
        banks=bank_table,
        families=dict(ready=len(ready), blocked=len(blocked),
                      dtypes=sorted({entry['dtype'] for entry in ready}),
                      operations=sorted({entry['operation'] for entry in ready})),
        max_region_count=max_region_count,
        max_command_bytes=max_command_bytes,
        buffer_sizes=buffer_sizes,
        union_span=union_span,
        union_span_bytes=union_span[1] - union_span[0],
        holes=[dict(start=start, end=end, bytes=end - start) for start, end in holes],
        blocked_cases=blocked_audit,
        cases=results,
        problems=problems,
        verdict='PASS' if not problems else 'FAIL',
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        aperture = result['aperture']
        print(f'ew-int aperture audit: {result["verdict"]}')
        print(f'  capture family: {result["families"]["ready"]} READY, '
              f'{result["families"]["blocked"]} BLOCKED')
        print(f'  decoded aperture: 0x{aperture["base"]:08x}..'
              f'0x{aperture["base"] + aperture["decoded_bytes"] - 1:08x} '
              f'({aperture["decoded_bytes"]} B, '
              f'{aperture["dense_bram36_tiles"]} dense BRAM36 tiles)')
        print(f'  physical sparse: {aperture["physical_bytes"]} B, '
              f'{aperture["physical_bram36_tiles"]} banks/tiles '
              f'(saves {aperture["saved_bram36_tiles"]} tiles)')
        for bank in result['banks']:
            print(f'    {bank["name"]:8s} 0x{bank["address"]:08x} '
                  f'{bank["bytes"]:5d} B  {bank["role"]}')
        print(f'  max region count: {result["max_region_count"]}; '
              f'buffer sizes: {result["buffer_sizes"]}; '
              f'max command BO: {result["max_command_bytes"]} B')
        print(f'  union span: 0x{result["union_span"][0]:08x}..'
              f'0x{result["union_span"][1]:08x} '
              f'({result["union_span_bytes"]} B)')
        for problem in result['problems']:
            print('  PROBLEM', problem)
    return 0 if result['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
