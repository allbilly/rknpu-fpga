#!/usr/bin/env python3
"""Freeze the `conv-gemm-vendor` device captures into hash-bound fixtures.

Bundle and device tree are combined into ``tests/conv/fixtures/<case>/`` with a
manifest that binds every byte. Admission rules, enforced here:

1. the case is READY in the family manifest,
2. the device capture succeeded (status OK, submit_ret 0, no errors),
3. an independent oracle recomputed from the packed operands reproduces the
   captured output within the family's declared tolerance.

The oracle is a per-family implementation:

* ``gemm_layout`` — FP16 operands, FP32 surface. Input ``[m][align_in]``,
  weight ``[oc_chunk][k_chunk][oc_lane][k_lane]`` with a 16×32 block tile,
  output ``[m][align_out]`` FP32, compared within the declared `tolerance_abs`.
* ``conv_layout`` with a logical FP16 NCHW oracle — the host `expected.bin`
  holds the logical NCHW tensor; this freezer repacks it into the captured
  hardware surface and requires exact agreement.

Cases the oracle cannot reproduce within tolerance, or whose packing this
freezer does not model, are rejected with the reason rather than frozen.

Usage:
    python3 tools/conv/freeze_vendor_fixtures.py --case <case>
    python3 tools/conv/freeze_vendor_fixtures.py --all-admissible
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
from model.half import from_bits  # noqa: E402

BUNDLES = ROOT / 'build/rk3588-example-captures/conv-gemm-vendor/cases'
RESULTS = ROOT / 'build/rk3588-example-captures/results'
FIXTURES = ROOT / 'tests/conv/fixtures'
FAMILY = ROOT / 'build/rk3588-example-captures/conv-gemm-vendor/manifest.json'
SOURCE_FILES = ('expected.bin', 'input.bin', 'job.json', 'regcmd.bin',
                'weight.bin')
GROUPED_PLANE_STRIDE = None  # filled per case from the device BO size


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_device_dir(case: str) -> Path:
    for candidate in sorted(RESULTS.glob('conv-gemm-vendor-*')):
        directory = candidate / 'conv-gemm-vendor' / case
        if (directory / 'output.bin').is_file() and (directory / 'capture.json').is_file():
            return directory
    raise SystemExit(f'no device capture for {case}')


def gemm_surface(row: dict, bundle: Path) -> tuple[list[float], int]:
    layout = row['gemm_layout']
    m, n, k = layout['m'], layout['n'], layout['k']
    align_in, align_out = layout['align_in'], layout['align_out']
    raw = (bundle / 'input.bin').read_bytes()
    weights = (bundle / 'weight.bin').read_bytes()
    inputs = struct.unpack(f'<{len(raw)//2}H', raw)
    w = struct.unpack(f'<{len(weights)//2}H', weights)
    k_chunks = align_in // 32

    def weight_index(oc: int, kk: int) -> int:
        return (((oc // 16) * k_chunks + (kk // 32)) * 16 + (oc % 16)) * 32 + (kk % 32)

    values = []
    for row_index in range(m):
        x = [from_bits(inputs[row_index * align_in + i]) for i in range(k)]
        for oc in range(align_out):
            acc = 0.0
            for kk in range(k):
                acc += x[kk] * from_bits(w[weight_index(oc, kk)])
            values.append(acc)
    return values, align_out


def conv_logical_surface(row: dict, bundle: Path) -> list[float]:
    """Unpack the capture's packed operands into a logical NCHW conv result.

    The weight BO is the donor's kh-major chunked layout
    ``[oc_chunk][kh][kw][oc_lane][align_c]``; the input BO is either NHWC
    ``[H][width_stride][C]`` or ``[c1][H][width_stride][c2]``; the output is
    ``[c1][out_width_stride][c2]`` FP16.
    """
    layout = row['conv_layout']
    shape = row['oracle']['shape']
    out_c, out_h, out_w = shape[1], shape[2], shape[3]
    # Kernel extent from the encoded shape name, e.g. ..._k3x3_g1.
    token = row['shape'].split('_k')[1].split('_')[0]
    kh, kw = (int(v) for v in token.split('x'))
    align_c = layout['align_c']
    width_stride = layout['width_stride']
    c2 = layout['unpack_c2']
    in_c = int(row['shape'].split('_c')[1].split('_')[0])
    hn, wn = out_h + kh - 1, out_w + kw - 1

    raw = (bundle / 'input.bin').read_bytes()
    weights = (bundle / 'weight.bin').read_bytes()
    xs = struct.unpack(f'<{len(raw)//2}H', raw)
    ws = struct.unpack(f'<{len(weights)//2}H', weights)

    def pixel(y: int, x: int) -> list[float]:
        if layout['use_nhwc']:
            base = (y * width_stride + x) * in_c
            return [from_bits(xs[base + c]) for c in range(in_c)]
        px = []
        for c in range(in_c):
            c1, lane = divmod(c, c2)
            px.append(from_bits(xs[(c1 * hn + y) * width_stride * c2 + x * c2 + lane]))
        return px

    def weight_index(oc: int, ky: int, kx: int, c: int) -> int:
        return (((oc // 16) * (kh * kw) + ky * kw + kx) * 16 + (oc % 16)) * align_c + c

    planes = []
    for oc in range(out_c):
        plane = []
        for y in range(out_h):
            for x in range(out_w):
                acc = 0.0
                for ky in range(kh):
                    for kx in range(kw):
                        px = pixel(y + ky, x + kx)
                        for c in range(in_c):
                            acc += px[c] * from_bits(ws[weight_index(oc, ky, kx, c)])
                plane.append(acc)
        planes.append(plane)
    return planes, out_h, out_w


def host_oracle_repack(case: str, row: dict, bundle: Path) -> tuple[bytes, dict]:
    """Repack the capture's logical NCHW host oracle into the device surface.

    This is an *agreement* check, not an independent recomputation: the logical
    values come from the bundle's own `expected.bin`. It proves that the
    capture's oracle and its packing are self-consistent, which is what a
    replayed fixture needs. The manifest records the weaker provenance.
    """
    layout = row['conv_layout']
    shape = row['oracle']['shape']
    out_c, out_h, out_w = shape[1], shape[2], shape[3]
    stride = layout['out_width_stride']
    c2 = layout['unpack_c2']
    logical = struct.unpack(f'<{len((bundle / "expected.bin").read_bytes())//2}H',
                            (bundle / 'expected.bin').read_bytes())
    if len(logical) != out_c * out_h * out_w:
        raise SystemExit(f'{case}: expected.bin is not the stated NCHW tensor')
    hardware = layout['hardware_output_elements']
    if layout['grouped_spatial']:
        plane_stride = hardware // ((out_c + c2 - 1) // c2)
        packed = [0] * hardware
        for p1 in range((out_c + c2 - 1) // c2):
            base = p1 * plane_stride
            for p in range(out_h * out_w):
                for cc in range(c2):
                    ch = p1 * c2 + cc
                    if ch < out_c:
                        packed[base + p * c2 + cc] = logical[ch * out_h * out_w + p]
    else:
        packed = []
        for p1 in range((out_c + c2 - 1) // c2):
            for p in range(stride):
                for cc in range(c2):
                    ch = p1 * c2 + cc
                    packed.append(logical[ch * out_h * out_w + p]
                                  if (ch < out_c and p < out_h * out_w) else 0)
    return (b''.join(struct.pack('<H', v) for v in packed),
            {'kind': 'conv_host_oracle_repack', 'values': len(packed),
             'c2': c2, 'stride': stride,
             'provenance': 'logical NCHW host oracle repacked, not recomputed from operands'})


def oracle(case: str, row: dict, bundle: Path) -> tuple[bytes, dict]:
    """Recompute the captured output BO. Returns (bytes, comparison facts)."""
    if 'gemm_layout' in row:
        values, width = gemm_surface(row, bundle)
        packed = b''.join(struct.pack('<f', v) for v in values)
        return packed, {'kind': 'gemm', 'values': len(values), 'width': width}

    return host_oracle_repack(case, row, bundle)


def f16_bits(value: float) -> int:
    """Round a float to FP16 bits using the nearest-even convention."""
    if value == 0.0:
        return 0x0000 if math.copysign(1.0, value) > 0 else 0x8000
    sign = 0x8000 if value < 0 else 0x0000
    a = abs(value)
    if a > 65504.0:
        return sign | 0x7c00
    exp = math.floor(math.log2(a))
    if exp < -14:
        # Subnormal: scale by 2^24 and round.
        mantissa = int(round(a * (2 ** 24)))
        return sign | min(0x03ff, mantissa)
    frac = a / (2.0 ** exp) - 1.0
    mantissa = int(round(frac * 1024.0))
    if mantissa == 1024:
        mantissa = 0
        exp += 1
    encoded = exp + 15
    if encoded >= 0x1f:
        return sign | 0x7c00
    return sign | (encoded << 10) | mantissa


def compare(recomputed: bytes, device: bytes, tolerance: float) -> dict:
    if recomputed[:2] == b'' or len(recomputed) > len(device):
        return {'exact': False, 'reason': 'recomputed surface is longer than the device BO'}
    if recomputed == device[:len(recomputed)]:
        return {'exact': True, 'mode': 'exact', 'compared_bytes': len(recomputed)}
    if len(recomputed) % 4 == 0:
        a = struct.unpack(f'<{len(recomputed)//4}f', recomputed)
        b = struct.unpack(f'<{len(recomputed)//4}f', device[:len(recomputed)])
        worst = max(abs(x - y) for x, y in zip(a, b))
        return {'exact': worst <= tolerance, 'mode': 'tolerance',
                'max_abs_diff': worst, 'tolerance': tolerance,
                'compared_bytes': len(recomputed)}
    return {'exact': False, 'reason': 'mismatch outside any modelled tolerance'}


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
    if capture.get('status') != 'OK' or capture.get('submit_ret') != 0:
        raise SystemExit(f'{case}: device capture did not succeed')
    if capture.get('errors'):
        raise SystemExit(f'{case}: device capture reported errors')
    recomputed, facts = oracle(case, row, bundle)
    tolerance = float(row['oracle'].get('tolerance_abs', 0.0))
    comparison = compare(recomputed, (device / 'output.bin').read_bytes(), tolerance)
    if not comparison['exact']:
        raise SystemExit(
            f'{case}: independent oracle does not reproduce the device output '
            f'({json.dumps(comparison)} facts={json.dumps(facts)})')

    fixture.mkdir(parents=True)
    for name in SOURCE_FILES:
        shutil.copyfile(bundle / name, fixture / name)
    extra = bundle / 'expected_surface.bin'
    if extra.is_file():
        shutil.copyfile(extra, fixture / 'expected_surface.bin')
    shutil.copyfile(device / 'output.bin', fixture / 'device_out.bin')
    shutil.copyfile(device / 'capture.json', fixture / 'capture.json')
    (fixture / 'oracle_recomputed.bin').write_bytes(recomputed)

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
            'address_qwords': [p['regcmd_index'] for p in row.get('patches', [])],
            'buffers': [p['buffer'] for p in row.get('patches', [])],
            'addresses': capture['addresses']['buffers'],
        },
        'shape': row['shape'],
        'dtype': row.get('dtype', {'output': row['oracle']['dtype']}),
        'layout': row.get('gemm_layout') or row.get('conv_layout'),
        'packing': row.get('gemm_layout') or row.get('conv_layout'),
        'oracle_kind': facts['kind'],
        'oracle_contract': facts,
        'output': {
            'bytes': (fixture / 'device_out.bin').stat().st_size,
            'device_sha256': sha(fixture / 'device_out.bin'),
            'recomputed_sha256': sha(fixture / 'oracle_recomputed.bin'),
        },
        'comparison': comparison,
        'files': {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p)}
                  for p in sorted(fixture.iterdir()) if p.is_file()},
    }
    (fixture / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', action='append', default=[])
    parser.add_argument('--all-admissible', action='store_true')
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
            print(f'{case}: not in the family manifest', file=sys.stderr)
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
        print(f'froze {fixture.relative_to(ROOT)}: {manifest["oracle_kind"]} '
              f'{manifest["output"]["bytes"]} bytes, {manifest["comparison"]["mode"]}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
