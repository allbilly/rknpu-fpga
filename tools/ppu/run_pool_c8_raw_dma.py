#!/usr/bin/env python3
"""Exercise the captured C8 raw profile through owned dispatch and serialized DMA."""
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
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ppu.run_pool_c8_raw_profile import (  # noqa: E402
    CASE, EMITTER_SOURCE, FILE_NAMES, FIXTURE, FATAL_RE, POOL_SOURCE,
    REGISTER_SOURCE, load_contract, sha, sha_bytes, version,
)

RTL = ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv'
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
CONTRACT_RUNNER = ROOT / 'tools/ppu/run_pool_c8_raw_profile.py'
TOP = 'tb_ppu_pool_c8_raw_dma'
ERROR_MODES = {1: 5, 2: 1, 3: 3, 4: 2, 6: 6, 7: 6, 8: 6}
PASS_RE = re.compile(r'^PASS ppu_c8_raw_dma mode=(?P<mode>\d+) (?P<details>.*)$')


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def save_report(outdir: Path, report: dict) -> None:
    (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def run_logged(name: str, argv: list[str], outdir: Path, report: dict, timeout: int) -> str:
    log = outdir / f'{name}.log'
    row = {'name': name, 'argv': [str(arg) for arg in argv],
           'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(row)
    save_report(outdir, report)
    started = time.monotonic()
    with log.open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, check=False, timeout=timeout)
    text = log.read_text()
    fatals = [line for line in text.splitlines() if FATAL_RE.search(line)]
    row.update(status='PASS' if result.returncode == 0 and not fatals else 'FAIL',
               returncode=result.returncode, seconds=round(time.monotonic()-started, 3),
               fatal_lines=fatals, log_sha256=sha(log),
               warnings=[line for line in text.splitlines()
                         if line.startswith('%Warning') or 'warning:' in line.lower()])
    save_report(outdir, report)
    if result.returncode or fatals:
        raise RuntimeError(f'{name} failed (exit={result.returncode}, fatal={len(fatals)}):\n{text[-6000:]}')
    return text


def run_simulator(simulator: str, outdir: Path, keep_build: bool, fixture_data: tuple) -> dict:
    compiler = shutil.which(simulator)
    if not compiler or (simulator == 'iverilog' and not shutil.which('vvp')):
        raise RuntimeError(f'{simulator} or its runtime is unavailable')
    manifest, _job, capture, raw, patched = fixture_data
    outdir.mkdir(parents=True, exist_ok=False)
    patched_path = outdir / 'patched_regcmd.bin'
    patched_path.write_bytes(patched)
    paths = [RTL, PROFILE_C3_RTL, PROFILE_C8_RTL, PROFILE_PAD1_RTL, PROFILE_MIN_RTL, PROFILE_AVG_RTL, PROFILE_INDEX_RTL, PROFILE_GLOBAL_RTL,
             POOL_C3_RTL, POOL_C8_RTL, POOL_PAD1_RTL, POOL_MIN_RTL, POOL_AVG_RTL, POOL_INDEX_RTL, POOL_GLOBAL_RTL, POOL_GLOBAL_AVG_RTL,
             DISPATCH_RTL, LAYOUT_RTL, TB, RUNNER, CONTRACT_RUNNER,
             POOL_SOURCE, REGISTER_SOURCE, EMITTER_SOURCE]
    paths += [FIXTURE / name for name in FILE_NAMES]
    hashes_before = {str(path): sha(path) for path in paths}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                              capture_output=True, check=True).stdout.strip()
    status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'], cwd=ROOT,
                            text=True, capture_output=True, check=True).stdout.splitlines()
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'case': CASE,
        'simulator': simulator, 'source_revision': revision,
        'source_worktree_status': status,
        'seed_policy': 'not applicable: deterministic captured input and scheduled serialized memory responses',
        'scope': 'Owned UI-dispatch PPU kind 3; exact C8 raw profile, serialized memory DMA, capture-bounded pooling leaf; EW/CMAC isolated, memory simulated.',
        'hardware_accessed': False, 'vivado_executed': False, 'bitstream_emitted': False,
        'source_hashes_before': hashes_before,
        'fixture': {'manifest': str((FIXTURE/'manifest.json').relative_to(ROOT)),
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
            'subnormal': {'mode': 7, 'expected_code': 6},
            'negative_zero': {'mode': 8, 'expected_code': 6},
            'writes_before_full_input_validation': 0},
        'commands': [], 'runs': [],
    }
    save_report(outdir, report)
    build_path: Path | None = None
    try:
        if simulator == 'iverilog':
            binary = outdir / 'tb.vvp'
            build_path = binary
            run_logged('compile', [compiler, '-g2012', '-Wall', '-s', TOP, '-o', str(binary),
                                    str(LAYOUT_RTL), str(PROFILE_C3_RTL), str(PROFILE_C8_RTL),
                                     str(PROFILE_PAD1_RTL), str(PROFILE_MIN_RTL), str(PROFILE_AVG_RTL), str(PROFILE_INDEX_RTL), str(PROFILE_GLOBAL_RTL), str(PROFILE_GLOBAL_AVG_RTL),
                                    str(POOL_C3_RTL), str(POOL_C8_RTL), str(POOL_PAD1_RTL),
                                     str(POOL_MIN_RTL), str(POOL_AVG_RTL), str(POOL_INDEX_RTL), str(POOL_GLOBAL_RTL), str(POOL_GLOBAL_AVG_RTL), str(RTL),
                                   str(DISPATCH_RTL), str(TB)], outdir, report, 600)
            run_prefix = [shutil.which('vvp'), str(binary)]
            report['tool_version'] = version([compiler, '-V'])
            report['runtime_version'] = version([shutil.which('vvp'), '-V'])
        else:
            mdir = outdir / 'obj'
            build_path = mdir
            run_logged('compile', [compiler, '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                                   '--top-module', TOP, '--Mdir', str(mdir), '-o', 'sim',
                                    str(LAYOUT_RTL), str(PROFILE_C3_RTL), str(PROFILE_C8_RTL),
                                     str(PROFILE_PAD1_RTL), str(PROFILE_MIN_RTL), str(PROFILE_AVG_RTL), str(PROFILE_INDEX_RTL), str(PROFILE_GLOBAL_RTL), str(PROFILE_GLOBAL_AVG_RTL),
                                    str(POOL_C3_RTL), str(POOL_C8_RTL), str(POOL_PAD1_RTL),
                                     str(POOL_MIN_RTL), str(POOL_AVG_RTL), str(POOL_INDEX_RTL), str(POOL_GLOBAL_RTL), str(POOL_GLOBAL_AVG_RTL), str(RTL),
                                   str(DISPATCH_RTL), str(TB)], outdir, report, 600)
            run_prefix = [str(mdir / 'sim')]
            report['tool_version'] = version([compiler, '--version'])
        report['python_version'] = platform.python_version()
        save_report(outdir, report)

        for mode in range(9):
            expected_error = ERROR_MODES.get(mode, 0)
            text = run_logged(f'mode-{mode}', run_prefix +
                              [f'+COMMAND_BIN={patched_path}', f'+INPUT_BIN={FIXTURE/"in.bin"}',
                               f'+OUTPUT_INIT_BIN={FIXTURE/"out_init.bin"}',
                               f'+EXPECTED_BIN={FIXTURE/"device_out.bin"}',
                               f'+MODE={mode}', f'+EXPECT_ERROR={expected_error}'],
                              outdir, report, 180)
            markers = [match for line in text.splitlines()
                       if (match := PASS_RE.match(line))]
            if len(markers) != 1 or int(markers[0].group('mode')) != mode:
                raise RuntimeError(f'mode {mode} missing unique C8 PASS marker')
            details = markers[0].group('details')
            if mode == 0 and details != (
                    'transactions=304 command_reads=104 input_reads=128 '
                    'output_writes=72 complete_output_bytes=4096'):
                raise RuntimeError(f'C8 full run traffic/result differs: {details}')
            if mode == 5 and details != (
                    'error_code=0 transactions=608 command_reads=208 input_reads=256 '
                    'output_writes=144 complete_output_bytes=4096 repeated_jobs=2'):
                raise RuntimeError(f'C8 repeat-job traffic/result differs: {details}')
            expected_domain_traffic = {
                6: 'error_code=6 transactions=105 responses=105 output_writes=0',
                7: 'error_code=6 transactions=205 responses=205 output_writes=0',
                8: 'error_code=6 transactions=232 responses=232 output_writes=0',
            }
            if mode in expected_domain_traffic and details != expected_domain_traffic[mode]:
                raise RuntimeError(f'C8 domain rejection traffic differs: {details}')
            if mode not in (0, 5) and f'error_code={expected_error}' not in details:
                raise RuntimeError(f'mode {mode} error code differs: {details}')
            report['runs'].append({'mode': mode,
                                   'result': ('PASS_COMPLETE_BO' if mode == 0 else
                                              'PASS_REPEAT_JOB_COMPLETE_BO' if mode == 5 else
                                              'PASS_REJECT'),
                                   'error_code': expected_error, 'details': details})
            save_report(outdir, report)

        hashes_after = {str(path): sha(path) for path in paths}
        if hashes_before != hashes_after:
            raise RuntimeError('C8 RTL, runner, or fixture changed during simulation')
        report['source_hashes_after'] = hashes_after
        report['status'] = 'PASS'
        report['finished_utc'] = utc_now()
        report['summary'] = {'raw_command_qwords_fetched': 26,
             'separate_strict_profiles': ['C3', 'C8-valid', 'C8-pad1'],
                             'only_job_address_relocations_applied': True,
                             'valid_serial_transactions': 304,
                             'full_output_bo_compared': True,
                             'repeat_job_transactions': 608,
                             'negative_controls': 7,
                             'input_special_value_controls': 3,
                             'hardware_accessed': False}
    except Exception as exc:
        report['status'] = 'FAIL'
        report['failure'] = str(exc)
        report['finished_utc'] = utc_now()
        raise
    finally:
        if not keep_build and build_path is not None:
            if build_path.is_dir():
                shutil.rmtree(build_path)
            else:
                build_path.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        save_report(outdir, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    try:
        fixture_data = load_contract()
    except Exception as exc:
        print(f'CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for simulator in simulators:
        outdir = ROOT / 'build/ppu-pooling' / f'c8-raw-dma-{simulator}-{stamp}'
        try:
            run_simulator(simulator, outdir, args.keep_build, fixture_data)
        except Exception as exc:
            print(f'FAIL C8 raw DMA {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS C8 raw DMA {simulator}: 304 transactions/job, same-epoch repeat job, '
              f'complete 4096-byte output BO, 7 negative controls; report={outdir/"report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
