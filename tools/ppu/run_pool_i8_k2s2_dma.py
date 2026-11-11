#!/usr/bin/env python3
"""Run the strict 26-QWORD signed-INT8 pooling descriptor endpoint.

Modes 0 and 7 compare the complete 4096-byte output BO against the frozen
device capture. Modes 1-6 and 8 are negative controls: launch rejection, raw
profile rejection, address rejection, bus fault and timeout. Every run records
the simulator version, exact source revisions and hashes before/after.
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
RUNNER = Path(__file__).resolve()
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_i8_k2s2_dma.sv'
RTL = [
    ROOT / 'rtl/ppu/rk_ppu_pool_int_k2s2.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_i8_k2s2_profile.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_i8_k2s2_dma.sv',
]
CASE = 'int8_max_k2s2_valid_c16_h2w2'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
TOP = 'tb_ppu_pool_i8_k2s2_dma'
PASS_RE = re.compile(
    r'^PASS ppu_pool_i8_k2s2_dma mode=(\d+) error_code=(\d+) transactions=(\d+) '
    r'command_reads=(\d+) input_reads=(\d+) output_writes=(\d+)$')
MODES = {
    0: {'error': 0, 'transactions': 144, 'command_reads': 104,
        'input_reads': 32, 'output_writes': 8, 'result': 'PASS_COMPLETE_BO'},
    1: {'error': 1, 'transactions': 0, 'command_reads': 0,
        'input_reads': 0, 'output_writes': 0, 'result': 'PASS_REJECT_AMOUNT'},
    2: {'error': 3, 'transactions': 0, 'command_reads': 0,
        'input_reads': 0, 'output_writes': 0, 'result': 'PASS_REJECT_ALIGNMENT'},
    3: {'error': 1, 'transactions': 104, 'command_reads': 104,
        'input_reads': 0, 'output_writes': 0, 'result': 'PASS_REJECT_FIELD'},
    4: {'error': 3, 'transactions': 104, 'command_reads': 104,
        'input_reads': 0, 'output_writes': 0, 'result': 'PASS_REJECT_OVERLAP'},
    5: {'error': 3, 'transactions': 104, 'command_reads': 104,
        'input_reads': 0, 'output_writes': 0, 'result': 'PASS_REJECT_APERTURE'},
    6: {'error': 5, 'transactions': 105, 'command_reads': 104,
        'input_reads': 1, 'output_writes': 0, 'result': 'PASS_BUS_FAULT'},
    7: {'error': 0, 'transactions': 288, 'command_reads': 208,
        'input_reads': 64, 'output_writes': 16, 'result': 'PASS_REPEAT_BO'},
    8: {'error': 8, 'transactions': 0, 'command_reads': 0,
        'input_reads': 0, 'output_writes': 0, 'result': 'PASS_TIMEOUT'},
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def first_line(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=30)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def patched_command() -> bytes:
    # The frozen capture stores the two address fields unpatched. Apply only
    # the declared relocations, exactly as the replay fixtures do.
    raw = bytearray((FIXTURE / 'regcmd.bin').read_bytes())
    for index, value in ((13, 0x10001000), (20, 0x10000200)):
        offset = index * 8
        raw[offset + 2:offset + 6] = value.to_bytes(4, 'little')
    return bytes(raw)


def validate_fixture() -> dict:
    manifest = json.loads((FIXTURE / 'manifest.json').read_text())
    if manifest['case'] != CASE:
        raise SystemExit('fixture identity mismatch')
    if manifest['ppu']['dtype'] != 'int8' or manifest['ppu']['method'] != 'maximum':
        raise SystemExit('fixture is not the captured INT8 maximum task')
    if manifest['ppu']['channels'] != 16 or manifest['ppu']['in_shape'] != [2, 2]:
        raise SystemExit('fixture geometry changed')
    if manifest['command_stream']['qwords'] != 26:
        raise SystemExit('fixture command length changed')
    if manifest['command_stream']['address_relocations'] != [13, 20]:
        raise SystemExit('fixture relocations changed')
    for name, record in manifest['files'].items():
        path = FIXTURE / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise SystemExit(f'fixture file changed: {name}')
    return manifest


def run_mode(simulator: str, outdir: Path, mode: int) -> dict:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    build = outdir / ('sim.vvp' if simulator == 'iverilog' else 'obj_dir')
    if simulator == 'iverilog':
        argv = [compiler, '-g2012', '-Wall',
                f'-P{TOP}.MODE={mode}', f'-P{TOP}.TIMEOUT_CYCLES=2048',
                '-s', TOP, '-o', str(build), *[str(p) for p in RTL], str(TB)]
        prefix = [runtime, str(build)]
    else:
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', f'-GMODE={mode}', '-GTIMEOUT_CYCLES=2048',
                '--top-module', TOP, '--Mdir', str(build), '-o', 'sim',
                *[str(p) for p in RTL], str(TB)]
        prefix = [str(build / 'sim')]
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=600)
    text = result.stdout + result.stderr
    (outdir / f'mode-{mode}-compile.log').write_text(text)
    if result.returncode or re.search(r'%Error|^error:', text, re.M):
        raise RuntimeError(f'mode {mode} compile failed: {text[-4000:]}')
    result = subprocess.run(prefix + [f'+COMMAND_BIN={outdir / "command.bin"}',
                                      f'+INPUT_BIN={FIXTURE / "in.bin"}',
                                      f'+OUTPUT_INIT_BIN={FIXTURE / "out_init.bin"}',
                                      f'+EXPECTED_BIN={FIXTURE / "device_out.bin"}'],
                            cwd=ROOT, text=True, capture_output=True, check=False,
                            timeout=600)
    output = result.stdout + result.stderr
    (outdir / f'mode-{mode}-run.log').write_text(output)
    matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
               if line.startswith('PASS ppu_pool_i8_k2s2_dma')]
    if result.returncode or len(matches) != 1:
        raise RuntimeError(f'mode {mode} run failed: {output[-4000:]}')
    counts = tuple(int(matches[0].group(index)) for index in range(1, 7))
    expected = MODES[mode]
    if counts != (mode, expected['error'], expected['transactions'],
                  expected['command_reads'], expected['input_reads'],
                  expected['output_writes']):
        raise RuntimeError(f'mode {mode} contract differs: {counts}')
    return {'mode': mode, 'result': expected['result'], 'counts': counts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()

    manifest = validate_fixture()
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    paths = [*RTL, TB, RUNNER, FIXTURE / 'manifest.json', FIXTURE / 'regcmd.bin',
             FIXTURE / 'in.bin', FIXTURE / 'out_init.bin', FIXTURE / 'device_out.bin']
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    try:
        for simulator in simulators:
            compiler = shutil.which(simulator)
            if not compiler or (simulator == 'iverilog' and not shutil.which('vvp')):
                raise RuntimeError(f'{simulator} and its runtime are required')
            outdir = (ROOT / 'build/ppu-pool-i8-k2s2-dma' /
                      f'{simulator}-{stamp}-{CASE}')
            outdir.mkdir(parents=True, exist_ok=False)
            command = patched_command()
            (outdir / 'command.bin').write_bytes(command)
            report = {
                'status': 'RUNNING', 'started_utc': utc_now(), 'case': CASE,
                'simulator': simulator, 'source_revision': revision,
                'source_hashes_before': {str(p.relative_to(ROOT)): sha(p) for p in paths},
                'fixture': {'manifest': str((FIXTURE / 'manifest.json').relative_to(ROOT)),
                            'command_sha256': hashlib.sha256(command).hexdigest(),
                            'device_output_sha256': manifest['comparison']['device_output_sha256'],
                            'input_base': 0x10000200,
                            'output_base': 0x10001000},
                'scope': ('Strict 26-QWORD signed-INT8 descriptor endpoint: raw command '
                          'fetch, separate strict profile, serialized 16-bit memory, '
                          'captured 2x2/stride-2 max leaf, complete 4096-byte output BO '
                          'and negative controls. Simulation only; no FPGA execution.'),
                'hardware_accessed': False, 'vivado_executed': False,
                'bitstream_emitted': False, 'modes': [],
            }
            (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                           sort_keys=True) + '\n')
            try:
                report['tool_version'] = first_line(
                    [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V'])
                for mode in MODES:
                    report['modes'].append(run_mode(simulator, outdir, mode))
                    (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                                   sort_keys=True) + '\n')
                after = {str(p.relative_to(ROOT)): sha(p) for p in paths}
                if after != report['source_hashes_before']:
                    raise RuntimeError('RTL, fixture or runner changed during the run')
                report.update(status='PASS', finished_utc=utc_now(),
                              source_hashes_after=after)
            except Exception as exc:
                report.update(status='FAIL', failure=str(exc), finished_utc=utc_now())
                (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                               sort_keys=True) + '\n')
                raise
            if not args.keep_build:
                if (outdir / 'obj_dir').is_dir():
                    shutil.rmtree(outdir / 'obj_dir')
                (outdir / 'sim.vvp').unlink(missing_ok=True)
                report['build_products_pruned'] = True
            (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                           sort_keys=True) + '\n')
            print(f'PASS signed-INT8 descriptor endpoint {simulator}: 9 modes, '
                  f'mode 0 and 7 complete 4096-byte BO; report={outdir / "report.json"}')
    except Exception as exc:
        print(f'FAIL signed-INT8 descriptor endpoint: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
