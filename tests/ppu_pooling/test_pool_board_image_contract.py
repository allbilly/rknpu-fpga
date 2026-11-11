#!/usr/bin/env python3
"""Contract checks for the first pooling board image and its descriptor path."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / 'fpga/ppu/sources.json'
TEMPLATE = ROOT / 'fpga/ppu/build_ppu.tcl.in'
RENDERER = ROOT / 'tools/ppu/vivado_ppu.py'
PROFILE = ROOT / 'rtl/ppu/rk_ppu_pool_i8_k2s2_profile.sv'
DMA = ROOT / 'rtl/ppu/rk_ppu_pool_i8_k2s2_dma.sv'
SELF_TEST = ROOT / 'rtl/ppu/rk_ppu_pool_self_test.sv'
ROM_GEN = ROOT / 'tools/ppu/gen_pool_demo.py'
ROM = ROOT / 'rtl/ppu/rk_ppu_pool_demo_rom.sv'
TOP = ROOT / 'fpga/ypcb_ppu_i8_top.sv'
XDC = ROOT / 'fpga/ypcb_ppu_i8.xdc'
BOARD_RUNNER = ROOT / 'tools/ppu/run_ppu_board.py'
DMA_RUNNER = ROOT / 'tools/ppu/run_pool_i8_k2s2_dma.py'
FIXTURE = ROOT / 'tests/ppu_pooling/fixtures/int8_max_k2s2_valid_c16_h2w2'


def code_only(path: Path) -> str:
    return '\n'.join(line.split('//', 1)[0] for line in path.read_text().splitlines())


class PoolBoardImageContractTests(unittest.TestCase):
    def test_profile_is_strict_and_pins_the_captured_fields(self) -> None:
        code = code_only(PROFILE)
        # Exactly two relocatable QWORDs.
        self.assertIn('word_index_q == 5\'d13 || word_index_q == 5\'d20', code)
        self.assertIn('rdma_transfer_bytes = 32\'d64', code)
        self.assertIn('output_write_bytes = 32\'d16', code)
        # The maximum/minimum captures differ only in the operation mode word.
        self.assertIn('MINIMUM ? 32\'h00000012 : 32\'h00000011', code)
        self.assertIn('32\'h00110101', code)
        # Any unmodelled field or wrong length is a fault, never ignored.
        self.assertIn('cmd_data[63:48] !== expected_target', code)
        self.assertIn('cmd_data[15:0] !== expected_offset', code)
        self.assertIn('cmd_data[47:16] !== expected_value', code)
        self.assertIn('cmd_last !== (word_index_q == 5\'d25)', code)
        self.assertIn('ST_FAULT', code)

    def test_endpoint_resets_profile_and_leaf_between_jobs(self) -> None:
        code = code_only(DMA)
        for token in ('profile_rst_n_q', 'leaf_rst_n_q', 'ST_GATE', 'ST_PROFILE',
                      'ST_INPUT_SEND', 'ST_POOL_WAIT', 'ST_OUTPUT_REQUEST', 'ST_FINISH'):
            self.assertIn(token, code)
        # Launch validation and post-profile address validation are both present.
        self.assertIn('start_amount != 32\'d26', code)
        self.assertIn('ranges_overlap', code)
        self.assertIn('in_aperture', code)
        # Gate advancement is tied to the profile's accepted handshake.
        self.assertIn('profile_cmd_ready', code)
        # No CPU-side repairs: writes only come from the captured leaf atom.
        self.assertIn('output_atom_q[output_halfword_q*16 +: 16]', code)
        self.assertNotIn('case (mem_req_addr', code)

    def test_self_test_compares_the_complete_output_bo(self) -> None:
        code = code_only(SELF_TEST)
        self.assertIn('OUTPUT_HALFWORDS = 2048', code)
        self.assertIn('expected_halfword', code)
        self.assertIn('host_rdata !== expected_halfword', code)
        # Only captured bytes drive the expected value; the untouched tail is 0.
        self.assertIn('check_index_q < 12\'(EXPECTED_HALFWORDS)', code)

    def test_generated_rom_is_current_and_matches_the_fixture(self) -> None:
        result = subprocess.run([sys.executable, str(ROM_GEN), '--check'], cwd=ROOT,
                                text=True, capture_output=True, check=False, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        self.assertEqual(manifest['command_stream']['qwords'], 26)
        self.assertEqual(manifest['command_stream']['address_relocations'], [13, 20])
        self.assertIn('10000000', ROM.read_text())
        self.assertIn('10000200', ROM.read_text())
        self.assertIn('10001000', ROM.read_text())
        record = json.loads((ROOT / 'tests/ppu_pool_demo_fixture.json').read_text())
        # Little-endian halfwords of the captured bytes 64 31 62 2f ...
        self.assertEqual(record['expected_values'],
                         [0x3164, 0x2f62, 0x2d60, 0x2b5e,
                          0x295c, 0x275a, 0x2558, 0x2356])

    def test_profile_binds_an_explicit_source_list_and_regenerates(self) -> None:
        spec = json.loads(SPEC.read_text())
        self.assertEqual(spec['top'], 'ypcb_ppu_i8_top')
        self.assertEqual(spec['part'], 'xc7k480tffg1156-2')
        self.assertEqual(spec['clock_period_ns'], 20)
        for name in spec['sources'] + [spec['constraints']]:
            self.assertTrue((ROOT / name).is_file(), name)
        self.assertEqual(len(spec['generated']), 1)
        self.assertEqual(spec['generated'][0]['path'],
                         'rtl/ppu/rk_ppu_pool_demo_rom.sv')
        # Every synthesis source must be listed exactly once.
        self.assertEqual(len(spec['sources']), len(set(spec['sources'])))
        template = TEMPLATE.read_text()
        self.assertIn('@READ_SOURCES@', template)
        self.assertIn('RK_EMIT_BITSTREAM', template)
        renderer = code_only(RENDERER)
        self.assertIn("if re.search(r'@[A-Z_]+@', text):", renderer)
        self.assertIn('verify_generated', renderer)

    def test_board_top_has_only_the_audited_pins(self) -> None:
        xdc = XDC.read_text()
        self.assertIn('PACKAGE_PIN AA28 [get_ports SYS_CLK]', xdc)
        for pin, index in (('P30', 0), ('M30', 1), ('N30', 2)):
            self.assertIn(f'PACKAGE_PIN {pin} [get_ports {{led_3bits_tri_o[{index}]}}]', xdc)
        self.assertIn('create_clock -name sys_clk -period 20.000', xdc)
        # Separate bring-up image: no external reset input is consumed.
        self.assertNotIn('SYS_RSTN', xdc)
        top = TOP.read_text()
        self.assertIn('rk_startup_reset', top)
        self.assertIn('rk_ppu_pool_self_test', top)
        self.assertNotIn('SYS_RSTN', top)

    def test_dma_runner_checks_nine_modes_and_full_bo(self) -> None:
        code = DMA_RUNNER.read_text()
        for mode in range(9):
            self.assertIn(f'    {mode}: {{', code)
        self.assertIn("'PASS_COMPLETE_BO'", code)
        self.assertIn("'PASS_REPEAT_BO'", code)
        self.assertIn("'PASS_TIMEOUT'", code)
        self.assertIn('hardware_accessed', code)
        self.assertIn('bitstream_emitted', code)

    def test_vivado_wrapper_gates_on_reports_not_only_exit_status(self) -> None:
        code = code_only(RENDERER)
        self.assertIn('parse_reports', code)
        self.assertIn('report_gate_ok', code)
        self.assertIn('Missing required implementation report', code)
        self.assertIn('timing_met', code)
        self.assertIn('ramb36e1', code)
        # A bitstream with unresolved configuration-bank properties is refused.
        self.assertIn('bitstream_emitted and any', code)

    def test_board_runner_asserts_the_captured_pass_line(self) -> None:
        code = BOARD_RUNNER.read_text()
        self.assertIn('PASS YPCB PPU INT8 image', code)
        self.assertIn('whole-BO', code)
        self.assertIn('vivado_executed', code)
        self.assertIn('bitstream_emitted', code)
        # The runner must prove rejection, not just that a PASS line appeared.
        self.assertIn('negative_controls', code)
        self.assertIn('REJECTED_WITH_CODE_51', code)
        self.assertIn('board self-test FAILED code=51', code)
        self.assertIn('negative control wrongly passed', code)


if __name__ == '__main__':
    unittest.main()
