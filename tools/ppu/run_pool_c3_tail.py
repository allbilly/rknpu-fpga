#!/usr/bin/env python3
"""Replay the single captured FP16 C3 physical-tail MAX case.

No device, backend, PPU decoder, DMA, AXI, Vivado, or FPGA is used.
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
CASE = 'fp16_max_k2s2_c3_tail_h2w2'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
MANIFEST = FIXTURE / 'manifest.json'
RTL = ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s2_c3_tail_h2w2.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_max2x2s2_c3_tail_h2w2.sv'
TOP = 'tb_ppu_pool_max2x2s2_c3_tail_h2w2'
BO_BYTES = 4096
INPUT_BYTES = 64
VALUE_BYTES = 16
LOGICAL_CHANNELS = 3
PHYSICAL_LANES = 8
TAIL_BITS = 0xd630
FIXTURE_FILES = (
    'capture.json', 'device_out.bin', 'expected.bin', 'in.bin', 'job.json',
    'out_init.bin', 'regcmd.bin', 'regcmd.txt',
)
PASS_RE = re.compile(
    r'^PASS ppu_max2x2s2_c3_tail_h2w2 case=(?P<case>\S+) '
    r'input_beats=(?P<input>\d+) output_atoms=(?P<atoms>\d+) '
    r'logical_channels=(?P<channels>\d+) physical_lanes=(?P<physical>\d+) '
    r'tail_lanes=(?P<tail_lanes>\d+) value_bytes=(?P<value_bytes>\d+) '
    r'buffer_bytes=(?P<buffer>\d+) byte_mismatches=(?P<byte_mismatches>\d+) '
    r'lane_mismatches=(?P<lane_mismatches>\d+) cycles=(?P<cycles>\d+) '
    r'stall=(?P<stall>\d+) stall_cycles=(?P<stall_cycles>\d+) '
    r'seed=(?P<seed>[0-9a-fA-F]+)$'
)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tool_version(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, text=True, capture_output=True,
                                check=False, timeout=30)
        return (result.stdout or result.stderr).splitlines()[0]
    except Exception as exc:  # pragma: no cover - environment diagnostic
        return f'UNAVAILABLE: {exc}'


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


def validate_contract(manifest: dict) -> None:
    """Admit only the pinned C3, 2x2/stride-2, -99-tail capture."""
    expected = {
        'case': CASE,
        'status': 'READY_CAPTURE_BOUNDED_CANDIDATE',
        'ppu': {
            'dtype': 'float16', 'method': 'maximum', 'method_selector': 1,
            'channels': 3, 'kernel': [2, 2], 'stride': [2, 2],
            'padding': [0, 0, 0, 0], 'index_en': False, 'use_cnt': 0,
            'in_shape': [2, 2], 'out_shape': [1, 1],
        },
        'layout': {
            'atom_bytes': 16, 'atom_channels': 8,
            'input': {'line_stride_bytes': 32, 'surface_stride_bytes': 64,
                      'surfaces': 1, 'logical_channels': 3,
                      'logical_bytes': INPUT_BYTES, 'tail_lanes_per_atom': 5,
                      'tail_value_fp16': -99.0, 'buffer_bytes': BO_BYTES},
            'output': {'line_stride_bytes': 16, 'surface_stride_bytes': 16,
                       'surfaces': 1, 'value_bytes': VALUE_BYTES,
                       'index_bytes': 0, 'logical_bytes': VALUE_BYTES,
                       'buffer_bytes': BO_BYTES},
        },
        'input_value_contract': {
            'logical_fp16_lanes': 12, 'physical_fp16_lanes': 32,
            'finite_lanes': 32,
            'logical_channels_by_position': [
                [1.0, 50.0, 3.0], [20.0, 2.0, 60.0],
                [4.0, 5.0, 6.0], [7.0, 8.0, 9.0],
            ],
            'tail_lanes_fp16': 20, 'tail_value_fp16': -99.0,
            'maximum_values_by_channel': [20.0, 50.0, 60.0],
            'output_tail_lanes_fp16': 5,
        },
        'comparison': {
            'logical_value_bytes': VALUE_BYTES,
            'logical_fp16_lanes_physical': PHYSICAL_LANES,
            'logical_channels': LOGICAL_CHANNELS,
            'mismatches_expected': 0, 'tolerance': 0.0,
            'device_output_sha256': 'e418e3dc9a8d3e678e369b58d817b8aadd073cd46dca3a7d251c90031a54af14',
            'source_expected_sha256': 'e418e3dc9a8d3e678e369b58d817b8aadd073cd46dca3a7d251c90031a54af14',
        },
    }
    for key, value in expected.items():
        if isinstance(value, dict):
            compare_subset(manifest.get(key), value, key)
        elif manifest.get(key) != value:
            raise ValueError(f'contract mismatch at {key}: {manifest.get(key)!r} != {value!r}')

    source = manifest.get('source', {})
    if (source.get('example_sha256') !=
            '2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e' or
            source.get('tolerance_abs') != 0.0):
        raise ValueError('source/numerical provenance differs from the pinned C3 case')
    capture = manifest.get('device_capture', {})
    if (capture.get('status'), capture.get('submit_ret'), capture.get('device'),
            capture.get('kernel'), capture.get('runner')) != (
            'OK', 0, '/dev/accel/accel0', '6.18.24-current-rockchip64',
            'rocket_run.py 1.0.0'):
        raise ValueError('device-capture provenance differs from the pinned case')
    stream = manifest.get('command_stream', {})
    if (stream.get('source_regcmd_sha256'), stream.get('qwords')) != (
            '9dc604e7342f0759b63222d24bbf4721cc50a6b6ec4becad1ffdb0c92205a55c', 26):
        raise ValueError('raw command stream provenance differs from capture')


def source_oracle(input_bo: bytes) -> bytes:
    """Source pool_reference MAX for C3 plus the pinned five-lane tail."""
    if len(input_bo) != BO_BYTES:
        raise ValueError('input BO must be exactly 4096 bytes')
    words = [int.from_bytes(input_bo[i:i + 2], 'little')
             for i in range(0, INPUT_BYTES, 2)]
    if any(((word >> 10) & 0x1f) == 0x1f for word in words):
        raise ValueError('non-finite input is outside the captured contract')
    if any(word in (0x0000, 0x8000) for word in words):
        raise ValueError('zero values are outside this exact C3 input contract')
    values = struct.unpack('<32e', input_bo[:INPUT_BYTES])
    logical = []
    for position in range(4):
        atom = values[position * PHYSICAL_LANES:(position + 1) * PHYSICAL_LANES]
        logical.append(atom[:LOGICAL_CHANNELS])
        if any(value != -99.0 for value in atom[LOGICAL_CHANNELS:]):
            raise ValueError(f'physical input tail at position {position} is not all -99')
    maxima = [max(logical[position][channel] for position in range(4))
              for channel in range(LOGICAL_CHANNELS)]
    output_atom = maxima + [-99.0] * (PHYSICAL_LANES - LOGICAL_CHANNELS)
    return struct.pack('<8e', *output_atom)


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
        raise ValueError('captured command stream must remain 26 QWORDs')

    input_bo = (FIXTURE / 'in.bin').read_bytes()
    expected_bo = (FIXTURE / 'expected.bin').read_bytes()
    device_bo = (FIXTURE / 'device_out.bin').read_bytes()
    out_init = (FIXTURE / 'out_init.bin').read_bytes()
    oracle = source_oracle(input_bo)
    if expected_bo[:VALUE_BYTES] != oracle:
        raise ValueError('source C3 maximum/tail oracle differs from expected BO')
    if expected_bo != device_bo:
        raise ValueError('source expected BO is not byte-identical to device output')
    if device_bo[VALUE_BYTES:] != out_init[VALUE_BYTES:]:
        raise ValueError('device output tail differs from initialized output BO')

    capture = json.loads((FIXTURE / 'capture.json').read_text())
    if (capture.get('case'), capture.get('status'), capture.get('submit_ret'),
            capture.get('schema')) != (CASE, 'OK', 0, 'rk3588-rocket-capture-v1'):
        raise ValueError('capture metadata is not a successful device result')
    if capture['hashes']['outputs']['out']['sha256'] != files['device_out.bin']['sha256']:
        raise ValueError('capture metadata does not bind device_out.bin')
    if capture['hashes']['command_stream']['sha256'] != manifest['command_stream']['device_patched_regcmd_sha256']:
        raise ValueError('capture metadata does not bind patched command stream')
    if capture['hashes']['regcmd_source'] != files['regcmd.bin']['sha256']:
        raise ValueError('capture metadata does not bind original raw stream')
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
        'scope': 'Standalone capture-bounded FP16 C3 max-pool physical-tail simulation; no PPU decoder, DMA, AXI, full-top, FPGA, or RK execution.',
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'seed': {'always_ready': '0x3588', 'backpressure': '0x600d'},
        'source_hashes_before': before,
        'fixture': {'manifest': str(MANIFEST.relative_to(ROOT)),
                    'files': fixture['files']},
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
            fixed = {'case': CASE, 'input': '4', 'atoms': '1',
                     'channels': str(LOGICAL_CHANNELS),
                     'physical': str(PHYSICAL_LANES), 'tail_lanes': '5',
                     'value_bytes': str(VALUE_BYTES), 'buffer': str(BO_BYTES),
                     'byte_mismatches': '0', 'lane_mismatches': '0',
                     'stall': str(stall), 'seed': f'{seed:08x}'}
            for key, value in fixed.items():
                if result[key] != value:
                    raise RuntimeError(f'{name}: {key}={result[key]} expected {value}')
            stall_cycles = int(result['stall_cycles'])
            if (stall == 0 and stall_cycles != 0) or (stall == 1 and stall_cycles == 0):
                raise RuntimeError(f'{name}: unexpected output-stall count {stall_cycles}')
            if not observed_path.exists():
                raise RuntimeError(f'{name}: no observed BO was written')
            observed = observed_path.read_bytes()
            if len(observed) != BO_BYTES or observed != device:
                raise RuntimeError(f'{name}: complete output BO differs from device capture')
            if observed[VALUE_BYTES:] != out_init[VALUE_BYTES:]:
                raise RuntimeError(f'{name}: untouched output tail changed')
            report['runs'].append({
                'name': name, 'stall_mode': stall, 'seed': f'{seed:08x}',
                'input_beats': int(result['input']), 'output_atoms': int(result['atoms']),
                'cycles': int(result['cycles']), 'output_stall_cycles': stall_cycles,
                'full_bo_byte_mismatches': 0, 'physical_lane_mismatches': 0,
                'logical_channels': LOGICAL_CHANNELS, 'tail_lane_bits_fp16': f'{TAIL_BITS:04x}',
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
            'input_atoms': 4, 'output_atoms': 1,
            'logical_channels': LOGICAL_CHANNELS, 'physical_lanes': PHYSICAL_LANES,
            'input_tail_lanes_per_atom': 5, 'output_tail_lanes': 5,
            'tail_value_fp16': -99.0, 'logical_value_bytes': VALUE_BYTES,
            'full_buffer_bytes': BO_BYTES, 'full_bo_byte_mismatches': 0,
            'source_oracle_device_exact': True, 'tail_preserved': True,
            'post_frame_input_rejection': 'PASS',
            'stalled_output_stability': 'PASS', 'hardware_accessed': False,
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
        outdir = (args.out.resolve() if args.out else
                  ROOT / 'build/ppu-pooling' / f'c3-tail-{simulator}-{stamp}')
        try:
            report = run_simulator(simulator, outdir, args.keep_build, fixture)
        except Exception as exc:
            print(f'FAIL ppu-c3-tail {simulator}: {exc}', file=sys.stderr)
            return 1
        summary = report['summary']
        print(f"PASS ppu-c3-tail {simulator}: {summary['runs']} runs, 4 input atoms, "
              f"8 output lanes (C3 + five -99 tail), 4096 BO bytes exact; "
              f"report={outdir / 'report.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
