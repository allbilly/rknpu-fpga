#!/usr/bin/env python3
"""USER2-mailbox replay of the pin-free dual-endpoint image.

The host path is the frozen OpenTPU JTAG mailbox, not a PCIe BAR: a 640-bit
frame carries an opcode, an address and up to 512 bits of data.

  0  page identities, word and block round trips, misaligned-block refusal,
     unmapped-page downstream error + quarantine
  1  conv-simple job end to end through frames; complete 4096-byte BO compare
  2  pooling job end to end through frames; complete 4096-byte BO compare
  3  FP32 GEMM job end to end through frames; complete 4096-byte BO compare
  4  FP32 conv profile-3 job end to end on the second conv page at 0xb000
  5  conv profile-1 (5x5 C4 OC16) job on the page at 0xc000
  6  conv profile-2 (3x3 C16 OC32) job on the page at 0xd000

Modes 1-6 load every BO through block writes and read every output word back
through block reads. Nothing here touches an engine internal, a board,
Vivado or a bitstream.
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
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNNER = Path(__file__).resolve()
TB = ROOT / 'tests/tb_ypcb_jtag_dual.sv'
CONV_FIXTURE = ROOT / 'tests/conv/fixtures/conv_simple_fp16_3x3_c4_h8_w8_oc16'
POOL_FIXTURE = ROOT / 'tests/ppu_pooling/fixtures/int8_max_k2s2_valid_c16_h2w2'
DONOR = ROOT / 'rtl/vendor/nvdla'
DONOR_SOURCES = [
    'compat/nv_assert_never.v', 'compat/nv_assert_no_x.v', 'NV_DW_lsd.v',
    'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'NV_NVDLA_CACC_CALC_fp_48b.v', 'HLS_fp32_to_fp16.v',
]
RTL = [
    'rtl/cmac/rk_cmac_fp16_cell.sv', 'rtl/cmac/rk_cmac_fp16_array.sv',
    'rtl/cmac/rk_nvdla_cacc.sv', 'rtl/cmac/rk_cacc_fp16_array.sv',
    'rtl/cmac/rk_cmac_cacc_fp16_array.sv', 'rtl/cmac/rk_nvdla_fp32_to_fp16.sv',
    'rtl/cmac/rk_cmac_writer.sv', 'rtl/cmac/rk_cmac_output_nvdla.sv',
    'rtl/cmac/rk_cmac_frame_output.sv', 'rtl/cmac/rk_cmac_rw_arbiter.sv',
    'rtl/cmac/rk_conv_output_atom.sv', 'rtl/cmac/rk_conv_simple_profile.sv',
    'rtl/cmac/rk_conv_3x3_valid_c4_front.sv', 'rtl/cmac/rk_frame_stage.sv',
    'rtl/cmac/rk_conv_simple_core.sv',
    'rtl/cmac/rk_conv_simple_dma.sv', 'rtl/cmac/rk_conv_simple_axi.sv',
    'rtl/ppu/rk_ppu_pool_int_k2s2.sv', 'rtl/ppu/rk_ppu_pool_i8_k2s2_profile.sv',
    'rtl/ppu/rk_ppu_pool_i8_k2s2_dma.sv', 'rtl/ppu/rk_ppu_pool_axi.sv',
    'rtl/rk_bram.sv', 'rtl/rk_startup_reset.sv', 'rtl/rk_axil_mem_bridge.sv',
    'rtl/rk_axil_error_slave.sv',
    # FP32 GEMM page and its datapath.
    'rtl/rk_cmac_profile.sv', 'rtl/rk_cmac_address.sv', 'rtl/rk_cmac_reader.sv',
    'rtl/rk_cmac_operand_front.sv',
    'rtl/cmac/rk_nvdla_cmac_group.sv', 'rtl/cmac/rk_nvdla_cmac_pipe.sv',
    'rtl/cmac/rk_cmac_nvdla_core.sv', 'rtl/cmac/rk_cmac_nvdla_dma.sv',
    'rtl/cmac/rk_cmac_job_control.sv', 'rtl/cmac/rk_cmac_gemm_axi.sv',
    'rtl/cmac/rk_cmac_fp32_writer.sv', 'rtl/cmac/rk_cmac_output_fp32.sv',
    'rtl/cmac/rk_conv_output_c1c2_fp32.sv',
    'rtl/cmac/rk_cmac_output_nvdla.sv',
    'rtl/vendor/opentpu/otpu_jtag_mailbox.sv',
    'rtl/host/rk_jtag_axil_bridge.sv', 'fpga/ypcb_dual_endpoint_top.sv',
]
CONV_ADDRESSES = {'input': 0x1000, 'weight': 0x2000, 'out': 0x3000}
POOL_ADDRESSES = {'in': 0x1000, 'out': 0x2000}
# 64-byte block writes: the conv stream is 416 bytes (7 blocks) and the pooling
# stream 208 bytes (4 blocks), so both fit the mailbox's 64-byte framing.
CONV_COMMAND_WORDS = 104
CONV_INPUT_WORDS = 128
CONV_WEIGHT_WORDS = 576
CONV_OUTPUT_WORDS = 1024
POOL_COMMAND_WORDS = 52
POOL_INPUT_WORDS = 1024
POOL_OUTPUT_WORDS = 1024
MODES = {0: {'kind': 'contract'}, 1: {'kind': 'conv_job'},
         2: {'kind': 'pool_job'}, 3: {'kind': 'gemm_job'},
         4: {'kind': 'conv_fp32_job'},
         5: {'kind': 'conv_k5_job'}, 6: {'kind': 'conv_c16_job'}}
PASS_RE = re.compile(r'^PASS YPCB_JTAG_DUAL mode=(\d+) frames=(\d+)$')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def words_from_bytes(payload: bytes) -> list[str]:
    if len(payload) % 4:
        raise ValueError('BO size is not a whole number of 32-bit words')
    return [f'{value:08x}'
            for value in struct.unpack(f'<{len(payload)//4}I', payload)]


def write_words(path: Path, words: list[str]) -> None:
    path.write_text(''.join(f'{word}\n' for word in words))


def check_fixture(fixture: Path) -> dict:
    manifest = json.loads((fixture / 'manifest.json').read_text())
    for name, record in manifest['files'].items():
        path = fixture / name
        if path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            raise ValueError(f'{fixture.name}: fixture file changed: {name}')
    return manifest


def prepare_conv(directory: Path) -> dict:
    manifest = check_fixture(CONV_FIXTURE)
    job = json.loads((CONV_FIXTURE / 'job.json').read_text())
    if manifest['command_stream']['addresses'] != CONV_ADDRESSES:
        raise ValueError('conv BO placement changed')
    raw = bytearray((CONV_FIXTURE / 'regcmd.bin').read_bytes())
    if len(raw) != 52 * 8:
        raise ValueError('conv command stream is not 52 QWORDs')
    for patch in job['patches']:
        offset = patch['regcmd_index'] * 8
        raw[offset + 2:offset + 6] = \
            manifest['command_stream']['addresses'][patch['buffer']].to_bytes(4, 'little')
    directory.mkdir(parents=True, exist_ok=True)
    write_words(directory / 'command_words.hex', words_from_bytes(bytes(raw)))
    write_words(directory / 'input_words.hex',
                words_from_bytes((CONV_FIXTURE / 'input.bin').read_bytes()))
    write_words(directory / 'weight_words.hex',
                words_from_bytes((CONV_FIXTURE / 'weight.bin').read_bytes()))
    write_words(directory / 'output_init_words.hex',
                words_from_bytes(b'\0' * 4096))
    captured = (CONV_FIXTURE / 'device_out.bin').read_bytes()
    write_words(directory / 'expected_words.hex',
                words_from_bytes(captured + b'\0' * (4096 - len(captured))))
    return {'case': CONV_FIXTURE.name, 'command_words': CONV_COMMAND_WORDS,
            'input_words': CONV_INPUT_WORDS, 'weight_words': CONV_WEIGHT_WORDS,
            'output_words': CONV_OUTPUT_WORDS}


GEMM_CASES = {
    'gemm_m2_n2_k1': 0.0,
    'gemm_m1_n16_k32': 0.1,
    'gemm_m2_n16_k32': 0.1,
    'gemm_m4_n32_k64': 0.1,
}
GEMM_FIXTURE = ROOT / 'tests/conv/fixtures/gemm_m2_n2_k1'
CONV_FP32_CASE = 'conv_simple_fp16_1x1_c4_h8_w8_oc16'
GEMM_ADDRESSES = {'input': 0x1000, 'weight': 0x2000, 'output': 0x3000}
GEMM_COMMAND_QWORDS = 49


def prepare_gemm(directory: Path, case: str = 'gemm_m2_n2_k1') -> dict:
    fixture = ROOT / 'tests/conv/fixtures' / case
    manifest = check_fixture(fixture)
    job = json.loads((fixture / 'job.json').read_text())
    addresses = manifest['command_stream']['addresses']
    if addresses != GEMM_ADDRESSES:
        raise ValueError('GEMM BO placement changed')
    raw = bytearray((fixture / 'regcmd.bin').read_bytes())
    if len(raw) != 50 * 8:
        raise ValueError('GEMM command stream is not 50 QWORDs')
    vendor = {'input': 0x10000000, 'weight': 0x20000000, 'output': 0x30000000}
    for patch in job['patches']:
        if patch.get('kind') != 'value32':
            raise ValueError('GEMM patch kind changed')
        offset = patch['regcmd_index'] * 8
        current = struct.unpack_from('<Q', bytes(raw), offset)[0]
        if (current >> 16) & 0xFFFFFFFF != vendor[patch['buffer']]:
            raise ValueError(f'GEMM field {patch["regcmd_index"]} changed')
        raw[offset + 2:offset + 6] = addresses[patch['buffer']].to_bytes(4, 'little')
    directory.mkdir(parents=True, exist_ok=True)
    write_words(directory / 'command_words.hex',
                words_from_bytes(bytes(raw[:GEMM_COMMAND_QWORDS * 8])))
    write_words(directory / 'input_words.hex',
                words_from_bytes((fixture / 'input.bin').read_bytes()))
    write_words(directory / 'weight_words.hex',
                words_from_bytes((fixture / 'weight.bin').read_bytes()))
    write_words(directory / 'output_init_words.hex',
                words_from_bytes(b'\0' * 4096))
    captured = (fixture / 'device_out.bin').read_bytes()
    if len(captured) != 4096:
        raise ValueError('GEMM capture is not a full output BO')
    write_words(directory / 'expected_words.hex', words_from_bytes(captured))
    return {'case': case, 'command_words': GEMM_COMMAND_QWORDS * 2,
            'input_words': 1024, 'weight_words': 1024, 'output_words': 1024,
            'tolerance_abs': GEMM_CASES[case]}


CONV_PROFILE_CASES = {
    'conv_simple_fp16_5x5_c4_h8_w8_oc16': {
        'profile': 1, 'command_words': 104, 'input_words': 128,
        'weight_words': 1600, 'output_words': 1024,
        'output_base': 0x4000},
    'conv_simple_fp16_3x3_c16_h8_w8_oc32': {
        'profile': 2, 'command_words': 104, 'input_words': 512,
        'weight_words': 2304, 'output_words': 1024,
        'output_base': 0x5000},
}


def prepare_conv_profile(directory: Path, case: str) -> dict:
    """Stage one of the two remaining frozen conv-simple captures.

    Sizes are 32-bit words. The captured output base is read from the manifest
    and asserted, because these captures write above the default 0x3000 window.
    """
    spec = CONV_PROFILE_CASES[case]
    fixture = ROOT / 'tests/conv/fixtures' / case
    manifest = check_fixture(fixture)
    job = json.loads((fixture / 'job.json').read_text())
    addresses = manifest['command_stream']['addresses']
    if addresses['out'] != spec['output_base']:
        raise ValueError(f'{case}: captured output base changed')
    raw = bytearray((fixture / 'regcmd.bin').read_bytes())
    if len(raw) != 52 * 8:
        raise ValueError(f'{case}: command stream is not 52 QWORDs')
    for patch in job['patches']:
        offset = patch['regcmd_index'] * 8
        raw[offset + 2:offset + 6] = \
            addresses[patch['buffer']].to_bytes(4, 'little')
    directory.mkdir(parents=True, exist_ok=True)
    write_words(directory / 'command_words.hex', words_from_bytes(bytes(raw)))
    write_words(directory / 'input_words.hex',
                words_from_bytes((fixture / 'input.bin').read_bytes()))
    write_words(directory / 'weight_words.hex',
                words_from_bytes((fixture / 'weight.bin').read_bytes()))
    write_words(directory / 'output_init_words.hex',
                words_from_bytes(b'\0' * 4096))
    captured = (fixture / 'device_out.bin').read_bytes()
    write_words(directory / 'expected_words.hex',
                words_from_bytes(captured + b'\0' * (4096 - len(captured))))
    return {'case': case, 'profile': spec['profile'],
            'command_words': spec['command_words'],
            'input_words': spec['input_words'],
            'weight_words': spec['weight_words'],
            'output_words': spec['output_words'],
            'output_base': spec['output_base'],
            'captured_bytes': len(captured)}


def prepare_conv_fp32(directory: Path) -> dict:
    """Stage the frozen FP32 conv-simple capture for the second conv page.

    Reuses the dedicated runner's fixture loader so the two paths cannot drift.
    """
    import importlib.util
    runner_path = ROOT / 'tools/conv/run_conv_simple_fp32.py'
    spec = importlib.util.spec_from_file_location('conv_fp32_runner', runner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest, patched = module.load()
    directory.mkdir(parents=True, exist_ok=True)
    write_words(directory / 'command_words.hex',
                [f'{v:08x}' for v in struct.unpack(f'<{len(patched)//4}I', patched)])
    fixture = ROOT / 'tests/conv/fixtures' / module.CASE
    for source, target, halfwords in (('input.bin', 'input_words.hex', 256),
                                      ('weight.bin', 'weight_words.hex', 128)):
        raw = (fixture / source).read_bytes()
        half = struct.unpack(f'<{halfwords}H', raw)
        write_words(directory / target,
                    [f'{(half[2*i+1] << 16) | half[2*i]:08x}'
                     for i in range(halfwords // 2)])
    captured = (fixture / 'device_out.bin').read_bytes()
    write_words(directory / 'expected_words.hex',
                [f'{v:08x}' for v in struct.unpack(f'<{len(captured)//4}I', captured)])
    write_words(directory / 'output_init_words.hex', ['00000000'] * 1024)
    return {'case': module.CASE, 'command_words': 104, 'input_words': 256,
            'weight_words': 128, 'output_words': 1024}


def prepare_pool(directory: Path) -> dict:
    manifest = check_fixture(POOL_FIXTURE)
    capture = json.loads((POOL_FIXTURE / 'capture.json').read_text())
    raw = bytearray((POOL_FIXTURE / 'regcmd.bin').read_bytes())
    if len(raw) != 26 * 8:
        raise ValueError('pool command stream is not 26 QWORDs')
    for patch in capture['patches']:
        offset = patch['regcmd_index'] * 8
        raw[offset + 2:offset + 6] = patch['dma_address'].to_bytes(4, 'little')
    if sorted(p['dma_address'] for p in capture['patches']) != \
            sorted(POOL_ADDRESSES.values()):
        raise ValueError('pool BO placement changed')
    directory.mkdir(parents=True, exist_ok=True)
    write_words(directory / 'command_words.hex', words_from_bytes(bytes(raw)))
    write_words(directory / 'input_words.hex',
                words_from_bytes((POOL_FIXTURE / 'in.bin').read_bytes()))
    write_words(directory / 'output_init_words.hex',
                words_from_bytes((POOL_FIXTURE / 'out_init.bin').read_bytes()))
    write_words(directory / 'expected_words.hex',
                words_from_bytes((POOL_FIXTURE / 'device_out.bin').read_bytes()))
    return {'case': POOL_FIXTURE.name, 'command_words': POOL_COMMAND_WORDS,
            'input_words': POOL_INPUT_WORDS, 'output_words': POOL_OUTPUT_WORDS}


def run_mode(simulator: str, mode: int, outdir: Path, keep_build: bool,
             gemm_case: str = 'gemm_m2_n2_k1') -> dict:
    conv = prepare_conv(outdir / 'conv-fixture')
    pool = prepare_pool(outdir / 'pool-fixture')
    gemm = prepare_gemm(outdir / 'gemm-fixture', gemm_case)
    conv_fp32 = prepare_conv_fp32(outdir / 'conv-fp32-fixture')
    conv_k5 = prepare_conv_profile(outdir / 'conv-k5-fixture',
                                   'conv_simple_fp16_5x5_c4_h8_w8_oc16')
    conv_c16 = prepare_conv_profile(outdir / 'conv-c16-fixture',
                                    'conv_simple_fp16_3x3_c16_h8_w8_oc32')
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    sources = [str(DONOR / n) for n in DONOR_SOURCES] + \
              [str(ROOT / n) for n in RTL] + [str(TB)]
    common = [
        f'MODE={mode}',
        f'CONV_COMMAND_WORDS={conv["command_words"]}',
        f'CONV_INPUT_WORDS={conv["input_words"]}',
        f'CONV_WEIGHT_WORDS={conv["weight_words"]}',
        f'CONV_OUTPUT_WORDS={conv["output_words"]}',
        f'POOL_COMMAND_WORDS={pool["command_words"]}',
        f'POOL_INPUT_WORDS={pool["input_words"]}',
        f'POOL_OUTPUT_WORDS={pool["output_words"]}',
        f'GEMM_COMMAND_WORDS={gemm["command_words"]}',
        f'GEMM_INPUT_WORDS={gemm["input_words"]}',
        f'GEMM_WEIGHT_WORDS={gemm["weight_words"]}',
        f'GEMM_OUTPUT_WORDS={gemm["output_words"]}',
        f'GEMM_TOLERANCE={gemm["tolerance_abs"]}',
        f'CONV_FP32_COMMAND_WORDS={conv_fp32["command_words"]}',
        f'CONV_FP32_INPUT_WORDS={conv_fp32["input_words"]}',
        f'CONV_FP32_WEIGHT_WORDS={conv_fp32["weight_words"]}',
        f'CONV_FP32_OUTPUT_WORDS={conv_fp32["output_words"]}',
        f'CONV_K5_COMMAND_WORDS={conv_k5["command_words"]}',
        f'CONV_K5_INPUT_WORDS={conv_k5["input_words"]}',
        f'CONV_K5_WEIGHT_WORDS={conv_k5["weight_words"]}',
        f'CONV_K5_OUTPUT_WORDS={conv_k5["output_words"]}',
        f'CONV_K5_OUTPUT_BASE={conv_k5["output_base"]}',
        f'CONV_C16_COMMAND_WORDS={conv_c16["command_words"]}',
        f'CONV_C16_INPUT_WORDS={conv_c16["input_words"]}',
        f'CONV_C16_WEIGHT_WORDS={conv_c16["weight_words"]}',
        f'CONV_C16_OUTPUT_WORDS={conv_c16["output_words"]}',
        f'CONV_C16_OUTPUT_BASE={conv_c16["output_base"]}',
    ]
    binary = outdir / ('sim.vvp' if simulator == 'iverilog' else 'obj_dir')
    if simulator == 'iverilog':
        argv = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-Irtl/vendor/opentpu', '-Itests',
                '-s', 'tb_ypcb_jtag_dual',
                *[f'-Ptb_ypcb_jtag_dual.{c}' for c in common],
                '-o', str(binary), *sources]
        prefix = [runtime, str(binary)]
    else:
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps',
                '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-Irtl/vendor/opentpu', '-Itests',
                '--top-module', 'tb_ypcb_jtag_dual', '--Mdir', str(binary),
                '-o', 'sim', *[f'-G{c}' for c in common], *sources]
        prefix = [str(binary / 'sim')]
    tracked = [*[ROOT / name for name in RTL], TB, RUNNER,
               CONV_FIXTURE / 'manifest.json', POOL_FIXTURE / 'manifest.json',
               GEMM_FIXTURE / 'manifest.json',
               ROOT / 'tests/conv/fixtures' / CONV_FP32_CASE / 'manifest.json']
    report = {
        'status': 'RUNNING', 'started_utc': utc_now(), 'mode': mode,
        'simulator': simulator, 'python_version': platform.python_version(),
        'source_hashes_before': {str(path.relative_to(ROOT)): sha(path)
                                 for path in tracked},
        'conv_fixture': conv, 'pool_fixture': pool, 'gemm_fixture': gemm,
        'conv_fp32_fixture': conv_fp32,
        'conv_k5_fixture': conv_k5, 'conv_c16_fixture': conv_c16,
        'hardware_accessed': False, 'vivado_executed': False,
        'bitstream_emitted': False, 'physical_board': False,
        'scope': ('USER2 mailbox frames drive the dual-endpoint image; the host '
                  'loads BOs through 64-byte block writes and reads the '
                  'complete output BO back. Simulation only.'),
    }
    try:
        result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                                check=False, timeout=3600)
        text = result.stdout + result.stderr
        (outdir / 'compile.log').write_text(text)
        if result.returncode or re.search(r'%Error', text):
            raise RuntimeError(f'compile failed: {text[-4000:]}')
        result = subprocess.run(
            prefix + [f'+CONV_DIR={outdir / "conv-fixture"}',
                      f'+POOL_DIR={outdir / "pool-fixture"}',
                      f'+GEMM_DIR={outdir / "gemm-fixture"}',
                      f'+CONV_FP32_DIR={outdir / "conv-fp32-fixture"}',
                      f'+CONV_K5_DIR={outdir / "conv-k5-fixture"}',
                      f'+CONV_C16_DIR={outdir / "conv-c16-fixture"}'],
            cwd=ROOT, text=True, capture_output=True, check=False, timeout=7200)
        output = result.stdout + result.stderr
        (outdir / 'run.log').write_text(output)
        matches = [PASS_RE.fullmatch(line) for line in output.splitlines()
                   if line.startswith('PASS YPCB_JTAG_DUAL')]
        if result.returncode or len(matches) != 1:
            raise RuntimeError(f'mode {mode} failed: {output[-4000:]}')
        groups = matches[0].groups()
        if int(groups[0]) != mode:
            raise RuntimeError(f'mode {mode} reported as {groups[0]}')
        after = {name: sha(ROOT / name)
                 for name in report['source_hashes_before']}
        if after != report['source_hashes_before']:
            raise RuntimeError('RTL or fixture changed during the run')
        # A real version string, not the simulator's name: the repo's evidence
        # rules require the concrete tool.
        version = subprocess.run(
            [shutil.which(simulator), '--version'] if simulator == 'verilator'
            else [shutil.which(simulator), '-V'],
            cwd=ROOT, text=True, capture_output=True, check=False, timeout=30)
        report.update(status='PASS', finished_utc=utc_now(),
                      frames=int(groups[1]),
                      tool_version=(version.stdout + version.stderr).strip().splitlines()[0]
                      if version.returncode == 0 and (version.stdout or version.stderr)
                      else 'unknown',
                      source_hashes_after=after)
    except Exception as exc:
        report.update(status='FAIL', failure=str(exc))
        raise
    finally:
        if not keep_build:
            for leftover in list(outdir.glob('obj_dir')):
                if leftover.is_dir():
                    shutil.rmtree(leftover)
            for leftover in list(outdir.glob('*.vvp')):
                leftover.unlink(missing_ok=True)
            report['build_products_pruned'] = True
        (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                       sort_keys=True) + '\n')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='iverilog')
    parser.add_argument('--mode', type=int, action='append', default=None,
                        choices=tuple(MODES))
    parser.add_argument('--keep-build', action='store_true')
    parser.add_argument('--gemm-case', choices=tuple(GEMM_CASES),
                        default='gemm_m2_n2_k1',
                        help='which frozen GEMM capture the page runs')
    args = parser.parse_args()
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    modes = args.mode or list(MODES)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    failures = 0
    for simulator in simulators:
        base = ROOT / 'build/jtag-dual' / f'{simulator}-{stamp}'
        ok = True
        for mode in modes:
            try:
                run_mode(simulator, mode, base / f'mode-{mode}',
                         args.keep_build, args.gemm_case)
            except Exception as exc:
                print(f'FAIL jtag dual mode {mode} {simulator}: {exc}',
                      file=sys.stderr)
                failures += 1
                ok = False
                break
            print(f'PASS jtag dual mode {mode} {simulator}')
        if ok:
            print(f'ALL {len(modes)} modes PASS: ypcb_jtag_dual {simulator}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
