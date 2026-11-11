#!/usr/bin/env python3
"""Offline EW aperture audit for the merged image (task-21).

Reads the frozen capture bundles under ``build/rk3588-example-captures/`` and
answers one question: if the merged image stages these families through the EW
memory aperture (1 MiB decoded, sparse banks), do all their absolute-address
needs fit the measured six-bank layout?

The EW endpoint executes a raw command BO whose data pointers are *patched by the
host* at staging time (job.json ``patches``); command QWORDs themselves carry no
fixed heap addresses except the three patched pointers and the (zero) PC-chain
tail. This tool therefore checks, per case:

* which register fields are address-bearing and whether every one of them is in
  the patch list (no captured absolute address is ever executed unpatched);
* the buffer set/sizes and the command-BO size the staging plan must provide;
* that a chosen staging layout inside the six measured EW banks covers the case
  (buffer sizes <= bank sizes, command bytes <= command bank, region count);
* the union span and the maximum number of distinct BO regions per case.

It reads only frozen files; it never writes under the capture tree, never runs
Vivado and never touches hardware. ``--json`` prints a machine summary.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from model.profile import decode  # noqa: E402

CAPTURES = ROOT / 'build/rk3588-example-captures'

# The six EW banks measured from the nine production captures
# (docs/MERGED_IMAGE_PLAN.md §3.5, docs/EW_APERTURE_AUDIT.md).
EW_BANKS = {
    'A': (0x1000_1000, 4096),
    'B': (0x1002_0000, 4096),
    'D': (0x1004_0000, 4096),
    'scratch': (0x1006_0000, 8192),
    'command': (0x100E_0000, 65536),
    'task': (0x100F_0000, 16384),
}

# Register fields that carry a device memory address in this raw-command family.
# Evidence: model/profile.py register map + the frozen job.json patch lists.
ADDRESS_FIELDS = {
    (0x1001, 0x4020): 'dpu_dst',           # DPU dst buffer pointer
    (0x2001, 0x5018): 'rdma_src_a',        # RDMA src_a pointer
    (0x2001, 0x5038): 'rdma_src_b',        # RDMA src_b pointer
    (0x0101, 0x0010): 'pc_next_address',   # terminal PC chain pointer
    (0x0101, 0x0014): 'pc_next_amount',    # chain amount (not an address)
}

# The staging plan for bundle families: operand buffers into A/B/D, command BO
# into the command bank. Bundle families are single-task and need no task BO.
STAGING = {
    'a': 'A',
    'b': 'B',
    'out': 'D',
    'command': 'command',
}


def sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode_words(raw: bytes) -> list[tuple[int, int, int]]:
    words = [int.from_bytes(raw[i:i + 8], 'little') for i in range(0, len(raw), 8)]
    return [decode(word) for word in words]


def audit_case(family: str, case_dir: Path) -> dict:
    job = json.loads((case_dir / 'job.json').read_text())
    regcmd = (case_dir / 'regcmd.bin').read_bytes()
    fields = decode_words(regcmd)
    patches = {int(p['regcmd_index']): p for p in job.get('patches', [])}
    padded = int(job.get('regcmd_padding_words', 0))
    command_words = int(job['tasks'][0]['regcmd_words'])
    assert len(regcmd) == 8 * (command_words + padded), case_dir

    problems: list[str] = []
    address_fields_seen: list[dict] = []
    for index, (target, offset, value) in enumerate(fields):
        name = ADDRESS_FIELDS.get((target, offset))
        if name is None:
            continue
        # pc_next_amount is an integer count, not an address; it must be zero for
        # these single-task families.
        if name == 'pc_next_amount':
            if value != 0:
                problems.append(f'Q{index} {name} nonzero ({value:#x}) — chained PC tasks are out of scope')
            continue
        patched = index in patches
        address_fields_seen.append(dict(index=index, field=name, value=value,
                                        patched=patched,
                                        patch_buffer=patches[index]['buffer'] if patched else None))
        if not patched:
            if name.startswith('dpu_') or name.startswith('rdma_'):
                problems.append(f'Q{index} {name} is an address field but is not host-patched')
            elif value != 0:
                problems.append(f'Q{index} {name} unpatched nonzero ({value:#x})')

    # Every patch must target a known address field of this family, with a
    # value32 patch (the frozen command words are 64-bit, addresses are 32-bit).
    for index, patch in patches.items():
        if index >= len(fields):
            problems.append(f'patch index {index} outside the command BO')
            continue
        target, offset, _ = fields[index]
        if (target, offset) not in ADDRESS_FIELDS:
            problems.append(f'patch Q{index} targets non-address field '
                            f'{(target, offset)}')
        if patch.get('kind') != 'value32':
            problems.append(f'patch Q{index} kind {patch.get("kind")} is not value32')
        if patch.get('buffer') not in STAGING or STAGING[patch['buffer']] not in EW_BANKS:
            problems.append(f'patch Q{index} buffer {patch.get("buffer")} has no EW bank')

    buffers = job.get('buffers', [])
    required = []
    for buffer in buffers:
        bank = STAGING.get(buffer['name'])
        if bank is None:
            # Extra buffers are a real aperture change, not a silent fallback.
            problems.append(f'buffer {buffer["name"]} has no planned EW bank')
            continue
        base, size = EW_BANKS[bank]
        if int(buffer['size']) > size:
            problems.append(f'buffer {buffer["name"]} size {buffer["size"]} > bank {bank} ({size})')
        required.append(dict(name=buffer['name'], size=int(buffer['size']),
                             direction=buffer['direction'], bank=bank,
                             address=base))
    command_bank = EW_BANKS[STAGING['command']]
    if len(regcmd) > command_bank[1]:
        problems.append(f'command BO {len(regcmd)} B > command bank {command_bank[1]}')
    if not any(p.get('buffer') == 'out' for p in patches.values()):
        # Every captured case patches the destination pointer; a case without it
        # would need an embedded address we have not audited.
        problems.append('no out-pointer patch in the command BO')

    regions = required + [dict(name='command', size=len(regcmd), bank='command',
                               address=command_bank[0])]
    width = max(regcmd[0:0].__len__(), 0)
    return dict(family=family, case=case_dir.name,
                source_example=job.get('source_example'),
                command_bytes=len(regcmd), command_words=command_words,
                padding_words=padded,
                buffers=[dict(name=b['name'], size=int(b['size']),
                              direction=b['direction']) for b in buffers],
                patches=[dict(index=i, buffer=p['buffer'], kind=p['kind'])
                         for i, p in sorted(patches.items())],
                address_fields=address_fields_seen,
                regions=regions,
                region_count=len(regions),
                problems=problems)


def audit_family(family: str) -> dict:
    directory = CAPTURES / family
    manifest = json.loads((directory / 'manifest.json').read_text())
    cases = [c['case'] for c in manifest['cases'] if c.get('status') == 'READY']
    results = [audit_case(family, directory / 'cases' / case) for case in cases]
    problems = [f'{family}/{r["case"]}: {p}' for r in results for p in r['problems']]
    return dict(family=family,
                cases=len(results),
                cases_with_problems=sum(1 for r in results if r['problems']),
                problems=problems,
                max_command_bytes=max(r['command_bytes'] for r in results),
                max_buffers=max(len(r['buffers']) for r in results),
                max_region_count=max(r['region_count'] for r in results),
                buffer_sizes=sorted({b['size'] for r in results for b in r['buffers']}),
                results=results)


def audit_backend_production() -> dict:
    """The nine production BO layouts the six banks were measured from."""
    import base64
    import zlib
    capture = json.loads((ROOT / 'tests/backend_ew_captures.json').read_text())
    results = []
    for case in capture['cases']:
        regions = []
        for region in case['regions']:
            data = zlib.decompress(base64.b64decode(region['zlib_base64'], validate=True))
            assert len(data) == region['size']
            regions.append(dict(address=region['address'], size=region['size'],
                                kind='production'))
        results.append(dict(case=case['name'], regions=regions,
                            region_count=len(regions),
                            span=[min(r['address'] for r in regions),
                                  max(r['address'] + r['size'] for r in regions)]))
    return dict(family='backend-ew-production', cases=len(results),
                max_region_count=max(r['region_count'] for r in results),
                union_span=[min(r['span'][0] for r in results),
                            max(r['span'][1] for r in results)],
                results=results)


def simple_add_evidence() -> dict:
    """There is no separate simple_add bundle family; document the evidence."""
    manifest = json.loads((CAPTURES / 'ew-fp16' / 'manifest.json').read_text())
    referenced = [c['case'] for c in manifest['cases']
                  if any('simple_add.py' in line for line in c.get('source_lines', []))]
    return dict(family='simple_add', separate_bundles=0,
                audited_via='ew-fp16',
                evidence=('No separate simple_add capture family exists under '
                          'build/rk3588-example-captures/. The frozen ew-fp16 family '
                          'cites /home/fedora/rk3588/examples/simple_add.py as the '
                          'EW_CFG/8-lane-width cross-check for every case; the '
                          'command grammar and buffer set are the same raw-command '
                          'family audited here.'),
                ew_fp16_cases_cross_checked=len(referenced))


def run(selected: list[str]) -> dict:
    families = []
    for family in selected:
        if family == 'simple_add':
            families.append(simple_add_evidence())
        else:
            families.append(audit_family(family))
    production = audit_backend_production()
    bank_bytes = {name: size for name, (_, size) in EW_BANKS.items()}
    problems = [p for f in families for p in f.get('problems', [])]
    return dict(schema='rk3588-ew-aperture-audit/v1',
                captures_root=str(CAPTURES.relative_to(ROOT)),
                ew_banks={name: dict(address=base, bytes=size)
                          for name, (base, size) in EW_BANKS.items()},
                families=families,
                production_baseline=production,
                problems=problems,
                verdict='PASS' if not problems else 'FAIL')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--families', default='ew-fp16,fdiv-systematic,simple_add',
                        help='comma separated; simple_add is documentation-only')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    selected = [item for item in args.families.split(',') if item]
    result = run(selected)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f'EW aperture audit: {result["verdict"]}')
        for family in result['families']:
            if 'results' not in family:
                print(f'  {family["family"]}: {family["evidence"][:100]}...')
                continue
            print(f'  {family["family"]}: {family["cases"]} cases, '
                  f'problems={family["cases_with_problems"]}, '
                  f'max_command_bytes={family["max_command_bytes"]}, '
                  f'max_buffers={family["max_buffers"]}, '
                  f'max_regions={family["max_region_count"]}, '
                  f'buffer_sizes={family["buffer_sizes"]}')
        production = result['production_baseline']
        print(f'  {production["family"]}: {production["cases"]} cases, '
              f'max_regions={production["max_region_count"]}, '
              f'union_span=0x{production["union_span"][0]:08x}..0x{production["union_span"][1]:08x}')
        for problem in result['problems'][:20]:
            print('  PROBLEM', problem)
    return 0 if result['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
