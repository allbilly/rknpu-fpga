#!/usr/bin/env python3
"""Render or run the source-gated first pooling FPGA image. Never programs.

The explicit profile lives in ``fpga/ppu/sources.json``; this tool refuses a
profile whose part, clock, top or generated-ROM binding differs, then:

* ``render`` writes a fresh ``build.tcl`` from the template (no Vivado),
* ``run`` re-validates and launches full Vivado batch synthesis/implementation.

No hardware is opened and no bitstream is emitted unless ``RK_EMIT_BITSTREAM=1``
is passed through to the Tcl, which itself requires reviewed electrical settings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / 'fpga/ppu/sources.json'
TEMPLATE = ROOT / 'fpga/ppu/build_ppu.tcl.in'
PART = 'xc7k480tffg1156-2'
TOP = 'ypcb_ppu_i8_top'
CLOCK_NS = 20
CONSTRAINTS = 'fpga/ypcb_ppu_i8.xdc'
ROM = 'rtl/ppu/rk_ppu_pool_demo_rom.sv'
ROM_FIXTURE = 'tests/ppu_pooling/fixtures/int8_max_k2s2_valid_c16_h2w2'
BITSTREAM = 'rk_ppu_i8.bit'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tcl_path(path: Path) -> str:
    value = str(path)
    if any(char in value for char in '{}\\\n\r'):
        raise ValueError('Unsupported Tcl path characters')
    return '{' + value + '}'


def load_spec() -> dict:
    spec = json.loads(SPEC.read_text())
    if spec.get('top') != TOP or spec.get('part') != PART:
        raise ValueError('Pooling profile top/part changed')
    if spec.get('clock_period_ns') != CLOCK_NS:
        raise ValueError('Pooling profile must keep the 50 MHz clock')
    if spec.get('constraints') != CONSTRAINTS:
        raise ValueError('Pooling constraints changed')
    sources = spec.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('Pooling profile has no sources')
    for name in sources + [spec['constraints']]:
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Missing or unsafe pooling input: {name}')
    generated = spec.get('generated', [])
    if len(generated) != 1 or generated[0]['path'] != ROM:
        raise ValueError('Pooling profile must bind exactly its generated ROM')
    if generated[0]['fixture'] != ROM_FIXTURE:
        raise ValueError('Generated ROM fixture binding changed')
    return spec


def verify_generated(spec: dict) -> None:
    generator = ROOT / spec['generated'][0]['generator']
    if not generator.is_file():
        raise ValueError('Missing pooling ROM generator')
    result = subprocess.run([sys.executable, str(generator), '--check'], cwd=ROOT,
                            text=True, capture_output=True, check=False, timeout=120)
    if result.returncode:
        raise ValueError(f'Generated pooling ROM is stale: {result.stdout}{result.stderr}')


def inputs(spec: dict) -> list[Path]:
    paths = [ROOT / name for name in spec['sources'] + [spec['constraints']]]
    paths += [SPEC, TEMPLATE, Path(__file__).resolve(),
              ROOT / spec['generated'][0]['generator'],
              ROOT / spec['generated'][0]['fixture'] / 'manifest.json',
              ROOT / spec['generated'][0]['fixture'] / 'regcmd.bin',
              ROOT / spec['generated'][0]['fixture'] / 'in.bin',
              ROOT / spec['generated'][0]['fixture'] / 'out_init.bin',
              ROOT / spec['generated'][0]['fixture'] / 'device_out.bin',
              ROOT / spec['benches']['board']]
    return paths


def render(spec: dict, out: Path) -> str:
    sources = '\n'.join('read_verilog -sv ' + tcl_path(ROOT / name)
                        for name in spec['sources'])
    text = TEMPLATE.read_text()
    replacements = {
        '@ROOT@': tcl_path(ROOT), '@OUT@': tcl_path(out),
        '@PART@': PART, '@TOP@': TOP, '@BITSTREAM@': BITSTREAM,
        '@CONSTRAINTS@': tcl_path(ROOT / CONSTRAINTS),
        '@READ_SOURCES@': sources,
    }
    allowed_counts = {'@PART@': 2}
    for token, value in replacements.items():
        expected = allowed_counts.get(token, 1)
        if text.count(token) != expected:
            raise ValueError(f'Unexpected template token count: {token}')
        text = text.replace(token, value)
    if re.search(r'@[A-Z_]+@', text):
        raise ValueError('Unexpanded Tcl token remains')
    if re.search(r'^\s*(write_bitstream|open_hw\w*|program_hw\w*)\b', text, re.M):
        pass  # write_bitstream is deliberately present but env-gated in the template
    return text


def render_only(out: Path) -> Path:
    spec = load_spec()
    verify_generated(spec)
    if out.exists():
        raise ValueError('Output already exists; preserve earlier evidence')
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'build.tcl'
    script.write_text(render(spec, out / 'implementation'))
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in inputs(spec)}
    (out / 'inputs.json').write_text(json.dumps({
        'schema': 1, 'profile': spec['profile'], 'top': TOP, 'part': PART,
        'clock_period_ns': CLOCK_NS, 'bitstream': BITSTREAM,
        'source_hashes': hashes, 'vivado_executed': False,
        'hardware_accessed': False, 'bitstream_emitted': False,
    }, indent=2, sort_keys=True) + '\n')
    return script


def run_with_vivado(out: Path, vivado: str, jobs: int | None) -> int:
    spec = load_spec()
    verify_generated(spec)
    if out.exists():
        raise ValueError('Output already exists; preserve earlier evidence')
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'build.tcl'
    script.write_text(render(spec, out / 'implementation'))
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in inputs(spec)}
    record = {
        'schema': 1, 'status': 'RUNNING', 'profile': spec['profile'],
        'top': TOP, 'part': PART, 'clock_period_ns': CLOCK_NS,
        'bitstream': BITSTREAM, 'source_hashes': hashes,
        'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'vivado_executed': False, 'hardware_accessed': False,
        'bitstream_emitted': False,
        'scope': ('First pooling RTL image: strict 26-QWORD signed-INT8 descriptor path, '
                  'captured C16 H2W2 max leaf, autonomous ROM self-test. '
                  'Synthesis and implementation only; no board run.'),
        'commands': [],
    }
    (out / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    argv = [vivado, '-mode', 'batch', '-source', str(script),
            '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou')]

    log = out / 'vivado-stdout.log'
    record['commands'].append({'argv': argv, 'log': str(log.relative_to(ROOT)),
                               'status': 'RUNNING'})
    (out / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    started = time.monotonic()
    result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, check=False)
    log.write_text(result.stdout)
    record['commands'][-1].update(
        status='PASS' if result.returncode == 0 else 'FAIL',
        returncode=result.returncode,
        seconds=round(time.monotonic() - started, 3))
    record['vivado_executed'] = True
    record['bitstream_emitted'] = (out / 'implementation' / BITSTREAM).is_file()
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    failed = result.returncode != 0
    if failed:
        record['failure'] = result.stdout[-4000:]
    else:
        try:
            record['reports'] = parse_reports(out / 'implementation')
            if not report_gate_ok(record['reports'], record['bitstream_emitted']):
                failed = True
                record['failure'] = 'Implementation reports failed the physical gate'
        except ValueError as error:
            failed = True
            record['failure'] = str(error)
    record['status'] = 'FAIL' if failed else 'PASS'
    (out / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return 1 if failed else 0


def parse_reports(directory: Path) -> dict:
    """Extract the physical gates from the reports; missing files fail closed."""
    timing = directory / 'timing.rpt'
    drc = directory / 'drc.rpt'
    util = directory / 'utilization.rpt'
    for path in (timing, drc, util, directory / 'routed.dcp'):
        if not path.is_file():
            raise ValueError(f'Missing required implementation report: {path.name}')
    text = timing.read_text().splitlines()
    wns = whs = None
    for index, line in enumerate(text):
        if line.strip().startswith('WNS(ns)'):
            for row in text[index + 1:index + 6]:
                columns = row.split()
                if len(columns) >= 6:
                    try:
                        wns, whs = float(columns[0]), float(columns[4])
                    except ValueError:
                        continue
                    break
            break
    if wns is None or whs is None:
        raise ValueError('Could not read WNS/WHS from timing.rpt')
    import re as _re
    drc_summary = []
    for line in drc.read_text().splitlines():
        # Report rows look like "| RULE-1 | Severity | Description | Checks |".
        if _re.match(r'^\|\s*[A-Z][A-Z0-9_]+-\d+\s*\|', line):
            drc_summary.append(line.strip())
    brams = 0
    for line in util.read_text().splitlines():
        if 'RAMB36E1 only' in line:
            cells = line.split('|')
            brams = int(cells[2].strip())
    return {'wns_ns': wns, 'whs_ns': whs, 'drc_summary': drc_summary,
            'ramb36e1': brams,
            'timing_met': wns >= 0 and whs >= 0}


def report_gate_ok(reports: dict, bitstream_emitted: bool = False) -> bool:
    if not reports.get('timing_met'):
        return False
    if reports.get('ramb36e1', 0) < 1:
        return False
    drc = reports.get('drc_summary', [])
    if any('| Error' in line for line in drc):
        return False
    # CFGBVS-1 means neither CONFIG_VOLTAGE nor CFGBVS was set. A routed
    # checkpoint built without a board-verified pair is reported as such; it is
    # never accepted once a bitstream would be emitted.
    if bitstream_emitted and any('CFGBVS-1' in line for line in drc):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('render', 'run'))
    parser.add_argument('--out', type=Path)
    parser.add_argument('--vivado', default=shutil.which('vivado') or 'vivado')
    parser.add_argument('--jobs', type=int, default=None)
    args = parser.parse_args()
    out = (args.out or ROOT / 'build/ppu-image' /
           time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())).resolve()
    if not out.is_relative_to(ROOT / 'build'):
        parser.exit(2, 'Output must be below build/\n')
    try:
        if args.action == 'render':
            print(render_only(out))
            return 0
        return run_with_vivado(out, args.vivado, args.jobs)
    except ValueError as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
