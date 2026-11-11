#!/usr/bin/env python3
"""Exercise the captured C8 MAX+INDEX profile through the owned raw DMA."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ppu.run_pool_index import (  # noqa: E402
    CASE, FIXTURE, FIXTURE_FILES, now, sha, sha_bytes,
)
from tools.ppu.run_pool_index_raw_profile import (  # noqa: E402
    load_contract,
)
from tools.ppu.run_pool_c8_raw_dma import run_logged, save_report  # noqa: E402
from tools.ppu.run_pool_pad1_raw_profile import (  # noqa: E402
    EMITTER_SOURCE, POOL_SOURCE, REGISTER_SOURCE, tool_version,
)

DMA_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv'
DISPATCH_RTL = ROOT / 'rtl/ddr/framework_factored/rk_layout_compute_dispatch_ppu.sv'
LAYOUT_RTL = ROOT / 'rtl/ddr/framework_factored/rk_layout_dma.sv'
PROFILE_RTLS = [ROOT / f'rtl/ppu/rk_ppu_pool_{name}_raw_profile.sv'
                for name in ('c3', 'c8', 'pad1', 'min', 'avg', 'index', 'global', 'global_avg')]
LEAF_RTLS = [
    ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s2_c3_tail_h2w2.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s1_c8.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_min2x2s1_fp16_capture.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg2x2s1_fp16_capture.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s2_index_c8_h2w2.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_max16x16s16_c8.sv',
    ROOT / 'rtl/ppu/rk_ppu_pool_avg_global3x5_c8_fp16_capture.sv',
]
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_c8_raw_dma.sv'
RUNNER = Path(__file__).resolve()
PROFILE_RUNNER = ROOT / 'tools/ppu/run_pool_index_raw_profile.py'
PASS_RE = re.compile(r'^PASS ppu_c8_raw_dma mode=(?P<mode>\d+) (?P<details>.*)$')
ERROR_MODES = {2: 6, 3: 6, 4: 2}


def run_simulator(simulator: str, outdir: Path, keep_build: bool, fixture: tuple) -> dict:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} or its runtime is unavailable')
    manifest, _job, capture, raw, patched = fixture
    outdir.mkdir(parents=True, exist_ok=False)
    patched_path = outdir / 'patched_regcmd.bin'
    patched_path.write_bytes(patched)
    sources = [LAYOUT_RTL, *PROFILE_RTLS, *LEAF_RTLS, DMA_RTL, DISPATCH_RTL,
               TB, RUNNER, PROFILE_RUNNER, ROOT/'tools/ppu/run_pool_index.py',
               ROOT/'tools/ppu/run_pool_c8_raw_dma.py',
               ROOT/'tools/ppu/run_pool_pad1_raw_profile.py',
               POOL_SOURCE, REGISTER_SOURCE, EMITTER_SOURCE]
    sources += [FIXTURE / name for name in FIXTURE_FILES]
    before = {str(path): sha(path) for path in sources}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'], cwd=ROOT,
                            text=True, capture_output=True, check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': CASE,
        'simulator': simulator, 'source_revision': revision,
        'source_worktree_status': status,
        'tool_version': tool_version([compiler, '--version'] if simulator == 'verilator'
                                     else [compiler, '-V']),
        'runtime_version': tool_version([runtime, '-V']) if runtime else None,
        'python_version': platform.python_version(), 'source_hashes_before': before,
        'seed_policy': 'not applicable: fixed capture and deterministic serialized response schedule',
        'scope': 'Owned kind-3 dispatch; strict 26-QWORD C8 MAX+INDEX profile, serialized DMA and capture-bounded indexed leaf; simulated memory only.',
        'hardware_accessed': False, 'vivado_executed': False, 'bitstream_emitted': False,
        'fixture': {'raw_command_sha256': sha_bytes(raw),
                    'patched_command_sha256': sha_bytes(patched),
                    'patched_command': str(patched_path.relative_to(ROOT)),
                    'captured_device_output_sha256': manifest['comparison']['device_output_sha256'],
                    'source_base': capture['addresses']['buffers']['in'],
                    'destination_base': capture['addresses']['buffers']['out'],
                    'input_bo_bytes': 4096, 'output_bo_bytes': 4096},
        'expected_traffic': {'command_halfword_reads': 104, 'input_halfword_reads': 32,
                             'output_halfword_writes': 16, 'total_serial_transactions': 152,
                             'full_output_bo_compared_bytes': 4096,
                             'value_offset': 0, 'index_offset': 32,
                             'gap_bytes_preserved': 16},
        'repeat_job_traffic': {'command_halfword_reads': 208, 'input_halfword_reads': 64,
                               'output_halfword_writes': 32, 'total_serial_transactions': 304,
                               'full_output_bo_compared_bytes': 4096},
        'negative_controls': {
            'tied_maximum_per_channel': {'mode': 2, 'expected_code': 6},
            'positive_infinity_input': {'mode': 3, 'expected_code': 6},
            'mutated_fixed_command_field': {'mode': 4, 'expected_code': 2},
            'writes_before_all_inputs_and_unique_max_validation': 0},
        'commands': [], 'runs': [],
    }
    save_report(outdir, report)
    build: Path | None = None
    try:
        hdl = [LAYOUT_RTL, *PROFILE_RTLS, *LEAF_RTLS, DMA_RTL, DISPATCH_RTL, TB]
        if simulator == 'iverilog':
            build = outdir / 'tb.vvp'
            run_logged('compile', [compiler, '-g2012', '-Wall', '-s',
                                   'tb_ppu_pool_c8_raw_dma', '-o', str(build),
                                   *map(str, hdl)], outdir, report, 600)
            prefix = [runtime, str(build)]
        else:
            build = outdir / 'obj'
            run_logged('compile', [compiler, '--binary', '--timing', '--assert', '-Wall',
                                   '-j', '2', '--top-module', 'tb_ppu_pool_c8_raw_dma',
                                   '--Mdir', str(build), '-o', 'sim', *map(str, hdl)],
                       outdir, report, 600)
            prefix = [str(build / 'sim')]
        for mode in range(5):
            expected_error = ERROR_MODES.get(mode, 0)
            output = run_logged(f'mode-{mode}', prefix +
                                [f'+COMMAND_BIN={patched_path}',
                                 f'+INPUT_BIN={FIXTURE/"in.bin"}',
                                 f'+OUTPUT_INIT_BIN={FIXTURE/"out_init.bin"}',
                                 f'+EXPECTED_BIN={FIXTURE/"device_out.bin"}',
                                 '+INDEX_CASE=1', f'+MODE={mode}',
                                 f'+EXPECT_ERROR={expected_error}'], outdir, report, 180)
            markers = [match for line in output.splitlines()
                       if (match := PASS_RE.match(line))]
            if len(markers) != 1 or int(markers[0].group('mode')) != mode:
                raise RuntimeError(f'index DMA mode {mode} emitted no unique PASS marker')
            details = markers[0].group('details')
            if mode == 0 and details != (
                    'transactions=152 command_reads=104 input_reads=32 output_writes=16 '
                    'complete_output_bytes=4096 index_profile=1'):
                raise RuntimeError(f'indexed complete-BO result/traffic differs: {details}')
            if mode == 1 and details != (
                    'error_code=0 transactions=304 command_reads=208 input_reads=64 '
                    'output_writes=32 complete_output_bytes=4096 repeated_jobs=2 index_profile=1'):
                raise RuntimeError(f'indexed repeat traffic/result differs: {details}')
            expected_details = {
                2: 'error_code=6 transactions=136 responses=136 output_writes=0',
                3: 'error_code=6 transactions=105 responses=105 output_writes=0',
                4: 'error_code=2 transactions=104 responses=104 output_writes=0',
            }
            if mode in expected_details and details != expected_details[mode]:
                raise RuntimeError(f'indexed negative mode {mode} differs: {details}')
            report['runs'].append({'mode': mode, 'expected_error': expected_error,
                                   'details': details})
            save_report(outdir, report)
        after = {str(path): sha(path) for path in sources}
        if before != after:
            raise RuntimeError('indexed DMA source or fixture changed during simulation')
        report.update(status='PASS', finished_utc=now(), source_hashes_after=after,
                      summary={'raw_command_qwords_fetched': 26,
                               'only_job_address_relocations_applied': True,
                               'valid_serial_transactions': 152,
                               'repeat_job_transactions': 304,
                               'complete_output_bo_compared': True,
                               'value_index_gap_and_tail_preserved': True,
                               'negative_controls': len(ERROR_MODES),
                               'hardware_accessed': False})
    except Exception as exc:
        report.update(status='FAIL', finished_utc=now(), failure=str(exc))
        raise
    finally:
        if not keep_build and build is not None:
            if build.is_dir():
                shutil.rmtree(build)
            else:
                build.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        save_report(outdir, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    try:
        fixture = load_contract()
    except Exception as exc:
        print(f'CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for simulator in simulators:
        outdir = ROOT / 'build/ppu-pooling' / f'index-raw-dma-{simulator}-{stamp}'
        try:
            run_simulator(simulator, outdir, args.keep_build, fixture)
        except Exception as exc:
            print(f'FAIL MAX+INDEX raw DMA {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS MAX+INDEX raw DMA {simulator}: 152 transactions/job, full 4096-byte BO, '
              f'value/index gap preserved, {len(ERROR_MODES)} negative controls; '
              f'report={outdir/"report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
