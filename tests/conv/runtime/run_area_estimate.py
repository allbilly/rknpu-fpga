#!/usr/bin/env python3
"""Synth-only area estimate for the runtime-decoded conv engine prototype.

Runs an out-of-context Vivado synthesis of `rk_conv_runtime_core` (no
opt/place/route, no bitstream, no hardware) and records a source-hash-bound
receipt with the utilization breakdown under `build/runtime-conv-lab/area/`.

The runtime engine has no geometry parameters: all geometry is decoded from the
command stream and the operand stores are sized for the corpus maxima, so one
OOC synthesis is the complete area estimate. The comparison against the adopted
per-profile page costs is written into the receipt (`fit_comparison`).

Launch through the host guard (required; the runner refuses to launch Vivado
unguarded):

    BENCH_MIN_BATTERY=30 BENCH_CPUS=4-7 BENCH_CPU_QUOTA=200 \
      build/verif/host_guard/safe_run.sh \
      python3 tests/conv/runtime/run_area_estimate.py
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
TCL = HERE / 'synth_runtime_core.tcl'
OUT_ROOT = ROOT / 'build/runtime-conv-lab/area'
GUARD = ROOT / 'build/verif/host_guard/safe_run.sh'
VIVADO = Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')

SOURCES = [
    'rtl/vendor/nvdla/compat/nv_assert_never.v',
    'rtl/vendor/nvdla/compat/nv_assert_no_x.v',
    'rtl/vendor/nvdla/NV_DW_lsd.v',
    'rtl/vendor/nvdla/NV_DW02_tree.v',
    'rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',
    'rtl/vendor/nvdla/HLS_fp32_to_fp16.v',
    'rtl/cmac/rk_cmac_fp16_cell.sv',
    'rtl/cmac/rk_cmac_fp16_array.sv',
    'rtl/cmac/rk_nvdla_cacc.sv',
    'rtl/cmac/rk_cacc_fp16_array.sv',
    'rtl/cmac/rk_cmac_cacc_fp16_array.sv',
    'rtl/cmac/rk_nvdla_fp32_to_fp16.sv',
    'rtl/cmac/rk_cmac_writer.sv',
    'rtl/cmac/rk_cmac_output_nvdla.sv',
    'rtl/cmac/rk_cmac_frame_output.sv',
    'rtl/cmac/rk_cmac_rw_arbiter.sv',
    'rtl/cmac/rk_conv_output_atom.sv',
    'rtl/cmac/rk_cmac_fp32_writer.sv',
    'rtl/cmac/rk_frame_stage.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_decode.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_front.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_fp32_output.sv',
    'rtl/cmac/experimental/runtime/rk_conv_runtime_core.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_sdp_bram.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_frame_stage.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_fp16_cell.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_fp16_array.sv',
    'rtl/cmac/experimental/runtime/rk_runtime_cacc_fp16_array.sv',
    'tests/conv/runtime/synth_runtime_core.tcl',
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_metric(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1).replace(',', '')) if match else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep-dcp', action='store_true')
    args = parser.parse_args(argv)
    if 'BENCH_MIN_BATTERY' not in os.environ:
        print('refused: launch through '
              f'`BENCH_MIN_BATTERY=30 BENCH_CPUS=4-7 BENCH_CPU_QUOTA=200 '
              f'{GUARD} python3 {Path(__file__).relative_to(ROOT)}`',
              file=sys.stderr)
        return 2
    if not VIVADO.exists():
        print(f'Vivado not found at {VIVADO}', file=sys.stderr)
        return 2
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outdir = OUT_ROOT / f'ooc-{stamp}'
    outdir.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / name for name in SOURCES]
    hashes_before = {name: sha(ROOT / name) for name in SOURCES}
    version = subprocess.run([str(VIVADO), '-version'], text=True,
                             capture_output=True, check=True)
    command = [str(VIVADO), '-mode', 'batch', '-notrace', '-nojournal',
               '-nolog', '-source', str(TCL), '-tclargs', str(outdir)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=7200)
    (outdir / 'vivado.log').write_text(result.stdout + result.stderr)
    hashes_after = {name: sha(ROOT / name) for name in SOURCES}
    util = outdir / 'utilization.rpt'
    text = util.read_text() if util.exists() else ''
    report = {
        'status': 'RUNNING', 'started_utc': datetime.now(timezone.utc).isoformat(),
        'tested': 'runtime-decoded conv engine OOC synthesis (area only)',
        'tool_version': (version.stdout + version.stderr).strip().splitlines()[0],
        'part': 'xc7k480tffg1156-2',
        'mode': 'out_of_context synthesis; no opt/place/route, no bitstream',
        'hardware_accessed': False, 'bitstream_emitted': False,
        'returncode': result.returncode,
        'source_hashes_before': hashes_before,
        'source_hashes_after': hashes_after,
        'source_match': hashes_before == hashes_after,
        'utilization_rpt': str(util.relative_to(ROOT)) if util.exists() else None,
        'metrics': {
            'slice_luts': report_metric(text, r'Slice LUTs\*?\s*\|\s*(\d+)'),
            'slice_registers': report_metric(
                text, r'Slice Registers\s*\|\s*(\d+)'),
            'block_ram_tiles': report_metric(
                text, r'Block RAM Tile\s*\|\s*([\d.]+)'),
            'dsp48e1': report_metric(text, r'DSP48E1\s*\|\s*(\d+)'),
            'slices': report_metric(text, r'\|\s*Slices\s*\|\s*(\d+)'),
        },
        'fit_comparison': {
            'measured_per_page_costs_from_task': {
                'conv_c4_page_luts': 39800,
                'conv_c16_page_luts': 100300,
                'six_page_image_luts': 231316,
                'six_page_image_slice_occupancy_pct': 94.35,
            },
            'replacement_target': (
                'one runtime engine replaces the four per-profile conv pages '
                '(conv p0 C4, k5 C4, C16, FP32 C4); the C16 page alone is '
                '~100.3k LUTs'),
            'd1_note': (
                'D1 area covers the explicit simple-dual-port BRAM mapping of '
                'the two operand stores (input_store 163840 bits = 16 x 10240, '
                'weight_store 73728 bits = 16 x 4608; '
                'rtl/cmac/experimental/runtime/rk_runtime_sdp_bram.sv under '
                '`ifdef SYNTHESIS), because Vivado 2026.1 cannot infer block '
                'RAM for the prototype plain-array pattern in OOC synthesis. '
                'Geometry and registered-read semantics are identical to the '
                'simulated arrays; the simulation RTL path is unchanged, so '
                'the accepted Leg A/B receipts stand for the simulation path. '
                'S1 page integration will adopt the explicit memory mapping '
                'and re-run equivalence so the synthesized design matches '
                'simulation.'),
        },
    }
    if result.returncode == 0 and 'RUNTIME_OOC_SYNTH_DONE' in (
            result.stdout + result.stderr):
        report['status'] = 'PASS'
    else:
        report['status'] = 'FAIL'
        report['failure'] = (result.stdout + result.stderr)[-4000:]
    if not args.keep_dcp:
        dcp = outdir / 'runtime_conv_core_ooc.dcp'
        if dcp.exists():
            dcp.unlink()
        report['dcp_pruned'] = True
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    (outdir / 'report.json').write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n')
    metrics = report['metrics']
    print(f'{report["status"]} runtime OOC synth: '
          f'LUTs={metrics["slice_luts"]} regs={metrics["slice_registers"]} '
          f'BRAM tiles={metrics["block_ram_tiles"]} DSP={metrics["dsp48e1"]} '
          f'-> {outdir / "report.json"}')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
