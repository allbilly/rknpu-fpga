#!/usr/bin/env python3
"""Real-board USER2-mailbox replay of the pin-free dual-endpoint image.

This is the hardware counterpart of ``tools/host/run_jtag_dual.py``. It drives
the *already loaded* ``ypcb_jtag_dual_top`` image through the frozen OpenTPU
USER2 mailbox over a Xilinx Platform Cable USB II (DLC10) and a native Vivado
scan bridge, then compares complete BO readbacks against the same frozen
fixtures the simulation replay uses.

It NEVER programs or reconfigures the FPGA, never resets fabric state, never
writes configuration flash and never touches a bitstream device. The image must
be loaded by a separate, documented, authorized step (docs/BOARD_RUN_PREP.md);
this tool only opens an owned hw_server, verifies the loaded image's identity,
and shifts mailbox frames.

Refusal gates, all required for any hardware access:

* ``--authorized``; without it the tool refuses before lease/USB/network work.
* ``--image`` SHA-256 must equal the bitstream of a real emitted build receipt
  under the image catalog (default ``build/jtag-dual-image``); a hash that does
  not name an emitted PASS image is refused.
* ``--target`` must be an exact local audited cable URI; the Vivado bridge Tcl
  re-checks the cable URI, DNA, INIT/DONE, source tag and device count.
* ``--lease`` must be the shared YPCB JTAG lease; a nonblocking exclusive flock
  is held from before hw_server start to after hw_server stop.

Wire mechanics are the ones in ``tools/host/transport.py``, not a new protocol:
640-bit DR frames shifted LSB first, opcodes 1..4, strobes 0xf, magic
0x4f54504a, sequence 1..65535, response magic/sequence matching. Status 0 is
success; 4 is alignment; 5 is malformed; 7 is a downstream error and 0x80 is a
timeout; 7 and 0x80 quarantine the bridge until a joint reset/reconfiguration.
The Python session below is a thin, audited re-implementation of the frame
writer/reader because ``transport.JtagTransport`` hard-wires the RKEW register
map, which this image does not expose; tests/host/test_run_jtag_dual_hardware.py
proves wire equality with ``transport.JtagTransport._command``.

Offline mode: ``--check`` validates arguments, the image catalog entry, the page
map, every staged fixture BO and the per-mode plan, writes a receipt with
``hardware_accessed=false`` and exits without opening a socket, a lease, USB or
Vivado.

Modes (same suite as the simulation replay; mode 0 is always executed last
because its final negative check deliberately quarantines the bridge):

  0  page identities/ABI, word and block round trips, misaligned-block refusal,
     unmapped-page downstream error + quarantine observation
  1  conv-simple profile 0 through the page at 0x8000; complete 4096-byte BO
  2  signed-INT8 pooling through the page at 0x9000; complete 4096-byte BO
  3  FP32 GEMM through the page at 0xa000; complete 4096-byte BO
  4  FP32 conv profile 3 through the page at 0xb000; complete 4096-byte BO
  5  conv k5 profile 1 through the page at 0xc000 (needs that page in the image)
  6  conv C16 profile 2 through the page at 0xd000 (needs that page in the image)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.host import native_link, qualification, run_jtag_dual, transport  # noqa: E402

TOOL = 'tools/host/run_jtag_dual_hardware.py'
IMAGE_CATALOG = ROOT / 'build/jtag-dual-image'
DEFAULT_TARGET = 'localhost:3125/xilinx_tcf/Xilinx/80802026a77a01'
DEFAULT_LEASE = '/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock'
DEFAULT_SERVER_PORT = 3125
DEFAULT_BRIDGE_PORT = 3741
DEFAULT_BRIDGE_TIMEOUT = 180.0
DEFAULT_JOB_TIMEOUT = 180.0
IDCODE = transport.IDCODE
MAGIC = transport.MAGIC
ABI_VERSION = 0x00010000
MEMORY_BASE = 0x00000000
MEMORY_END = 0x00008000
ST_OK = 0
ST_ALIGN = 4
ST_FRAME = 5
ST_DOWNSTREAM = 7
ST_TIMEOUT = 0x80
QUARANTINE_STATUSES = frozenset((ST_DOWNSTREAM, ST_TIMEOUT))
SOURCE_TAG_RE = re.compile('^[0-9a-f]{8}$')
TARGET_RE = re.compile('^(?P<server>[A-Za-z0-9_.:-]+)/xilinx_tcf/Xilinx/(?P<serial>[0-9a-f]{8,32})$')
IMAGE_RE = re.compile('^[0-9a-f]{64}$')
FORBIDDEN_CONTROLLERS = ('openFPGALoader', 'xsdb', 'openocd', 'fxload', 'xvcserver', 'xvc-server', 'xvc_server')

# Page instance name -> (AXI byte base, page DEVICE_ID). The names are the
# exact page-presence gate list in fpga/jtag_dual/build_jtag_dual.tcl.in.
PAGE_MAP = {
    'conv_page': (0x00008000, 0x524B4353),
    'pool_page': (0x00009000, 0x524B5050),
    'gemm_page': (0x0000A000, 0x524B434D),
    'conv_fp32_page': (0x0000B000, 0x524B4415),
    'conv_k5_page': (0x0000C000, 0x524B4416),
    'conv_c16_page': (0x0000D000, 0x524B4417),
}
PAGE_GATE_RE = re.compile(r'foreach page \{([A-Za-z0-9_ ]+)\}')

# Same seven modes, tags, amounts and output windows as tests/tb_ypcb_jtag_dual.sv
# and tools/host/run_jtag_dual.py. Mode 0 carries no job.
MODE_SPECS = {
    0: {'kind': 'contract'},
    1: {'kind': 'job', 'page': 'conv_page', 'amount': 52, 'tag': 0xC0DE4001,
        'output_base': 0x3000, 'output_words': 1024, 'tolerance': 0.0},
    2: {'kind': 'job', 'page': 'pool_page', 'amount': 26, 'tag': 0xC0DE4002,
        'output_base': 0x2000, 'output_words': 1024, 'tolerance': 0.0},
    3: {'kind': 'job', 'page': 'gemm_page', 'amount': 45, 'tag': 0xC0DE4003,
        'output_base': 0x3000, 'output_words': 1024, 'tolerance': None},
    4: {'kind': 'job', 'page': 'conv_fp32_page', 'amount': 52, 'tag': 0xC0DE6001,
        'output_base': 0x3000, 'output_words': 1024, 'tolerance': 0.001},
    5: {'kind': 'job', 'page': 'conv_k5_page', 'amount': 52, 'tag': 0xC0DE7001,
        'output_base': 0x4000, 'output_words': 1024, 'tolerance': 0.0},
    6: {'kind': 'job', 'page': 'conv_c16_page', 'amount': 52, 'tag': 0xC0DE8001,
        'output_base': 0x5000, 'output_words': 1024, 'tolerance': 0.0},
}
TRACKED_INPUTS = (
    TOOL,
    'tools/host/transport.py',
    'tools/host/native_link.py',
    'tools/host/run_jtag_dual.py',
    'tools/host/qualification.py',
    'fpga/host/native_rpc.tcl.in',
    'tests/host/test_run_jtag_dual_hardware.py',
    'tests/conv/fixtures/conv_simple_fp16_3x3_c4_h8_w8_oc16/manifest.json',
    'tests/conv/fixtures/conv_simple_fp16_5x5_c4_h8_w8_oc16/manifest.json',
    'tests/conv/fixtures/conv_simple_fp16_3x3_c16_h8_w8_oc32/manifest.json',
    'tests/conv/fixtures/conv_simple_fp16_1x1_c4_h8_w8_oc16/manifest.json',
    'tests/conv/fixtures/gemm_m2_n2_k1/manifest.json',
    'tests/conv/fixtures/gemm_m1_n16_k32/manifest.json',
    'tests/conv/fixtures/gemm_m2_n16_k32/manifest.json',
    'tests/conv/fixtures/gemm_m4_n32_k64/manifest.json',
    'tests/ppu_pooling/fixtures/int8_max_k2s2_valid_c16_h2w2/manifest.json',
)
# xc7k480tffg1156-2 bitstream sizes are ~18.7 MB; anything wildly different is
# not an emitted configuration image.
MIN_BITSTREAM_BYTES = 1024 * 1024
MAX_BITSTREAM_BYTES = 64 * 1024 * 1024


class Refusal(RuntimeError):
    """Hardware work is not authorized or a precondition is not met."""


class PlanUnsupported(RuntimeError):
    """A requested mode needs a page the audited image does not contain."""


class ModeFailure(RuntimeError):
    """A mode ran but its evidence did not match the frozen expectation."""


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def need(condition, message):
    if not condition:
        raise ValueError(message)


def manifest(names, root=ROOT):
    return qualification.fingerprint(names, root=root)


def block_count(words):
    return (words + 15) // 16


def read_hex_words(path):
    values = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        need(re.fullmatch('[0-9a-fA-F]{8}', line) is not None, f'{path}: not a 32-bit hex word')
        values.append(int(line, 16))
    return values


def words_bytes(values):
    return struct.pack(f'<{len(values)}I', *values) if values else b''


def f32_to_real(word):
    """The bench's FP32 comparison model (tests/tb_ypcb_jtag_dual.sv), unchanged.

    Fixture oracles never exercise denormals/NaN/inf; the model treats an
    all-zero exponent as 0.0, exactly as the bench does, so hardware and
    simulation comparisons mean the same thing.
    """
    if (word >> 23) & 0xFF == 0:
        value = 0.0
    else:
        exponent = ((word >> 23) & 0xFF) - 127
        mantissa = 1.0
        for bit_index in range(22, -1, -1):
            if (word >> bit_index) & 1:
                mantissa += 2.0 ** (bit_index - 23)
        value = mantissa * (2.0 ** exponent)
    if (word >> 31) & 1:
        value = -value
    return value


def compare_output(observed, expected, words, tolerance):
    """Complete-word comparison with the bench's tolerance semantics."""
    need(len(observed) >= words * 4, 'short output readback')
    need(len(expected) >= words * 4, 'short expected BO')
    mismatched = 0
    worst_abs = 0.0
    first = None
    for index in range(words):
        got = struct.unpack_from('<I', observed, index * 4)[0]
        want = struct.unpack_from('<I', expected, index * 4)[0]
        if got == want:
            continue
        mismatched += 1
        if first is None:
            first = {'word': index, 'got': f'{got:08x}', 'expected': f'{want:08x}'}
        if tolerance:
            diff = abs(f32_to_real(got) - f32_to_real(want))
            if diff > worst_abs:
                worst_abs = diff
    within = mismatched == 0 or (tolerance is not None and tolerance > 0 and worst_abs <= tolerance)
    return {
        'words': words, 'differing_words': mismatched,
        'tolerance_abs': tolerance, 'worst_abs': worst_abs,
        'first_mismatch': first,
        'passed': within,
        'observed_sha256': sha_bytes(observed[:words * 4]),
        'expected_sha256': sha_bytes(expected[:words * 4]),
    }


# ---------------------------------------------------------------------------
# Image catalog and page map
# ---------------------------------------------------------------------------

def parse_page_gate(build_tcl):
    text = Path(build_tcl).read_text()
    matches = PAGE_GATE_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(f'{build_tcl}: expected exactly one page-presence gate')
    names = matches[0].split()
    if not names or len(set(names)) != len(names):
        raise ValueError(f'{build_tcl}: empty or duplicate page gate')
    for name in names:
        if name not in PAGE_MAP:
            raise ValueError(f'{build_tcl}: unrecognized page gate entry {name!r}')
    return names


def scan_image_catalog(root):
    """Return (emitted, rejected) lists of build receipts under one catalog root."""
    emitted, rejected = [], []
    if not root.is_dir():
        return emitted, rejected
    for receipt_path in sorted(root.glob('*/inputs.json')):
        directory = receipt_path.parent
        reasons = []
        try:
            receipt = json.loads(receipt_path.read_text())
        except (OSError, ValueError) as error:
            rejected.append({'receipt': str(receipt_path), 'reasons': [f'unreadable receipt: {error}']})
            continue
        if receipt.get('profile') != 'ypcb_jtag_dual':
            continue
        if receipt.get('status') != 'PASS':
            reasons.append(f"receipt status {receipt.get('status')!r}")
        if receipt.get('bitstream_emitted') is not True:
            reasons.append('bitstream_emitted is not true')
        if receipt.get('hardware_accessed') is not False:
            reasons.append('receipt does not record hardware_accessed=false')
        if receipt.get('top') != 'ypcb_jtag_dual_top':
            reasons.append(f"top {receipt.get('top')!r}")
        if receipt.get('part') != 'xc7k480tffg1156-2':
            reasons.append(f"part {receipt.get('part')!r}")
        bit_name = receipt.get('bitstream')
        bit = directory / 'implementation' / bit_name if isinstance(bit_name, str) else None
        if bit is None or not bit.is_file():
            reasons.append('emitted bitstream file missing')
        elif not MIN_BITSTREAM_BYTES <= bit.stat().st_size <= MAX_BITSTREAM_BYTES:
            reasons.append(f'bitstream size {bit.stat().st_size} outside audited bounds')
        entry = {'stamp': directory.name, 'directory': str(directory),
                 'receipt': str(receipt_path), 'receipt_sha256': sha_file(receipt_path),
                 'top': receipt.get('top'), 'part': receipt.get('part'),
                 'reports': receipt.get('reports') or {},
                 'source_hashes': receipt.get('source_hashes') or {}}
        gate = directory / 'build.tcl'
        if not gate.is_file():
            reasons.append('rendered build.tcl (page gate) missing')
        else:
            try:
                names = parse_page_gate(gate)
            except ValueError as error:
                reasons.append(str(error))
            else:
                entry['page_names'] = names
                entry['page_gate_source'] = str(gate)
                entry['page_gate_sha256'] = sha_file(gate)
                entry['pages'] = [
                    {'name': name, 'base': PAGE_MAP[name][0], 'identity': PAGE_MAP[name][1]}
                    for name in names
                ]
        if bit is not None and bit.is_file():
            entry['bitstream'] = str(bit)
            entry['bitstream_sha256'] = sha_file(bit)
            entry['bitstream_bytes'] = bit.stat().st_size
        if reasons:
            entry['reasons'] = reasons
            rejected.append(entry)
        else:
            emitted.append(entry)
    emitted.sort(key=lambda item: item['stamp'])
    return emitted, rejected


def find_emitted_image(image_sha, catalog_root):
    emitted, rejected = scan_image_catalog(catalog_root)
    matches = [entry for entry in emitted if entry.get('bitstream_sha256') == image_sha]
    if len(matches) != 1:
        known = ', '.join(f"{entry['bitstream_sha256'][:12]}… ({entry['stamp']})" for entry in emitted) or 'none'
        refused = '; '.join(f"{entry['stamp']}: {', '.join(entry['reasons'])}"
                            for entry in rejected[:8]) or 'none'
        raise Refusal(f'--image {image_sha} does not name exactly one real emitted '
                      f'bitstream under {catalog_root} (found {len(matches)}). '
                      f'Emitted images: {known}. Rejected receipts: {refused}')
    return matches[0], emitted, rejected


def source_freshness(image):
    matched, changed, missing = 0, [], []
    for name, recorded in sorted(image['source_hashes'].items()):
        path = ROOT / name
        if not path.is_file():
            missing.append(name)
        elif sha_file(path) == recorded:
            matched += 1
        else:
            changed.append(name)
    return {
        'files_recorded': len(image['source_hashes']),
        'matched': matched,
        'changed_count': len(changed),
        'changed': changed[:40],
        'missing_count': len(missing),
        'missing': missing[:40],
        'current_tree_matches_image_sources': not changed and not missing,
    }


# ---------------------------------------------------------------------------
# Fixture staging and per-mode plans (exactly the simulation replay's loaders)
# ---------------------------------------------------------------------------

def _load(name, base, path, words):
    path = Path(path)
    values = read_hex_words(path)
    blocks = block_count(len(values))
    return {
        'name': name, 'base': base, 'file': path.name, 'path': str(path),
        'sha256': sha_file(path), 'words': len(values), 'bytes': len(values) * 4,
        'blocks': blocks, 'zero_pad_words': blocks * 16 - len(values),
    }


def stage_mode(mode, directory, gemm_case):
    """Stage one mode's BOs with the same loaders/patches as the sim replay."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if mode == 0:
        return {'kind': 'contract'}
    if mode == 1:
        meta = run_jtag_dual.prepare_conv(directory / 'conv')
        return {'kind': 'job', 'case': meta['case'],
                'loads': [
                    _load('command', 0x0000, directory / 'conv/command_words.hex', meta['command_words']),
                    _load('input', 0x1000, directory / 'conv/input_words.hex', meta['input_words']),
                    _load('weight', 0x2000, directory / 'conv/weight_words.hex', meta['weight_words']),
                    _load('output_init', 0x3000, directory / 'conv/output_init_words.hex', meta['output_words']),
                ],
                'expected_file': directory / 'conv/expected_words.hex'}
    if mode == 2:
        meta = run_jtag_dual.prepare_pool(directory / 'pool')
        return {'kind': 'job', 'case': meta['case'],
                'loads': [
                    _load('command', 0x0000, directory / 'pool/command_words.hex', meta['command_words']),
                    _load('input', 0x1000, directory / 'pool/input_words.hex', meta['input_words']),
                    _load('output_init', 0x2000, directory / 'pool/output_init_words.hex', meta['output_words']),
                ],
                'expected_file': directory / 'pool/expected_words.hex'}
    if mode == 3:
        meta = run_jtag_dual.prepare_gemm(directory / 'gemm', gemm_case)
        return {'kind': 'job', 'case': meta['case'],
                'loads': [
                    _load('command', 0x0000, directory / 'gemm/command_words.hex', meta['command_words']),
                    _load('input', 0x1000, directory / 'gemm/input_words.hex', meta['input_words']),
                    _load('weight', 0x2000, directory / 'gemm/weight_words.hex', meta['weight_words']),
                    _load('output_init', 0x3000, directory / 'gemm/output_init_words.hex', meta['output_words']),
                ],
                'expected_file': directory / 'gemm/expected_words.hex'}
    if mode == 4:
        meta = run_jtag_dual.prepare_conv_fp32(directory / 'conv-fp32')
        return {'kind': 'job', 'case': meta['case'],
                'loads': [
                    _load('command', 0x0000, directory / 'conv-fp32/command_words.hex', meta['command_words']),
                    _load('input', 0x1000, directory / 'conv-fp32/input_words.hex', meta['input_words']),
                    _load('weight', 0x2000, directory / 'conv-fp32/weight_words.hex', meta['weight_words']),
                    _load('output_init', 0x3000, directory / 'conv-fp32/output_init_words.hex', meta['output_words']),
                ],
                'expected_file': directory / 'conv-fp32/expected_words.hex'}
    if mode in (5, 6):
        case = ('conv_simple_fp16_5x5_c4_h8_w8_oc16' if mode == 5
                else 'conv_simple_fp16_3x3_c16_h8_w8_oc32')
        sub = 'conv-k5' if mode == 5 else 'conv-c16'
        meta = run_jtag_dual.prepare_conv_profile(directory / sub, case)
        return {'kind': 'job', 'case': meta['case'],
                'output_base': meta['output_base'],
                'loads': [
                    _load('command', 0x0000, directory / sub / 'command_words.hex', meta['command_words']),
                    _load('input', 0x1000, directory / sub / 'input_words.hex', meta['input_words']),
                    _load('weight', 0x2000, directory / sub / 'weight_words.hex', meta['weight_words']),
                    _load('output_init', meta['output_base'],
                          directory / sub / 'output_init_words.hex', meta['output_words']),
                ],
                'expected_file': directory / sub / 'expected_words.hex'}
    raise ValueError(f'invalid mode {mode}')


def _check_region(loads):
    spans = []
    for load in loads:
        start = load['base']
        end = start + load['blocks'] * 64
        need(start % 64 == 0, f"{load['name']}: unaligned BO base")
        need(MEMORY_BASE <= start and end <= MEMORY_END,
             f"{load['name']}: BO range {start:#x}..{end:#x} leaves the memory window")
        spans.append((start, end, load['name']))
    spans.sort()
    for (_, end, name), (start, _, other) in zip(spans, spans[1:]):
        need(end <= start, f'{name} and {other} BO ranges overlap')
    return spans


def build_plan(mode, staged, image, gemm_case):
    """Turn a staged mode into the exact audited hardware execution plan."""
    spec = dict(MODE_SPECS[mode])
    if spec['kind'] == 'contract':
        return {
            'mode': mode, 'kind': 'contract',
            'pages': [dict(page) for page in image['pages']],
            'subchecks': [
                'page identity and ABI for every page in the audited image page map',
                'word round trip through the memory window',
                '64-byte block round trip through the memory window',
                'misaligned 64-byte read is refused with status 4 (no quarantine)',
                f'unmapped read at 0xe000 reports status {ST_DOWNSTREAM} and quarantines',
            ],
            'quarantines_bridge': True,
        }
    page_name = spec['page']
    pages = {page['name']: page for page in image['pages']}
    if page_name not in pages:
        raise PlanUnsupported(f'mode {mode} needs page {page_name}, but image '
                              f"{image['stamp']} contains {sorted(pages)}")
    page = pages[page_name]
    if mode == 3:
        spec['tolerance'] = run_jtag_dual.GEMM_CASES[gemm_case]
    loads = staged['loads']
    if 'output_base' in staged:
        if staged['output_base'] != spec['output_base']:
            raise ValueError(f'mode {mode}: staged output base changed')
    _check_region(loads)
    output_init = next((item for item in loads if item['name'] == 'output_init'), None)
    need(output_init is not None, 'missing output_init BO')
    need(output_init['base'] == spec['output_base'], 'output init is not at the output base')
    need(output_init['words'] == spec['output_words'], 'output init word count changed')
    command = next(item for item in loads if item['name'] == 'command')
    need(spec['amount'] * 8 <= command['words'] * 4, 'descriptor amount exceeds the command BO')
    expected_words = read_hex_words(staged['expected_file'])
    need(len(expected_words) <= spec['output_words'], 'expected BO is larger than the output window')
    expected_padded = expected_words + [0] * (spec['output_words'] - len(expected_words))
    expected_bytes = words_bytes(expected_padded)
    staged_files = {}
    for load in loads:
        staged_files[load['file']] = load['sha256']
    staged_files[Path(staged['expected_file']).name] = sha_file(staged['expected_file'])
    return {
        'mode': mode, 'kind': 'job', 'case': staged['case'],
        'page': page_name, 'page_base': page['base'], 'page_identity': page['identity'],
        'tag': spec['tag'], 'amount': spec['amount'],
        'output_base': spec['output_base'], 'output_words': spec['output_words'],
        'tolerance_abs': spec['tolerance'],
        'loads': loads,
        'expected': {
            'file': Path(staged['expected_file']).name,
            'sha256': sha_file(staged['expected_file']),
            'words_used': len(expected_words),
            'zero_pad_words': spec['output_words'] - len(expected_words),
            'compare_bytes': len(expected_bytes),
        },
        'staged_files': staged_files,
        'expected_bytes': expected_bytes,
        'quarantines_bridge': False,
    }


def plan_summary(plan):
    record = {key: value for key, value in plan.items()
              if key not in ('expected_bytes',)}
    return record


def stage_and_plan(modes, directory, image, gemm_case):
    plans = {}
    for mode in modes:
        staged = stage_mode(mode, Path(directory) / f'mode-{mode}', gemm_case)
        plans[mode] = build_plan(mode, staged, image, gemm_case)
    return plans


# ---------------------------------------------------------------------------
# USER2 mailbox session (wire mechanics of tools/host/transport.py)
# ---------------------------------------------------------------------------

class MailboxSession:
    """One owner of the 640-bit USER2 mailbox on an already verified raw link.

    This mirrors ``transport.JtagTransport._command`` exactly for the fields it
    uses (frame layout, sequence wrap, magic/reserved checks, response payload
    rules, quarantine statuses). It cannot reuse ``JtagTransport`` itself
    because that class hard-wires the RKEW register map at offsets 0..0x24,
    while this image exposes page registers above 0x8000.
    """

    def __init__(self, link, *, timeout=30.0, clock=time.monotonic, sleep=time.sleep):
        self.link = link
        self.timeout = float(timeout)
        self._clock = clock
        self._sleep = sleep
        self._mutex = threading.RLock()
        self._seq = 0
        self._failed = False
        self._verified = False
        self.quarantined = False
        self.attached = False
        self.commands = 0
        self.scans = 0
        self.polls = 0
        self.ops = []
        self.attach_identity = None

    def _check_response(self, response):
        if (response >> 536) & 0xFFFFFFFF != MAGIC or response >> 568:
            raise transport.ProtocolError('Invalid USER2 response magic or reserved bits')

    @property
    def failed(self):
        return self._failed

    def _usable(self):
        if self._failed:
            raise transport.ProtocolError('USER2 owner is closed or poisoned; joint recovery is required')
        if self.quarantined:
            raise transport.ProtocolError('USER2 bridge is quarantined; reconfiguration is required')

    def attach(self):
        """TAP reset (not fabric reset), IDCODE, then select USER2 and verify magic."""
        with self._mutex:
            self._usable()
            try:
                self.link.reset()
                self.link.scan(0x09, 6, ir=True)
                ident = self.link.scan(0, 32)
                if ident != IDCODE:
                    raise transport.ProtocolError(
                        f'Expected single XC7K480T TAP {IDCODE:#010x}, got {ident:#010x}')
                self.link.scan(0x03, 6, ir=True)
                response = self.link.scan(0, transport.FRAME_BITS)
                self._check_response(response)
                self._seq = (response >> 520) & 0xFFFF
                self.attached = True
                self.attach_identity = {
                    'idcode': f'{ident:08x}',
                    'frame_bits': transport.FRAME_BITS,
                    'initial_sequence': self._seq,
                    'actual_tck_frequency_hz': getattr(self.link, 'actual_frequency_hz', None),
                    'actual_tck_period_ns': self._period_record(),
                }
                return self.attach_identity
            except BaseException:
                self._failed = True
                raise

    def _period_record(self):
        period = getattr(self.link, 'actual_period_ns', None)
        if period is None:
            return None
        try:
            return {'numerator': period.numerator, 'denominator': period.denominator}
        except AttributeError:
            return str(period)

    def close(self):
        with self._mutex:
            self._failed = True
            close = getattr(self.link, 'close', None)
            if close is not None:
                close()

    def _deadline(self):
        return transport._Deadline(self.timeout, self._clock)

    def command(self, opcode, address, data=0, *, expected_status=ST_OK):
        """One mailbox request; returns the 512-bit response payload."""
        need(type(opcode) is int and 1 <= opcode <= 4, 'opcode must be 1..4')
        transport._uint(address, 32, 'mailbox address')
        transport._uint(data, 512, 'mailbox data')
        if opcode in (1, 3):
            need(data == 0, 'read opcodes require zero data')
        with self._mutex:
            self._usable()
            if opcode in (2, 4) and not self._verified:
                raise transport.ProtocolError('Page identity must be verified before writes')
            deadline = self._deadline()
            try:
                self._seq = self._seq % 65535 + 1
                sequence = self._seq
                frame = (data | address << 512 | 0xF << 544 | opcode << 548 |
                         sequence << 556 | MAGIC << 572)
                self.link.scan(frame)
                self.scans += 1
                polls = 0
                while True:
                    deadline.remaining()
                    response = self.link.scan(0)
                    self.scans += 1
                    self._check_response(response)
                    if (response >> 520) & 0xFFFF == sequence:
                        break
                    polls += 1
                    self._sleep(min(0.001, deadline.remaining()))
                status = (response >> 512) & 0xFF
                value = response & ((1 << 512) - 1)
                self.polls += polls
                self.commands += 1
                envelope = {
                    'index': self.commands, 'opcode': opcode, 'address': f'{address:#010x}',
                    'sequence': sequence, 'status': status, 'expected_status': expected_status,
                    'polls': polls,
                    'data_sha256': sha_bytes(data.to_bytes(64, 'little')) if opcode in (2, 4) else None,
                    'response_sha256': sha_bytes(value.to_bytes(64, 'little')),
                }
                self.ops.append(envelope)
                if status != expected_status:
                    self._failed = True
                    if status in QUARANTINE_STATUSES:
                        self.quarantined = True
                    raise transport.MailboxError(opcode, address, status)
                if expected_status != ST_OK:
                    if status in QUARANTINE_STATUSES:
                        self.quarantined = True
                    if value:
                        raise transport.ProtocolError('Nonzero payload on expected-error response')
                    return value
                if opcode == 1 and value >> 32:
                    raise transport.ProtocolError('Unexpected register-read payload')
                if opcode in (2, 4) and value:
                    raise transport.ProtocolError('Unexpected write response payload')
                return value
            except BaseException:
                self._failed = True
                raise

    # Register helpers -----------------------------------------------------
    def reg_read(self, offset):
        return self.command(1, offset)

    def read_word(self, offset):
        return self.reg_read(offset) & 0xFFFFFFFF

    def reg_write(self, offset, value):
        transport._uint(value, 32, 'register value')
        self.command(2, offset, value)

    def write_word(self, offset, value):
        self.reg_write(offset, value)

    def read_block(self, address):
        return self.command(3, address).to_bytes(64, 'little')

    def write_block(self, address, payload):
        need(isinstance(payload, (bytes, bytearray)) and len(payload) == 64,
             'block payload must be exactly 64 bytes')
        self.command(4, address, int.from_bytes(bytes(payload), 'little'))

    # BO helpers -----------------------------------------------------------
    def write_bo(self, base, words):
        """Write ceil(words/16) full blocks, zero-padding the final block as the bench does."""
        need(base % 64 == 0, 'BO base must be 64-byte aligned')
        transport._uint(base, 32, 'BO base')
        need(base + block_count(len(words)) * 64 <= MEMORY_END, 'BO leaves the memory window')
        for block in range(block_count(len(words))):
            chunk = words[block * 16:(block + 1) * 16]
            chunk = chunk + [0] * (16 - len(chunk))
            self.write_block(base + block * 64, words_bytes(chunk))

    def read_bo(self, base, words):
        need(words % 16 == 0, 'complete BO readback requires a whole number of blocks')
        need(base % 64 == 0, 'BO base must be 64-byte aligned')
        data = bytearray()
        for block in range(words // 16):
            data.extend(self.read_block(base + block * 64))
        return bytes(data)

    def poll_status(self, offset, mask, want, timeout, what):
        deadline = self._clock() + timeout
        while True:
            status = self.read_word(offset)
            if (status & mask) == want:
                return status
            if status & (1 << 5):
                raise ModeFailure(f'{what}: page engine error, status {status:#05x}')
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise ModeFailure(f'{what}: timeout, last status {status:#05x}')
            self._sleep(min(0.001, remaining))


# ---------------------------------------------------------------------------
# Image/plan preflight shared by --check and hardware runs
# ---------------------------------------------------------------------------

def parse_target(target):
    match = TARGET_RE.fullmatch(target)
    if match is None:
        raise ValueError('--target must be an exact local cable URI of the form '
                         'localhost:PORT/xilinx_tcf/Xilinx/<16 hex serial>')
    server = match['server']
    server_match = re.fullmatch(r'(?:localhost|127\.0\.0\.1):([1-9][0-9]{0,4})', server)
    if server_match is None or not 1 <= int(server_match[1]) <= 65535:
        raise ValueError('--target server must be the locally owned hw_server '
                         '(localhost:PORT or 127.0.0.1:PORT)')
    return {'uri': target, 'server': server, 'port': int(server_match[1]),
            'serial': match['serial']}


def validate_lease(path):
    lease = Path(path)
    need(lease.is_absolute(), '--lease must be an absolute path')
    need(lease.parent.is_dir(), f'--lease parent directory does not exist: {lease.parent}')
    return {'path': str(lease), 'exists': lease.is_file(), 'size': lease.stat().st_size if lease.is_file() else None}


def selected_modes(args):
    modes = list(args.mode) if args.mode else sorted(MODE_SPECS)
    if len(set(modes)) != len(modes):
        raise ValueError('--mode must not repeat')
    return modes


def validate_source_tag(value):
    if value is None:
        raise ValueError('--source-tag is required for hardware runs: 8 hex digits, or "none" '
                         'for an image built without BITSTREAM.CONFIG.USR_ACCESS')
    if value == 'none':
        return {'present': False, 'expected_usr_access': '00000000'}
    if not SOURCE_TAG_RE.fullmatch(value):
        raise ValueError('--source-tag must be 8 lowercase hex digits or "none"')
    return {'present': True, 'expected_usr_access': value}


def tool_versions(probe):
    record = {
        'python': platform.python_version(),
        'python_implementation': platform.python_implementation(),
        'paths': {name: shutil.which(name) for name in
                  ('vivado', 'hw_server', 'openFPGALoader', 'fxload', 'lsusb', 'ss', 'fuser')},
    }
    if not probe:
        return record
    vivado = record['paths'].get('vivado') or str(ROOT.parent / 'vivado/2026.1/Vivado/bin/vivado')
    probes = {'vivado': [vivado, '-version']}
    if record['paths'].get('openFPGALoader'):
        probes['openFPGALoader'] = [record['paths']['openFPGALoader'], '-V']
    for name, argv in probes.items():
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
            first = (result.stdout or result.stderr).strip().splitlines()
            record[name] = first[0] if result.returncode == 0 and first else 'unavailable'
        except (OSError, subprocess.SubprocessError) as error:
            record[name] = f'unavailable: {error}'
    return record


def preflight(args, *, for_hardware):
    """Validate every audited input and build the plan. No hardware touched."""
    if not IMAGE_RE.fullmatch(args.image):
        raise ValueError('--image must be a lowercase 64-digit SHA-256')
    for name in ('bridge_timeout', 'job_timeout'):
        value = getattr(args, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
            raise ValueError(f'--{name.replace("_", "-")} must be finite and positive')
    if type(args.bridge_port) is not int or not 1 <= args.bridge_port <= 65535:
        raise ValueError('--bridge-port must be in 1..65535')
    target = parse_target(args.target)
    lease = validate_lease(args.lease)
    modes = selected_modes(args)
    image, emitted, rejected = find_emitted_image(args.image, Path(args.catalog_root))
    image['source_freshness'] = source_freshness(image)
    plan_dir = Path(args.stage_dir) if getattr(args, 'stage_dir', None) else None
    if plan_dir is None:
        plan_dir = Path(tempfile.mkdtemp(prefix='jtag-dual-hw-plan-'))
    plans = {}
    blockers = []
    for mode in modes:
        try:
            staged = stage_mode(mode, plan_dir / f'mode-{mode}', args.gemm_case)
            plans[mode] = build_plan(mode, staged, image, args.gemm_case)
        except PlanUnsupported as error:
            blockers.append(str(error))
    if for_hardware:
        tag = validate_source_tag(args.source_tag)
    else:
        tag = ({'present': False, 'expected_usr_access': '00000000'}
               if args.source_tag is None else validate_source_tag(args.source_tag))
    return {
        'image': image, 'plans': plans, 'blockers': blockers, 'modes': modes,
        'target': target, 'lease': lease, 'source_tag': tag,
        'catalog': {'root': str(Path(args.catalog_root)), 'emitted': len(emitted),
                    'rejected': len(rejected),
                    'emitted_images': [
                        {'stamp': entry['stamp'], 'bitstream_sha256': entry['bitstream_sha256'],
                         'page_names': entry.get('page_names')} for entry in emitted]},
        'stage_dir': plan_dir,
    }


# ---------------------------------------------------------------------------
# Local process/hardware preconditions (hardware runs only)
# ---------------------------------------------------------------------------

def check_controllers():
    found = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            comm = (proc / 'comm').read_text().strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if comm in FORBIDDEN_CONTROLLERS:
            found.append({'pid': int(proc.name), 'name': comm})
    need(not found, f'Other cable/controller processes are running: {found}')
    existing = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            comm = (proc / 'comm').read_text().strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if comm == 'hw_server':
            existing.append({'pid': int(proc.name), 'name': comm})
    need(not existing, f'Another hw_server is already running: {existing}. '
                       'Stop it; this tool owns its own server, or check whether it is yours.')
    return {'forbidden_controller_processes': found, 'preexisting_hw_servers': existing,
            'checked_utc': utc_now()}


def check_ports(server_port, bridge_port):
    ports = sorted({server_port, bridge_port} | {3121, 3721, 3741})
    busy = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                busy.append(port)
    need(not busy, f'Hardware debug/bridge port(s) already listening: {busy}')
    return {'checked_ports': ports, 'listening': busy}


def check_cable():
    def usb_devices(identifier):
        try:
            result = subprocess.run(['lsusb', '-d', identifier], capture_output=True,
                                    text=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            raise Refusal(f'Cannot enumerate USB devices with lsusb: {error}') from error
        return [line for line in result.stdout.splitlines() if line.strip()]

    lines = usb_devices('03fd:0008')
    if len(lines) != 1:
        if usb_devices('03fd:0013'):
            raise Refusal('The DLC10 cable is present but not initialized (03fd:0013). '
                          'Run "bash ~/ypcb/dlc10-init.sh" as a separate authorized cable-init '
                          'step; it must report IDCODE 0x23751093. This tool never writes cable RAM.')
        raise Refusal('Expected exactly one initialized DLC10 (03fd:0008) on USB; found '
                      f'{len(lines)}. Plug in the Xilinx Platform Cable USB II and initialize it '
                      'with "bash ~/ypcb/dlc10-init.sh".')
    match = re.fullmatch(r'Bus (\d{3}) Device (\d{3}): ID 03fd:0008.*', lines[0])
    need(match is not None, f'Unrecognized DLC10 lsusb line: {lines[0]!r}')
    node = f'/dev/bus/usb/{match[1]}/{match[2]}'
    record = {'lsusb': lines[0], 'usb_node': node, 'node_present': Path(node).exists(),
              'note': 'fuser is recorded read-only; the owned hw_server may or may not hold the node'}
    try:
        fuser = subprocess.run(['fuser', node], capture_output=True, text=True, timeout=15, check=False)
        record.update(fuser_returncode=fuser.returncode,
                      fuser_stdout=fuser.stdout.strip(),
                      fuser_stderr=(fuser.stderr or '').strip()[:400])
    except (OSError, subprocess.SubprocessError) as error:
        record['fuser_unavailable'] = str(error)
    return record


def acquire_lease(path):
    lease = Path(path)
    fd = os.open(lease, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise Refusal(f'Shared JTAG lease is already held: {lease}; no hardware access was attempted')
    except BaseException:
        os.close(fd)
        raise
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f'{os.getpid()}\n'.encode())
    except BaseException:
        os.close(fd)
        raise
    return fd


def release_lease(fd, path):
    if fd is None:
        return
    try:
        os.ftruncate(fd, 0)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def wait_port(port, deadline, child=None):
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                return True
        if child is not None and child.poll() is not None:
            raise RuntimeError(f'owned process exited before port {port} was ready')
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def start_owned(argv, log_path, cwd):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open('w')
    try:
        child = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, cwd=cwd,
                                 start_new_session=True)
    finally:
        log.close()
    return child


def stop_owned(child, *, graceful=True):
    """Stop one owned process group; returns (returncode, forced)."""
    if child is None:
        return None, False
    if child.poll() is not None:
        return child.returncode, False
    try:
        os.killpg(child.pid, signal.SIGTERM if graceful else signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        return child.wait(timeout=15), False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return child.wait(timeout=15), True


# ---------------------------------------------------------------------------
# Native Vivado bridge (owned hw_server + Tcl numeric-scan RPC)
# ---------------------------------------------------------------------------

def run_bridge_hardware(args, target, image, source_tag, out):
    """Launch owned hw_server, render/launch the native bridge. Returns session context."""
    tools = tool_versions(probe=True)
    vivado = tools['paths'].get('vivado') or str(Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado'))
    hw_server = tools['paths'].get('hw_server') or str(Path(vivado).with_name('hw_server'))
    need(Path(vivado).is_file(), f'Vivado executable not found: {vivado}')
    need(Path(hw_server).is_file(), f'hw_server executable not found: {hw_server}')
    bridge_dir = Path(out) / 'bridge'
    bridge_dir.mkdir(parents=True, exist_ok=True)
    record = {'argv_hw_server': [hw_server, '-s', f"tcp::{target['port']}"],
              'argv_vivado': None, 'tcl_sha256': None, 'ready_marker': None,
              'log': str(bridge_dir / 'bridge-stdout.log'),
              'template': 'fpga/host/native_rpc.tcl.in',
              'template_sha256': sha_file(ROOT / 'fpga/host/native_rpc.tcl.in'),
              'source_tag': source_tag}
    server_proc = None
    bridge_proc = None
    link = None
    try:
        server_proc = start_owned(record['argv_hw_server'], bridge_dir / 'hw-server.log', bridge_dir)
        deadline = time.monotonic() + 30
        if not wait_port(target['port'], deadline, server_proc):
            raise RuntimeError('owned hw_server did not start listening within 30 s')
        record['hw_server_pid'] = server_proc.pid
        ready_path = bridge_dir / 'ready.txt'
        if ready_path.exists():
            ready_path.unlink()
        script = bridge_dir / 'bridge.tcl'
        script.write_text(native_link.render_bridge(
            target['uri'], target['server'], source_tag['expected_usr_access'],
            str(ready_path), args.bridge_port))
        record['tcl_sha256'] = sha_file(script)
        record['argv_vivado'] = [vivado, '-mode', 'batch', '-nojournal', '-nolog',
                                 '-notrace', '-source', str(script)]
        bridge_proc = start_owned(record['argv_vivado'], bridge_dir / 'bridge-stdout.log', bridge_dir)
        record['bridge_pid'] = bridge_proc.pid
        deadline = time.monotonic() + args.bridge_timeout
        while not ready_path.exists():
            if bridge_proc.poll() is not None:
                tail = (bridge_dir / 'bridge-stdout.log').read_text()[-4000:]
                raise RuntimeError(f'native bridge exited before READY (rc={bridge_proc.returncode}): {tail}')
            if time.monotonic() >= deadline:
                raise RuntimeError(f'native bridge READY timeout after {args.bridge_timeout} s')
            time.sleep(0.1)
        marker = ready_path.read_text().strip()
        record['ready_marker'] = marker
        need(marker == 'PASS_AUDITED_NATIVE_USER2_BRIDGE_READY',
             f'Unexpected native bridge READY marker: {marker!r}')
        record['ready_file_sha256'] = sha_file(ready_path)
        link = native_link.NativeLink(host='127.0.0.1', port=args.bridge_port, timeout=30.0)
        record['native_link'] = {'host': '127.0.0.1', 'port': args.bridge_port,
                                 'actual_tck_frequency_hz': link.actual_frequency_hz,
                                 'actual_period_ns': {'numerator': link.actual_period_ns.numerator,
                                                      'denominator': link.actual_period_ns.denominator}}
        return {'record': record, 'tools': tools, 'link': link,
                'server_proc': server_proc, 'bridge_proc': bridge_proc,
                'bridge_dir': bridge_dir, 'ready_path': ready_path}
    except BaseException:
        if bridge_proc is not None:
            stop_owned(bridge_proc)
        if link is not None:
            try:
                link.close()
            except BaseException:
                pass
        stop_owned(server_proc)
        raise


def close_bridge_hardware(context, session=None):
    """Orderly bridge QUIT, owned-server stop. Never resets the fabric."""
    record = context['record']
    link = context.get('link')
    cleanup = {}
    try:
        if link is not None:
            try:
                link.shutdown_bridge()
                cleanup['bridge_quit_ack'] = True
            except BaseException as error:
                cleanup['bridge_quit_error'] = str(error)
            try:
                link.close()
            except BaseException:
                pass
        if session is not None:
            try:
                session.close()
            except BaseException as error:
                cleanup['session_close_error'] = str(error)
        bridge = context['bridge_proc']
        try:
            cleanup['bridge_returncode'] = bridge.wait(timeout=20)
        except subprocess.TimeoutExpired:
            rc, forced = stop_owned(bridge)
            cleanup['bridge_returncode'] = rc
            cleanup['bridge_forced_termination'] = forced
        log_path = context['bridge_dir'] / 'bridge-stdout.log'
        if log_path.is_file():
            text = log_path.read_text()
            cleanup['bridge_log_sha256'] = sha_file(log_path)
            cleanup['bridge_clean_exit_marker'] = 'PASS_NATIVE_USER2_BRIDGE_CLEAN_EXIT' in text
            cleanup['bridge_log_tail'] = text[-1500:]
        rc, forced = stop_owned(context['server_proc'])
        cleanup['owned_hw_server_exit'] = rc
        cleanup['owned_hw_server_forced_termination'] = forced
        hw_log = context['bridge_dir'] / 'hw-server.log'
        if hw_log.is_file():
            cleanup['hw_server_log_sha256'] = sha_file(hw_log)
    finally:
        record['cleanup'] = cleanup
        record['bridge_clean_quit'] = bool(cleanup.get('bridge_quit_ack')) and \
            bool(cleanup.get('bridge_clean_exit_marker', False))
        record['owned_hw_server_stopped'] = cleanup.get('owned_hw_server_exit') in (0, -15, -9, None)
        record['fabric_reset'] = False
        record['fabric_programmed'] = False
        record['flash_written'] = False
    return cleanup


# ---------------------------------------------------------------------------
# Mode execution (hardware)
# ---------------------------------------------------------------------------

def check_page_identities(session, image):
    """Verify every page in the audited image map; sets session write permission."""
    checks = []
    for page in image['pages']:
        identity = session.read_word(page['base'] + 0x00)
        abi = session.read_word(page['base'] + 0x04)
        checks.append({'page': page['name'], 'base': page['base'],
                       'identity': f'{identity:08x}', 'expected_identity': f"{page['identity']:08x}",
                       'abi': f'{abi:08x}', 'expected_abi': f'{ABI_VERSION:08x}',
                       'passed': identity == page['identity'] and abi == ABI_VERSION})
        need(identity == page['identity'],
             f"{page['name']} identity is {identity:08x}, expected {page['identity']:08x}")
        need(abi == ABI_VERSION, f"{page['name']} ABI is {abi:08x}, expected {ABI_VERSION:08x}")
    session._verified = True
    return checks


def write_page_descriptor(session, plan):
    page = plan['page_base']
    session.poll_status(page + 0x08, (1 << 1) | (1 << 2) | (1 << 5) | (1 << 6) | 0x700,
                        0, DEFAULT_JOB_TIMEOUT, f"mode {plan['mode']} pre-descriptor idle")
    session.write_word(page + 0x10, 0x00000000)
    session.write_word(page + 0x14, plan['amount'])
    session.write_word(page + 0x18, plan['tag'])
    status = session.poll_status(page + 0x08, 1 << 0, 1 << 0, DEFAULT_JOB_TIMEOUT,
                                 f"mode {plan['mode']} can_submit")
    return status


def wait_completion(session, page, mode, timeout):
    """Poll the page STATUS for result_valid, failing fast on result_error."""
    deadline = session._clock() + timeout
    while True:
        status = session.read_word(page + 0x08)
        if status & (1 << 3):
            tag = session.read_word(page + 0x1c)
            tasks = session.read_word(page + 0x20)
            code = session.read_word(page + 0x24)
            raise ModeFailure(f'mode {mode}: page result_error, tag {tag:08x} '
                              f'tasks {tasks} error_code {code}')
        if status & (1 << 2):
            return status
        remaining = deadline - session._clock()
        if remaining <= 0:
            raise ModeFailure(f'mode {mode}: completion timeout, last status {status:#05x}')
        session._sleep(min(0.001, remaining))


def run_job_mode(session, plan, receipt_dir):
    result = {'mode': plan['mode'], 'kind': plan['kind'], 'status': 'RUNNING',
              'case': plan['case'], 'page': plan['page'], 'page_base': plan['page_base'],
              'tag': f"{plan['tag']:08x}", 'amount': plan['amount'],
              'output_base': plan['output_base'], 'output_words': plan['output_words'],
              'tolerance_abs': plan['tolerance_abs'], 'loads': [], 'load_results': []}
    ops_before = len(session.ops)
    commands_before = session.commands
    result['ops_start'] = ops_before
    try:
        for load in plan['loads']:
            values = read_hex_words(load['path'])
            session.write_bo(load['base'], values)
            result['loads'].append({
                'name': load['name'], 'base': load['base'], 'words': len(values),
                'bytes': len(values) * 4, 'blocks': block_count(len(values)),
                'zero_pad_words': load['zero_pad_words'],
                'file_sha256': load['sha256'],
                'readback_sha256': None,
                'readback_matches': None,
            })
        # Read every loaded BO back before launch; a failed load must be visible.
        for entry, load in zip(result['loads'], plan['loads']):
            values = read_hex_words(load['path'])
            padded = values + [0] * (entry['blocks'] * 16 - len(values))
            observed = session.read_bo(load['base'], entry['blocks'] * 16)
            expected = words_bytes(padded)
            entry['readback_sha256'] = sha_bytes(observed)
            entry['readback_matches'] = observed == expected
            need(entry['readback_matches'], f"mode {plan['mode']}: {entry['name']} BO loadback mismatch")
        status = write_page_descriptor(session, plan)
        result['descriptor_status'] = f'{status:#05x}'
        session.write_word(plan['page_base'] + 0x0c, 1)
        result['submitted_utc'] = utc_now()
        completed = wait_completion(session, plan['page_base'], plan['mode'], DEFAULT_JOB_TIMEOUT)
        result['completion_status'] = f'{completed:#05x}'
        tag = session.read_word(plan['page_base'] + 0x1c)
        tasks = session.read_word(plan['page_base'] + 0x20)
        code = session.read_word(plan['page_base'] + 0x24)
        result['result'] = {'tag': f'{tag:08x}', 'tasks': tasks, 'error_code': code,
                            'tag_matches': tag == plan['tag'], 'tasks_expected': 1}
        need(tag == plan['tag'], f"mode {plan['mode']}: result tag {tag:08x} != {plan['tag']:08x}")
        need(tasks == 1, f"mode {plan['mode']}: completed tasks {tasks}, expected 1")
        need(code == 0, f"mode {plan['mode']}: engine error code {code}")
        observed = session.read_bo(plan['output_base'], plan['output_words'])
        comparison = compare_output(observed, plan['expected_bytes'],
                                    plan['output_words'], plan['tolerance_abs'])
        result['compare'] = comparison
        result['observed_file'] = f"mode-{plan['mode']}-output.bin"
        (Path(receipt_dir) / result['observed_file']).write_bytes(observed)
        result['observed_file_sha256'] = sha_bytes(observed)
        need(comparison['passed'], f"mode {plan['mode']}: complete BO compare failed "
                                   f"({comparison['differing_words']} words, worst {comparison['worst_abs']})")
        # ACK only after the complete owned BO readback and comparison succeed.
        session.write_word(plan['page_base'] + 0x0c, 2)
        cleared = session.poll_status(plan['page_base'] + 0x08, (1 << 2) | (1 << 3), 0,
                                      DEFAULT_JOB_TIMEOUT, f"mode {plan['mode']} acknowledge")
        result['ack'] = {'written': True, 'status_after': f'{cleared:#05x}',
                         'completion_cleared': not (cleared & ((1 << 2) | (1 << 3)))}
        result['frames'] = session.commands - commands_before
        result['ops_written'] = len(session.ops) - ops_before
        result['status'] = 'PASS'
        result['pass_marker'] = f"PASS YPCB_JTAG_DUAL_HARDWARE mode={plan['mode']} frames={result['frames']}"
        return result
    except BaseException as error:
        result['status'] = 'FAIL'
        result['failure'] = str(error)
        result['frames'] = session.commands - commands_before
        result['ops_written'] = len(session.ops) - ops_before
        raise
    finally:
        (Path(receipt_dir) / f"mode-{plan['mode']}.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + '\n')


def run_contract_mode(session, plan, image):
    result = {'mode': 0, 'kind': 'contract', 'status': 'RUNNING',
              'pages': [], 'round_trips': {}, 'negative_checks': {},
              'quarantines_bridge': True}
    commands_before = session.commands
    result['ops_start'] = len(session.ops)
    try:
        result['pages'] = check_page_identities(session, image)
        session.write_word(0x00000100, 0xCAFE1234)
        value = session.read_word(0x00000100)
        result['round_trips']['word'] = {'address': '0x00000100', 'wrote': 'cafe1234',
                                         'read': f'{value:08x}', 'passed': value == 0xCAFE1234}
        need(value == 0xCAFE1234, 'word round trip failed')
        payload = [(0xA5A50000 + index) for index in range(16)]
        session.write_block(0x00000140, words_bytes(payload))
        observed = session.read_block(0x00000140)
        expected = words_bytes(payload)
        result['round_trips']['block'] = {'address': '0x00000140', 'bytes': 64,
                                          'passed': observed == expected,
                                          'observed_sha256': sha_bytes(observed),
                                          'expected_sha256': sha_bytes(expected)}
        need(observed == expected, 'block round trip failed')
        try:
            session.command(3, 0x00000122, expected_status=ST_ALIGN)
            result['negative_checks']['misaligned_block'] = {'status': ST_ALIGN, 'passed': True}
        except transport.MailboxError as error:
            result['negative_checks']['misaligned_block'] = {'status': error.status, 'passed': False}
            raise ModeFailure(f'misaligned block read returned status {error.status}, expected {ST_ALIGN}') from error
        try:
            session.command(1, 0x0000E000, expected_status=ST_DOWNSTREAM)
            result['negative_checks']['unmapped_read'] = {'status': ST_DOWNSTREAM, 'passed': True}
        except transport.MailboxError as error:
            result['negative_checks']['unmapped_read'] = {'status': error.status, 'passed': False}
            raise ModeFailure(f'unmapped read returned status {error.status}, expected {ST_DOWNSTREAM}') from error
        result['quarantine_observed'] = session.quarantined
        need(session.quarantined, 'downstream error did not quarantine the bridge')
        # Documented consequence: no further request may be shifted.
        scans_before = session.scans
        try:
            session.read_word(0x00000000)
        except transport.ProtocolError:
            pass
        else:
            raise ModeFailure('quarantined bridge accepted another request')
        need(session.scans == scans_before, 'quarantined bridge issued another scan')
        result['quarantine_recovery'] = ('volatile image reload (reconfiguration) is required; '
                                         'there is no reset opcode')
        result['frames'] = session.commands - commands_before
        result['status'] = 'PASS'
        result['pass_marker'] = f"PASS YPCB_JTAG_DUAL_HARDWARE mode=0 frames={result['frames']}"
        result['note'] = ('The audited page map of this image is verified; absent pages are not '
                          'probed because a downstream error would quarantine the bridge before '
                          'the rest of the contract ran. Mode 0 always runs last.')
        return result
    except BaseException as error:
        result['status'] = 'FAIL'
        result['failure'] = str(error)
        result['frames'] = session.commands - commands_before
        raise
    finally:
        (Path(plan['receipt_dir']) / 'mode-0.json').write_text(
            json.dumps(result, indent=2, sort_keys=True) + '\n')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--image', required=True,
                        help='SHA-256 of the exact bitstream already loaded on the card; must '
                             'match a real emitted PASS receipt in the image catalog')
    parser.add_argument('--target', required=True, default=None,
                        help='exact audited cable URI, e.g. '
                             'localhost:3125/xilinx_tcf/Xilinx/80802026a77a01')
    parser.add_argument('--lease', required=True,
                        help='shared YPCB JTAG lease path (exclusive nonblocking flock)')
    parser.add_argument('--authorized', action='store_true',
                        help='explicit authorization for hardware access and mailbox writes; '
                             'hardware runs refuse without it')
    parser.add_argument('--authorization-note', default='',
                        help='who authorized this run (recorded verbatim in the receipt)')
    parser.add_argument('--source-tag', default=None,
                        help='8-hex USR_ACCESS tag of the loaded image, or "none" when the '
                             'bitstream carries no BITSTREAM.CONFIG.USR_ACCESS; required for '
                             'hardware runs')
    parser.add_argument('--mode', type=int, action='append', default=None,
                        choices=tuple(MODE_SPECS),
                        help='mode to run (repeatable); default all 0..6. Mode 0 always runs '
                             'last and quarantines the bridge at its end')
    parser.add_argument('--gemm-case', choices=tuple(run_jtag_dual.GEMM_CASES),
                        default='gemm_m2_n2_k1',
                        help='frozen GEMM capture staged for mode 3 (amount/tag are fixed)')
    parser.add_argument('--check', action='store_true',
                        help='offline validation of fixtures/plan/args; no lease, USB, network, '
                             'hw_server or Vivado is touched')
    parser.add_argument('--out', type=Path, default=None,
                        help='fresh output directory (default build/board-prep/<UTC>-<kind>)')
    parser.add_argument('--catalog-root', type=Path, default=IMAGE_CATALOG,
                        help='build receipt catalog searched for the emitted bitstream')
    parser.add_argument('--bridge-port', type=int, default=DEFAULT_BRIDGE_PORT)
    parser.add_argument('--bridge-timeout', type=float, default=DEFAULT_BRIDGE_TIMEOUT)
    parser.add_argument('--job-timeout', type=float, default=DEFAULT_JOB_TIMEOUT)
    parser.add_argument('--probe-tool-versions', action='store_true',
                        help='in --check, also run offline "vivado -version" and '
                             '"openFPGALoader -V" and record them')
    return parser


def _default_out(kind):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return ROOT / 'build/board-prep' / f'{stamp}-{kind}'


def _fresh_directory(path):
    path = Path(path)
    need(not path.exists(), f'--out must name a fresh directory; it exists: {path}')
    path.mkdir(parents=True)
    return path


def _receipt_base(args, kind):
    return {
        'schema': 1, 'tool': TOOL, 'kind': kind,
        'started_utc': utc_now(), 'finished_utc': None,
        'status': 'RUNNING',
        'hardware_accessed': False, 'network_accessed': False,
        'vivado_executed': False, 'hw_server_started': False,
        'fabric_programmed': False, 'fabric_reset': False,
        'configuration_written': False, 'flash_written': False,
        'bitstream_written': False, 'image_loaded_by_this_tool': False,
        'lease_acquired': False, 'authorized': bool(getattr(args, 'authorized', False)),
        'authorization_note': getattr(args, 'authorization_note', ''),
        'command': getattr(args, 'command', sys.argv),
    }


def check_main(args):
    out = _fresh_directory(args.out or _default_out('check'))
    receipt = _receipt_base(args, 'check')
    receipt.update({'check_only': True, 'stage_dir': str(out / 'staged')})
    receipt_path = out / 'receipt.json'
    write_json(receipt_path, receipt)
    try:
        args.stage_dir = str(out / 'staged')
        result = preflight(args, for_hardware=False)
        receipt.update({
            'image': result['image'], 'target': result['target'], 'lease': result['lease'],
            'source_tag': result['source_tag'], 'catalog': result['catalog'],
            'modes': result['modes'],
            'plans': {str(mode): plan_summary(plan) for mode, plan in result['plans'].items()},
            'blockers': result['blockers'],
            'tools': tool_versions(probe=args.probe_tool_versions),
            'source_hashes_before': manifest(TRACKED_INPUTS),
            'offline_guarantees': {
                'lease_opened': False, 'usb_enumerated': False,
                'socket_opened': False,
                'subprocess_launched': bool(args.probe_tool_versions),
                'subprocess_scope': 'offline tool version probes only' if args.probe_tool_versions else 'none',
                'vivado_or_hw_server_started': False,
            },
        })
        receipt['source_hashes_after'] = receipt['source_hashes_before']
        if result['blockers']:
            receipt['status'] = 'CHECK_BLOCKED'
            print('CHECK_BLOCKED: ' + '; '.join(result['blockers']), file=sys.stderr)
            for mode, plan in sorted(result['plans'].items()):
                print(f"MODE {mode}: {plan['kind']}"
                      + (f" page={plan.get('page')}" if plan.get('kind') == 'job' else ''))
            return 1
        receipt['status'] = 'PASS_CHECK'
        for mode, plan in sorted(result['plans'].items()):
            detail = (f"page={plan['page']} loads={len(plan['loads'])} "
                      f"output_words={plan['output_words']} tolerance={plan['tolerance_abs']}"
                      if plan['kind'] == 'job' else 'contract')
            print(f'MODE {mode}: {plan["kind"]} {detail}')
        print(f"PASS YPCB_JTAG_DUAL_HARDWARE --check image={args.image[:12]}… "
              f"pages={len(result['image']['pages'])} modes={result['modes']} "
              f"hardware_accessed=false receipt={receipt_path}")
        return 0
    except (Refusal, ValueError) as error:
        receipt['status'] = 'CHECK_FAILED'
        receipt['failure'] = str(error)
        print(f'CHECK_FAILED: {error}', file=sys.stderr)
        return 1
    except Exception as error:  # unreadable bitstream, malformed JSON, staging I/O
        receipt['status'] = 'CHECK_FAILED'
        receipt['failure'] = f'{type(error).__name__}: {error}'
        print(f'CHECK_FAILED: {type(error).__name__}: {error}', file=sys.stderr)
        return 1
    finally:
        receipt['finished_utc'] = utc_now()
        receipt['source_hashes_after'] = receipt.get('source_hashes_after') or \
            manifest(TRACKED_INPUTS)
        write_json(receipt_path, receipt)


def hardware_main(args):
    out = _fresh_directory(args.out or _default_out('hardware'))
    receipt = _receipt_base(args, 'hardware')
    receipt_path = out / 'receipt.json'
    receipt.update({'stage_dir': str(out / 'staged'), 'modes': [], 'mode_receipts': []})
    write_json(receipt_path, receipt)
    lease_fd = None
    context = None
    session = None
    try:
        if not args.authorized:
            raise Refusal('Hardware access refused: pass --authorized only after the user has '
                          'authorized programming/loading of this exact audited image and the '
                          'board identity is confirmed. Nothing was opened.')
        args.stage_dir = str(out / 'staged')
        result = preflight(args, for_hardware=True)
        if result['blockers']:
            raise Refusal('Plan blocked: ' + '; '.join(result['blockers']))
        receipt.update({'image': result['image'], 'target': result['target'],
                        'lease': result['lease'], 'source_tag': result['source_tag'],
                        'catalog': result['catalog'],
                        'source_hashes_before': manifest(TRACKED_INPUTS),
                        'plans': {str(mode): plan_summary(plan)
                                  for mode, plan in result['plans'].items()}})
        lease_fd = acquire_lease(args.lease)
        receipt['lease_acquired'] = True
        receipt['lease'] = result['lease'] | {'acquired': True}
        write_json(receipt_path, receipt)
        receipt['controllers'] = check_controllers()
        receipt['ports'] = check_ports(result['target']['port'], args.bridge_port)
        receipt['cable'] = check_cable()
        write_json(receipt_path, receipt)
        receipt['status'] = 'RUNNING_BRIDGE'
        context = run_bridge_hardware(args, result['target'], result['image'],
                                      result['source_tag'], out)
        receipt['hardware_accessed'] = True
        receipt['network_accessed'] = True
        receipt['vivado_executed'] = True
        receipt['hw_server_started'] = True
        receipt['bridge'] = context['record']
        receipt['tools'] = context['tools']
        write_json(receipt_path, receipt)
        session = MailboxSession(context['link'], timeout=args.job_timeout)
        receipt['identity'] = session.attach()
        session._verified = False  # page identities must be verified before writes
        write_json(receipt_path, receipt)
        receipt['page_identities'] = check_page_identities(session, result['image'])
        receipt['status'] = 'RUNNING_MODES'
        write_json(receipt_path, receipt)
        order = [mode for mode in result['modes'] if mode != 0]
        if 0 in result['modes']:
            order.append(0)
        for mode in order:
            plan = result['plans'][mode]
            plan['receipt_dir'] = out
            if plan['kind'] == 'contract':
                mode_result = run_contract_mode(session, plan, result['image'])
            else:
                mode_result = run_job_mode(session, plan, out)
            receipt['modes'].append(mode)
            receipt['mode_receipts'].append({
                'mode': mode, 'status': mode_result['status'],
                'receipt': f'mode-{mode}.json',
                'receipt_sha256': sha_file(out / f'mode-{mode}.json'),
                'frames': mode_result.get('frames'),
                'pass_marker': mode_result.get('pass_marker'),
            })
            ops_path = out / f'mode-{mode}-ops.jsonl'
            ops_start = mode_result.get('ops_start', 0)
            with ops_path.open('w') as ops:
                for item in session.ops[ops_start:]:
                    ops.write(json.dumps(item, separators=(',', ':')) + '\n')
            receipt['mode_receipts'][-1]['ops_sha256'] = sha_file(ops_path)
            write_json(receipt_path, receipt)
            print(mode_result['pass_marker'])
        receipt['status'] = 'PASS'
        receipt['finished_utc'] = utc_now()
        write_json(receipt_path, receipt)
        print(f'PASS YPCB_JTAG_DUAL_HARDWARE image={args.image[:12]}… modes={receipt["modes"]} '
              f'frames={session.commands} scans={session.scans} '
              f'flash_written=false receipt={receipt_path}')
        return 0
    except Refusal as error:
        receipt['status'] = 'REFUSED'
        receipt['failure'] = str(error)
        print(f'REFUSED: {error}', file=sys.stderr)
        return 2
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['failure'] = str(error)
        print(f'FAIL: {error}', file=sys.stderr)
        return 1
    finally:
        if context is not None:
            close_bridge_hardware(context, session=session)
            receipt['cleanup'] = context['record'].get('cleanup', {})
            receipt['bridge'] = context['record']
        if lease_fd is not None:
            try:
                release_lease(lease_fd, args.lease)
                receipt['lease_released'] = True
            except BaseException as error:
                receipt['lease_release_error'] = str(error)
        receipt['finished_utc'] = utc_now()
        receipt['source_hashes_after'] = manifest(TRACKED_INPUTS)
        write_json(receipt_path, receipt)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    args.command = [sys.executable, str(Path(__file__).resolve()), *argv]
    try:
        if args.check:
            return check_main(args)
        return hardware_main(args)
    except ValueError as error:
        print(f'FAIL: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
