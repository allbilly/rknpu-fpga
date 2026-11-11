#!/usr/bin/env python3
"""Exercise captured C8 minimum commands through the owned serialized DMA."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ppu.run_pool_c8_raw_dma import run_logged, save_report  # noqa: E402
from tools.ppu.run_pool_min_raw_profile import (  # noqa: E402
    CASE, FILE_NAMES, load_contract, now, sha, sha_bytes,
)
from tools.ppu.run_pool_pad1_raw_profile import (  # noqa: E402
    EMITTER_SOURCE, FATAL_RE, POOL_SOURCE, REGISTER_SOURCE, tool_version,
)
import re  # noqa: E402

DMA_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv'
PROFILE_C3_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_c3_raw_profile.sv'
PROFILE_C8_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_c8_raw_profile.sv'
PROFILE_PAD1_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_pad1_raw_profile.sv'
PROFILE_MIN_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_min_raw_profile.sv'
PROFILE_AVG_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_avg_raw_profile.sv'
PROFILE_INDEX_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_index_raw_profile.sv'
PROFILE_GLOBAL_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_global_raw_profile.sv'
PROFILE_GLOBAL_AVG_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_global_avg_raw_profile.sv'
POOL_C3_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s2_c3_tail_h2w2.sv'
POOL_C8_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s1_c8.sv'
POOL_PAD1_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2.sv'
POOL_MIN_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_min2x2s1_fp16_capture.sv'
POOL_AVG_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_avg2x2s1_fp16_capture.sv'
POOL_INDEX_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_max2x2s2_index_c8_h2w2.sv'
POOL_GLOBAL_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_max16x16s16_c8.sv'
POOL_GLOBAL_AVG_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_avg_global3x5_c8_fp16_capture.sv'
DISPATCH_RTL = ROOT / 'rtl/ddr/framework_factored/rk_layout_compute_dispatch_ppu.sv'
LAYOUT_RTL = ROOT / 'rtl/ddr/framework_factored/rk_layout_dma.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_c8_raw_dma.sv'
RUNNER = Path(__file__).resolve()
CONTRACT_RUNNER = ROOT / 'tools/ppu/run_pool_min_raw_profile.py'
TOP = 'tb_ppu_pool_c8_raw_dma'
ERROR_MODES = {1: 5, 2: 1, 3: 3, 4: 2, 6: 6, 7: 6, 8: 6, 9: 6, 10: 6,
               11: 2, 12: 2}
PASS_RE = re.compile(r'^PASS ppu_c8_raw_dma mode=(?P<mode>\d+) (?P<details>.*)$')


def run_simulator(simulator: str, outdir: Path, keep_build: bool, fixture: tuple) -> dict:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} or its runtime is unavailable')
    manifest, _job, capture, raw, patched = fixture
    outdir.mkdir(parents=True, exist_ok=False)
    patched_path = outdir / 'patched_regcmd.bin'
    patched_path.write_bytes(patched)
    sources = [LAYOUT_RTL, PROFILE_C3_RTL, PROFILE_C8_RTL, PROFILE_PAD1_RTL,
               PROFILE_MIN_RTL, PROFILE_AVG_RTL, PROFILE_INDEX_RTL, PROFILE_GLOBAL_RTL, PROFILE_GLOBAL_AVG_RTL, POOL_C3_RTL, POOL_C8_RTL, POOL_PAD1_RTL,
               POOL_MIN_RTL, POOL_AVG_RTL, POOL_INDEX_RTL, POOL_GLOBAL_RTL, POOL_GLOBAL_AVG_RTL, DMA_RTL, DISPATCH_RTL, TB, RUNNER, CONTRACT_RUNNER,
               ROOT/'tools/ppu/run_pool_min.py',
               ROOT/'tools/ppu/run_pool_pad1_raw_profile.py',
               POOL_SOURCE, REGISTER_SOURCE, EMITTER_SOURCE]
    sources += [ROOT / 'tests/ppu_pooling/fixtures' / CASE / name for name in FILE_NAMES]
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
        'seed_policy': 'not applicable: deterministic captured input and scheduled serialized responses',
        'scope': 'Owned kind-3 dispatch; strict captured minimum profile, serialized 16-bit DMA and minimum leaf; simulated memory and isolated EW/CMAC.',
        'hardware_accessed': False, 'vivado_executed': False, 'bitstream_emitted': False,
        'fixture': {'manifest': str((ROOT/'tests/ppu_pooling/fixtures'/CASE/'manifest.json').relative_to(ROOT)),
                    'raw_command_sha256': sha_bytes(raw),
                    'patched_command_sha256': sha_bytes(patched),
                    'patched_command': str(patched_path.relative_to(ROOT)),
                    'captured_device_output_sha256': manifest['comparison']['device_output_sha256'],
                    'source_base': capture['addresses']['buffers']['in'],
                    'destination_base': capture['addresses']['buffers']['out'],
                    'input_bo_bytes': manifest['layout']['input']['buffer_bytes'],
                    'output_bo_bytes': manifest['layout']['output']['buffer_bytes']},
        'expected_traffic': {'command_halfword_reads': 104, 'input_halfword_reads': 128,
                             'output_halfword_writes': 72, 'total_serial_transactions': 304,
                             'complete_output_bo_bytes_compared': 4096},
        'repeat_job_traffic': {'command_halfword_reads': 208, 'input_halfword_reads': 256,
                               'output_halfword_writes': 144, 'total_serial_transactions': 608,
                               'complete_output_bo_bytes_compared': 4096},
        'input_domain_negative_controls': {
            'positive_infinity': {'mode': 6, 'expected_code': 6},
            'negative_infinity': {'mode': 7, 'expected_code': 6},
            'negative_zero': {'mode': 8, 'expected_code': 6},
            'positive_subnormal': {'mode': 9, 'expected_code': 6},
            'negative_subnormal': {'mode': 10, 'expected_code': 6},
            'writes_before_full_input_validation': 0},
        'commands': [], 'runs': [],
    }
    save_report(outdir, report)
    build: Path | None = None
    try:
        hdl = [LAYOUT_RTL, PROFILE_C3_RTL, PROFILE_C8_RTL, PROFILE_PAD1_RTL,
                PROFILE_MIN_RTL, PROFILE_AVG_RTL, PROFILE_INDEX_RTL, PROFILE_GLOBAL_RTL, PROFILE_GLOBAL_AVG_RTL, POOL_C3_RTL, POOL_C8_RTL, POOL_PAD1_RTL,
                POOL_MIN_RTL, POOL_AVG_RTL, POOL_INDEX_RTL, POOL_GLOBAL_RTL, POOL_GLOBAL_AVG_RTL, DMA_RTL, DISPATCH_RTL, TB]
        if simulator == 'iverilog':
            build = outdir/'tb.vvp'
            run_logged('compile', [compiler, '-g2012', '-Wall', '-s', TOP, '-o', str(build),
                                   *map(str, hdl)], outdir, report, 600)
            prefix = [runtime, str(build)]
        else:
            build = outdir/'obj'
            run_logged('compile', [compiler, '--binary', '--timing', '--assert', '-Wall',
                                   '-j', '2', '--top-module', TOP, '--Mdir', str(build),
                                   '-o', 'sim', *map(str, hdl)], outdir, report, 600)
            prefix = [str(build/'sim')]
        report['python_version'] = platform.python_version()
        save_report(outdir, report)

        for mode in range(13):
            expected_error = ERROR_MODES.get(mode, 0)
            output = run_logged(f'mode-{mode}', prefix +
                                [f'+COMMAND_BIN={patched_path}',
                                 f'+INPUT_BIN={ROOT/"tests/ppu_pooling/fixtures"/CASE/"in.bin"}',
                                 f'+OUTPUT_INIT_BIN={ROOT/"tests/ppu_pooling/fixtures"/CASE/"out_init.bin"}',
                                 f'+EXPECTED_BIN={ROOT/"tests/ppu_pooling/fixtures"/CASE/"device_out.bin"}',
                                 '+MIN_CASE=1', f'+MODE={mode}',
                                 f'+EXPECT_ERROR={expected_error}'], outdir, report, 180)
            markers = [match for line in output.splitlines()
                       if (match := PASS_RE.match(line))]
            if len(markers) != 1 or int(markers[0].group('mode')) != mode:
                raise RuntimeError(f'mode {mode} did not emit one unique minimum-DMA PASS marker')
            details = markers[0].group('details')
            if mode == 0 and details != (
                    'transactions=304 command_reads=104 input_reads=128 output_writes=72 '
                    'complete_output_bytes=4096 minimum_profile=1'):
                raise RuntimeError(f'minimum full-run traffic/result differs: {details}')
            if mode == 5 and details != (
                    'error_code=0 transactions=608 command_reads=208 input_reads=256 '
                    'output_writes=144 complete_output_bytes=4096 repeated_jobs=2'):
                raise RuntimeError(f'minimum repeat-job traffic/result differs: {details}')
            if mode in (6, 7, 9, 10) and details != (
                    'error_code=6 transactions=105 responses=105 output_writes=0'):
                raise RuntimeError(f'minimum invalid input was not rejected before writes: {details}')
            if mode == 8 and details != (
                    'error_code=6 transactions=232 responses=232 output_writes=0'):
                raise RuntimeError(f'late negative-zero input was not rejected before writes: {details}')
            if mode not in (0, 5) and f'error_code={expected_error}' not in details:
                raise RuntimeError(f'mode {mode} returned wrong error code: {details}')
            report['runs'].append({'mode': mode,
                                   'result': ('PASS_COMPLETE_BO' if mode == 0 else
                                              'PASS_REPEAT_JOB_COMPLETE_BO' if mode == 5 else
                                              'PASS_REJECT'),
                                   'error_code': expected_error, 'details': details})
            save_report(outdir, report)

        after = {str(path): sha(path) for path in sources}
        if before != after:
            raise RuntimeError('minimum DMA RTL, runner or fixture changed during simulation')
        report.update(status='PASS', finished_utc=now(), source_hashes_after=after,
                      summary={'raw_command_qwords_fetched': 26,
                               'separate_strict_profiles': ['C3', 'C8-valid', 'C8-pad1', 'C8-min'],
                               'only_job_address_relocations_applied': True,
                               'valid_serial_transactions': 304,
                               'full_output_bo_compared': True,
                               'repeat_job_transactions': 608,
                               'negative_controls': len(ERROR_MODES),
                               'input_domain_controls': 5, 'hardware_accessed': False})
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
        outdir = ROOT/'build/ppu-pooling'/f'min-raw-dma-{simulator}-{stamp}'
        try:
            run_simulator(simulator, outdir, args.keep_build, fixture)
        except Exception as exc:
            print(f'FAIL minimum raw DMA {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS minimum raw DMA {simulator}: 304 transactions/job, same-epoch repeat, '
              f'complete 4096-byte output BO, {len(ERROR_MODES)} negative controls; '
              f'report={outdir/"report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
