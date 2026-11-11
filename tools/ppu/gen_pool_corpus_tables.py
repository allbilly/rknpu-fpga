#!/usr/bin/env python3
"""Generate the per-fixture case RTL for the pooling-corpus image.

The frozen pooling corpus is the 19 READY cases of
``build/rk3588-example-captures/pooling/manifest.json`` (18 live-captured + one
source-derived). Each case is one AXI page; this generator emits
``rtl/ppu/rk_ppu_pool_corpus_case.sv``, a ``CASE``-parameterised module whose
generate branches hold, for one fixture each:

  * the strict command gate: every bit of the captured 26/28-QWORD stream is
    compared exactly, except the two 32-bit base-address fields that the host
    relocates (job.json patches). The generated constants are taken from the
    frozen ``regcmd.bin`` of the fixture, never from a hand-written table;
  * the elaboration constants (command length, input/output atom counts, index
    placement, device identity, fixture-name CRC);
  * the captured pooling leaf, wired to the module's atom-stream ports.

Everything is derived from frozen files whose sha256 is pinned by each fixture's
manifest.json (checked here), so ``--check`` is a generated-source gate in the
same style as the pooling demo ROM.

Usage:
    python3 tools/ppu/gen_pool_corpus_tables.py            # write RTL
    python3 tools/ppu/gen_pool_corpus_tables.py --check    # verify RTL is fresh
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/ppu_pooling/fixtures'
CAPTURE_CASES = ROOT / 'build/rk3588-example-captures/pooling/cases'
CAPTURE_MANIFEST = ROOT / 'build/rk3588-example-captures/pooling/manifest.json'
OUT = ROOT / 'rtl/ppu/rk_ppu_pool_corpus_case.sv'

# Relocatable base-address fields sit at bits [47:16] of their QWORD; the host
# patches exactly those 32 bits (see tools/conv/run_conv_simple_axi.py for the
# same QWORD layout in the conv corpus).
ADDR_MASK = 0x0000_FFFF_FFFF_0000
# Every bit of a relocatable QWORD except the 32-bit base-address field must
# still match the capture exactly.
NONADDR_MASK = (~ADDR_MASK) & 0xFFFF_FFFF_FFFF_FFFF

# Captured leaves, one per corpus case. Every pooling leaf has the identical
# atom-stream interface, which is what lets one generic DMA drive all of them.
LEAF = {
    'fp16_avg_global_k3x5_valid_c8_h3w5':
        'rk_ppu_pool_avg_global3x5_c8_fp16_capture',
    'fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1':
        'rk_ppu_pool_avg2x2s1_pad1_c8_h1w1',
    'fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1':
        'rk_ppu_pool_avg2x2s1_pad1_c8_h1w1',
    'fp16_avg_k2s1_valid_c8_h4w4':
        'rk_ppu_pool_avg2x2s1_fp16_capture',
    'fp16_max_k2s1_pad1_neg_c8_h2w2':
        'rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2',
    'fp16_max_k2s1_valid_c8_h4w4':
        'rk_ppu_pool_max2x2s1_c8',
    'fp16_max_k2s2_c3_tail_h2w2':
        'rk_ppu_pool_max2x2s2_c3_tail_h2w2',
    'fp16_max_k2s2_index_c8_h2w2':
        ('rk_ppu_pool_max2x2s2_index_c8_h2w2', 'index'),
    'fp16_max_k3s2_pad1_c8_h4w4':
        'rk_ppu_pool_max3x3s2_pad1_c8_h4w4',
    'fp16_min_k2s1_valid_c8_h4w4':
        'rk_ppu_pool_min2x2s1_fp16_capture',
    'int16_avg_q16_k2s2_valid_c8_h2w2':
        'rk_ppu_pool_avg_q16_i16_c8_k2s2',
    'int16_avg_q16_k3x3_valid_c8_h3w3':
        'rk_ppu_pool_avg_q16_i16_c8_k3x3',
    'int16_max_k2s2_valid_c8_h2w2':
        'rk_ppu_pool_max_k2s2_i16_c8_h2w2',
    'int16_min_k2s2_valid_c8_h2w2':
        'rk_ppu_pool_min_k2s2_i16_c8_h2w2',
    'int8_avg_q16_k2s2_valid_c16_h2w2':
        'rk_ppu_pool_avg_q16_i8_c16_k2s2',
    'int8_avg_q16_k3x3_valid_c16_h3w3':
        'rk_ppu_pool_avg_q16_i8_c16_k3x3',
    'int8_max_k1s1_valid_c32_h1w1':
        'rk_ppu_pool_max_k1s1_i8_c32',
    'int8_max_k2s2_valid_c16_h2w2':
        'rk_ppu_pool_max_k2s2_i8_c16_h2w2',
    'int8_min_k2s2_valid_c16_h2w2':
        'rk_ppu_pool_min_k2s2_i8_c16_h2w2',
}
DEVICE_ID_BASE = 0x524b5000  # 'RKPP' + per-page identity byte
ATOM_BYTES = 16


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_cases() -> list[str]:
    """The frozen corpus, sorted into the fixed page order (the page map)."""
    manifest = json.loads(CAPTURE_MANIFEST.read_text())
    ready = sorted(manifest['ready_cases'])
    blocked = set(manifest['blocked_cases'])
    missing = [case for case in ready if not (FIXTURES / case).is_dir()]
    if missing:
        raise ValueError(f'corpus fixtures missing from tests/: {missing}')
    overlap = sorted(set(ready) & blocked)
    if overlap:
        raise ValueError(f'blocked cases marked READY: {overlap}')
    if len(ready) != 19:
        raise ValueError(f'expected 19 READY corpus cases, found {len(ready)}')
    unmapped = [case for case in ready if case not in LEAF]
    if unmapped:
        raise ValueError(f'no captured leaf mapping for: {unmapped}')
    stale = sorted(set(LEAF) - set(ready))
    if stale:
        raise ValueError(f'leaf table lists non-corpus cases: {stale}')
    return ready


def capture_entry(case: str) -> dict:
    manifest = json.loads(CAPTURE_MANIFEST.read_text())
    for entry in manifest['cases']:
        if entry['case'] == case:
            return entry
    raise ValueError(f'{case}: not present in the capture manifest')


def resolve_file(case: str, name: str) -> Path:
    """Locate one frozen fixture file and verify its captured sha256.

    The versioned ``tests/ppu_pooling/fixtures`` copy is preferred; three of the
    older fixtures never had an ``expected.bin``/``regcmd.txt`` copied there, so
    the frozen capture bundle is the fallback. Both locations are checked
    against the capture manifest so a drifted copy fails here, not in a build.
    """
    record = capture_entry(case)['files'].get(name)
    if record is None:
        raise ValueError(f'{case}: capture manifest does not pin {name}')
    candidates = [FIXTURES / case / name, CAPTURE_CASES / case / name]
    found = [path for path in candidates if path.is_file()]
    if not found:
        raise ValueError(f'{case}: no frozen copy of {name}')
    payload = found[0].read_bytes()
    if len(payload) != record['bytes'] or hashlib.sha256(payload).hexdigest() != record['sha256']:
        raise ValueError(f'{case}: frozen {name} does not match the capture hash')
    for path in found[1:]:
        if path.read_bytes() != payload:
            raise ValueError(f'{case}: fork between frozen copies of {name}')
    return found[0]


def load_case(case: str, page: int) -> dict:
    fixture = FIXTURES / case
    manifest = json.loads((fixture / 'manifest.json').read_text())
    job = json.loads(resolve_file(case, 'job.json').read_text())
    entry = capture_entry(case)
    if manifest.get('case', case) != case:
        raise ValueError(f'{case}: fixture identity mismatch')
    if entry['status'] != 'READY':
        raise ValueError(f'{case}: capture is not READY')
    required = ('job.json', 'regcmd.bin', 'in.bin', 'out_init.bin', 'expected.bin')
    paths = {name: resolve_file(case, name) for name in required}
    qwords = job['tasks'][0]['regcmd_words']
    regcmd = paths['regcmd.bin'].read_bytes()
    if len(regcmd) != qwords * 8:
        raise ValueError(f'{case}: regcmd is not {qwords} QWORDs')
    if job['tasks'][0]['regcmd_offset_words'] != 0:
        raise ValueError(f'{case}: non-zero task offset is not supported')
    words = [int.from_bytes(regcmd[i * 8:(i + 1) * 8], 'little')
             for i in range(qwords)]
    patches = job['patches']
    if len(patches) != 2:
        raise ValueError(f'{case}: expected exactly two address relocations')
    reloc = {}
    for patch in patches:
        if patch['kind'] != 'value32':
            raise ValueError(f'{case}: unexpected patch kind {patch["kind"]}')
        reloc[patch['buffer']] = patch['regcmd_index']
    if set(reloc) != {'in', 'out'}:
        raise ValueError(f'{case}: relocations must be for in and out only')
    for index in reloc.values():
        if not 0 <= index < qwords:
            raise ValueError(f'{case}: relocation index out of range')
        if words[index] & ADDR_MASK:
            raise ValueError(f'{case}: captured QWORD {index} is not a zero '
                             'address placeholder')
    layout = entry['layout']['input']
    out_layout = entry['layout']['output']
    in_bytes = layout['logical_bytes']
    value_bytes = out_layout.get('value_bytes', out_layout['logical_bytes'])
    index_bytes = out_layout.get('index_bytes', 0)
    index_en = bool(out_layout.get('index_en', False))
    if in_bytes % ATOM_BYTES or value_bytes % ATOM_BYTES or index_bytes % ATOM_BYTES:
        raise ValueError(f'{case}: logical bytes are not whole atoms')
    in_atoms = in_bytes // ATOM_BYTES
    out_atoms = value_bytes // ATOM_BYTES + (index_bytes // ATOM_BYTES)
    if not 0 < in_atoms <= 31 or not 0 < out_atoms <= 31:
        raise ValueError(f'{case}: atom count out of range')
    index_offset = int(out_layout.get('index_offset') or 0)
    if index_en and (index_offset % ATOM_BYTES or index_offset < value_bytes
                     or index_bytes % ATOM_BYTES):
        raise ValueError(f'{case}: unexpected index placement')
    index_atom = value_bytes // ATOM_BYTES if index_en else 0
    if index_en and index_atom != 1:
        raise ValueError(f'{case}: the index adapter serialises a single value '
                         'atom, this corpus case is expected to have one')
    return {
        'case': case,
        'page': page,
        'qwords': qwords,
        'words': words,
        'reloc_in': reloc['in'],
        'reloc_out': reloc['out'],
        'in_atoms': in_atoms,
        'out_atoms': out_atoms,
        'index_en': int(index_en),
        'index_atom': index_atom,
        'index_offset': index_offset,
        'device_id': DEVICE_ID_BASE + page + 1,
        'crc32': zlib.crc32(case.encode('utf-8')) & 0xFFFF_FFFF,
        'leaf': LEAF[case],
        'tolerance': float(entry.get('oracle', {}).get('tolerance', 0.0)),
        'in_bytes': in_bytes,
        'out_bytes': value_bytes + index_bytes,
        'description': entry.get('description', ''),
    }


def qword_literal(value: int) -> str:
    return f"64'h{value:016x}"


def emit_gate(case: dict, lines: list[str]) -> None:
    qwords = case['qwords']
    lines.append(f'        localparam int unsigned CMD_QWORDS = {qwords};')
    lines.append('        logic [5:0] word_q;')
    lines.append('        logic error_q, done_q;')
    lines.append('        logic [7:0] code_q;')
    lines.append('        logic [31:0] src_q, dst_q;')
    lines.append('        assign cmd_ready = 1\'b1;')
    lines.append('        always_ff @(posedge clk or negedge gate_rst_n) begin')
    lines.append('            if (!gate_rst_n) begin')
    lines.append('                word_q <= 6\'d0; error_q <= 1\'b0; done_q <= 1\'b0;')
    lines.append('                code_q <= 8\'d0; src_q <= 32\'d0; dst_q <= 32\'d0;')
    lines.append('            end else if (cmd_valid && !done_q && !error_q) begin')
    lines.append('                if (!cmd_last && (word_q == 6\'(CMD_QWORDS - 1))) begin')
    lines.append('                    error_q <= 1\'b1; code_q <= 8\'d3;')
    lines.append('                end else if (cmd_last && (word_q != 6\'(CMD_QWORDS - 1))) begin')
    lines.append('                    error_q <= 1\'b1; code_q <= 8\'d3;')
    lines.append('                end else begin')
    lines.append('                    case (word_q)')
    for index, word in enumerate(case['words']):
        if index == case['reloc_out'] or index == case['reloc_in']:
            masked = word & ~ADDR_MASK
            lines.append(f'                        6\'d{index}: begin')
            lines.append(f'                            if ((cmd_data & 64\'h{NONADDR_MASK:016x}) !== 64\'h{masked:016x}) begin')
            lines.append('                                error_q <= 1\'b1; code_q <= 8\'d2;')
            lines.append('                            end')
            if index == case['reloc_in']:
                lines.append('                            src_q <= cmd_data[47:16];')
            else:
                lines.append('                            dst_q <= cmd_data[47:16];')
            lines.append('                        end')
        else:
            lines.append(f'                        6\'d{index}: if (cmd_data !== {qword_literal(word)}) begin')
            lines.append('                            error_q <= 1\'b1; code_q <= 8\'d1;')
            lines.append('                        end')
    lines.append('                        default: begin error_q <= 1\'b1; code_q <= 8\'d1; end')
    lines.append('                    endcase')
    lines.append('                    if (word_q == 6\'(CMD_QWORDS - 1)) done_q <= 1\'b1;')
    lines.append('                    word_q <= word_q + 1\'b1;')
    lines.append('                end')
    lines.append('            end')
    lines.append('        end')
    lines.append('        assign profile_valid = done_q && !error_q;')
    lines.append('        assign profile_error = error_q;')
    lines.append('        assign profile_code = code_q;')
    lines.append('        assign rdma_src_base = src_q;')
    lines.append('        assign ppu_dst_base = dst_q;')


def emit_case(case: dict, lines: list[str], first: bool) -> None:
    keyword = 'if' if first else 'end else if'
    lines.append(f'        {keyword} (CASE == {case["page"]}) begin : g_case_{case["page"]}')
    lines.append(f'            // page {case["page"]}: {case["case"]}')
    lines.append(f'            // {case["description"]}')
    emit_gate(case, lines)
    lines.append(f'        localparam int unsigned IN_ATOMS = {case["in_atoms"]};')
    lines.append(f'        localparam int unsigned OUT_ATOMS = {case["out_atoms"]};')
    lines.append(f'        localparam int unsigned INDEX_EN = {case["index_en"]};')
    lines.append(f'        localparam int unsigned INDEX_ATOM = {case["index_atom"]};')
    lines.append(f'        localparam logic [31:0] INDEX_OFFSET = 32\'d{case["index_offset"]};')
    lines.append(f'        localparam logic [31:0] CASE_DEVICE_ID = 32\'h{case["device_id"]:08x};')
    lines.append(f'        localparam logic [31:0] CASE_CRC32 = 32\'h{case["crc32"]:08x};')
    lines.append(f'        localparam int unsigned CASE_FIXTURE_INDEX = {case["page"]};')
    lines.append('        assign cmd_qwords = 6\'(CMD_QWORDS);')
    lines.append('        assign in_atoms = 5\'(IN_ATOMS);')
    lines.append('        assign out_atoms = 5\'(OUT_ATOMS);')
    lines.append('        assign index_en = (INDEX_EN != 0);')
    lines.append('        assign index_atom = 5\'(INDEX_ATOM);')
    lines.append('        assign index_offset = INDEX_OFFSET;')
    lines.append('        assign device_id = CASE_DEVICE_ID;')
    lines.append('        assign fixture_crc32 = CASE_CRC32;')
    lines.append('        assign fixture_index = 5\'(CASE_FIXTURE_INDEX);')
    leaf = case['leaf']
    if isinstance(leaf, tuple):
        module, style = leaf
    else:
        module, style = leaf, 'atom'
    if style == 'atom':
        lines.append(f'        {module} leaf (')
        lines.append('            .clk, .rst_n(leaf_rst_n),')
        lines.append('            .in_valid(leaf_in_valid), .in_ready(leaf_in_ready),')
        lines.append('            .in_atom(leaf_in_atom),')
        lines.append('            .out_valid(leaf_out_valid), .out_ready(leaf_out_ready),')
        lines.append('            .out_atom(leaf_out_atom), .out_last(leaf_out_last));')
    else:
        # This captured leaf emits its value atom and its uint16 index atom on
        # the same cycle. The adapter serialises the pair into two standard
        # atom beats (value first, then index at the captured index offset), so
        # the generic DMA and the output-atom budget stay unchanged.
        lines.append('        logic leaf_dual_valid, leaf_dual_ready, leaf_dual_last;')
        lines.append('        logic [127:0] leaf_value_atom, leaf_index_atom;')
        lines.append(f'        {module} index_leaf (')
        lines.append('            .clk, .rst_n(leaf_rst_n),')
        lines.append('            .in_valid(leaf_in_valid), .in_ready(leaf_in_ready),')
        lines.append('            .in_atom(leaf_in_atom),')
        lines.append('            .out_valid(leaf_dual_valid), .out_ready(leaf_dual_ready),')
        lines.append('            .out_value_atom(leaf_value_atom),')
        lines.append('            .out_index_atom(leaf_index_atom),')
        lines.append('            .out_unique(), .out_last(leaf_dual_last));')
        lines.append('        rk_ppu_pool_corpus_index_leaf index_adapter (')
        lines.append('            .clk, .rst_n(leaf_rst_n),')
        lines.append('            .leaf_valid(leaf_dual_valid), .leaf_ready(leaf_dual_ready),')
        lines.append('            .leaf_value_atom(leaf_value_atom),')
        lines.append('            .leaf_index_atom(leaf_index_atom),')
        lines.append('            .leaf_last(leaf_dual_last),')
        lines.append('            .out_valid(leaf_out_valid), .out_ready(leaf_out_ready),')
        lines.append('            .out_atom(leaf_out_atom), .out_last(leaf_out_last));')



def render() -> str:
    cases = corpus_cases()
    lines = [
        '// SPDX-License-Identifier: MIT',
        '`timescale 1ns/1ps',
        '// GENERATED by tools/ppu/gen_pool_corpus_tables.py -- do not edit.',
        '// Regenerate: python3 tools/ppu/gen_pool_corpus_tables.py',
        '// Verify:     python3 tools/ppu/gen_pool_corpus_tables.py --check',
        '//',
        '// One generate branch per frozen pooling fixture: strict command gate over',
        '// the captured raw QWORD stream, the elaboration constants of the page, and',
        '// the captured atom-stream leaf. There is exactly one branch for each READY',
        '// case of build/rk3588-example-captures/pooling/manifest.json, in sorted',
        '// order, which is also the image page order.',
        f'// Corpus size: {len(cases)}',
        'module rk_ppu_pool_corpus_case #(',
        '    parameter int unsigned CASE = 0',
        ') (',
        '    input  logic         clk,',
        '    // Separate child resets: the DMA releases the command gate once the',
        '    // complete stream is buffered and the leaf only after the operand',
        '    // windows are proven, exactly like the existing raw pooling engines.',
        '    input  logic         gate_rst_n,',
        '    input  logic         leaf_rst_n,',
        '    // Strict captured-command gate: one QWORD per cycle, always accepted.',
        '    input  logic         cmd_valid,',
        '    output logic         cmd_ready,',
        '    input  logic [63:0]  cmd_data,',
        '    input  logic         cmd_last,',
        '    output logic         profile_valid,',
        '    output logic         profile_error,',
        '    output logic [7:0]   profile_code,',
        '    output logic [31:0]  rdma_src_base,',
        '    output logic [31:0]  ppu_dst_base,',
        '    // Elaboration constants published to the generic DMA/page.',
        '    output logic [5:0]   cmd_qwords,',
        '    output logic [4:0]   in_atoms,',
        '    output logic [4:0]   out_atoms,',
        '    output logic         index_en,',
        '    output logic [4:0]   index_atom,',
        '    output logic [31:0]  index_offset,',
        '    output logic [31:0]  device_id,',
        '    output logic [31:0]  fixture_crc32,',
        '    output logic [4:0]   fixture_index,',
        '    // Atom stream to the selected captured leaf.',
        '    input  logic         leaf_in_valid,',
        '    output logic         leaf_in_ready,',
        '    input  logic [127:0] leaf_in_atom,',
        '    output logic         leaf_out_valid,',
        '    input  logic         leaf_out_ready,',
        '    output logic [127:0] leaf_out_atom,',
        '    output logic         leaf_out_last',
        ');',
        '    generate',
    ]
    for index, name in enumerate(cases):
        case = load_case(name, index)
        emit_case(case, lines, first=(index == 0))
    lines += [
        '        end else begin : g_unsupported',
        '            // A page elaborated with a CASE this generator never emitted is a',
        '            // build-time error, not an inert page.',
        '            initial $fatal(1, "unsupported pooling corpus CASE");',
        '        end',
        '    endgenerate',
        'endmodule',
        '',
    ]
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='verify the generated RTL matches the frozen fixtures')
    args = parser.parse_args()
    text = render()
    if args.check:
        if not OUT.is_file():
            print(f'MISSING {OUT.relative_to(ROOT)}', file=sys.stderr)
            return 1
        if OUT.read_text() != text:
            print(f'STALE {OUT.relative_to(ROOT)}; run '
                  f'python3 {Path(__file__).relative_to(ROOT)}', file=sys.stderr)
            return 1
        print(f'OK {OUT.relative_to(ROOT)} matches the frozen pooling corpus')
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f'wrote {OUT.relative_to(ROOT)} ({len(corpus_cases())} cases)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
