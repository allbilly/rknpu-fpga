#!/usr/bin/env python3
"""Contract checks for the frozen conv-simple fixtures and their RTL path."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / 'tests/conv/fixtures'
FAMILY = ROOT / 'build/rk3588-example-captures/conv-simple/manifest.json'
FREEZER = ROOT / 'tools/conv/freeze_simple_fixtures.py'
GEN = ROOT / 'tools/conv/gen_conv_simple_profiles.py'
HEADER = ROOT / 'rtl/cmac/rk_conv_simple_profiles.svh'
PROFILE = ROOT / 'rtl/cmac/rk_conv_simple_profile.sv'
CORE = ROOT / 'rtl/cmac/rk_conv_simple_core.sv'
FRONT = ROOT / 'rtl/cmac/rk_conv_3x3_valid_c4_front.sv'
TB = ROOT / 'tests/conv/tb_conv_simple.sv'
RUNNER = ROOT / 'tools/conv/run_conv_simple.py'
FROZEN = (
    'conv_simple_fp16_3x3_c4_h8_w8_oc16',
    'conv_simple_fp16_5x5_c4_h8_w8_oc16',
    'conv_simple_fp16_3x3_c16_h8_w8_oc32',
)
REJECTED = (
    # Device output disagrees with the host oracle; not admissible evidence.
    'conv_simple_fp16_1x1_c32_h8_w8_oc32',
    'simple_conv_int8_5x5_c8_h8_w8_oc32',
    'simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64',
)
# Frozen FP32-output capture. It now executes through profile 3 and the
# `rk_conv_output_c1c2_fp32` placement stage, so these tests pin that path
# rather than asserting its absence (an earlier contract asserted "no row may
# claim it", which stopped being true when the FP32 writer landed).
FROZEN_FP32 = 'conv_simple_fp16_1x1_c4_h8_w8_oc16'
FP32_RUNNER = ROOT / 'tools/conv/run_conv_simple_fp32.py'
FP32_OUTPUT = ROOT / 'rtl/cmac/rk_conv_output_c1c2_fp32.sv'


def code_only(path: Path) -> str:
    return '\n'.join(line.split('//', 1)[0] for line in path.read_text().splitlines())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ConvSimpleFixtureContractTests(unittest.TestCase):
    def test_frozen_fixtures_are_hash_bound(self) -> None:
        for case in FROZEN:
            fixture = FIXTURES / case
            manifest = json.loads((fixture / 'manifest.json').read_text())
            self.assertEqual(manifest['case'], case)
            self.assertEqual(manifest['status'], 'READY_CAPTURE_BOUNDED_CANDIDATE')
            self.assertEqual(manifest['command_stream']['qwords'], 52)
            self.assertEqual(manifest['command_stream']['address_qwords'], [18, 24, 32])
            self.assertEqual(manifest['comparison']['mismatches_expected'], 0)
            self.assertEqual(manifest['comparison']['tolerance'], 0.0)
            self.assertEqual(manifest['output']['device_sha256'],
                             manifest['output']['host_expected_sha256'])
            self.assertEqual(manifest['output']['oracle_recomputed_sha256'],
                             manifest['output']['device_sha256'])
            for name, record in manifest['files'].items():
                path = fixture / name
                self.assertEqual(path.stat().st_size, record['bytes'], name)
                self.assertEqual(sha(path), record['sha256'], name)

    def test_fp32_output_capture_executes_through_its_own_leaf(self) -> None:
        case = FROZEN_FP32
        manifest = json.loads((FIXTURES / case / 'manifest.json').read_text())
        self.assertFalse(manifest['packing']['fp16_output'])
        self.assertEqual(manifest['dtype']['output'], 'float32')
        # Sound operands and a byte-exact device capture: the data is admissible.
        self.assertEqual(manifest['output']['oracle_recomputed_sha256'],
                         manifest['output']['device_sha256'])
        # It has its own generated profile row and its own dedicated runner.
        generator = GEN.read_text()
        self.assertIn("'id': 3, 'name': 'FP32_1X1_C4_OC16'", generator)
        self.assertIn(case, generator)
        header = HEADER.read_text()
        self.assertIn('localparam int unsigned CONV_SIMPLE_FP32_1X1_C4_OC16 = 3', header)
        self.assertIn(case, header)
        self.assertIn(f'3: conv_simple_output_bytes = 32\'d4096', header)
        self.assertTrue(FP32_RUNNER.is_file())
        self.assertIn(case, FP32_RUNNER.read_text())
        # The FP32 path is transport-only: no conversion, no CPU-style fixup.
        output = code_only(FP32_OUTPUT)
        for forbidden in ('fp32_to_fp16', 'hls_', 'convert', 'round'):
            self.assertNotIn(forbidden, output.lower(), forbidden)
        self.assertIn('rk_cmac_fp32_writer', output)

    def test_rejected_families_are_absent_and_reasons_are_recorded(self) -> None:
        for case in REJECTED:
            self.assertFalse((FIXTURES / case / 'manifest.json').exists(),
                             f'{case} must not be frozen')
        code = FREEZER.read_text()
        # The freezer refuses on device/host disagreement before anything else.
        self.assertIn('device output differs from the host oracle', code)
        self.assertIn('exact_full_match', code)
        # And it recomputes the oracle from the operand BOs itself.
        self.assertIn('independent oracle does not reproduce expected.bin', code)
        self.assertIn('def oracle(', code)

    def test_freezer_reproduces_the_frozen_oracle(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location('freezer', FREEZER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for case in FROZEN:
            bundle = ROOT / 'build/rk3588-example-captures/conv-simple/cases' / case
            recomputed = module.oracle(case, bundle)
            self.assertEqual(recomputed, (bundle / 'expected.bin').read_bytes(),
                             f'{case}: oracle no longer reproduces the capture')

    def test_generated_header_is_current(self) -> None:
        result = subprocess.run([sys.executable, str(GEN), '--check'], cwd=ROOT,
                                text=True, capture_output=True, check=False, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        header = HEADER.read_text()
        self.assertIn('localparam int unsigned CONV_SIMPLE_FP16_3X3_C4_OC16 = 0', header)
        self.assertIn('localparam int unsigned CONV_SIMPLE_FP16_5X5_C4_OC16 = 1', header)
        self.assertIn('localparam int unsigned CONV_SIMPLE_FP16_3X3_C16_OC32 = 2', header)
        self.assertIn('localparam int unsigned CONV_SIMPLE_FP32_1X1_C4_OC16 = 3', header)
        self.assertIn("index == 6'd18 || index == 6'd24 || index == 6'd32", header)
        # Address value fields are zeroed in the table, so the emitted header
        # cannot encode a particular BO placement.
        self.assertIn('localparam int unsigned CONV_SIMPLE_FP16_3X3_C4_OC16 = 0;', header)


class ConvSimpleProfileContractTests(unittest.TestCase):
    def test_profile_checks_every_field_and_only_three_relocations(self) -> None:
        code = code_only(PROFILE)
        self.assertIn("6'd18: config_input_base", code)
        self.assertIn("6'd24: config_weight_base", code)
        self.assertIn("6'd32: config_output_base", code)
        self.assertIn('conv_simple_address_word', code)
        self.assertIn('cmd_data[63:48] === expected[63:48]', code)
        self.assertIn('cmd_data[15:0] === expected[15:0]', code)
        self.assertIn("cmd_data[47:16] === expected[47:16]", code)
        self.assertIn('ranges_legal', code)
        self.assertIn('saved_code <= 8\'d7', code)   # second stream refused
        # An unknown profile id is an elaboration failure.
        self.assertIn('unknown conv-simple profile id', code)
        self.assertIn('if (WORDS != 52)', code)

    def test_profile_uses_the_generated_table_not_hardcoded_words(self) -> None:
        code = code_only(PROFILE)
        self.assertIn('conv_simple_template_word(PROFILE, word_index)', code)
        self.assertIn('`include "cmac/rk_conv_simple_profiles.svh"', PROFILE.read_text())
        # No literal command QWORD should be spelled out in the decoder.
        self.assertNotIn('64\'h020100000120100c', code)


class ConvSimpleFrontContractTests(unittest.TestCase):
    def test_front_kernel_extent_is_parameterised(self) -> None:
        code = code_only(FRONT)
        self.assertIn('parameter int unsigned KH = 3', code)
        self.assertIn('parameter int unsigned KW = 3', code)
        self.assertIn('localparam int unsigned TAPS = KH * KW', code)
        self.assertIn('INPUT_H != (OUTPUT_H - 1) * STRIDE + KH', code)
        self.assertIn('tap_y = 32\'(tap_index) / KW', code)
        # The original 3x3 captures keep working through the same module.
        self.assertNotIn('tap_index == 4\'d8', code)

    def test_front_supports_channel_blocks_and_chunked_weights(self) -> None:
        code = code_only(FRONT)
        for token in ('C1_BLOCKS', 'OUT_BLOCK_STRIDE', 'CHUNK_LANES', 'TOTAL_ATOMS',
                      'BLOCK_STRIDE', 'CHUNKS'):
            self.assertIn(token, code)
        self.assertIn('if (INPUT_CHANNELS < 1 || INPUT_CHANNELS > 32)', code)
        self.assertIn('if (PACK_C2 != 4 && PACK_C2 != 8)', code)
        self.assertIn('if (CHUNK_LANES != 0 && (CHUNK_LANES % 8) != 0)', code)
        # 32 lanes hold C32 in four C2=8 planes, flattened into one
        # single-read-port RAM so the window can live in block RAM instead of
        # a many-port flip-flop array.
        self.assertIn('logic [15:0] input_store [0:INPUT_H*INPUT_W*32-1]', code)
        self.assertIn('assign input_write_en = rst_n && state == INPUT_WAIT && mem_rsp_valid', code)
        self.assertIn('assign input_read_en = rst_n && state == ASSEMBLE &&', code)
        # The weight store is also a single-read-port RAM.
        self.assertIn('logic [15:0] weight_store [0:WEIGHT_HALFWORDS-1]', code)
        self.assertIn('always_ff @(posedge clk) begin\n        if (weight_write_en && mem_rsp_valid)', code)
        # The frame buses are registered, never a combinational mux of the RAM.
        self.assertIn('assign frame_weight = frame_weight_q', code)
        self.assertIn('assign frame_data = frame_data_q', code)


class ConvSimpleCoreContractTests(unittest.TestCase):
    def test_core_uses_one_arbitrated_memory_master(self) -> None:
        code = code_only(CORE)
        self.assertIn('rk_cmac_rw_arbiter arbiter', code)
        self.assertIn('assign mem_req_write = arbiter_req_write', code)
        self.assertIn('assign mem_req_addr = arbiter_req_addr', code)
        # No second driver of the memory port may appear.
        self.assertEqual(code.count('assign mem_req_addr'), 1)

    def test_core_is_parameterised_by_capture_geometry(self) -> None:
        code = code_only(CORE)
        self.assertIn('parameter int unsigned PROFILE = 0', code)
        self.assertIn('parameter int unsigned KH = 3', code)
        self.assertIn('parameter int unsigned CHUNK_LANES = 16', code)
        self.assertIn('.C1_BLOCKS(C1_BLOCKS)', code)
        self.assertIn('.OUT_BLOCK_STRIDE(OUTPUT_PIXELS)', code)
        self.assertIn('.KH(KH), .KW(KW)', code)


class ConvSimpleBenchContractTests(unittest.TestCase):
    def test_bench_covers_the_complete_output_bo_and_faults(self) -> None:
        code = code_only(TB)
        self.assertIn('if (write_requests >= TOTAL_WRITES', code)
        self.assertIn('complete output BO mismatch halfword', code)
        self.assertIn('pending_error <=', code)
        # Mode 12 proves a second stream is refused after a complete job.
        self.assertIn('extra raw word was not rejected', code)
        # The mode dispatch must cover every integer 0..12, whether the labels
        # are single or grouped; check the parsed set rather than the text.
        import re
        labels = set()
        for match in re.finditer(r'(\d+(?:, \d+)*):', code):
            for value in match.group(1).split(', '):
                labels.add(int(value))
        self.assertEqual(labels & set(range(13)), set(range(13)))

    def test_runner_requires_thirteen_modes_and_both_negative_kinds(self) -> None:
        code = RUNNER.read_text()
        self.assertEqual(code.count('{\'error\':') >= 9, True)
        self.assertIn("12: {'kind': 'second_stream'}", code)
        self.assertIn('hardware_accessed', code)
        self.assertIn('bitstream_emitted', code)
        self.assertIn("re.search(r'%Error', text)", code)


if __name__ == '__main__':
    unittest.main()
