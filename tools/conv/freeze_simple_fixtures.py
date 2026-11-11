#!/usr/bin/env python3
"""Freeze the `conv-simple` device captures into hash-bound fixtures.

The host bundle under ``build/rk3588-example-captures/conv-simple/cases`` and
the device run under ``build/rk3588-example-captures/results/conv-simple-*/``
are combined into ``tests/conv/fixtures/<case>/`` with a manifest that binds
every byte.

Admission rules, all enforced here rather than assumed:

1. the case is READY in the family manifest,
2. the device capture succeeded (status OK, submit_ret 0, no errors),
3. the device output equals the host ``expected.bin`` byte for byte,
4. an independent oracle recomputed from the packed input and weight BOs in
   pure Python reproduces ``expected.bin`` byte for byte.

Rule 3 rejects the cases whose host oracle disagrees with the device; they are
reported, not silently frozen. Rule 4 rejects a fixture whose expected bytes
cannot be derived from its own operands, so no later RTL can be "validated"
against an unrelated oracle.

Usage:
    python3 tools/conv/freeze_simple_fixtures.py --case <case>
    python3 tools/conv/freeze_simple_fixtures.py --all-admissible
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from model.half import from_bits, to_bits  # noqa: E402

BUNDLES = ROOT / 'build/rk3588-example-captures/conv-simple/cases'
RESULTS = ROOT / 'build/rk3588-example-captures/results'
FIXTURES = ROOT / 'tests/conv/fixtures'
FAMILY = ROOT / 'build/rk3588-example-captures/conv-simple/manifest.json'
SOURCE_FILES = ('input.bin', 'weight.bin', 'expected.bin', 'regcmd.bin', 'job.json')

# Per-case packing facts, taken from the family manifest `layout` and
# `shape` fields. Anything not listed here is refused rather than guessed.
LAYOUTS = {
    'conv_simple_fp16_1x1_c4_h8_w8_oc16': dict(
        in_c=4, kh=1, kw=1, align_c=8, c2_in=4, c2_out=4, fp16_output=False),
    'conv_simple_fp16_3x3_c4_h8_w8_oc16': dict(
        in_c=4, kh=3, kw=3, align_c=8, c2_in=4, c2_out=8, fp16_output=True),
    'conv_simple_fp16_5x5_c4_h8_w8_oc16': dict(
        in_c=4, kh=5, kw=5, align_c=8, c2_in=4, c2_out=8, fp16_output=True),
    'conv_simple_fp16_3x3_c16_h8_w8_oc32': dict(
        in_c=16, kh=3, kw=3, align_c=16, c2_in=8, c2_out=8, fp16_output=True),
    'conv_simple_fp16_1x1_c32_h8_w8_oc32': dict(
        in_c=32, kh=1, kw=1, align_c=32, c2_in=8, c2_out=4, fp16_output=False),
}
IN_H = IN_W = 8


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_device_dir(case: str) -> Path:
    for candidate in sorted(RESULTS.glob('conv-simple-*')):
        directory = candidate / 'conv-simple' / case
        if (directory / 'out.bin').is_file() and (directory / 'capture.json').is_file():
            return directory
    raise SystemExit(f'no device capture for {case}')


def oracle(case: str, bundle: Path) -> bytes:
    """Recompute the captured output BO from the packed operands.

    This mirrors the documented device layout exactly:
      input  [c1][H][width_stride][c2] or NHWC [H][width][c2]
      weight [oc_chunk][kh][kw][oc_lane][align_c]
      output [c1][out_width_stride][c2], stride rounded up to 4 atoms.
    """
    facts = LAYOUTS[case]
    in_c, kh, kw = facts['in_c'], facts['kh'], facts['kw']
    align_c, c2_in, c2_out = facts['align_c'], facts['c2_in'], facts['c2_out']
    raw = (bundle / 'input.bin').read_bytes()
    weights = (bundle / 'weight.bin').read_bytes()
    if len(raw) % 2 or len(weights) % 2:
        raise SystemExit(f'{case}: operand BUFs are not whole FP16 elements')
    x = [from_bits(v) for v in struct.unpack(f'<{len(raw)//2}H', raw)]
    w = [from_bits(v) for v in struct.unpack(f'<{len(weights)//2}H', weights)]
    expected = (bundle / 'expected.bin').read_bytes()
    bpe = 2 if facts['fp16_output'] else 4
    out_h, out_w = IN_H - kh + 1, IN_W - kw + 1
    stride = ((out_h * out_w + 3) // 4) * 4
    out_c = len(expected) // (stride * bpe)
    if out_c < 1 or out_c * stride * bpe != len(expected):
        raise SystemExit(f'{case}: expected.bin does not match the atom geometry')

    def pixel(y: int, xpos: int) -> list[float]:
        if in_c <= c2_in:  # NHWC: [H][width_stride][c2]
            base = (y * IN_W + xpos) * c2_in
            return [x[base + c] for c in range(in_c)]
        return [x[(((c // c2_in) * IN_H + y) * IN_W + xpos) * c2_in + (c % c2_in)]
                for c in range(in_c)]

    def weight_index(oc: int, ky: int, kx: int, c: int) -> int:
        return (((oc // 16) * (kh * kw) + ky * kw + kx) * 16 + (oc % 16)) * align_c + c

    planes = []
    for oc in range(out_c):
        plane = []
        for y in range(out_h):
            for xpos in range(out_w):
                acc = 0.0
                for ky in range(kh):
                    for kx in range(kw):
                        px = pixel(y + ky, xpos + kx)
                        for c in range(in_c):
                            acc += px[c] * w[weight_index(oc, ky, kx, c)]
                plane.append(acc)
        planes.append(plane)

    packed = []
    for c1 in range(out_c // c2_out):
        for position in range(stride):
            for c2 in range(c2_out):
                value = planes[c1 * c2_out + c2][position] if position < out_h * out_w else 0.0
                if facts['fp16_output']:
                    packed.append(to_bits(value))
                else:
                    packed.extend(struct.pack('<f', value))
    if facts['fp16_output']:
        return b''.join(struct.pack('<H', v) for v in packed)
    return bytes(packed)


def freeze(case: str, row: dict) -> Path:
    bundle = BUNDLES / case
    device = find_device_dir(case)
    fixture = FIXTURES / case
    if (fixture / 'manifest.json').exists():
        raise SystemExit(f'{case}: fixture already exists')
    if fixture.exists():
        shutil.rmtree(fixture)
    for name in SOURCE_FILES:
        if not (bundle / name).is_file():
            raise SystemExit(f'{case}: bundle is missing {name}')
    capture = json.loads((device / 'capture.json').read_text())
    # The comparison lives beside the case directory, not inside it:
    # results/<run>/conv-simple/<case>/capture.json  and
    # results/<run>/host-analysis/comparison.json.
    run_root = device.parent.parent
    comparison = json.loads((run_root / 'host-analysis' / 'comparison.json').read_text())
    case_comparison = next(c for c in comparison['cases'] if c['case'] == case)
    if capture.get('status') != 'OK' or capture.get('submit_ret') != 0:
        raise SystemExit(f'{case}: device capture did not succeed')
    if capture.get('errors'):
        raise SystemExit(f'{case}: device capture reported errors')
    # Device/host agreement is checked before anything about this freezer's
    # own capabilities: a case the device itself contradicts is inadmissible
    # regardless of whether a packing table exists.
    if sha(device / 'out.bin') != sha(bundle / 'expected.bin'):
        raise SystemExit(
            f'{case}: device output differs from the host oracle '
            f'({case_comparison.get("mismatch_element_count", "?")} elements, '
            f'first offset {case_comparison.get("first_diff_offset", "?")}, '
            f'comparison={case_comparison.get("comparison", "?")})')
    if not case_comparison.get('exact_full_match'):
        raise SystemExit(f'{case}: capture comparison is not an exact full match')
    if case not in LAYOUTS:
        raise SystemExit(f'{case}: no documented packing layout in this freezer')
    recomputed = oracle(case, bundle)
    if recomputed != (bundle / 'expected.bin').read_bytes():
        raise SystemExit(f'{case}: independent oracle does not reproduce expected.bin')

    fixture.mkdir(parents=True)
    for name in SOURCE_FILES:
        shutil.copyfile(bundle / name, fixture / name)
    shutil.copyfile(device / 'out.bin', fixture / 'device_out.bin')
    shutil.copyfile(device / 'capture.json', fixture / 'capture.json')
    with (fixture / 'oracle_recomputed.bin').open('wb') as stream:
        stream.write(recomputed)

    facts = LAYOUTS[case]
    manifest = {
        'case': case,
        'status': 'READY_CAPTURE_BOUNDED_CANDIDATE',
        'description': row['description'],
        'source_example': row['source_example'],
        'source_bundle': str(bundle.relative_to(ROOT)),
        'device_capture': {
            'capture_json_sha256': sha(fixture / 'capture.json'),
            'device': capture.get('device_path'),
            'kernel': capture['device']['kernel'],
            'board_compatible': capture['device']['board_compatible'],
            'submit_ret': capture['submit_ret'],
            'errors': capture.get('errors', []),
        },
        'command_stream': {
            'qwords': len((fixture / 'regcmd.bin').read_bytes()) // 8,
            'regcmd_sha256': sha(fixture / 'regcmd.bin'),
            'address_qwords': [p['regcmd_index'] for p in row['patches']],
            'buffers': [p['buffer'] for p in row['patches']],
            # The capture's own BO placement, not a convenient default: the
            # 5x5 and C16 cases need output above the weight BO to stay disjoint.
            'addresses': {p['buffer']: p['dma_address'] for p in capture['patches']},
            'fetch_words': row.get('regcmd_fetch_words'),
            'padding_words': row.get('regcmd_padding_words'),
        },
        'shape': row['shape'],
        'dtype': row['dtype'],
        'layout': row['layout'],
        'packing': facts,
        'output': {
            'bytes': (fixture / 'device_out.bin').stat().st_size,
            'device_sha256': sha(fixture / 'device_out.bin'),
            'host_expected_sha256': sha(fixture / 'expected.bin'),
            'oracle_recomputed_sha256': sha(fixture / 'oracle_recomputed.bin'),
        },
        'comparison': {
            'scope': 'complete captured output BO',
            'mismatches_expected': 0,
            'tolerance': 0.0,
            'note': ('Device output, host expected.bin and the independent '
                     'recomputed oracle are byte-identical.'),
        },
        'files': {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p)}
                  for p in sorted(fixture.iterdir()) if p.is_file()},
    }
    (fixture / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--all-admissible', action='store_true')
    parser.add_argument('--explain-rejects', action='store_true')
    args = parser.parse_args()
    family = json.loads(FAMILY.read_text())['cases']
    rows = {row['case']: row for row in family}
    targets = list(args.case)
    if args.all_admissible:
        targets += [row['case'] for row in family
                    if row['status'] == 'READY'
                    and not (FIXTURES / row['case'] / 'manifest.json').exists()]
    if not targets:
        print('nothing to do; pass --case or --all-admissible', file=sys.stderr)
        return 2
    failures = 0
    for case in targets:
        if case not in rows:
            print(f'{case}: not in the conv-simple family manifest', file=sys.stderr)
            return 1
        row = rows[case]
        if row['status'] != 'READY':
            print(f'{case}: family status is {row["status"]}', file=sys.stderr)
            failures += 1
            continue
        try:
            fixture = freeze(case, row)
        except SystemExit as error:
            print(f'REJECT {case}: {error}', file=sys.stderr)
            failures += 1
            continue
        manifest = json.loads((fixture / 'manifest.json').read_text())
        print(f'froze {fixture.relative_to(ROOT)}: {manifest["shape"]["in_c"]}x'
              f'{manifest["shape"]["in_h"]}x{manifest["shape"]["in_w"]} -> '
              f'OC{manifest["shape"]["out_c"]} k{manifest["shape"]["kh"]}x'
              f'{manifest["shape"]["kw"]} {manifest["dtype"]["output"]}, '
              f'{manifest["output"]["bytes"]} bytes exact')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
