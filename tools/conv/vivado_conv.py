#!/usr/bin/env python3
"""Render or run the source-gated conv board image. Never programs.

The explicit profile lives in ``fpga/conv/sources.json``; this tool refuses a
profile whose part, clock, top, generated ROM or source list differs, then:

* ``render`` writes a fresh ``build.tcl`` from the template (no Vivado),
* ``run`` re-validates and launches full Vivado batch synthesis/implementation.

No hardware is opened and no bitstream is emitted unless
``RK_EMIT_BITSTREAM=1`` is passed through, which the Tcl itself requires a
board-verified ``CONFIG_VOLTAGE``/``CFGBVS`` pair for.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / 'fpga/conv/sources.json'
TEMPLATE = ROOT / 'fpga/conv/build_conv.tcl.in'
PART = 'xc7k480tffg1156-2'
TOP = 'ypcb_conv_simple_top'
CLOCK_NS = 20
CONSTRAINTS = 'fpga/ypcb_conv_simple.xdc'
ROM = 'rtl/cmac/rk_conv_simple_demo_rom.sv'
ROM_FIXTURE = 'tests/conv/fixtures/conv_simple_fp16_3x3_c4_h8_w8_oc16'
GEN = 'tools/conv/gen_conv_demo.py'
BITSTREAM = 'rk_conv_simple.bit'


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
        raise ValueError('Conv profile top/part changed')
    if spec.get('clock_period_ns') != CLOCK_NS:
        raise ValueError('Conv profile must keep the 50 MHz clock')
    if spec.get('constraints') != CONSTRAINTS:
        raise ValueError('Conv constraints changed')
    sources = spec.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('Conv profile has no sources')
    if len(sources) != len(set(sources)):
        raise ValueError('Conv profile lists a source twice')
    for name in sources + [spec['constraints']]:
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f'Missing or unsafe conv input: {name}')
    generated = spec.get('generated', [])
    if len(generated) != 1 or generated[0]['path'] != ROM:
        raise ValueError('Conv profile must bind exactly its generated ROM')
    if generated[0]['fixture'] != ROM_FIXTURE:
        raise ValueError('Generated conv ROM fixture binding changed')
    return spec


def verify_generated(spec: dict) -> None:
    generator = ROOT / spec['generated'][0]['generator']
    if not generator.is_file():
        raise ValueError('Missing conv ROM generator')
    result = subprocess.run([sys.executable, str(generator), '--check'], cwd=ROOT,
                            text=True, capture_output=True, check=False, timeout=120)
    if result.returncode:
        raise ValueError(f'Generated conv ROM is stale: {result.stdout}{result.stderr}')


def inputs(spec: dict) -> list[Path]:
    fixture = ROOT / spec['generated'][0]['fixture']
    return ([ROOT / name for name in spec['sources'] + [spec['constraints']]] +
            [SPEC, TEMPLATE, Path(__file__).resolve(), ROOT / GEN,
             ROOT / 'rtl/vendor/nvdla/compat/nv_assert_never.v',
             ROOT / 'rtl/vendor/nvdla/compat/nv_assert_no_x.v',
             ROOT / 'rtl/vendor/nvdla/NV_DW_lsd.v',
             ROOT / 'rtl/vendor/nvdla/NV_DW02_tree.v',
             ROOT / 'rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v',
             ROOT / 'rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',
             ROOT / 'rtl/vendor/nvdla/HLS_fp32_to_fp16.v',
             fixture / 'manifest.json', fixture / 'regcmd.bin',
             fixture / 'input.bin', fixture / 'weight.bin',
             fixture / 'device_out.bin', ROOT / 'tests/conv_simple_demo_fixture.json',
             ROOT / spec['benches']['board']])


def render(spec: dict, out: Path) -> str:
    sources = '\n'.join('read_verilog -sv ' + tcl_path(ROOT / name)
                        for name in spec['sources'])
    text = TEMPLATE.read_text()
    replacements = {
        '@ROOT@': tcl_path(ROOT), '@OUT@': tcl_path(out),
        '@PART@': PART, '@TOP@': TOP, '@BITSTREAM@': BITSTREAM,
        '@CONSTRAINTS@': tcl_path(ROOT / CONSTRAINTS),
        '@READ_SOURCES@': sources,
        '@INCLUDE_DIRS@': ' '.join(tcl_path(ROOT / n) for n in ('rtl', 'rtl/vendor/nvdla')),
    }
    allowed = {'@PART@': 2}
    for token, value in replacements.items():
        if text.count(token) != allowed.get(token, 1):
            raise ValueError(f'Unexpected template token count: {token}')
        text = text.replace(token, value)
    if re.search(r'@[A-Z_]+@', text):
        raise ValueError('Unexpanded Tcl token remains')
    return text


def parse_reports(directory: Path) -> dict:
    """Extract physical gates from the reports; a missing report fails closed."""
    for name in ('timing.rpt', 'drc.rpt', 'utilization.rpt', 'routed.dcp'):
        if not (directory / name).is_file():
            raise ValueError(f'Missing required implementation report: {name}')
    lines = (directory / 'timing.rpt').read_text().splitlines()
    wns = whs = None
    for index, line in enumerate(lines):
        if line.strip().startswith('WNS(ns)'):
            for row in lines[index + 1:index + 6]:
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
    drc_rows = [line.strip() for line in (directory / 'drc.rpt').read_text().splitlines()
                if re.match(r'^\|\s*[A-Z][A-Z0-9_]+-\d+\s*\|', line)]
    brams = 0
    for line in (directory / 'utilization.rpt').read_text().splitlines():
        if 'RAMB36E1 only' in line:
            brams = int(line.split('|')[2].strip())
    return {'wns_ns': wns, 'whs_ns': whs, 'drc_rows': drc_rows,
            'ramb36e1': brams, 'timing_met': wns >= 0 and whs >= 0}


def report_gate_ok(reports: dict, bitstream: bool) -> bool:
    if not reports.get('timing_met') or reports.get('ramb36e1', 0) < 1:
        return False
    rows = reports.get('drc_rows', [])
    if any('| Error' in row for row in rows):
        return False
    # CFGBVS-1 is only acceptable while no image is emitted.
    if bitstream and any('CFGBVS-1' in row for row in rows):
        return False
    return True


def run_with_vivado(out: Path, vivado: str) -> int:
    spec = load_spec()
    verify_generated(spec)
    if out.exists():
        raise ValueError('Output already exists; preserve earlier evidence')
    out.mkdir(parents=True, exist_ok=False)
    script = out / 'build.tcl'
    script.write_text(render(spec, out / 'implementation'))
    record = {
        'schema': 1, 'status': 'RUNNING', 'profile': spec['profile'],
        'top': TOP, 'part': PART, 'clock_period_ns': CLOCK_NS,
        'bitstream': BITSTREAM,
        'source_hashes': {str(p.relative_to(ROOT)): sha(p) for p in inputs(spec)},
        'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'vivado_executed': False, 'hardware_accessed': False,
        'bitstream_emitted': False,
        'scope': ('First conv RTL image: frozen conv-simple C4 8x8 -> OC16 k3x3 '
                  'capture through the raw 52-QWORD endpoint, parameterised spatial '
                  'front, donor CMAC/CACC arithmetic and FP16 output writer. '
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('render', 'run'))
    parser.add_argument('--out', type=Path)
    parser.add_argument('--vivado', default=shutil.which('vivado') or 'vivado')
    args = parser.parse_args()
    out = (args.out or ROOT / 'build/conv-image' /
           time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())).resolve()
    if not out.is_relative_to(ROOT / 'build'):
        parser.exit(2, 'Output must be below build/\n')
    try:
        if args.action == 'render':
            spec = load_spec()
            verify_generated(spec)
            if out.exists():
                raise ValueError('Output already exists; preserve earlier evidence')
            out.mkdir(parents=True, exist_ok=False)
            script = out / 'build.tcl'
            script.write_text(render(spec, out / 'implementation'))
            (out / 'inputs.json').write_text(json.dumps({
                'schema': 1, 'profile': spec['profile'], 'top': TOP, 'part': PART,
                'clock_period_ns': CLOCK_NS, 'bitstream': BITSTREAM,
                'source_hashes': {str(p.relative_to(ROOT)): sha(p) for p in inputs(spec)},
                'vivado_executed': False, 'hardware_accessed': False,
                'bitstream_emitted': False,
            }, indent=2, sort_keys=True) + '\n')
            print(script)
            return 0
        return run_with_vivado(out, args.vivado)
    except ValueError as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
