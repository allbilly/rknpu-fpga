#!/usr/bin/env python3
"""Host-drivable AXI-Lite pooling endpoint replay.

Eight modes: full job, incomplete descriptor, wrong amount, premature
acknowledge, read-only writes, submit-while-active, two sequential jobs, and
memory-not-ready. Modes 0, 5 and 6 compare the complete 4096-byte output BO
against the frozen device capture.
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

ROOT = Path(__file__).resolve().parents[2]
RUNNER = Path(__file__).resolve()
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_axi.sv'
RTL = [
    ROOT / 'rtl/ppu/rk_ppu_pool_int_k2s2.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_i8_k2s2_profile.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_i8_k2s2_dma.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_axi.sv',
]
CASE = 'int8_max_k2s2_valid_c16_h2w2'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
WORDS = 26
MODES = {
    0: {'starts': 1, 'transactions': 144, 'output_writes': 8, 'kind': 'bo'},
    1: {'starts': 0, 'transactions': 0, 'output_writes': 0, 'kind': 'reject'},
    2: {'starts': 1, 'transactions': 0, 'output_writes': 0, 'kind': 'reject'},
    3: {'starts': 0, 'transactions': 0, 'output_writes': 0, 'kind': 'reject'},
    4: {'starts': 0, 'transactions': 0, 'output_writes': 0, 'kind': 'reject'},
    5: {'starts': 1, 'transactions': 144, 'output_writes': 8, 'kind': 'bo'},
    6: {'starts': 2, 'transactions': 288, 'output_writes': 16, 'kind': 'bo'},
    7: {'starts': 0, 'transactions': 0, 'output_writes': 0, 'kind': 'reject'},
}
PASS_RE = re.compile(
    r'^PASS PPU_POOL_AXI mode=(\d+) starts=(\d+) transactions=(\d+) '
    r'output_writes=(\d+)$')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tool_version(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=30)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def load() -> tuple[dict, bytes]:
    manifest = json.loads((FIXTURE / 'manifest.json').read_text())
    if manifest['case'] != CASE:
        raise ValueError('fixture identity mismatch')
    for name, record in manifest['files'].items():
        path = FIXTURE / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'fixture file changed: {name}')
    raw = bytearray((FIXTURE / 'regcmd.bin').read_bytes())
    capture = json.loads((FIXTURE / 'capture.json').read_text())
    for patch in capture['patches']:
        offset = patch['regcmd_index'] * 8
        raw[offset + 2:offset + 6] = patch['dma_address'].to_bytes(4, 'little')
    if len(raw) != WORDS * 8:
        raise ValueError('command stream is not 26 QWORDs')
    return manifest, bytes(raw)


def write_hex(patched: bytes, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    # The bench loads command bytes, so the file is one byte per line.
    (directory / 'commands.hex').write_text(
        ''.join(f'{value:02x}\n' for value in patched))
    for source, target in (('in.bin', 'input.hex'),
                           ('out_init.bin', 'out_init.hex'),
                           ('device_out.bin', 'expected.hex')):
        (directory / target).write_text(
            ''.join(f'{value:02x}\n' for value in (FIXTURE / source).read_bytes()))


def run_mode(simulator: str, mode: int, outdir: Path, keep_build: bool) -> dict:
    manifest, patched = load()
    outdir.mkdir(parents=True)
    hexdir = outdir / 'fixture-hex'
    write_hex(patched, hexdir)
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    binary = outdir / ('sim.vvp' if simulator == 'iverilog' else 'obj_dir')
    if simulator == 'iverilog':
        argv = [compiler, '-g2012', '-Irtl', '-Itests', '-s', 'tb_ppu_pool_axi',
                f'-Ptb_ppu_pool_axi.MODE={mode}', '-o', str(binary),
                *[str(p) for p in RTL], str(TB)]
        prefix = [runtime, str(binary)]
    else:
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps', '-Irtl', '-Itests',
                f'-GMODE={mode}', '--top-module', 'tb_ppu_pool_axi',
                '--Mdir', str(binary), '-o', 'sim',
                *[str(p) for p in RTL], str(TB)]
        prefix = [str(binary / 'sim')]
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': CASE, 'mode': mode,
        'simulator': simulator, 'python_version': platform.python_version(),
        'fixture_manifest': str((FIXTURE / 'manifest.json').relative_to(ROOT)),
        'patched_command_sha256': hashlib.sha256(patched).hexdigest(),
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'source_hashes_before': {str(p.relative_to(ROOT)): sha(p)
                                 for p in [*RTL, TB, RUNNER]},
    }
    try:
        result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                                check=False, timeout=900)
        text = result.stdout + result.stderr
        (outdir / 'compile.log').write_text(text)
        if result.returncode or re.search(r'%Error', text):
            raise RuntimeError(f'compile failed: {text[-4000:]}')
        report['tool_version'] = tool_version(
            [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V'])
        result = subprocess.run(prefix + [f'+FIXTURE={hexdir}'], cwd=ROOT,
                                text=True, capture_output=True, check=False,
                                timeout=900)
        output = result.stdout + result.stderr
        (outdir / 'run.log').write_text(output)
        matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                   if line.startswith('PASS PPU_POOL_AXI')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'mode {mode} failed: {output[-4000:]}')
        counts = tuple(int(matches[0].group(i)) for i in range(1, 5))
        expected = MODES[mode]
        if counts[0] != mode or counts[1] != expected['starts']:
            raise RuntimeError(f'mode {mode} contract differs: {counts}')
        if (counts[2], counts[3]) != (expected['transactions'],
                                      expected['output_writes']):
            raise RuntimeError(f'mode {mode} traffic differs: {counts}')
        hashes_after = {name: sha(ROOT / name)
                        for name in report['source_hashes_before']}
        if hashes_after != report['source_hashes_before']:
            raise RuntimeError('RTL or fixture changed during the run')
        report.update(status='PASS', finished_utc=utc_now(),
                      counts=dict(mode=counts[0], starts=counts[1],
                                  transactions=counts[2],
                                  output_writes=counts[3]),
                      source_hashes_after=hashes_after)
    except Exception as exc:
        report.update(status='FAIL', failure=str(exc))
        raise
    finally:
        if not keep_build:
            if binary.is_dir():
                shutil.rmtree(binary)
            else:
                binary.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                       sort_keys=True) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    failures = 0
    for simulator in simulators:
        base = ROOT / 'build/ppu-pool-axi' / f'{simulator}-{stamp}'
        ok = True
        for mode in MODES:
            try:
                run_mode(simulator, mode, base / f'mode-{mode}', args.keep_build)
            except Exception as exc:
                print(f'FAIL pooling endpoint mode {mode} {simulator}: {exc}',
                      file=sys.stderr)
                failures += 1
                ok = False
                break
        if ok:
            print(f'ALL {len(MODES)} modes PASS: pooling endpoint {simulator}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
