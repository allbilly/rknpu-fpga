#!/usr/bin/env python3
"""Characterize YPCB placement/routing with openXC7; NEVER emit a bitstream.

This does not replace the electrical, setup/hold and DRC gates in build.tcl.
The pinned nextpnr backend lacks complete timing/signoff coverage. No option
in this runner relaxes a clock target, routing error or timing failure.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

from evidence import ROOT, fingerprint, source_revision, timestamp

PART = 'xc7k480tffg1156-2'
NEXTPNR_REV = 'd486d8ef6a1c756ca72b2ba495e7e18e4c24815d'
XRAY_REV = '1768fb35d68468eac2f4319ff66d0c27863267b6'
META_REV = 'a4af910cac907f2cbd3a545f26f8e26573e860de'
PINS = {'SYS_CLK': 'AA28', 'SYS_RSTN': 'R28', 'led_3bits_tri_o[0]': 'P30',
        'led_3bits_tri_o[1]': 'M30', 'led_3bits_tri_o[2]': 'N30'}
EXCEPTIONS = ('set_false_path -from [get_ports SYS_RSTN]',
              'set_false_path -to [get_ports {led_3bits_tri_o[*]}]')
SIGNOFF_GAPS = [
    'No hold analysis in the pinned nextpnr backend.',
    'BRAM and registered DSP ports lack complete timing models; FF timing uses constants.',
    'Generic family timing data does not establish all speed-grade -2 corners.',
    'Vivado DRC coverage is not reproduced by nextpnr placement/routing checks.',
    'Physical board supply/CFGBVS confirmation and configuration validation are outstanding.',
    'External reset/LED false paths are recorded but not implemented by this XDC parser.',
]


def normalized_xdc(source: str) -> tuple[str, list[str]]:
    """Accept only the reviewed board profile, without evaluating arbitrary Tcl.

    Expand grouped I/O selectors to literal ports. Explicitly account for the
    two external-only exceptions; never delete/ignore an unknown constraint.
    Neither exception is an internal datapath timing exception.
    """
    lines = [' '.join(line.split('#', 1)[0].split()) for line in source.splitlines()]
    lines = [line for line in lines if line]
    pin_lines = [f'set_property PACKAGE_PIN {pin} [get_ports ' +
                 (port if '[' not in port else '{' + port + '}') + ']' for port, pin in PINS.items()]
    group = 'set_property IOSTANDARD LVCMOS18 [get_ports {SYS_CLK SYS_RSTN led_3bits_tri_o[*]}]'
    clock = 'create_clock -name sys_clk -period 20.000 [get_ports SYS_CLK]'
    expected = pin_lines + [group, clock, *EXCEPTIONS]
    if Counter(lines) != Counter(expected):
        raise ValueError('XDC differs from the reviewed profile: ' +
                         repr({'unexpected': list((Counter(lines) - Counter(expected)).elements()),
                               'missing': list((Counter(expected) - Counter(lines)).elements())}))
    expanded = pin_lines + ['set_property IOSTANDARD LVCMOS18 [get_ports {' + port + '}]' for port in PINS]
    return '\n'.join(expanded + [clock]) + '\n', list(EXCEPTIONS)


def package_pins(source: str) -> dict:
    rows = list(csv.DictReader(io.StringIO(source)))
    found = {}
    for port, pin in PINS.items():
        selected = [row for row in rows if row['pin'] == pin]
        if len(selected) != 1:
            raise ValueError(f'Package pin {pin} missing or duplicated')
        row = selected[0]
        bank = '14' if port == 'SYS_CLK' else '15'
        if row['bank'] != bank or not row['site'].startswith('IOB_') or not row['tile'].startswith('LIOB33_'):
            raise ValueError(f'Unexpected physical I/O site for {port}: {row}')
        if port == 'SYS_CLK' and 'MRCC' not in row['pin_function']:
            raise ValueError('SYS_CLK is not on the expected MRCC pin')
        found[port] = row
    return found


def check_timing_report(report: dict) -> dict:
    clocks = report.get('fmax', {})
    if set(clocks) != {'SYS_CLK'}:
        raise ValueError(f'Expected one constrained SYS_CLK domain, got {list(clocks)}')
    clock = clocks['SYS_CLK']
    achieved, constraint = clock.get('achieved'), clock.get('constraint')
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (achieved, constraint)):
        raise ValueError('Missing, nonpositive or nonfinite clock result')
    if constraint != 50.0 or achieved < constraint:
        raise ValueError(f'50 MHz target was changed or failed: {clock}')
    return clock


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pinned_checkout(path: Path, expected: str) -> dict:
    actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain'], text=True).strip()
    if actual != expected or dirty:
        raise ValueError(f'Expected clean checkout {expected} at {path}; got {actual}, status={dirty!r}')
    return {'path': str(path), 'commit': actual}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    base = ROOT / 'build/openxc7'
    parser.add_argument('--nextpnr', type=Path, default=base / 'nextpnr-build/nextpnr-xilinx')
    parser.add_argument('--checkout', type=Path, default=ROOT / 'build/reference/nextpnr-xilinx')
    parser.add_argument('--chipdb', type=Path, default=base / (PART + '.bin'))
    parser.add_argument('--seed', type=int, default=3588)
    parser.add_argument('--out', type=Path, default=base / 'runs' / time.strftime('%Y%m%dT%H%M%S', time.gmtime()))
    args = parser.parse_args()
    if not 1 <= args.seed <= 0xffffffff:
        parser.error('seed must be a positive uint32')
    if os.environ.get('RK_EMIT_BITSTREAM', '0') != '0':
        parser.error('This characterization runner cannot emit a bitstream; signoff is incomplete')
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / 'build') or out == ROOT / 'build':
        parser.error('output must be a new directory below this project build/')
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'RUNNING', 'scope': 'OpenXC7 placement/routing characterization ONLY',
              'started_utc': timestamp(), 'source_revision': source_revision(), 'part': PART, 'seed': args.seed,
              'bitstream_emitted': False, 'hardware_programmed': False,
              'signoff': 'NOT_ESTABLISHED', 'signoff_gaps': SIGNOFF_GAPS, 'commands': []}

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, name, timeout=1800):
        log = out / (name + '.log')
        step = {'argv': [str(a) for a in argv], 'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with log.open('w') as stream:
                result = subprocess.run(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            step.update(returncode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL')
            output = log.read_text()
            step['warnings'] = [line for line in output.splitlines() if 'warning' in line.lower()]
            if result.returncode:
                raise RuntimeError(f'{name} failed ({result.returncode}); see {log}')
            return output
        except subprocess.TimeoutExpired:
            step['status'] = 'TIMEOUT'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    try:
        checkout = args.checkout.resolve()
        database = checkout / 'xilinx/external/prjxray-db'
        metadata = checkout / 'xilinx/external/nextpnr-xilinx-meta'
        report['tool_sources'] = [pinned_checkout(checkout, NEXTPNR_REV), pinned_checkout(database, XRAY_REV),
                                  pinned_checkout(metadata, META_REV)]
        report['package_pins'] = package_pins((database / 'kintex7' / PART / 'package_pins.csv').read_text())
        normalized, exceptions = normalized_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        xdc = out / 'ypcb.literal.xdc'
        xdc.write_text(normalized)
        report['external_exceptions_not_applied'] = exceptions
        report['inputs'] = {str(p): digest(p) for p in (args.nextpnr, args.chipdb, Path(__file__).resolve(),
                                                      database / 'kintex7' / PART / 'package_pins.csv')}
        report['nextpnr_version'] = run([args.nextpnr, '--version'], 'nextpnr_version').strip()
        yosys = shutil.which('yosys')
        if yosys is None:
            raise RuntimeError('Yosys unavailable')
        report['yosys_version'] = run([yosys, '-V'], 'yosys_version').strip()
        sources = [ROOT / 'rtl' / (name + '.sv') for name in
                   ('rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_dma', 'rk_bram',
                    'rk_demo_memory', 'rk_dma_demo_rom', 'rk_ew_dma_demo')] + [ROOT / 'fpga/ypcb_top.sv']
        design = out / 'synth.json'
        synthesis = ('read_verilog -sv ' + ' '.join(json.dumps(str(p)) for p in sources) +
                     '; hierarchy -check -top ypcb_top; proc; opt_clean; check -assert; ' +
                     'synth_xilinx -family xc7 -top ypcb_top -flatten; check -assert; write_json ' + json.dumps(str(design)))
        run([yosys, '-Q', '-T', '-p', synthesis], 'synthesis')
        module = json.loads(design.read_text())['modules']['ypcb_top']
        ports = {name: (value['direction'], len(value['bits'])) for name, value in module['ports'].items()}
        if ports != {'SYS_CLK': ('input', 1), 'SYS_RSTN': ('input', 1), 'led_3bits_tri_o': ('output', 3)}:
            raise ValueError(f'Unexpected top-level ports: {ports}')
        counts = Counter(cell['type'] for cell in module['cells'].values())
        if not counts['RAMB18E1'] + counts['RAMB36E1'] or any(k.startswith('$') and k != '$scopeinfo' for k in counts):
            raise ValueError('Missing block RAM or unmapped synthesis cells')
        report['synthesis_cells'] = dict(counts)
        report_path = out / 'pnr.json'
        log = run([args.nextpnr, '--chipdb', args.chipdb, '--json', design, '--xdc', xdc,
                   '--freq', '50', '--seed', str(args.seed), '--verbose', '--report', report_path,
                   '--write', out / 'routed.json'], 'place_route', timeout=7200)
        if any(message in log.lower() for message in ('ignored', 'not supported', 'not applied', 'matched nothing')):
            raise ValueError('nextpnr ignored an input or constraint; inspect the complete place_route.log')
        report['estimated_clock_only'] = check_timing_report(json.loads(report_path.read_text()))
        if source_revision() != report['source_revision']:
            raise RuntimeError('Production sources changed during characterization')
        if any(digest(Path(path)) != sha for path, sha in report['inputs'].items()):
            raise RuntimeError('Tool, database or runner input changed during characterization')
        report.update(status='PNR_CHARACTERIZED_NOT_SIGNOFF', finished_utc=timestamp())
        returncode = 0
    except Exception as exc:
        report.update(status='FAIL', reason=str(exc), finished_utc=timestamp())
        returncode = 1
    report['artifacts'] = fingerprint([p for p in out.iterdir() if p.is_file() and p.name != 'report.json'])
    save()
    print(json.dumps({key: report[key] for key in ('status', 'signoff', 'part', 'bitstream_emitted')}, indent=2))
    if 'reason' in report:
        print(report['reason'])
    print(out / 'report.json')
    return returncode


if __name__ == '__main__':
    raise SystemExit(main())
