#!/usr/bin/env python3
"""Replay the donor-emitted 16x16 FP16 C8 MAX profile through owned raw DMA.

The QWORDs and numerical input are generated from the donor's decoded source
case. No raw command or output device capture exists for this candidate.
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

ROOT = Path(__file__).resolve().parents[2]
CASE = 'fp16_max_k16s16_c8_h16w16'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
MANIFEST = FIXTURE / 'manifest.json'
JOB = FIXTURE / 'job.json'
FILES = ('expected.bin', 'in.bin', 'job.json', 'out_init.bin',
         'regcmd.bin', 'regcmd.txt')

DMA_RTL = ROOT / 'rtl/ppu/rk_ppu_pool_raw_dma.sv'
DISPATCH_RTL = ROOT / 'rtl/ddr/framework_factored/rk_layout_compute_dispatch_ppu.sv'
LAYOUT_RTL = ROOT / 'rtl/ddr/framework_factored/rk_layout_dma.sv'
PROFILE_NAMES = ('c3', 'c8', 'pad1', 'min', 'avg', 'index', 'global', 'global_avg')
PROFILE_RTLS = [ROOT / f'rtl/ppu/rk_ppu_pool_{name}_raw_profile.sv'
                for name in PROFILE_NAMES]
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
ERROR_MODES = {2: 6, 3: 6, 4: 2, 5: 6, 6: 3, 7: 3, 8: 6}
PASS_RE = re.compile(r'^PASS ppu_c8_raw_dma mode=(?P<mode>\d+) (?P<details>.*)$')
EXPECTED_WORDS = (
    0x40010000000E6004, 0x80010000000E7004,
    0x40010000000F600C, 0x40010000000F6010, 0x4001000000076014,
    0x4001000000006018, 0x400100000000601C, 0x4001000000076020,
    0x4001000000116024, 0x400100FF0F0F6034,
    0x4001000000006040, 0x4001000000006044, 0x4001000000006048,
    0x4001000000006070, 0x400100000010607C, 0x4001000000126084,
    0x40010000000360DC, 0x80010000000F700C, 0x80010000000F7010,
    0x8001000000077014, 0x800100000000701C, 0x8001000001007024,
    0x8001000010007028, 0x8001000000027030, 0x8001000000017008,
    0x0081000000600008,
)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tool_version(argv: list[str]) -> str:
    result = subprocess.run(argv, text=True, capture_output=True,
                            check=False, timeout=30)
    return (result.stdout or result.stderr).splitlines()[0]


def load_contract() -> tuple[dict, dict, bytes, bytes]:
    manifest = json.loads(MANIFEST.read_text())
    job = json.loads(JOB.read_text())
    if (manifest.get('case'), manifest.get('status')) != (
            CASE, 'SOURCE_DERIVED_SIMULATION_CANDIDATE'):
        raise ValueError('wrong global MAX case or provenance status')
    if manifest.get('device_capture') is not None:
        raise ValueError('a device capture must not be implied for this source-derived fixture')
    if set(manifest.get('files', {})) != set(FILES):
        raise ValueError('global MAX fixture file census differs')
    for name in FILES:
        path = FIXTURE / name
        expected = manifest['files'][name]
        if path.stat().st_size != expected['bytes'] or sha(path) != expected['sha256']:
            raise ValueError(f'fixture hash/size mismatch: {name}')

    raw = (FIXTURE / 'regcmd.bin').read_bytes()
    words = tuple(int.from_bytes(raw[i:i + 8], 'little') for i in range(0, len(raw), 8))
    if len(words) != 26 or words != EXPECTED_WORDS:
        raise ValueError('emitter-derived 26-QWORD stream differs from pinned words')
    patches = job.get('patches')
    if patches != [
            {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 13},
            {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 20}]:
        raise ValueError('only the two source-declared BO address words may be relocated')
    addresses = job.get('simulation_addresses')
    if addresses != {'in': 0x1000, 'out': 0x2000}:
        raise ValueError('simulation address map differs from the fixture contract')
    patched = bytearray(raw)
    for index, name in ((13, 'out'), (20, 'in')):
        start = index * 8
        word = int.from_bytes(patched[start:start + 8], 'little')
        patched[start:start + 8] = (
            (word & ~(0xFFFFFFFF << 16)) | (addresses[name] << 16)
        ).to_bytes(8, 'little')
    patched_bytes = bytes(patched)
    if sha_bytes(raw) != manifest['command_stream']['source_regcmd_sha256'] or \
            sha_bytes(patched_bytes) != manifest['command_stream']['simulation_patched_regcmd_sha256']:
        raise ValueError('raw or relocated command hash differs from pinned source emitter output')
    changed = [i for i, (a, b) in enumerate(zip(words, (int.from_bytes(
        patched_bytes[j:j + 8], 'little') for j in range(0, len(patched_bytes), 8)))) if a != b]
    if changed != [13, 20]:
        raise ValueError(f'address relocation changed QWORDs other than [13,20]: {changed}')

    import struct
    input_bo = (FIXTURE / 'in.bin').read_bytes()
    if input_bo != struct.pack('<2048e', *range(2048)):
        raise ValueError('input bytes do not match row-major arange(2048, float16)')
    output_init = (FIXTURE / 'out_init.bin').read_bytes()
    expected = bytearray(output_init)
    expected[:16] = struct.pack('<8e', *range(2040, 2048))
    if bytes(expected) != (FIXTURE / 'expected.bin').read_bytes():
        raise ValueError('complete expected BO differs from the source maximum reference')
    if output_init[16:] != bytes([0xA5]) * (4096 - 16):
        raise ValueError('output initialization is not the complete pinned 4096-byte surface')
    return manifest, job, raw, patched_bytes


def save_report(outdir: Path, report: dict) -> None:
    (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')


def run_logged(name: str, argv: list[str], outdir: Path, report: dict,
               timeout: int = 600) -> str:
    log = outdir / f'{name}.log'
    row = {'name': name, 'argv': [str(arg) for arg in argv],
           'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(row)
    save_report(outdir, report)
    with log.open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout, check=False)
    text = log.read_text(errors='replace')
    fatal = [line for line in text.splitlines()
             if '%Fatal' in line or 'FATAL' in line or '$fatal' in line]
    row.update(returncode=result.returncode,
               status='PASS' if result.returncode == 0 and not fatal else 'FAIL',
               tool_fatal_lines=fatal, log_sha256=sha(log))
    save_report(outdir, report)
    if result.returncode or fatal:
        raise RuntimeError(f'{name} failed: {text[-5000:]}')
    return text


def run_simulator(simulator: str, outdir: Path, keep_build: bool,
                  fixture: tuple[dict, dict, bytes, bytes]) -> dict:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} or its runtime is unavailable')
    manifest, job, raw, patched = fixture
    outdir.mkdir(parents=True, exist_ok=False)
    patched_path = outdir / 'source_emitted_patched_regcmd.bin'
    patched_path.write_bytes(patched)
    sources = [LAYOUT_RTL, *PROFILE_RTLS, *LEAF_RTLS, DMA_RTL,
               DISPATCH_RTL, TB, RUNNER, MANIFEST, JOB]
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
        'python_version': platform.python_version(), 'source_hashes_before': before,
        'scope': 'Kind-3 dispatch, strict source-emitter-derived 26-QWORD profile, 4096-byte input DMA, global max leaf, and complete 4096-byte output BO. Simulation-only; no device capture or hardware access.',
        'hardware_accessed': False, 'vivado_executed': False, 'bitstream_emitted': False,
        'fixture': {'raw_command_sha256': sha_bytes(raw),
                    'patched_command_sha256': sha_bytes(patched),
                    'patched_command_file': str(patched_path.relative_to(ROOT)),
                    'device_capture': None,
                    'input_bo_bytes': 4096, 'output_bo_bytes': 4096,
                    'simulation_addresses': job['simulation_addresses']},
        'expected_traffic_per_job': {'command_halfword_reads': 104,
                                     'input_halfword_reads': 2048,
                                     'output_halfword_writes': 8,
                                     'total_transactions': 2160,
                                     'complete_output_bo_compared_bytes': 4096},
        'negative_controls': {'positive_infinity': {'mode': 2, 'expected_code': 6},
                              'late_negative_zero': {'mode': 3, 'expected_code': 6},
                              'mutated_fixed_register': {'mode': 4, 'expected_code': 2},
                              'out_of_range_positive': {'mode': 5, 'expected_code': 6},
                              'overlapping_output_address': {'mode': 6, 'expected_code': 3},
                              'unaligned_output_address': {'mode': 7, 'expected_code': 3},
                              'positive_subnormal': {'mode': 8, 'expected_code': 6},
                              'output_writes_on_rejection': 0},
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
                                   *map(str, hdl)], outdir, report)
            prefix = [runtime, str(build)]
        else:
            build = outdir / 'obj'
            run_logged('compile', [compiler, '--binary', '--timing', '--assert', '-Wall',
                                   '-j', '2', '--top-module', 'tb_ppu_pool_c8_raw_dma',
                                   '--Mdir', str(build), '-o', 'sim', *map(str, hdl)],
                       outdir, report)
            prefix = [str(build / 'sim')]
        for mode in range(9):
            expected_error = ERROR_MODES.get(mode, 0)
            text = run_logged(f'mode-{mode}', prefix + [
                f'+COMMAND_BIN={patched_path}', f'+INPUT_BIN={FIXTURE / "in.bin"}',
                f'+OUTPUT_INIT_BIN={FIXTURE / "out_init.bin"}',
                f'+EXPECTED_BIN={FIXTURE / "expected.bin"}',
                '+GLOBAL_CASE=1', f'+MODE={mode}', f'+EXPECT_ERROR={expected_error}',
            ], outdir, report, timeout=180)
            matches = [m for line in text.splitlines() if (m := PASS_RE.match(line))]
            if len(matches) != 1 or int(matches[0].group('mode')) != mode:
                raise RuntimeError(f'mode {mode} emitted no unique global MAX PASS marker')
            details = matches[0].group('details')
            if mode == 0:
                wanted = ('transactions=2160 command_reads=104 input_reads=2048 '
                          'output_writes=8 complete_output_bytes=4096 global_profile=1')
            elif mode == 1:
                wanted = ('error_code=0 transactions=4320 command_reads=208 input_reads=4096 '
                          'output_writes=16 complete_output_bytes=4096 repeated_jobs=2 global_profile=1')
            else:
                transactions = {2: 105, 3: 2152, 4: 104, 5: 105,
                                6: 104, 7: 104, 8: 105}[mode]
                wanted = (f'error_code={expected_error} transactions={transactions} '
                          f'responses={transactions} output_writes=0')
            if details != wanted:
                raise RuntimeError(f'mode {mode} output/traffic differs: {details!r} != {wanted!r}')
            report['runs'].append({'mode': mode, 'expected_error': expected_error,
                                   'details': details})
            save_report(outdir, report)
        after = {str(path): sha(path) for path in sources}
        if before != after:
            raise RuntimeError('RTL, source fixture, or runner changed during simulation')
        report.update(status='PASS', finished_utc=now(), source_hashes_after=after,
                      summary={'raw_qwords': 26, 'relocatable_qwords': [13, 20],
                               'transactions_per_job': 2160,
                               'same_epoch_repeat_transactions': 4320,
                               'whole_output_bo_compared': True,
                               'negative_controls': len(ERROR_MODES),
                               'device_capture_present': False,
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
        outdir = ROOT / 'build/ppu-pooling' / f'global-raw-dma-{simulator}-{stamp}'
        try:
            run_simulator(simulator, outdir, args.keep_build, fixture)
        except Exception as exc:
            print(f'FAIL global MAX raw DMA {simulator}: {exc}', file=sys.stderr)
            return 1
        print(f'PASS source-derived global MAX raw DMA {simulator}: 2160 transactions/job, '
              f'complete 4096-byte BO, repeat and {len(ERROR_MODES)} negative controls; '
              f'no device capture; report={outdir / "report.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
