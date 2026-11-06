#!/usr/bin/env python3
"""Replay the one captured FP16 minimum PPU case through its standalone leaf.

No device, backend, PPU command decoder, DMA, AXI, Vivado, or FPGA is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CASE = 'fp16_min_k2s1_valid_c8_h4w4'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
MANIFEST = FIXTURE / 'manifest.json'
RTL = ROOT / 'rtl/ppu/rk_ppu_pool_min2x2s1_fp16_capture.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_min2x2s1_fp16_capture.sv'
TOP = 'tb_ppu_pool_min2x2s1_fp16_capture'
BO_BYTES = 4096
INPUT_BYTES = 256
VALUE_BYTES = 144
VALUE_LANES = 72
FIXTURE_FILES = (
    'capture.json', 'device_out.bin', 'expected.bin', 'in.bin', 'job.json',
    'out_init.bin', 'regcmd.bin', 'regcmd.txt',
)
PASS_RE = re.compile(
    r'^PASS ppu_min2x2s1_fp16_capture case=(?P<case>\S+) input_beats=(?P<input>\d+) '
    r'output_atoms=(?P<atoms>\d+) value_bytes=(?P<value_bytes>\d+) '
    r'lanes=(?P<lanes>\d+) buffer_bytes=(?P<buffer>\d+) '
    r'mismatches=(?P<mismatches>\d+) lane_mismatches=(?P<lane_mismatches>\d+) '
    r'cycles=(?P<cycles>\d+) stall=(?P<stall>\d+) seed=(?P<seed>[0-9a-fA-F]+)$'
)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tool_version(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, text=True, capture_output=True, check=False,
                                timeout=30)
        return (result.stdout or result.stderr).splitlines()[0]
    except Exception as exc:  # pragma: no cover - environment diagnostic
        return f'UNAVAILABLE: {exc}'


def validate_contract(manifest: dict) -> None:
    """Reject any fixture change beyond this captured one-case contract."""
    exact = {
        'case': CASE,
        'status': 'READY_CAPTURE_BOUNDED_CANDIDATE',
        'ppu': {
            'dtype': 'float16', 'method': 'minimum', 'method_selector': 2,
            'channels': 8, 'kernel': [2, 2], 'stride': [1, 1],
            'padding': [0, 0, 0, 0], 'index_en': False, 'use_cnt': 0,
            'in_shape': [4, 4], 'out_shape': [3, 3],
        },
        'layout': {
            'atom_bytes': 16,
            'input': {'line_stride_bytes': 64, 'surface_stride_bytes': 256,
                      'surfaces': 1, 'logical_bytes': INPUT_BYTES,
                      'buffer_bytes': BO_BYTES},
            'output': {'line_stride_bytes': 48, 'surface_stride_bytes': 144,
                       'surfaces': 1, 'value_bytes': VALUE_BYTES,
                       'index_bytes': 0, 'logical_bytes': VALUE_BYTES,
                       'buffer_bytes': BO_BYTES},
        },
        'input_value_contract': {
            'logical_fp16_lanes': 128, 'finite_lanes': 128,
            'negative_lanes': 32, 'positive_zero_lanes': 1,
            'negative_zero_lanes': 0, 'nan_or_infinity_lanes': 0,
            'minimum': -4.0, 'maximum': 11.875,
        },
        'comparison': {
            'logical_value_bytes': VALUE_BYTES,
            'logical_value_lanes_fp16': VALUE_LANES,
            'mismatches_expected': 0, 'tolerance': 0.0,
            'device_output_sha256': 'bca82f92970dbcd7ad4a31a89d3f1e0868276c16b25185b8081e8e3234bd4d6a',
            'source_expected_sha256': 'bca82f92970dbcd7ad4a31a89d3f1e0868276c16b25185b8081e8e3234bd4d6a',
        },
    }

    def compare_subset(actual: object, expected: dict, path: str) -> None:
        if not isinstance(actual, dict):
            raise ValueError(f'missing contract object {path}')
        for key, value in expected.items():
            got = actual.get(key)
            field = f'{path}.{key}'
            if isinstance(value, dict):
                compare_subset(got, value, field)
            elif got != value:
                raise ValueError(f'contract mismatch at {field}: {got!r} != {value!r}')

    for key, expected in exact.items():
        actual = manifest.get(key)
        if isinstance(expected, dict):
            compare_subset(actual, expected, key)
        elif actual != expected:
            raise ValueError(f'contract mismatch at {key}: {actual!r} != {expected!r}')

    source = manifest.get('source', {})
    if (source.get('example_sha256') !=
            '2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e' or
            source.get('tolerance_abs') != 0.0):
        raise ValueError('source/numerical provenance differs from the pinned case')
    capture = manifest.get('device_capture', {})
    if (capture.get('status'), capture.get('submit_ret'), capture.get('device'),
            capture.get('kernel'), capture.get('runner')) != (
            'OK', 0, '/dev/accel/accel0', '6.18.24-current-rockchip64',
            'rocket_run.py 1.0.0'):
        raise ValueError('device-capture provenance differs from the pinned case')


def source_oracle(input_bo: bytes) -> bytes:
    """Finite captured-data equivalent of pooling.py's per-window np.min."""
    if len(input_bo) != BO_BYTES:
        raise ValueError('input BO must be exactly 4096 bytes')
    words = [int.from_bytes(input_bo[i:i + 2], 'little')
             for i in range(0, INPUT_BYTES, 2)]
    if any(((word >> 10) & 0x1f) == 0x1f for word in words):
        raise ValueError('non-finite input is outside the captured numerical contract')
    if 0x8000 in words:
        raise ValueError('negative zero is outside the captured numerical contract')
    values = struct.unpack('<128e', input_bo[:INPUT_BYTES])
    outputs = []
    for y in range(3):
        for x in range(3):
            for channel in range(8):
                window = [values[(y + dy) * 32 + (x + dx) * 8 + channel]
                          for dy in range(2) for dx in range(2)]
                outputs.append(min(window))
    return struct.pack('<72e', *outputs)


def fixture_check() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    validate_contract(manifest)
    if set(manifest.get('files', {})) != set(FIXTURE_FILES):
        raise ValueError('fixture file census differs from pinned capture')
    files = {}
    for name in FIXTURE_FILES:
        expected = manifest['files'][name]
        path = FIXTURE / name
        actual = {'bytes': path.stat().st_size, 'sha256': sha(path)}
        if actual != {'bytes': expected['bytes'], 'sha256': expected['sha256']}:
            raise ValueError(f'fixture {name} hash/size mismatch: {actual!r} != {expected!r}')
        files[name] = actual
    for name in ('in.bin', 'out_init.bin', 'expected.bin', 'device_out.bin'):
        if files[name]['bytes'] != BO_BYTES:
            raise ValueError(f'{name} must be a complete 4096-byte BO')
    if files['regcmd.bin']['bytes'] != 26 * 8:
        raise ValueError('raw captured command stream must remain 26 QWORDs')

    input_bo = (FIXTURE / 'in.bin').read_bytes()
    expected_bo = (FIXTURE / 'expected.bin').read_bytes()
    device_bo = (FIXTURE / 'device_out.bin').read_bytes()
    out_init = (FIXTURE / 'out_init.bin').read_bytes()
    oracle = source_oracle(input_bo)
    if expected_bo[:VALUE_BYTES] != oracle or device_bo[:VALUE_BYTES] != oracle:
        raise ValueError('source minimum oracle, expected BO and device BO disagree')
    if expected_bo != device_bo:
        raise ValueError('source expected BO is not byte-identical to device output')
    if device_bo[VALUE_BYTES:] != out_init[VALUE_BYTES:]:
        raise ValueError('device output tail differs from initialized output BO')

    capture = json.loads((FIXTURE / 'capture.json').read_text())
    if (capture.get('case'), capture.get('status'), capture.get('submit_ret'),
            capture.get('schema')) != (CASE, 'OK', 0, 'rk3588-rocket-capture-v1'):
        raise ValueError('capture metadata is not a successful pinned device result')
    if capture['hashes']['outputs']['out']['sha256'] != files['device_out.bin']['sha256']:
        raise ValueError('capture metadata does not bind device_out.bin')
    if capture['hashes']['command_stream']['sha256'] != manifest['command_stream']['device_patched_regcmd_sha256']:
        raise ValueError('capture metadata does not bind patched device command stream')
    return {'manifest': manifest, 'files': files}


def save_report(outdir: Path, report: dict) -> None:
    (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def run_command(name: str, argv: list[str], outdir: Path, report: dict,
                timeout: int) -> tuple[int, str]:
    log = outdir / f'{name}.log'
    record = {'name': name, 'argv': [str(arg) for arg in argv],
              'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(record)
    save_report(outdir, report)
    started = time.monotonic()
    with log.open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout,
                                check=False)
    text = log.read_text()
    record.update(returncode=result.returncode,
                  status='PASS' if result.returncode == 0 else 'FAIL',
                  seconds=round(time.monotonic() - started, 3),
                  log_sha256=sha(log),
                  warnings=[line for line in text.splitlines()
                            if line.startswith('%Warning') or 'warning:' in line.lower()])
    save_report(outdir, report)
    return result.returncode, text


def run_simulator(simulator: str, outdir: Path, keep_build: bool,
                  fixture: dict) -> dict:
    compiler = shutil.which(simulator)
    if not compiler:
        raise RuntimeError(f'{simulator} is not installed')
    if simulator == 'iverilog' and not shutil.which('vvp'):
        raise RuntimeError('vvp is not installed')
    source_inputs = [RTL, TB, MANIFEST, Path(__file__).resolve()] + [
        FIXTURE / name for name in FIXTURE_FILES]
    before = {str(path.relative_to(ROOT)): sha(path) for path in source_inputs}
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'simulator': simulator,
        'case': CASE,
        'scope': 'Standalone capture-bounded FP16 minimum leaf simulation; no PPU decoder, DMA, AXI, full-top, FPGA, or RK execution.',
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'seed': {'always_ready': '0x3588', 'backpressure': '0x600d'},
        'source_hashes_before': before,
        'fixture': {'manifest': str(MANIFEST.relative_to(ROOT)), 'files': fixture['files']},
        'commands': [], 'runs': [],
    }
    outdir.mkdir(parents=True, exist_ok=False)
    save_report(outdir, report)
    build_dir = None
    try:
        if simulator == 'iverilog':
            binary = outdir / 'tb.vvp'
            build_dir = binary
            argv = [compiler, '-g2012', '-Wall', '-s', TOP, '-o', str(binary), str(RTL), str(TB)]
            rc, text = run_command('compile', argv, outdir, report, 600)
            if rc:
                raise RuntimeError(f'Icarus compile failed: {text[-4000:]}')
            report['binary'] = {'path': str(binary.relative_to(ROOT)), 'sha256': sha(binary)}
            run_prefix = [shutil.which('vvp'), str(binary)]
        else:
            mdir = outdir / 'obj'
            build_dir = mdir
            argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                    '--top-module', TOP, '--Mdir', str(mdir), '-o', 'sim', str(RTL), str(TB)]
            rc, text = run_command('compile', argv, outdir, report, 600)
            if rc:
                raise RuntimeError(f'Verilator compile failed: {text[-4000:]}')
            binary = mdir / 'sim'
            report['binary'] = {'path': str(binary.relative_to(ROOT)), 'sha256': sha(binary)}
            run_prefix = [str(binary)]

        report['tool_version'] = tool_version(
            [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V'])
        if simulator == 'iverilog':
            report['runtime_version'] = tool_version([shutil.which('vvp'), '-V'])
        report['python_version'] = platform.python_version()
        report['cxx_version'] = tool_version(['c++', '--version'])
        report['git_commit'] = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
            capture_output=True, check=False).stdout.strip()
        save_report(outdir, report)

        device = (FIXTURE / 'device_out.bin').read_bytes()
        out_init = (FIXTURE / 'out_init.bin').read_bytes()
        for stall, seed in ((0, 0x3588), (1, 0x600d)):
            observed_path = outdir / f'out_stall{stall}_seed{seed:08x}.bin'
            argv = run_prefix + [
                f'+IN_BIN={FIXTURE / "in.bin"}',
                f'+OUT_INIT_BIN={FIXTURE / "out_init.bin"}',
                f'+DEVICE_OUT_BIN={FIXTURE / "device_out.bin"}',
                f'+OBSERVED_BIN={observed_path}',
                f'+STALL={stall}', f'+SEED={seed}', f'+CASE={CASE}',
            ]
            name = f'run_stall{stall}_seed{seed:08x}'
            rc, text = run_command(name, argv, outdir, report, 120)
            if rc:
                raise RuntimeError(f'{name} failed: {text[-4000:]}')
            matches = [match.groupdict() for line in text.splitlines()
                       if (match := PASS_RE.match(line))]
            if len(matches) != 1:
                raise RuntimeError(f'{name} did not emit exactly one PASS marker')
            result = matches[0]
            fixed = {'case': CASE, 'input': '16', 'atoms': '9',
                     'value_bytes': str(VALUE_BYTES), 'lanes': str(VALUE_LANES),
                     'buffer': str(BO_BYTES), 'mismatches': '0',
                     'lane_mismatches': '0', 'stall': str(stall),
                     'seed': f'{seed:08x}'}
            for key, value in fixed.items():
                if result[key] != value:
                    raise RuntimeError(f'{name}: {key}={result[key]} expected {value}')
            if not observed_path.exists():
                raise RuntimeError(f'{name}: no observed BO was written')
            observed = observed_path.read_bytes()
            mismatch_offsets = [i for i, (got, want) in enumerate(zip(observed, device))
                                if got != want]
            if len(observed) != BO_BYTES or mismatch_offsets:
                raise RuntimeError(f'{name}: BO mismatch count={len(mismatch_offsets)}')
            if observed[VALUE_BYTES:] != out_init[VALUE_BYTES:]:
                raise RuntimeError(f'{name}: untouched output tail changed')
            report['runs'].append({
                'name': name, 'stall_mode': stall, 'seed': f'{seed:08x}',
                'input_beats': int(result['input']), 'output_atoms': int(result['atoms']),
                'cycles': int(result['cycles']), 'full_bo_byte_mismatches': 0,
                'value_lane_mismatches': 0,
                'tail_preserved': True,
                'observed_bo': str(observed_path.relative_to(ROOT)),
                'observed_bo_sha256': sha(observed_path),
                'log': str((outdir / f'{name}.log').relative_to(ROOT)),
            })
            save_report(outdir, report)

        after = {str(path.relative_to(ROOT)): sha(path) for path in source_inputs}
        if before != after:
            raise RuntimeError('source or fixture files changed during replay')
        report['source_hashes_after'] = after
        report['status'] = 'PASS'
        report['finished_utc'] = now()
        report['summary'] = {
            'case': CASE, 'runs': len(report['runs']),
            'input_atoms_per_frame': 16, 'output_atoms_per_frame': 9,
            'logical_value_bytes': VALUE_BYTES, 'logical_value_lanes': VALUE_LANES,
            'full_buffer_bytes': BO_BYTES, 'full_bo_byte_mismatches': 0,
            'source_oracle_device_exact': True, 'tail_preserved': True,
            'post_frame_input_rejection': 'PASS', 'stalled_output_stability': 'PASS',
            'hardware_accessed': False,
        }
    except Exception as exc:
        report['status'] = 'FAIL'
        report['failure'] = str(exc)
        report['finished_utc'] = now()
        raise
    finally:
        if not keep_build and build_dir is not None:
            if build_dir.is_dir():
                shutil.rmtree(build_dir)
            else:
                build_dir.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        save_report(outdir, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--out', type=Path, help='output directory for one simulator')
    parser.add_argument('--keep-build', action='store_true', help='retain simulator products')
    args = parser.parse_args()
    try:
        fixture = fixture_check()
    except Exception as exc:
        print(f'FIXTURE FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    if args.out and len(simulators) != 1:
        print('--out requires one simulator', file=sys.stderr)
        return 1
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for simulator in simulators:
        outdir = args.out.resolve() if args.out else ROOT / 'build/ppu-pooling' / f'min-{simulator}-{stamp}'
        try:
            report = run_simulator(simulator, outdir, args.keep_build, fixture)
        except Exception as exc:
            print(f'FAIL ppu-min {simulator}: {exc}', file=sys.stderr)
            return 1
        summary = report['summary']
        print(f"PASS ppu-min {simulator}: {summary['runs']} runs, 16 input atoms, "
              f"9 outputs, 4096 BO bytes exact, tail preserved; report={outdir / 'report.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
