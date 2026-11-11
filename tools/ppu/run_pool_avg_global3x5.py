#!/usr/bin/env python3
"""Replay the pinned RK3588 global-average capture through its leaf only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CASE = 'fp16_avg_global_k3x5_valid_c8_h3w5'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures' / CASE
MANIFEST = FIXTURE / 'manifest.json'
RTL = ROOT / 'rtl/ppu/rk_ppu_pool_avg_global3x5_c8_fp16_capture.sv'
TB = ROOT / 'tests/ppu_pooling/tb_ppu_pool_avg_global3x5_c8_fp16_capture.sv'
DONOR = Path('/home/fedora/rk3588/examples/expt/pooling.py')
FILES = ('capture.json', 'device_out.bin', 'expected.bin', 'in.bin', 'job.json',
         'out_init.bin', 'regcmd.bin', 'regcmd.txt')
TOP = 'tb_ppu_pool_avg_global3x5_c8_fp16_capture'


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


def load_contract() -> tuple[dict, dict, bytes]:
    manifest = json.loads(MANIFEST.read_text())
    if (manifest.get('case'), manifest.get('status')) != (
            CASE, 'READY_CAPTURE_BOUNDED_CANDIDATE'):
        raise ValueError('wrong global-average fixture identity/provenance')
    if manifest['source']['example_sha256'] != sha(DONOR):
        raise ValueError('donor pooling source does not match the fixture pin')
    if set(manifest['files']) != set(FILES):
        raise ValueError('fixture file census differs')
    for name in FILES:
        path = FIXTURE / name
        expected = manifest['files'][name]
        if {'bytes': path.stat().st_size, 'sha256': sha(path)} != expected:
            raise ValueError(f'fixture hash/size mismatch: {name}')
    capture = json.loads((FIXTURE / 'capture.json').read_text())
    job = json.loads((FIXTURE / 'job.json').read_text())
    raw = (FIXTURE / 'regcmd.bin').read_bytes()
    if len(raw) != 28 * 8 or sha_bytes(raw) != manifest['source']['regcmd_sha256']:
        raise ValueError('raw captured command is not the pinned 28-QWORD stream')
    if capture.get('status') != 'OK' or capture.get('submit_ret') != 0:
        raise ValueError('RK3588 capture did not complete successfully')
    if capture.get('hashes', {}).get('regcmd_source') != sha_bytes(raw):
        raise ValueError('capture does not bind the original raw stream')
    if capture.get('hashes', {}).get('outputs', {}).get('out', {}).get('sha256') != sha(FIXTURE / 'device_out.bin'):
        raise ValueError('capture does not bind the captured output BO')
    if job.get('patches') != [
            {'buffer': 'out', 'kind': 'value32', 'regcmd_index': 15},
            {'buffer': 'in', 'kind': 'value32', 'regcmd_index': 22}]:
        raise ValueError('only the two captured address QWORDs may relocate')
    addresses = capture.get('addresses', {}).get('buffers')
    if addresses != {'in': 4096, 'out': 8192}:
        raise ValueError('captured BO address map differs')
    patched = bytearray(raw)
    for index, key in ((15, 'out'), (22, 'in')):
        offset = index * 8
        word = int.from_bytes(patched[offset:offset + 8], 'little')
        patched[offset:offset + 8] = (
            (word & ~(0xffffffff << 16)) | (addresses[key] << 16)
        ).to_bytes(8, 'little')
    if sha_bytes(patched) != capture['hashes']['command_stream']['sha256']:
        raise ValueError('relocated stream differs from the captured RK command')
    if sha_bytes(patched) != manifest['device_capture']['patched_regcmd_sha256']:
        raise ValueError('relocated stream differs from the fixture pin')
    if (FIXTURE / 'expected.bin').read_bytes() != (FIXTURE / 'device_out.bin').read_bytes():
        raise ValueError('source oracle and device capture differ')
    return manifest, job, bytes(patched)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'), default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    try:
        manifest, job, patched = load_contract()
    except Exception as exc:
        print(f'CONTRACT FAIL: {exc}', file=sys.stderr)
        return 1

    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for simulator in simulators:
        compiler = shutil.which(simulator)
        runtime = shutil.which('vvp') if simulator == 'iverilog' else None
        if not compiler or (simulator == 'iverilog' and not runtime):
            print(f'UNAVAILABLE: {simulator} and runtime are required', file=sys.stderr)
            return 2
        outdir = ROOT / 'build/ppu-pooling' / f'global-average-leaf-{simulator}-{stamp}'
        outdir.mkdir(parents=True, exist_ok=False)
        patched_path = outdir / 'patched_regcmd.bin'
        patched_path.write_bytes(patched)
        observed_path = outdir / 'observed.bin'
        inputs = [MANIFEST, RTL, TB, Path(__file__).resolve(), DONOR] + [FIXTURE / n for n in FILES]
        before = {str(path): sha(path) for path in inputs}
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                                  capture_output=True, check=True).stdout.strip()
        status = subprocess.run(['git', 'status', '--short', '--untracked-files=all'],
                                cwd=ROOT, text=True, capture_output=True,
                                check=True).stdout.splitlines()
        report = {
            'status': 'RUNNING', 'started_utc': now(), 'case': CASE,
            'source_revision': revision, 'source_worktree_status': status,
            'simulator': simulator,
            'tool_version': tool_version([compiler, '--version'] if simulator == 'verilator' else [compiler, '-V']),
            'runtime_version': tool_version([runtime, '-V']) if runtime else None,
            'python_version': platform.python_version(),
            'seed_policy': 'deterministic fixture, fixed output backpressure of three cycles; seed=0x72667555',
            'scope': 'Standalone fixed-shape global-average leaf; no register/DMA/top hardware or FPGA qualification.',
            'hardware_accessed': False, 'vivado_executed': False, 'bitstream_emitted': False,
            'fixture': {'raw_command_sha256': sha(FIXTURE / 'regcmd.bin'),
                        'patched_command_sha256': sha_bytes(patched),
                        'device_output_sha256': manifest['comparison']['device_output_sha256'],
                        'relocatable_qwords': [15, 22],
                        'input_bo_bytes': 4096, 'logical_input_bytes': 240,
                        'output_bo_bytes': 4096, 'logical_output_bytes': 16,
                        'addresses': capture_addresses(job)},
            'source_hashes_before': before,
            'commands': [],
        }
        build = outdir / ('obj' if simulator == 'verilator' else 'sim.vvp')
        try:
            if simulator == 'iverilog':
                compile_argv = [compiler, '-g2012', '-Wall', '-s', TOP, '-o', str(build), str(RTL), str(TB)]
                run_prefix = [runtime, str(build)]
            else:
                compile_argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                                '--top-module', TOP, '--Mdir', str(build), '-o', 'sim', str(RTL), str(TB)]
                run_prefix = [str(build / 'sim')]
            compile_result = subprocess.run(compile_argv, cwd=ROOT, text=True,
                                            capture_output=True, check=False, timeout=600)
            (outdir / 'compile.log').write_text(compile_result.stdout + compile_result.stderr)
            if compile_result.returncode:
                raise RuntimeError(f'compile failed: {(compile_result.stdout + compile_result.stderr)[-5000:]}')
            run_argv = run_prefix + [
                f'+IN_BIN={FIXTURE / "in.bin"}',
                f'+OUT_INIT_BIN={FIXTURE / "out_init.bin"}',
                f'+EXPECTED_BIN={FIXTURE / "expected.bin"}',
                f'+DEVICE_OUT_BIN={FIXTURE / "device_out.bin"}',
                f'+OBSERVED_BIN={observed_path}',
            ]
            run_result = subprocess.run(run_argv, cwd=ROOT, text=True,
                                        capture_output=True, check=False, timeout=180)
            output = run_result.stdout + run_result.stderr
            (outdir / 'run.log').write_text(output)
            if run_result.returncode or 'PASS ppu_avg_global3x5_c8_fp16_capture ' not in output:
                raise RuntimeError(f'simulation failed: {output[-5000:]}')
            observed = observed_path.read_bytes()
            device = (FIXTURE / 'device_out.bin').read_bytes()
            if observed != device:
                raise RuntimeError('whole output BO differs from captured device output')
            after = {str(path): sha(path) for path in inputs}
            if before != after:
                raise RuntimeError('source or fixture changed during the simulation')
            report.update(status='PASS', finished_utc=now(), source_hashes_after=after,
                          observed_output_sha256=sha(observed_path),
                          simulator_output=output.strip(),
                          complete_output_bo_bytes_compared=4096)
        except Exception as exc:
            report.update(status='FAIL', finished_utc=now(), failure=str(exc))
            print(f'FAIL global-average leaf {simulator}: {exc}', file=sys.stderr)
            (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
            return 1
        finally:
            if not args.keep_build:
                if build.is_dir():
                    shutil.rmtree(build)
                else:
                    build.unlink(missing_ok=True)
        (outdir / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(f'PASS global-average leaf {simulator}: 15 C8 input atoms, 8 output lanes, '
              f'complete 4096-byte device BO exact, report={outdir / "report.json"}')
    return 0


def capture_addresses(job: dict) -> dict:
    return {'in': 0x1000, 'out': 0x2000}


if __name__ == '__main__':
    raise SystemExit(main())
