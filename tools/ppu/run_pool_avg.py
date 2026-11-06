#!/usr/bin/env python3
"""Replay the one captured FP16 average PPU case through its standalone leaf.

No device, backend, PPU command decoder, DMA, AXI, Vivado, or FPGA is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CASE = 'fp16_avg_k2s1_valid_c8_h4w4'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
MANIFEST = FIXTURE / 'manifest.json'
RTL = ROOT / 'rtl/ppu/rk_ppu_pool_avg2x2s1_fp16_capture.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_avg2x2s1_fp16_capture.sv'
TOP = 'tb_ppu_pool_avg2x2s1_fp16_capture'
BO_BYTES = 4096
VALUE_BYTES = 144
VALUE_LANES = 72
TOLERANCE = 0.0625
FIXTURE_FILES = (
    'capture.json', 'device_out.bin', 'expected.bin', 'in.bin', 'job.json',
    'out_init.bin', 'regcmd.bin',
)

PASS_RE = re.compile(
    r'^PASS ppu_avg2x2s1_fp16_capture case=(?P<case>\S+) input_beats=(?P<input>\d+) '
    r'output_atoms=(?P<atoms>\d+) value_bytes=(?P<value_bytes>\d+) '
    r'lanes=(?P<lanes>\d+) buffer_bytes=(?P<buffer>\d+) '
    r'tail_mismatches=(?P<tail_mismatches>\d+) cycles=(?P<cycles>\d+) '
    r'stall=(?P<stall>\d+) stall_cycles=(?P<stall_cycles>\d+) '
    r'seed=(?P<seed>[0-9a-fA-F]+)$'
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tool_version(argv: list[str]) -> str:
    try:
        out = subprocess.run(argv, text=True, capture_output=True, check=False,
                             timeout=30)
        return (out.stdout or out.stderr).splitlines()[0]
    except Exception as exc:  # pragma: no cover - environment diagnostic
        return f'UNAVAILABLE: {exc}'


def validate_contract(manifest: dict) -> None:
    """Reject shape, mode or numerical-contract drift rather than generalize."""
    required = {
        'case': CASE,
        'status': 'READY_CAPTURE_BOUNDED_CANDIDATE',
        'ppu': {
            'dtype': 'float16', 'method': 'average', 'method_selector': 0,
            'channels': 8, 'kernel': [2, 2], 'stride': [1, 1],
            'padding': [0, 0, 0, 0], 'index_en': False, 'use_cnt': 0,
            'in_shape': [4, 4], 'out_shape': [3, 3],
            'recip_kernel_width': '0x7800', 'recip_kernel_height': '0x7800',
        },
        'layout': {
            'atom_bytes': 16,
            'input': {'line_stride_bytes': 64, 'surface_stride_bytes': 256,
                      'surfaces': 1, 'logical_bytes': 256, 'buffer_bytes': BO_BYTES},
            'output': {'line_stride_bytes': 48, 'surface_stride_bytes': 144,
                       'surfaces': 1, 'value_bytes': VALUE_BYTES,
                       'index_bytes': 0, 'logical_bytes': VALUE_BYTES,
                       'buffer_bytes': BO_BYTES},
        },
        'source': {
            'example_sha256': '2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e',
            'bundle_manifest_sha256': '42b7ae1c9cbe80d48b9f59ed2f675bdc280d6daa7b22e720a7eee8794db0afd7',
            'case_job_sha256': '4739e6d4d20f5d5d99a9cdf41c3cb607b5944f0bdc5831cba69074f07b947cc2',
            'regcmd_sha256': '79dd6b60547879d4a8019b6a2c5862e8dd23d881a5d68f4250707b5b909ccfee',
            'regcmd_text_sha256': '732cc60f66904d2ba140123508ee8ac22d41405d053eb21275abb43649311273',
            'tolerance_abs': TOLERANCE,
            'numerical_contract': (
                'For each 2x2 FP16 window, source pool_reference converts to float32, '
                'takes the mean over both spatial axes, then casts to FP16. Source '
                'atol is 0.0625. No generic hardware rounding or special-value policy is inferred.'
            ),
        },
        'device_capture': {
            'capture_json_sha256': '6623a95632b1f85e235b27779d62f362c3cdc217fb069ac2119be10d8f110860',
            'started_utc': '2026-11-05T20:32:42Z',
            'status': 'OK', 'submit_ret': 0,
            'device': '/dev/accel/accel0',
            'kernel': '6.18.24-current-rockchip64',
            'runner': 'rocket_run.py 1.0.0',
            'runner_sha256': '824f129261a2a0337b3da6720a46d1f9cff23e5d31efff9a0fa085f72f1b43cf',
        },
    }

    def check_subset(actual: object, expected: dict, path: str) -> None:
        if not isinstance(actual, dict):
            raise ValueError(f'missing contract object {path}')
        for key, value in expected.items():
            got = actual.get(key)
            field = f'{path}.{key}'
            if isinstance(value, dict):
                check_subset(got, value, field)
            elif got != value:
                raise ValueError(f'contract mismatch at {field}: {got!r} != {value!r}')

    for section, values in required.items():
        actual = manifest.get(section)
        if section in ('case', 'status'):
            if actual != values:
                raise ValueError(f'contract mismatch at {section}: {actual!r} != {values!r}')
            continue
        check_subset(actual, values, section)


def fixture_check() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    validate_contract(manifest)
    expected_file_records = set(FIXTURE_FILES) | {'regcmd.txt'}
    if set(manifest.get('files', {})) != expected_file_records:
        raise ValueError('fixture file census differs from the pinned capture')
    if manifest['files']['regcmd.txt'] != {
        'bytes': 1666,
        'sha256': '732cc60f66904d2ba140123508ee8ac22d41405d053eb21275abb43649311273',
        'copied': False,
    }:
        raise ValueError('decoded source command table must remain hash-bound and hash-only')
    files = {}
    for name in FIXTURE_FILES:
        expected = manifest['files'][name]
        path = FIXTURE / name
        actual = {'bytes': path.stat().st_size, 'sha256': sha(path)}
        if actual != {'bytes': expected['bytes'], 'sha256': expected['sha256']}:
            raise ValueError(f'fixture {name} hash/size mismatch: {actual!r} != {expected!r}')
        files[name] = actual

    if any(files[name]['bytes'] != BO_BYTES for name in
           ('in.bin', 'out_init.bin', 'expected.bin', 'device_out.bin')):
        raise ValueError('all captured BO fixtures must remain exactly 4096 bytes')
    if files['regcmd.bin']['bytes'] != 28 * 8:
        raise ValueError('captured PPU command stream is not the original 28-QWORD task')

    capture = json.loads((FIXTURE / 'capture.json').read_text())
    for path, expected in (
        (('case',), CASE), (('status',), 'OK'), (('submit_ret',), 0),
        (('schema',), 'rk3588-rocket-capture-v1'),
        (('tool', 'version'), '1.0.0'),
        (('device', 'path'), '/dev/accel/accel0'),
        (('hashes', 'outputs', 'out', 'sha256'), files['device_out.bin']['sha256']),
    ):
        got = capture
        for key in path:
            got = got.get(key) if isinstance(got, dict) else None
        if got != expected:
            raise ValueError(f'capture metadata mismatch at {".".join(path)}: {got!r}')

    expected_bo = (FIXTURE / 'expected.bin').read_bytes()
    device_bo = (FIXTURE / 'device_out.bin').read_bytes()
    init_bo = (FIXTURE / 'out_init.bin').read_bytes()
    if expected_bo != device_bo:
        raise ValueError('source oracle BO is not byte-identical to the pinned device output')
    if device_bo[VALUE_BYTES:] != init_bo[VALUE_BYTES:]:
        raise ValueError('device capture tail differs from the initialized output BO')
    return {'manifest': manifest, 'files': files}


def half_values(data: bytes) -> tuple[float, ...]:
    if len(data) % 2:
        raise ValueError('FP16 byte region has odd length')
    return struct.unpack('<' + 'e' * (len(data) // 2), data)


def compare_bo(observed: bytes, device: bytes, expected: bytes,
               out_init: bytes) -> dict:
    if any(len(buf) != BO_BYTES for buf in (observed, device, expected, out_init)):
        raise ValueError('full BO comparison requires four 4096-byte buffers')
    got_values = half_values(observed[:VALUE_BYTES])
    device_values = half_values(device[:VALUE_BYTES])
    source_values = half_values(expected[:VALUE_BYTES])
    if len(got_values) != VALUE_LANES:
        raise ValueError('wrong number of captured FP16 output lanes')
    diffs_device = [abs(got - ref) for got, ref in zip(got_values, device_values)]
    diffs_source = [abs(got - ref) for got, ref in zip(got_values, source_values)]
    if not all(math.isfinite(value) for group in
               (got_values, device_values, source_values) for value in group):
        raise ValueError('captured contract contains a non-finite value')
    over_device = [i for i, diff in enumerate(diffs_device) if diff > TOLERANCE]
    over_source = [i for i, diff in enumerate(diffs_source) if diff > TOLERANCE]
    tail_matches = observed[VALUE_BYTES:] == out_init[VALUE_BYTES:]
    exact_byte_mismatches = sum(a != b for a, b in zip(observed, device))
    exact_value_byte_mismatches = sum(
        a != b for a, b in zip(observed[:VALUE_BYTES], device[:VALUE_BYTES]))
    tail_mismatches = sum(
        a != b for a, b in zip(observed[VALUE_BYTES:], out_init[VALUE_BYTES:]))
    passed = not over_device and not over_source and tail_matches
    return {
        'whole_bo_bytes_checked': BO_BYTES,
        'logical_value_bytes': VALUE_BYTES,
        'logical_fp16_lanes': VALUE_LANES,
        'comparison_contract': 'FP16 value lanes within absolute tolerance 0.0625; untouched tail byte-exact to out_init.bin',
        'absolute_tolerance': TOLERANCE,
        'device_lane_mismatches_over_tolerance': len(over_device),
        'source_lane_mismatches_over_tolerance': len(over_source),
        'first_device_lane_over_tolerance': over_device[0] if over_device else None,
        'first_source_lane_over_tolerance': over_source[0] if over_source else None,
        'max_abs_diff_vs_device': max(diffs_device),
        'max_abs_diff_vs_source': max(diffs_source),
        'value_byte_mismatches_vs_device_exact': exact_value_byte_mismatches,
        'whole_bo_byte_mismatches_vs_device_exact': exact_byte_mismatches,
        'tail_mismatches_vs_initialized_output': tail_mismatches,
        'tail_preserved': tail_matches,
        'observed_sha256': hashlib.sha256(observed).hexdigest(),
        'device_sha256': hashlib.sha256(device).hexdigest(),
        'source_expected_sha256': hashlib.sha256(expected).hexdigest(),
        'pass': passed,
    }


def run_command(name: str, argv: list[str], outdir: Path, report: dict,
                timeout: int) -> tuple[int, str]:
    log = outdir / f'{name}.log'
    started = time.monotonic()
    record = {'name': name, 'argv': [str(x) for x in argv],
              'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(record)
    try:
        with log.open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout,
                                    check=False)
        text = log.read_text()
    except subprocess.TimeoutExpired as exc:
        record.update(status='TIMEOUT', seconds=round(time.monotonic()-started, 3))
        raise RuntimeError(f'{name} timed out after {timeout}s') from exc
    record.update(returncode=result.returncode,
                  status='PASS' if result.returncode == 0 else 'FAIL',
                  seconds=round(time.monotonic()-started, 3),
                  log_sha256=sha(log),
                  warnings=[line for line in text.splitlines()
                            if line.startswith('%Warning') or 'warning:' in line.lower()])
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
        'status': 'RUNNING',
        'started_utc': now(),
        'simulator': simulator,
        'case': CASE,
        'scope': ('Standalone, capture-bounded FP16 average leaf simulation only; '
                  'not PPU register/DMA/AXI/full-top integration, FPGA execution, '
                  'or a generic PPU numerical claim'),
        'hardware_accessed': False,
        'vivado_executed': False,
        'bitstream_emitted': False,
        'seed': {'always_ready': '0x3588', 'backpressure': '0x600d'},
        'source_hashes_before': before,
        'fixture': {'manifest': str(MANIFEST.relative_to(ROOT)),
                    'files': fixture['files']},
        'commands': [],
        'runs': [],
    }
    outdir.mkdir(parents=True, exist_ok=False)
    save = lambda: (outdir / 'report.json').write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n')
    save()
    build_dir = None
    try:
        if simulator == 'iverilog':
            binary = outdir / 'tb.vvp'
            build_dir = binary
            build_argv = [compiler, '-g2012', '-Wall', '-s', TOP, '-o', str(binary),
                          str(RTL), str(TB)]
            rc, text = run_command('compile', build_argv, outdir, report, 600)
            if rc:
                raise RuntimeError(f'Icarus compile failed: {text[-4000:]}')
            report['binary'] = {'path': str(binary.relative_to(ROOT)), 'sha256': sha(binary)}
            run_prefix = [shutil.which('vvp'), str(binary)]
        else:
            mdir = outdir / 'obj'
            build_dir = mdir
            build_argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                          '--top-module', TOP, '--Mdir', str(mdir), '-o', 'sim',
                          str(RTL), str(TB)]
            rc, text = run_command('compile', build_argv, outdir, report, 600)
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
        report['git_status_before'] = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=ROOT, text=True,
            capture_output=True, check=False).stdout.splitlines()
        save()

        device = (FIXTURE / 'device_out.bin').read_bytes()
        expected = (FIXTURE / 'expected.bin').read_bytes()
        out_init = (FIXTURE / 'out_init.bin').read_bytes()
        input_bo = (FIXTURE / 'in.bin').read_bytes()
        if len(input_bo) != BO_BYTES:
            raise RuntimeError('input BO is not 4096 bytes')

        for stall, seed in ((0, 0x3588), (1, 0x600d)):
            observed_path = outdir / f'out_stall{stall}_seed{seed:08x}.bin'
            argv = run_prefix + [
                f'+IN_BIN={FIXTURE / "in.bin"}',
                f'+OUT_INIT_BIN={FIXTURE / "out_init.bin"}',
                f'+EXPECTED_BIN={FIXTURE / "expected.bin"}',
                f'+DEVICE_OUT_BIN={FIXTURE / "device_out.bin"}',
                f'+OBSERVED_BIN={observed_path}',
                f'+STALL={stall}', f'+SEED={seed}', f'+CASE={CASE}',
            ]
            name = f'run_stall{stall}_seed{seed:08x}'
            rc, text = run_command(name, argv, outdir, report, 120)
            if rc:
                raise RuntimeError(f'{name} failed: {text[-4000:]}')
            matches = [PASS_RE.match(line) for line in text.splitlines()]
            matches = [match.groupdict() for match in matches if match]
            if len(matches) != 1:
                raise RuntimeError(f'{name} did not emit exactly one PASS marker')
            result = matches[0]
            fixed = {'case': CASE, 'input': '16', 'atoms': '9',
                     'value_bytes': str(VALUE_BYTES), 'lanes': str(VALUE_LANES),
                     'buffer': str(BO_BYTES), 'tail_mismatches': '0',
                     'stall': str(stall), 'seed': f'{seed:08x}'}
            for key, value in fixed.items():
                if result[key] != value:
                    raise RuntimeError(f'{name}: PASS field {key}={result[key]} expected {value}')
            stall_cycles = int(result['stall_cycles'])
            if (stall == 0 and stall_cycles != 0) or (stall == 1 and stall_cycles == 0):
                raise RuntimeError(f'{name}: unexpected stall cycle count {stall_cycles}')
            if not observed_path.exists():
                raise RuntimeError(f'{name}: testbench did not write an observed BO')
            observed = observed_path.read_bytes()
            comparison = compare_bo(observed, device, expected, out_init)
            if not comparison['pass']:
                raise RuntimeError(f'{name}: whole-BO tolerance/tail comparison failed: {comparison}')
            report['runs'].append({
                'name': name,
                'stall_mode': stall,
                'seed': f'{seed:08x}',
                'input_beats': int(result['input']),
                'output_atoms': int(result['atoms']),
                'cycles': int(result['cycles']),
                'output_stall_cycles': stall_cycles,
                'stalled_output_stability_assertion': 'PASS',
                'post-frame_input_rejection': 'PASS',
                'comparison': comparison,
                'observed_bo': str(observed_path.relative_to(ROOT)),
                'log': str((outdir / f'{name}.log').relative_to(ROOT)),
            })
            save()

        after = {str(path.relative_to(ROOT)): sha(path) for path in source_inputs}
        if after != before:
            raise RuntimeError('source or fixture files changed during the run')
        report['source_hashes_after'] = after
        report['status'] = 'PASS'
        report['finished_utc'] = now()
        report['summary'] = {
            'case': CASE,
            'simulator': simulator,
            'runs': len(report['runs']),
            'input_atoms_per_frame': 16,
            'output_atoms_per_frame': 9,
            'logical_value_bytes': VALUE_BYTES,
            'logical_value_lanes': VALUE_LANES,
            'full_buffer_bytes': BO_BYTES,
            'absolute_tolerance': TOLERANCE,
            'max_abs_diff': max(run['comparison']['max_abs_diff_vs_device']
                                for run in report['runs']),
            'full_buffer_tail_mismatches': sum(
                run['comparison']['tail_mismatches_vs_initialized_output']
                for run in report['runs']),
            'post_frame_input_rejection': 'PASS',
            'stalled_output_stability': 'PASS',
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
        save()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--out', type=Path, help='output directory for one simulator')
    parser.add_argument('--keep-build', action='store_true', help='retain simulator build products')
    args = parser.parse_args()

    try:
        fixture = fixture_check()
    except Exception as exc:
        print(f'FIXTURE FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    if args.out and len(simulators) != 1:
        print('--out requires a single simulator', file=sys.stderr)
        return 1
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for simulator in simulators:
        outdir = args.out.resolve() if args.out else ROOT / 'build/ppu-pooling' / f'average-{simulator}-{stamp}'
        try:
            report = run_simulator(simulator, outdir, args.keep_build, fixture)
        except Exception as exc:
            print(f'FAIL ppu-average {simulator}: {exc}', file=sys.stderr)
            return 1
        summary = report['summary']
        print(f"PASS ppu-average {simulator}: {summary['runs']} runs, "
              f"{summary['input_atoms_per_frame']} input atoms, "
              f"{summary['output_atoms_per_frame']} outputs, "
              f"{summary['full_buffer_bytes']} BO bytes checked, "
              f"max_abs_diff={summary['max_abs_diff']}, "
              f"tail mismatches={summary['full_buffer_tail_mismatches']}; "
              f"report={outdir / 'report.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
