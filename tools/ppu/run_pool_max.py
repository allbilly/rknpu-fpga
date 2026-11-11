#!/usr/bin/env python3
"""Replay one captured RK3588 PPU FP16 max-pooling case through the PPU core.

The fixture files are the exact submitted input BO, initialized output BO and
device output BO copied from the 2026-11-05 RK3588 capture. The HDL testbench
reads those raw BOs with $fread(); this runner independently recompares the
written observed BO against the device BO and records the simulator, source,
seed and artifact hashes.
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
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CASE = 'fp16_max_k2s1_valid_c8_h4w4'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
MANIFEST = FIXTURE / 'manifest.json'
RTL = ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s1_c8.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_max2x2s1_c8.sv'
TOP = 'tb_ppu_pool_max2x2s1_c8'
BO_BYTES = 4096
VALUE_BYTES = 144
VALUE_LANES = 72
PASS_RE = re.compile(
    r'^PASS ppu_max2x2s1_c8 case=(?P<case>\S+) input_beats=(?P<input>\d+) '
    r'output_atoms=(?P<atoms>\d+) value_bytes=(?P<value_bytes>\d+) '
    r'lanes=(?P<lanes>\d+) buffer_bytes=(?P<buffer>\d+) '
    r'mismatches=(?P<mismatches>\d+) lane_mismatches=(?P<lane_mismatches>\d+) '
    r'cycles=(?P<cycles>\d+) stall=(?P<stall>\d+) seed=(?P<seed>[0-9a-fA-F]+)$'
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


def fixture_check() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    files = {}
    for name, expected in manifest['files'].items():
        path = FIXTURE / name
        actual = {'bytes': path.stat().st_size, 'sha256': sha(path)}
        if actual['bytes'] != expected['bytes'] or actual['sha256'] != expected['sha256']:
            raise RuntimeError(f'fixture {name} does not match manifest: {actual} != {expected}')
        files[name] = actual
    if (manifest['case'] != CASE or
            manifest['status'] != 'READY_CAPTURE_BOUNDED_CANDIDATE'):
        raise RuntimeError('fixture manifest is not the selected capture-bounded candidate')
    if manifest['layout']['input']['line_stride_bytes'] != 64:
        raise RuntimeError('unexpected captured input line stride')
    if manifest['layout']['output']['line_stride_bytes'] != 48:
        raise RuntimeError('unexpected captured output line stride')
    return {'manifest': manifest, 'files': files}


def compare_bo(observed: bytes, device: bytes, out_init: bytes) -> dict:
    if len(observed) != BO_BYTES or len(device) != BO_BYTES or len(out_init) != BO_BYTES:
        raise RuntimeError('BO comparison requires three 4096-byte buffers')
    full_mismatches = []
    for offset, (got, want) in enumerate(zip(observed, device)):
        if got != want:
            full_mismatches.append((offset, got, want))
    lane_mismatches = []
    for lane in range(VALUE_LANES):
        got = observed[lane*2:lane*2+2]
        want = device[lane*2:lane*2+2]
        if got != want:
            lane_mismatches.append((lane, got.hex(), want.hex()))
    value_byte_mismatches = sum(1 for offset in range(VALUE_BYTES)
                                if observed[offset] != device[offset])
    tail_mismatches = sum(1 for offset in range(VALUE_BYTES, BO_BYTES)
                          if observed[offset] != device[offset])
    if observed[VALUE_BYTES:] != out_init[VALUE_BYTES:]:
        raise RuntimeError('observed output tail differs from the initialized output BO')
    return {
        'buffer_bytes': BO_BYTES,
        'value_bytes': VALUE_BYTES,
        'value_lanes_fp16': VALUE_LANES,
        'full_byte_mismatches': len(full_mismatches),
        'value_byte_mismatches': value_byte_mismatches,
        'lane_mismatches': len(lane_mismatches),
        'tail_mismatches': tail_mismatches,
        'first_byte_mismatch': None if not full_mismatches else {
            'offset': full_mismatches[0][0],
            'observed': f'{full_mismatches[0][1]:02x}',
            'device': f'{full_mismatches[0][2]:02x}',
        },
        'first_lane_mismatch': None if not lane_mismatches else {
            'lane': lane_mismatches[0][0],
            'observed': lane_mismatches[0][1],
            'device': lane_mismatches[0][2],
        },
        'observed_sha256': hashlib.sha256(observed).hexdigest(),
        'device_sha256': hashlib.sha256(device).hexdigest(),
        'tail_preserved': observed[VALUE_BYTES:] == out_init[VALUE_BYTES:],
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
        FIXTURE / name for name in fixture['files']]
    before = {str(p.relative_to(ROOT)): sha(p) for p in source_inputs}
    report = {
        'status': 'RUNNING',
        'started_utc': now(),
        'simulator': simulator,
        'case': CASE,
        'scope': ('Standalone PPU FP16 max-pooling RTL simulation only; '
                  'not register/DMA/full-top integration and not FPGA or RK3588 execution'),
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

    compile_timeout = 600
    if simulator == 'iverilog':
        binary = outdir / 'tb.vvp'
        build_argv = [compiler, '-g2012', '-Wall', '-s', TOP, '-o', str(binary),
                      str(RTL), str(TB)]
        rc, text = run_command('compile', build_argv, outdir, report, compile_timeout)
        if rc:
            raise RuntimeError(f'Icarus compile failed: {text[-4000:]}')
        report['binary'] = {'path': str(binary.relative_to(ROOT)), 'sha256': sha(binary)}
        run_prefix = [shutil.which('vvp'), str(binary)]
    else:
        mdir = outdir / 'obj'
        build_argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                      '--top-module', TOP, '--Mdir', str(mdir), '-o', 'sim',
                      str(RTL), str(TB)]
        rc, text = run_command('compile', build_argv, outdir, report, compile_timeout)
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
    report['cwd'] = str(ROOT)
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                         capture_output=True, check=False)
    report['git_commit'] = git.stdout.strip() if git.returncode == 0 else None
    report['git_status'] = subprocess.run(
        ['git', 'status', '--porcelain'], cwd=ROOT, text=True,
        capture_output=True, check=False).stdout.splitlines()
    save()

    device = (FIXTURE / 'device_out.bin').read_bytes()
    out_init = (FIXTURE / 'out_init.bin').read_bytes()
    input_bo = (FIXTURE / 'in.bin').read_bytes()
    if len(input_bo) != BO_BYTES:
        raise RuntimeError('input BO is not 4096 bytes')

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
        matches = [PASS_RE.match(line) for line in text.splitlines()]
        matches = [m.groupdict() for m in matches if m]
        if len(matches) != 1:
            raise RuntimeError(f'{name} did not emit exactly one PASS marker')
        result = matches[0]
        expected = {'case': CASE, 'input': '16', 'atoms': '9',
                    'value_bytes': str(VALUE_BYTES), 'lanes': str(VALUE_LANES),
                    'buffer': str(BO_BYTES), 'mismatches': '0',
                    'lane_mismatches': '0', 'stall': str(stall),
                    'seed': f'{seed:08x}'}
        for key, value in expected.items():
            if result[key] != value:
                raise RuntimeError(f'{name}: PASS field {key}={result[key]} expected {value}')
        if not observed_path.exists():
            raise RuntimeError(f'{name}: testbench did not write an observed BO')
        observed = observed_path.read_bytes()
        comparison = compare_bo(observed, device, out_init)
        if comparison['full_byte_mismatches'] or comparison['lane_mismatches']:
            raise RuntimeError(f'{name}: observed BO differs: {comparison}')
        if comparison['observed_sha256'] != sha(FIXTURE / 'device_out.bin'):
            raise RuntimeError(f'{name}: observed BO SHA256 differs from device')
        report['runs'].append({
            'name': name,
            'stall_mode': stall,
            'seed': f'{seed:08x}',
            'input_beats': int(result['input']),
            'output_atoms': int(result['atoms']),
            'cycles': int(result['cycles']),
            'comparison': comparison,
            'observed_bo': str(observed_path.relative_to(ROOT)),
            'observed_bo_sha256': comparison['observed_sha256'],
            'log': str((outdir / f'{name}.log').relative_to(ROOT)),
        })
        save()

    after = {str(p.relative_to(ROOT)): sha(p) for p in source_inputs}
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
        'full_byte_mismatches': sum(r['comparison']['full_byte_mismatches']
                                    for r in report['runs']),
        'lane_mismatches': sum(r['comparison']['lane_mismatches']
                               for r in report['runs']),
        'device_bo_sha256': sha(FIXTURE / 'device_out.bin'),
        'tail_preserved': all(r['comparison']['tail_preserved']
                              for r in report['runs']),
    }
    if not keep_build:
        if simulator == 'verilator':
            shutil.rmtree(outdir / 'obj', ignore_errors=True)
        else:
            (outdir / 'tb.vvp').unlink(missing_ok=True)
        report['build_products_pruned'] = True
    save()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='both')
    parser.add_argument('--out', type=Path,
                        help='explicit output directory (single simulator only)')
    parser.add_argument('--keep-build', action='store_true',
                        help='retain simulator object directories and executables')
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
    reports = []
    for simulator in simulators:
        outdir = (args.out.resolve() if args.out else
                  ROOT / 'build/ppu-pooling' / f'{simulator}-{stamp}')
        try:
            report = run_simulator(simulator, outdir, args.keep_build, fixture)
        except Exception as exc:
            print(f'FAIL ppu-pooling {simulator}: {exc}', file=sys.stderr)
            return 1
        reports.append(report)
        summary = report['summary']
        print(f"PASS ppu-pooling {simulator}: {summary['runs']} runs, "
              f"{summary['input_atoms_per_frame']} input atoms, "
              f"{summary['output_atoms_per_frame']} output atoms, "
              f"{summary['full_buffer_bytes']} bytes, "
              f"{summary['logical_value_bytes']} value bytes, "
              f"{summary['logical_value_lanes']} lanes, "
              f"{summary['full_byte_mismatches']} byte mismatches, "
              f"{summary['lane_mismatches']} lane mismatches; "
              f"report={outdir / 'report.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
