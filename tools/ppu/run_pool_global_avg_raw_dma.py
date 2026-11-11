#!/usr/bin/env python3
"""Replay the captured C8 global-average raw command through owned DMA."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ppu.run_pool_avg_global3x5 import (  # noqa: E402
    CASE, DONOR, FILES, FIXTURE, MANIFEST, load_contract, now, sha,
    sha_bytes, tool_version,
)
from tools.ppu.run_pool_c8_raw_dma import run_logged, save_report  # noqa: E402

LAYOUT_RTL = ROOT / 'rtl/ddr/framework_factored/rk_layout_dma.sv'
DISPATCH_RTL = ROOT / 'rtl/ddr/framework_factored/rk_layout_compute_dispatch_ppu.sv'
DMA_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv'
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
PASS_RE = re.compile(r'^PASS ppu_c8_raw_dma mode=(?P<mode>\d+) (?P<details>.*)$')
ERROR_MODES = {2: 6, 3: 6, 4: 6, 5: 6, 6: 2, 7: 3, 8: 3}


def run_simulator(simulator: str, outdir: Path, keep_build: bool,
                  fixture: tuple[dict, dict, bytes]) -> dict:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    manifest, job, patched = fixture
    outdir.mkdir(parents=True, exist_ok=False)
    patched_path = outdir / 'captured_patched_regcmd.bin'
    patched_path.write_bytes(patched)
    sources = [LAYOUT_RTL, DISPATCH_RTL, DMA_RTL, *PROFILE_RTLS, *LEAF_RTLS,
               TB, RUNNER, DONOR, MANIFEST]
    sources += [FIXTURE / name for name in FILES]
    before = {str(path): sha(path) for path in sources}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'],
                            cwd=ROOT, text=True, capture_output=True,
                            check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': now(), 'case': CASE,
        'simulator': simulator, 'source_revision': revision,
        'source_worktree_status': status,
        'tool_version': tool_version([compiler, '--version'] if simulator == 'verilator'
                                     else [compiler, '-V']),
        'runtime_version': tool_version([runtime, '-V']) if runtime else None,
        'python_version': platform.python_version(),
        'scope': 'Owned kind-3 dispatch, strict captured 28-QWORD profile, serialized input/output DMA, fixed H3/W5 C8 average leaf; simulated memory only.',
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False,
        'seed_policy': 'deterministic capture with fixed serialized response schedule; testbench seed=0x72667555',
        'fixture': {'raw_command_sha256': sha(FIXTURE / 'regcmd.bin'),
                    'patched_command_sha256': sha_bytes(patched),
                    'captured_device_output_sha256': manifest['comparison']['device_output_sha256'],
                    'input_base': 0x1000, 'output_base': 0x2000,
                    'relocations': [15, 22], 'input_bo_bytes': 4096,
                    'output_bo_bytes': 4096},
        'expected_traffic_per_job': {'command_halfword_reads': 112,
                                     'input_halfword_reads': 120,
                                     'output_halfword_writes': 8,
                                     'total_serial_transactions': 240,
                                     'complete_output_bo_bytes_compared': 4096},
        'repeat_job_traffic': {'command_halfword_reads': 224,
                               'input_halfword_reads': 240,
                               'output_halfword_writes': 16,
                               'total_serial_transactions': 480},
        'negative_controls': {
            'positive_infinity': {'mode': 2, 'expected_code': 6},
            'late_negative_zero': {'mode': 3, 'expected_code': 6},
            'positive_out_of_range': {'mode': 4, 'expected_code': 6},
            'positive_subnormal': {'mode': 5, 'expected_code': 6},
            'mutated_fixed_register': {'mode': 6, 'expected_code': 2},
            'unaligned_output_address': {'mode': 7, 'expected_code': 3},
            'overlapping_output_address': {'mode': 8, 'expected_code': 3},
            'output_writes_on_rejection': 0},
        'source_hashes_before': before, 'commands': [], 'runs': [],
    }
    save_report(outdir, report)
    build: Path | None = None
    try:
        hdl = [LAYOUT_RTL, DISPATCH_RTL, *PROFILE_RTLS, *LEAF_RTLS, DMA_RTL, TB]
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
        for mode in range(9):
            expected_error = ERROR_MODES.get(mode, 0)
            output = run_logged(f'mode-{mode}', prefix + [
                f'+COMMAND_BIN={patched_path}', f'+INPUT_BIN={FIXTURE / "in.bin"}',
                f'+OUTPUT_INIT_BIN={FIXTURE / "out_init.bin"}',
                f'+EXPECTED_BIN={FIXTURE / "device_out.bin"}',
                '+GLOBAL_AVG_CASE=1', f'+MODE={mode}',
                f'+EXPECT_ERROR={expected_error}',
            ], outdir, report, 180)
            markers = [match for line in output.splitlines()
                       if (match := PASS_RE.match(line))]
            if len(markers) != 1 or int(markers[0].group('mode')) != mode:
                raise RuntimeError(f'mode {mode} emitted no unique global-average DMA PASS marker')
            details = markers[0].group('details')
            if mode == 0:
                wanted = ('transactions=240 command_reads=112 input_reads=120 '
                          'output_writes=8 complete_output_bytes=4096 global_avg_profile=1')
            elif mode == 1:
                wanted = ('error_code=0 transactions=480 command_reads=224 input_reads=240 '
                          'output_writes=16 complete_output_bytes=4096 repeated_jobs=2 global_avg_profile=1')
            else:
                count = 232 if mode == 3 else 113 if mode in (2, 4, 5) else 112
                wanted = (f'error_code={expected_error} transactions={count} '
                          f'responses={count} output_writes=0')
            if details != wanted:
                raise RuntimeError(f'mode {mode} traffic/rejection differs: {details!r} != {wanted!r}')
            report['runs'].append({'mode': mode, 'expected_error': expected_error,
                                   'details': details, 'status': 'PASS'})
            save_report(outdir, report)
        after = {str(path): sha(path) for path in sources}
        if before != after:
            raise RuntimeError('global-average DMA source or fixture changed during simulation')
        report.update(status='PASS', finished_utc=now(), source_hashes_after=after,
                      summary={'command_qwords': 28, 'relocatable_qwords': [15, 22],
                               'transactions_per_job': 240,
                               'same_epoch_repeat_transactions': 480,
                               'whole_output_bo_compared': True,
                               'negative_controls': len(ERROR_MODES),
                               'input_domain_controls': 4,
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
        outdir = ROOT / 'build/ppu-pooling' / f'global-average-raw-dma-{simulator}-{stamp}'
        try:
            run_simulator(simulator, outdir, args.keep_build, fixture)
        except Exception as exc:
            print(f'FAIL global-average raw DMA {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS captured global-average raw DMA {simulator}: 240 transactions/job, '
              f'whole 4096-byte BO, repeat and {len(ERROR_MODES)} negative controls; '
              f'report={outdir / "report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
