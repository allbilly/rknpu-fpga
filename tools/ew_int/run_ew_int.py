#!/usr/bin/env python3
"""Offline replay + receipts for the captured RK3588 integer EW family.

Runs the 15 READY ew-int bundles through:
  1. the software reference (model.int_profile decoder + model.int_sim emulator),
  2. the new integer RTL path (rtl/rk_ew_int_dma: int decoder + int engine),
  3. the integer ALU unit-vector check (captured lanes + labelled source-formula
     saturation edges) on the same simulators,
  4. fail-closed negative controls whose explicit error codes must match.

This tool never touches hardware, Vivado, or the network. It writes fresh,
source-hash-bound receipts under build/ew-int/<UTC stamp>/. Simulation runs are
short (<a few seconds); the host heavy-job guard is not needed for these, but the
driver runs one simulator command at a time and refuses to run in parallel.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from model.int_alu import (DTYPE_ITEMS, OP_CODES, alu, decode_item,  # noqa: E402
                           signed16)
from model.int_profile import decode_regcmd  # noqa: E402
from model.profile import ProfileError  # noqa: E402
from model.int_sim import IntEmulator, IntMemory, masked_compare  # noqa: E402

CAPTURE = ROOT / 'build/rk3588-example-captures/ew-int'
MANIFEST = CAPTURE / 'manifest.json'
BASE = 0x10000000
WINDOW_BYTES = 0x8000                    # 32 KiB simulated device window
OFF_REGS = 0x0000
OFF_A = 0x0400
OFF_B = 0x1400
OFF_OUT = 0x2400
BO_BYTES = 4096
RTL_FILES = ['rtl/rk_int_alu.sv', 'rtl/rk_ew_int_regs.sv',
             'rtl/rk_ew_int_engine.sv', 'rtl/rk_ew_int_dma.sv']
MODEL_FILES = ['model/int_alu.py', 'model/int_profile.py', 'model/int_sim.py']
TB_FILES = ['tests/tb_ew_int.sv', 'tests/tb_int_alu.sv']
TOOL_FILES = ['tools/ew_int/run_ew_int.py']
PY_TESTS = ['tests/test_ew_int.py']
DOCS = ['docs/EW_INT.md', 'fpga/ewint/sources.json',
        'fpga/ewint/ypcb_jtag_ew_int_top.sv', 'rtl/host/rk_jtag_ew_int_bram.sv']
DATA_FILES = ['build/rk3588-example-captures/ew-int/manifest.json']
SCOPE = ('Offline RTL/software replay only. Not timing closure, place-and-route, '
         'FPGA programming or RK3588 silicon validation. Transport is the frozen '
         'rk_jtag_backend/rk_bram/rk_job_control wrapper and is not re-tested here.')


def utc() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha(Path(path).read_bytes())


def run(command: list[str], log: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('wb') as stream:
        stream.write(('$ ' + ' '.join(command) + '\n').encode())
        stream.flush()
        result = subprocess.run(command, cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    text = log.read_text(errors='replace')
    # Repository discipline: simulator warnings are fatal, not chatter.
    warning = [line for line in text.splitlines()
               if line.startswith('%Warning') or 'warning:' in line.lower()]
    if result.returncode or warning:
        tail = '\n'.join(text.splitlines()[-40:])
        raise SystemExit(f'command failed or warned: {log}\n{tail}')
    return result


def tool_version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        text = (result.stdout or '') + (result.stderr or '')
        return text.strip().splitlines()[0] if text.strip() else 'unknown'
    except Exception as error:  # pragma: no cover - diagnostic only
        return f'unavailable: {error}'


# ---------------------------------------------------------------------------
# Captured-bundle helpers
# ---------------------------------------------------------------------------
def load_manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    for entry in manifest['cases']:
        if entry['status'] != 'READY':
            continue
        bundle = CAPTURE / entry['bundle_dir']
        for name, digest in entry['hashes'].items():
            path = bundle / name
            if not path.is_file():
                raise SystemExit(f'missing bundle file {path}')
            if sha_file(path) != digest:
                raise SystemExit(f'bundle hash mismatch: {path}')
    return manifest


def patch_words(words: list[int], key: tuple[int, int], value: int) -> None:
    target, offset = key
    matches = [i for i, w in enumerate(words)
               if (w >> 48) == target and (w & 0xFFFF) == offset]
    if len(matches) != 1:
        raise SystemExit(f'expected one {key} write, found {len(matches)}')
    words[matches[0]] = (words[matches[0]] & 0xFFFF_0000_0000_FFFF) | (value << 16)


def words_bytes(words: list[int]) -> bytes:
    return b''.join(int(w).to_bytes(8, 'little') for w in words)


def bytes_words(raw: bytes) -> list[int]:
    return [int(v[0]) for v in struct.iter_unpack('<Q', raw)]


def patched_stream(entry: dict) -> tuple[bytes, list[int]]:
    raw = (CAPTURE / entry['bundle_dir'] / 'regcmd.bin').read_bytes()
    words = bytes_words(raw)
    patch_words(words, (0x1001, 0x4020), BASE + OFF_OUT)
    patch_words(words, (0x2001, 0x5018), BASE + OFF_A)
    patch_words(words, (0x2001, 0x5038), BASE + OFF_B)
    return words_bytes(words), words


def lane_offset(lane: int, item: int, layout: str, width: int, channels: int) -> int:
    if layout == 'surface':
        atom = 16 // item
        channel = lane % channels
        pixel = lane // channels
        return (((channel // atom) * width + pixel) * atom +
                (channel % atom)) * item
    return lane * item


def logical_values(payload: bytes, cfg, out: bool = False) -> list[int]:
    dtype = cfg.out_dtype if out else cfg.dtype
    item = DTYPE_ITEMS[dtype]
    values = []
    for lane in range(cfg.count):
        offset = lane_offset(lane, item, cfg.layout, cfg.width, cfg.channels)
        values.append(decode_item(payload[offset:offset + item], dtype))
    return values


def build_window(entry: dict, stream: bytes, out_bytes: bytes | None = None) -> bytes:
    """64 KiB device window: regcmd, a BO, b BO, zeroed/expected output BO."""
    bundle = CAPTURE / entry['bundle_dir']
    window = bytearray(WINDOW_BYTES)
    window[OFF_REGS:OFF_REGS + len(stream)] = stream
    window[OFF_A:OFF_A + BO_BYTES] = (bundle / 'a.bin').read_bytes()
    window[OFF_B:OFF_B + BO_BYTES] = (bundle / 'b.bin').read_bytes()
    if out_bytes is not None:
        if len(out_bytes) > BO_BYTES:
            raise SystemExit('stimulus output BO exceeds 4096 bytes')
        window[OFF_OUT:OFF_OUT + len(out_bytes)] = out_bytes
    return bytes(window)


def window_hex(window: bytes) -> str:
    lines = []
    for index in range(0, len(window), 2):
        word = window[index] | (window[index + 1] << 8)
        lines.append(f'{word:04x}')
    return '\n'.join(lines) + '\n'


def hex_to_bytes(text: str) -> bytes:
    data = bytearray()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        word = int(line, 16)
        data += bytes((word & 0xFF, (word >> 8) & 0xFF))
    return bytes(data)


# ---------------------------------------------------------------------------
# Python reference replay
# ---------------------------------------------------------------------------
def python_replay(entry: dict, stream: bytes) -> dict:
    bundle = CAPTURE / entry['bundle_dir']
    memory = IntMemory()
    memory.map(BASE + OFF_A, (bundle / 'a.bin').read_bytes())
    memory.map(BASE + OFF_B, (bundle / 'b.bin').read_bytes())
    out = memory.map(BASE + OFF_OUT, bytes(BO_BYTES))
    emulator = IntEmulator(memory)
    emulator.submit(stream)
    actual = bytes(out)
    expected = (bundle / 'expected.bin').read_bytes()
    mask = (bundle / 'expected.mask.bin').read_bytes()
    result = masked_compare(actual, expected, mask)
    configs = decode_regcmd(stream)
    result.update(config=configs[0].__dict__ if configs else None,
                  actual_sha256=sha(actual), expected_sha256=sha(expected),
                  mask_sha256=sha(mask),
                  memory_transactions=emulator.memory_transactions)
    return result


# ---------------------------------------------------------------------------
# ALU vectors: captured lanes + labelled source-formula saturation edges
# ---------------------------------------------------------------------------
def alu_vectors(manifest: dict) -> tuple[list[str], int, int]:
    lines: list[str] = []
    captured = 0
    candidate = 0
    for entry in manifest['cases']:
        if entry['status'] != 'READY':
            continue
        bundle = CAPTURE / entry['bundle_dir']
        stream, _ = patched_stream(entry)
        cfg = decode_regcmd(stream)[0]
        a_values = logical_values((bundle / 'a.bin').read_bytes(), cfg)
        b_values = logical_values((bundle / 'b.bin').read_bytes(), cfg)
        expected_values = logical_values((bundle / 'expected.bin').read_bytes(), cfg, out=True)
        for a, b, expected in zip(a_values, b_values, expected_values):
            # The engine applies the captured INT32-MUL signed-INT16 operand
            # truncation before the ALU; feed the unit under test that operand.
            if cfg.op == 'MUL' and cfg.dtype == 'INT32':
                b = signed16(b)
            lines.append(f"{OP_CODES[cfg.op]} {_dtype_code(cfg.out_dtype)} "
                         f"{a & 0xFFFFFFFF:08x} {b & 0xFFFFFFFF:08x} "
                         f"{expected & 0xFFFFFFFF:08x} 1")
            captured += 1
    # Source-formula candidate saturation edges. These are NOT captured device
    # outputs: they exercise the clamping path that the source's saturate()
    # defines but the captured vectors never reach (all captured lanes in range).
    edges = [
        ('ADD', 'INT8', 127, 1), ('ADD', 'INT8', -128, -1),
        ('MINUS', 'INT8', -128, 1), ('MINUS', 'INT8', 127, -1),
        ('MUL', 'INT8', 100, 2), ('MUL', 'INT8', -100, 2),
        ('ADD', 'INT16', 32767, 1), ('ADD', 'INT16', -32768, -1),
        ('MINUS', 'INT16', -32768, 1), ('MINUS', 'INT16', 32767, -1),
        ('MUL', 'INT16', 30000, 2), ('MUL', 'INT16', -30000, 2),
        ('ADD', 'INT32', 2147483647, 1), ('ADD', 'INT32', -2147483648, -1),
        ('MINUS', 'INT32', -2147483648, 1), ('MINUS', 'INT32', 2147483647, -1),
        ('MUL', 'INT32', 2147483647, 2), ('MUL', 'INT32', -2147483648, 2),
        ('MUL', 'INT32', 1000, -15536),
        ('MAX', 'INT8', -5, 3), ('MIN', 'INT16', -32768, 32767),
        ('MAX', 'INT32', -2147483648, 2147483647),
    ]
    for op, dtype, a, b in edges:
        expected = alu(op, dtype, a, b)
        lines.append(f"{OP_CODES[op]} {_dtype_code(dtype)} {a & 0xFFFFFFFF:08x} "
                     f"{b & 0xFFFFFFFF:08x} {expected & 0xFFFFFFFF:08x} 0")
        candidate += 1
    return lines, captured, candidate


def _dtype_code(dtype: str) -> int:
    from model.int_alu import DTYPE_CODES
    return DTYPE_CODES[dtype]


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------
def value_word(target: int, offset: int, value: int) -> int:
    return (target << 48) | ((value & 0xFFFFFFFF) << 16) | offset


def mutate(words: list[int], key: tuple[int, int], value: int | None) -> list[int]:
    result = list(words)
    index = [i for i, w in enumerate(result)
             if (w >> 48) == key[0] and (w & 0xFFFF) == key[1]]
    if len(index) != 1:
        raise SystemExit(f'mutation key {key} not unique')
    if value is None:
        result.pop(index[0])
    else:
        result[index[0]] = (result[index[0]] & 0xFFFF_0000_0000_FFFF) | (value << 16)
    return result


def insert_before_tail(words: list[int], extra: list[int]) -> list[int]:
    return list(words[:-4]) + extra + list(words[-4:])


def negative_controls(manifest: dict) -> list[dict]:
    entries = {entry['case']: entry for entry in manifest['cases']
               if entry['status'] == 'READY'}
    simple = entries['int8_add_c8_w1']
    layout = entries['int32_add_c9_w1_layout']
    base_stream, base_words = patched_stream(simple)
    layout_stream, layout_words = patched_stream(layout)

    controls: list[dict] = []

    def add(name: str, words: list[int], code: int, note: str,
            expected_case: str = 'int8_add_c8_w1', ncmd: int | None = None,
            stim: bytes | None = None) -> None:
        raw = words_bytes(words)
        entry = entries[expected_case]
        controls.append({'name': name, 'stream': raw, 'words': words,
                         'error_code': code, 'note': note, 'case': expected_case,
                         'ncmd': ncmd if ncmd is not None else len(words),
                         'stimulus': stim})

    removed = list(base_words)
    removed = [w for i, w in enumerate(removed) if i != 11]
    add('nc_missing_src_register', removed, 3,
        'RDMA.SRC_BASE_ADDR write removed from the simple contract -> E3')
    words = list(base_words)
    index = [i for i, w in enumerate(words)
             if (w >> 48) == 0x2001 and (w & 0xFFFF) == 0x5018][0]
    words[index] = (words[index] & 0xFFFF_FFFF_0000_0000) | 0x00FE
    add('nc_unknown_offset', words, 1,
        'RDMA write retargeted to unmapped offset 0x00fe -> E1')
    # Unknown target/offset directly: rewrite a QWORD key to an unmapped target.
    words = list(base_words)
    index = [i for i, w in enumerate(words) if (w >> 48) == 0x2001 and (w & 0xFFFF) == 0x5044][0]
    words[index] = (0x3001 << 48) | ((words[index] >> 16) & 0xFFFFFFFF) << 16 | 0x5044
    add('nc_unknown_target', words, 1, 'RDMA.FEATURE_MODE_CFG retargeted to 0x3001 -> E1')
    add('nc_unsupported_op_div',
        mutate(base_words, (0x1001, 0x4070), 0x104302C0), 2,
        'EW_CFG ALU code 3 (DIV) is not an evidenced integer op -> E2')
    add('nc_unsupported_op_abs',
        mutate(base_words, (0x1001, 0x4070), 0x104502C0), 2,
        'EW_CFG ALU code 5 (ABS) has no captured oracle -> E2')
    add('nc_fp16_dtype',
        mutate(base_words, (0x1001, 0x4010), 0x48000002), 2,
        'DATA_FORMAT FP16 precision is not an evidenced integer dtype -> E2')
    add('nc_dtype_mismatch',
        mutate(base_words, (0x1001, 0x4010), 0x24000001), 2,
        'INT16 DATA_FORMAT on an INT8 EW_CFG stream -> E2')
    add('nc_proc_precision_mismatch',
        mutate(base_words, (0x1001, 0x4010), 0x00000001), 2,
        'process precision differs from input/output precision -> E2')
    add('nc_mul_with_alu_bits',
        mutate(base_words, (0x1001, 0x4070), 0x104202C4), 2,
        'EW_CFG sets the MUL lane and an ALU code at once -> E2')
    add('nc_width_mismatch',
        mutate(base_words, (0x2001, 0x500c), 1), 6,
        'RDMA width differs from the DPU width -> E6')
    add('nc_channel_mismatch',
        mutate(base_words, (0x2001, 0x5014), 8), 6,
        'RDMA channel count differs from the DPU channel count -> E6')
    add('nc_missing_register',
        [w for i, w in enumerate(base_words) if i != 5], 3,
        'EW_CVT_SCALE write removed from the simple contract -> E3')
    words = insert_before_tail(base_words, [value_word(0x1001, 0x4060, 0x53)])
    add('nc_extra_register', words, 2,
        'BN_CFG appears in a simple-mode stream -> E2')
    words = insert_before_tail(base_words, [value_word(0x1001, 0x400C, 0x1E4)])
    add('nc_duplicate_conflict', words, 2,
        'same register written twice with different values -> E2')
    words = mutate(base_words, (0x2001, 0x5018), BASE + OFF_A + 2)
    add('nc_unaligned_address', words, 4,
        'src_a base is not 16-byte aligned -> E4')
    words = mutate(layout_words, (0x1001, 0x4020), 0xFFFFFFE0)
    add('nc_wrapping_address', words, 4,
        'dst 48-byte range wraps the 32-bit address space -> E4',
        expected_case='int32_add_c9_w1_layout')
    words = mutate(layout_words, (0x2001, 0x5018), BASE + OFF_OUT + 16)
    add('nc_partial_alias', words, 4,
        '48-byte input BO partially aliases the 48-byte output BO -> E4',
        expected_case='int32_add_c9_w1_layout')
    add('nc_pc_chain',
        mutate(base_words, (0x0101, 0x0010), 0x100), 2,
        'non-zero PC next address is not evidenced for ew-int -> E2')
    words = list(base_words[:-1])
    add('nc_missing_enable', words, 3,
        'operation-enable QWORD removed -> framing/missing-enable E3',
        ncmd=len(words))
    return controls


# ---------------------------------------------------------------------------
# Simulator drivers
# ---------------------------------------------------------------------------
def compile_replay(simulator: str, work: Path) -> list[str]:
    sources = [str(ROOT / name) for name in RTL_FILES + ['tests/tb_ew_int.sv']]
    if simulator == 'verilator':
        obj = work / 'obj_tb_ew_int'
        command = ['verilator', '--binary', '--timing', '--assert', '-Wall',
                   '-j', '2', '--top-module', 'tb_ew_int', '--Mdir', str(obj),
                   '-o', 'sim'] + sources
        result = run(command, work / f'{simulator}_tb_ew_int_build.log')
        if result.returncode:
            raise SystemExit(f'{simulator} replay build failed; see {work}')
        return [str(obj / 'sim')]
    binary = work / 'tb_ew_int.vvp'
    command = ['iverilog', '-g2012', '-o', str(binary)] + sources
    result = run(command, work / 'iverilog_tb_ew_int_build.log')
    if result.returncode:
        raise SystemExit(f'{simulator} replay build failed; see {work}')
    return ['vvp', str(binary)]


def compile_alu(simulator: str, work: Path) -> list[str]:
    sources = [str(ROOT / 'rtl/rk_int_alu.sv'), str(ROOT / 'tests/tb_int_alu.sv')]
    if simulator == 'verilator':
        obj = work / 'obj_tb_int_alu'
        command = ['verilator', '--binary', '--timing', '--assert', '-Wall',
                   '-j', '2', '--top-module', 'tb_int_alu', '--Mdir', str(obj),
                   '-o', 'sim'] + sources
        result = run(command, work / f'{simulator}_tb_int_alu_build.log')
        if result.returncode:
            raise SystemExit(f'{simulator} ALU build failed; see {work}')
        return [str(obj / 'sim')]
    binary = work / 'tb_int_alu.vvp'
    command = ['iverilog', '-g2012', '-o', str(binary)] + sources
    result = run(command, work / 'iverilog_tb_int_alu_build.log')
    if result.returncode:
        raise SystemExit(f'{simulator} ALU build failed; see {work}')
    return ['vvp', str(binary)]


def run_case(launch: list[str], work: Path, tag: str, plusargs: list[str],
             timeout: int = 300) -> tuple[int, str]:
    command = list(launch) + plusargs
    log = work / 'logs' / f'{tag}.log'
    result = run(command, log, timeout=timeout)
    return result.returncode, log.read_text(errors='replace')


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('both', 'verilator', 'iverilog'),
                        default='both')
    parser.add_argument('--stamp', default=None, help='receipt directory name')
    parser.add_argument('--skip-sim', action='store_true',
                        help='software reference only (no simulator run)')
    args = parser.parse_args()

    manifest = load_manifest()
    ready = [entry for entry in manifest['cases'] if entry['status'] == 'READY']
    blocked = [entry for entry in manifest['cases'] if entry['status'] != 'READY']
    if len(ready) != 15 or len(blocked) != 3:
        raise SystemExit('unexpected capture family counts')

    stamp = args.stamp or time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    work = ROOT / 'build/ew-int' / stamp
    if work.exists():
        raise SystemExit(f'receipt directory already exists: {work}')
    work.mkdir(parents=True)

    source_hashes = {}
    for name in (RTL_FILES + MODEL_FILES + TB_FILES + TOOL_FILES +
                 DATA_FILES + PY_TESTS + DOCS):
        path = ROOT / name
        source_hashes[name] = sha_file(path) if path.is_file() else 'MISSING'
    bundle_hashes = {entry['case']: entry['hashes'] for entry in ready}

    report = {
        'schema': 1,
        'status': 'RUNNING',
        'scope': SCOPE,
        'started_utc': utc(),
        'stamp': stamp,
        'execution_root': str(ROOT),
        'capture_family': str(CAPTURE.relative_to(ROOT)),
        'capture_manifest_sha256': sha_file(MANIFEST),
        'source_revision': subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        'git_dirty': bool(subprocess.run(
            ['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True,
            text=True).stdout.strip()),
        'simulators': {},
        'python_version': platform.python_version(),
        'source_hashes': source_hashes,
        'bundle_hashes': bundle_hashes,
        'cases': {},
        'negative_controls': {},
        'alu': {},
        'blocked_cases': [{'case': entry['case'],
                           'blocked_reason': entry.get('blocked_reason')}
                          for entry in blocked],
        'notes': [
            'The captured expected.bin is a host-side formula oracle, not device data.',
            'No captured lane triggers integer overflow: saturation is source-formula '
            'behaviour (kernel_6_18 saturate()), not a captured overflow vector.',
            'The INT32-MUL signed-INT16 operand limitation is source-captured: '
            'kernel_6_18 run_operation lines 430-443 require the limited result.',
            'Transport (rk_jtag_backend/rk_job_control/rk_bram) is frozen and not '
            'exercised here; this replay covers decoder + engine + BO images.',
        ],
    }

    def save() -> None:
        (work / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    save()
    print(f'[ew-int] receipts: {work}')
    failures: list[str] = []

    # ---- 1. software reference replay -------------------------------------
    print('[ew-int] software reference replay (decoder + emulator)')
    stim_dir = work / 'stimulus'
    stim_dir.mkdir()
    for entry in ready:
        stream, _ = patched_stream(entry)
        result = python_replay(entry, stream)
        report['cases'][entry['case']] = {
            'status': 'PASS' if result['exact'] else 'FAIL',
            'mode': result['config']['mode'],
            'op': result['config']['op'],
            'dtype': result['config']['dtype'],
            'out_dtype': result['config']['out_dtype'],
            'count': result['config']['count'],
            'width': result['config']['width'],
            'channels': result['config']['channels'],
            'layout': result['config']['layout'],
            'asserted_bytes': result['asserted_bytes'],
            'output_bo_bytes': result['bytes'],
            'mismatch_count': result['mismatch_count'],
            'actual_sha256': result['actual_sha256'],
            'expected_sha256': result['expected_sha256'],
            'mask_sha256': result['mask_sha256'],
            'memory_transactions': result['memory_transactions'],
            'python_replay': 'exact-masked' if result['exact'] else 'MISMATCH',
        }
        if not result['exact']:
            failures.append(f'python replay {entry["case"]}')
        # stimulus window for the RTL replay (written once per case)
        window = build_window(entry, stream)
        (stim_dir / f'{entry["case"]}.hex').write_text(window_hex(window))
        report['cases'][entry['case']]['stimulus_sha256'] = sha(window)
    save()

    # ---- 2. ALU unit vectors ---------------------------------------------
    vector_lines, captured_lanes, candidate_edges = alu_vectors(manifest)
    vector_path = work / 'alu_vectors.txt'
    vector_path.write_text('\n'.join(vector_lines) + '\n')
    report['alu'] = {
        'vectors': len(vector_lines),
        'captured_lanes': captured_lanes,
        'source_formula_candidate_edges': candidate_edges,
        'vector_file_sha256': sha_file(vector_path),
        'source_formula_note': ('captured=1 vectors are captured a/b/expected lanes; '
                                'captured=0 vectors exercise the source-formula '
                                'saturation edges and are not captured outputs'),
    }
    if failures:
        report['status'] = 'FAIL'
        save()
        print('FAILED python replay:', failures)
        return 1

    # ---- 3. negative controls (software side) ----------------------------
    controls = negative_controls(manifest)
    ctrl_dir = work / 'stimulus'
    for control in controls:
        entry = next(e for e in ready if e['case'] == control['case'])
        window = build_window(entry, control['stream'])
        (ctrl_dir / f"{control['name']}.hex").write_text(window_hex(window))
        control['stimulus_sha256'] = sha(window)
        code = None
        detail = ''
        try:
            decode_regcmd(control['stream'])
        except ProfileError as error:
            code = error.code
            detail = str(error)
        expected_ok = code == control['error_code']
        report['negative_controls'][control['name']] = {
            'expected_error_code': control['error_code'],
            'software_error_code': code,
            'software_detail': detail,
            'software_status': 'PASS' if expected_ok else 'FAIL',
            'note': control['note'],
            'stimulus_sha256': control['stimulus_sha256'],
        }
        if not expected_ok:
            failures.append(f'negative control {control["name"]} software '
                            f'(got {code})')
    save()

    # ---- 4. simulator replay ---------------------------------------------
    if not args.skip_sim:
        simulators = ['verilator', 'iverilog'] if args.simulator == 'both' \
            else [args.simulator]
        versions = {
            'verilator': tool_version(['verilator', '--version']),
            'iverilog': tool_version(['iverilog', '-V']),
        }
        for simulator in simulators:
            if shutil.which(simulator) is None:
                report['simulators'][simulator] = {'status': 'UNAVAILABLE'}
                failures.append(f'{simulator} unavailable')
                continue
            print(f'[ew-int] {simulator}: building replay + ALU testbenches')
            report['simulators'][simulator] = {
                'status': 'RUNNING',
                'version': versions[simulator],
                'cases': {},
            }
            launch_replay = compile_replay(simulator, work)
            launch_alu = compile_alu(simulator, work)
            # ALU vectors first (unit level).
            code, log = run_case(
                launch_alu, work, f'{simulator}_tb_int_alu',
                [f'+VECFILE={vector_path}', f'+VECOUNT={len(vector_lines)}'])
            report['simulators'][simulator]['alu'] = {
                'status': 'PASS' if code == 0 else 'FAIL',
                'log': f'logs/{simulator}_tb_int_alu.log',
                'log_sha256': sha_file(work / 'logs' /
                                       f'{simulator}_tb_int_alu.log'),
            }
            if code:
                failures.append(f'{simulator} ALU vectors')
            # Replay every READY bundle and verify the 4096-byte output BO.
            for entry in ready:
                name = entry['case']
                out_path = work / 'out' / f'{simulator}' / f'{name}.hex'
                out_path.parent.mkdir(parents=True, exist_ok=True)
                code, _log = run_case(
                    launch_replay, work, f'{simulator}_{name}',
                    [f'+STIM={stim_dir / (name + ".hex")}',
                     f'+NCMD={entry["regcmd_qwords"]}',
                     f'+OUTFILE={out_path}',
                     f'+NAME={name}'])
                record = {'status': 'FAIL'}
                if code == 0:
                    actual = hex_to_bytes(out_path.read_text())[:BO_BYTES]
                    bundle = CAPTURE / entry['bundle_dir']
                    comparison = masked_compare(
                        actual, (bundle / 'expected.bin').read_bytes(),
                        (bundle / 'expected.mask.bin').read_bytes())
                    record = {
                        'status': 'PASS' if comparison['exact'] else 'FAIL',
                        'asserted_bytes': comparison['asserted_bytes'],
                        'output_bo_bytes': comparison['bytes'],
                        'mismatch_count': comparison['mismatch_count'],
                        'actual_sha256': sha(actual),
                        'expected_sha256': report['cases'][name]['expected_sha256'],
                        'mask_sha256': report['cases'][name]['mask_sha256'],
                    }
                    if not comparison['exact']:
                        failures.append(f'{simulator} replay {name}')
                else:
                    failures.append(f'{simulator} replay {name} (simulator exit)')
                record['log'] = f'logs/{simulator}_{name}.log'
                record['log_sha256'] = sha_file(work / 'logs' / f'{simulator}_{name}.log')
                report['simulators'][simulator]['cases'][name] = record
            # Negative controls through the RTL path.
            for control in controls:
                name = control['name']
                code, _log = run_case(
                    launch_replay, work, f'{simulator}_{name}',
                    [f'+STIM={ctrl_dir / (name + ".hex")}',
                     f'+NCMD={control["ncmd"]}',
                     f'+ECODE={control["error_code"]}',
                     f'+OUTFILE={work / "out" / simulator / (name + ".hex")}',
                     f'+NAME={name}'])
                record = {'status': 'PASS' if code == 0 else 'FAIL',
                          'expected_error_code': control['error_code'],
                          'log': f'logs/{simulator}_{name}.log',
                          'log_sha256': sha_file(work / 'logs' /
                                                 f'{simulator}_{name}.log')}
                report['simulators'][simulator].setdefault(
                    'negative_controls', {})[name] = record
                if code:
                    failures.append(f'{simulator} negative control {name}')
            report['simulators'][simulator]['status'] = 'PASS' if not [
                f for f in failures
                if f.startswith(simulator)] else 'FAIL'
            save()
        report['tool_versions'] = versions
    else:
        report['tool_versions'] = {}

    report['completed_utc'] = utc()
    report['status'] = 'PASS' if not failures else 'FAIL'
    report['failures'] = failures
    (work / 'report.txt').write_text(
        f"ew-int replay receipt {stamp}\n"
        f"status: {report['status']}\n"
        f"scope: {SCOPE}\n"
        f"capture manifest sha256: {report['capture_manifest_sha256']}\n"
        f"READY cases: {len(ready)}  BLOCKED cases: {len(blocked)}\n"
        f"alu: {report['alu']}\n"
        f"failures: {failures}\n")
    save()
    print(f"[ew-int] {report['status']}: {len(ready)} READY cases, "
          f"{len(controls)} negative controls, {len(vector_lines)} ALU vectors")
    if failures:
        for failure in failures:
            print('  FAIL', failure)
        return 1
    print(f'[ew-int] receipt: {work / "report.json"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
