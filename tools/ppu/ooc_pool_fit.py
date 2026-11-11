#!/usr/bin/env python3
"""SECONDARY per-page OOC fit estimate for the pooling-corpus image.

Why this exists: a whole-image synthesis of the 19-page image takes longer than
this heat-marginal host can sustain at one core (the host guard's sustained-heat
rule stops it), so the exact whole-image number is deferred. This tool measures
small, one-to-two-minute out-of-context synthesis runs instead:

  * five representative pages (CASE 0/3/7/14/16) covering the page RTL plus the
    three leaf shapes (FP16 16-atom, FP16 global-average, FP16 max-with-index +
    adapter, INT8 average k3x3, INT8 max k2s2);
  * one infra synth of the real build top `ypcb_ppu_corpus_jtag_top` with
    `-generic N_PAGES=1`, i.e. mailbox + 32 KiB BRAM + AXI front-end + arbiter
    + exactly one page.

The reported whole-image figure is an ESTIMATE, never a measured whole-image
number:

    estimate = LUT(infra + 1 page) + 18 * mean(sampled page LUTs)

with the min/max sample spread reported so the uncertainty is explicit. The
shared BRAM count and the page-identity RTL are fully exercised by the
simulation matrix; only the area is sampled here.

Every run is a plain Vivado batch synthesis: no implementation, no bitstream,
no hardware access. `general.maxThreads 1` keeps the thermal ramp gentle and
does not change synthesis results. The caller serialises runs through
build/verif/host_guard/safe_run.sh.
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
SPEC = ROOT / 'fpga/ppu/corpus_sources.json'
OOC_TOP = ROOT / 'fpga/ppu/ooc_pool_page_top.sv'
IMAGE_TOP = ROOT / 'fpga/ypcb_ppu_corpus_top.sv'
WRAPPER = ROOT / 'fpga/ypcb_ppu_corpus_jtag_top.sv'
PART = 'xc7k480tffg1156-2'
CONFIGS = {
    'page0': {'kind': 'page', 'case': 0,
              'label': 'FP16 global-average leaf, 15 input atoms'},
    'page3': {'kind': 'page', 'case': 3,
              'label': 'FP16 average k2s1 4x4 leaf, 16 input atoms'},
    'page7': {'kind': 'page', 'case': 7,
              'label': 'FP16 max-with-index leaf + serialising adapter'},
    'page14': {'kind': 'page', 'case': 14,
               'label': 'INT8 average-q16 k3x3 leaf, 9 input atoms'},
    'page16': {'kind': 'page', 'case': 16,
               'label': 'INT8 max k2s2 leaf (int_k2s2 core)'},
    'infra1': {'kind': 'infra',
               'label': 'build top + mailbox + BRAM + arbiter + 1 page'},
}
PAGE_SAMPLES = ('page0', 'page3', 'page7', 'page14', 'page16')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tcl_path(path: Path) -> str:
    value = str(path)
    if any(char in value for char in '{}\\\n\r'):
        raise ValueError(f'unsupported Tcl path characters: {value}')
    return '{' + value + '}'


def load_spec() -> dict:
    spec = json.loads(SPEC.read_text())
    for name in spec['sources'] + [spec['constraints'], spec['cdc']]:
        if not (ROOT / name).is_file():
            raise ValueError(f'missing corpus source: {name}')
    return spec


def sources_for(spec: dict, config: dict) -> list[Path]:
    if config['kind'] == 'page':
        names = [name for name in spec['sources']
                 if name not in ('fpga/ypcb_ppu_corpus_top.sv',
                                 'fpga/ypcb_ppu_corpus_jtag_top.sv')]
        return [ROOT / name for name in names] + [OOC_TOP]
    return [ROOT / name for name in spec['sources']]


def render(spec: dict, name: str, config: dict, out: Path) -> tuple[str, str]:
    sources = sources_for(spec, config)
    lines = [
        '# Rendered by tools/ppu/ooc_pool_fit.py (SECONDARY area estimate).',
        '# Synthesis only: no implementation, no bitstream, no hardware.',
        f'set out {tcl_path(out)}',
        f'create_project -in_memory -part {PART}',
        f'set_property include_dirs [list {tcl_path(ROOT / "rtl")} '
        f'{tcl_path(ROOT / "rtl/ppu")} {tcl_path(ROOT / "rtl/vendor/nvidia")} '
        f'{tcl_path(ROOT / "rtl/vendor/opentpu")}] [current_fileset]',
        'set_property verilog_define {DESIGNWARE_NOEXIST} [current_fileset]',
    ]
    lines += [f'read_verilog -sv {tcl_path(path)}' for path in sources]
    lines += [
        '# Lab-only build-tool setting: one thread, gentle thermal ramp, and',
        '# does not change synthesis utilisation results.',
        'set_param general.maxThreads 1',
    ]
    if config['kind'] == 'page':
        lines.append(f'synth_design -top ooc_pool_page_top -part {PART} '
                     f'-generic CASE={config["case"]}')
        top = 'ooc_pool_page_top'
    else:
        lines.append(f'synth_design -top ypcb_ppu_corpus_jtag_top -part {PART} '
                     f'-generic LED_ACTIVE_LOW=0 -generic N_PAGES=1')
        top = 'ypcb_ppu_corpus_jtag_top'
    lines += [
        'report_utilization -file [file join $out utilization_synth.rpt]',
        'puts "LAB_DONE"',
    ]
    script = out / 'synth.tcl'
    script.write_text('\n'.join(lines) + '\n')
    return str(script), top


def parse(out: Path) -> dict:
    report = out / 'utilization_synth.rpt'
    if not report.is_file():
        raise ValueError('missing synthesis utilisation report')
    text = report.read_text()
    def grab(pattern: str):
        match = re.search(pattern, text)
        return int(match.group(1)) if match else None
    bram = re.search(r'\| Block RAM Tile\s*\|\s*([0-9.]+)', text)
    return {
        'slice_luts_synth': grab(r'\| Slice LUTs\*?\s*\|\s*(\d+)'),
        'slice_registers_synth': grab(r'\| Slice Registers\s*\|\s*(\d+)'),
        'block_ram_tiles_synth': float(bram.group(1)) if bram else 0.0,
    }


def run_config(name: str, spec: dict, out: Path, vivado: str) -> dict:
    config = CONFIGS[name]
    if out.exists():
        raise ValueError(f'output already exists: {out}')
    out.mkdir(parents=True, exist_ok=False)
    script, top = render(spec, name, config, out)
    sources = sources_for(spec, config)
    record = {
        'schema': 1, 'config': name, 'kind': config['kind'],
        'label': config['label'], 'top': top,
        'generic_case': config.get('case'),
        'part': PART, 'status': 'RUNNING',
        'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'run_parameters': {
            'general_maxThreads': 1,
            'wrapper': 'build/verif/host_guard/safe_run.sh',
            'note': 'SECONDARY per-page OOC area estimate; thread count does '
                    'not change synthesis utilisation results.',
        },
        'source_hashes': {str(path.relative_to(ROOT)): sha(path)
                          for path in sources},
    }
    (out / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    argv = [vivado, '-mode', 'batch', '-source', script,
            '-log', str(out / 'vivado.log'), '-journal', str(out / 'vivado.jou')]
    started = time.monotonic()
    result = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, check=False)
    (out / 'vivado-stdout.log').write_text(result.stdout)
    record['returncode'] = result.returncode
    record['seconds'] = round(time.monotonic() - started, 3)
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    failed = result.returncode != 0
    if failed:
        record['failure'] = result.stdout[-4000:]
    else:
        try:
            record.update(parse(out))
            if record.get('slice_luts_synth') is None:
                failed = True
                record['failure'] = 'could not read Slice LUTs from report'
        except ValueError as error:
            failed = True
            record['failure'] = str(error)
    record['status'] = 'FAIL' if failed else 'PASS'
    (out / 'inputs.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(f'{record["status"]} {name}: luts={record.get("slice_luts_synth")} '
          f'regs={record.get("slice_registers_synth")} '
          f'bram_tiles={record.get("block_ram_tiles_synth")} '
          f'seconds={record.get("seconds")}')
    return record


def summarise(root: Path) -> dict:
    records = {}
    for name in CONFIGS:
        path = root / name / 'inputs.json'
        if not path.is_file():
            raise ValueError(f'missing sample: {path}')
        record = json.loads(path.read_text())
        if record.get('status') != 'PASS':
            raise ValueError(f'sample {name} is not a PASS: {record.get("status")}')
        records[name] = record
    page_luts = [records[name]['slice_luts_synth'] for name in PAGE_SAMPLES]
    mean_page = sum(page_luts) / len(page_luts)
    infra = records['infra1']['slice_luts_synth']
    estimate = infra + 18 * mean_page
    spread = (max(page_luts), min(page_luts))
    summary = {
        'kind': 'SECONDARY_ESTIMATE_NOT_A_MEASURED_WHOLE_IMAGE_NUMBER',
        'formula': 'LUT(infra + 1 page) + 18 * mean(sampled page LUTs)',
        'samples': {name: {
            'case': records[name].get('generic_case'),
            'label': records[name]['label'],
            'slice_luts_synth': records[name]['slice_luts_synth'],
            'slice_registers_synth': records[name]['slice_registers_synth'],
            'block_ram_tiles_synth': records[name]['block_ram_tiles_synth'],
            'seconds': records[name].get('seconds'),
        } for name in CONFIGS},
        'page_sample_luts': page_luts,
        'page_sample_mean_luts': round(mean_page, 1),
        'page_sample_spread_luts': {'max': spread[0], 'min': spread[1]},
        'infra_plus_one_page_luts': infra,
        'infra_plus_one_page_bram_tiles': records['infra1']['block_ram_tiles_synth'],
        'estimated_whole_image_luts': round(estimate),
        'estimated_whole_image_luts_low': round(infra + 18 * spread[1]),
        'estimated_whole_image_luts_high': round(infra + 18 * spread[0]),
        'device_slice_luts': 298600,
        'estimated_utilisation_pct': round(100.0 * estimate / 298600, 2),
        'pages': 19,
        'caveat': ('Per-page OOC synthesis does not model cross-page sharing or '
                   'top-level placement; this is an area ESTIMATE for the '
                   'merged-image decision, not a measured whole-image number. '
                   'The exact whole-image synth is deferred for thermal reasons.'),
    }
    (root / 'fit_estimate.json').write_text(json.dumps(summary, indent=2,
                                                       sort_keys=True) + '\n')
    print(json.dumps({key: summary[key] for key in
                      ('page_sample_luts', 'page_sample_mean_luts',
                       'infra_plus_one_page_luts', 'estimated_whole_image_luts',
                       'estimated_whole_image_luts_low',
                       'estimated_whole_image_luts_high',
                       'estimated_utilisation_pct')}, indent=1))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'summary'))
    parser.add_argument('--config', action='append', choices=tuple(CONFIGS),
                        default=None)
    parser.add_argument('--root', type=Path,
                        default=ROOT / 'build/pooling-image/ooc-fit')
    parser.add_argument('--vivado', default=shutil.which('vivado') or 'vivado')
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_relative_to(ROOT / 'build'):
        parser.exit(2, 'root must be below build/\n')
    try:
        if args.action == 'summary':
            summarise(root)
            return 0
        spec = load_spec()
        configs = args.config or ['page0']
        for name in configs:
            run_config(name, spec, root / name, args.vivado)
        return 0
    except ValueError as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
