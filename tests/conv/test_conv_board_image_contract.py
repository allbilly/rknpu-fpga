#!/usr/bin/env python3
"""Contract checks for the conv-simple board image."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / 'fpga/conv/sources.json'
TEMPLATE = ROOT / 'fpga/conv/build_conv.tcl.in'
RENDERER = ROOT / 'tools/conv/vivado_conv.py'
SELF_TEST = ROOT / 'rtl/cmac/rk_conv_simple_self_test.sv'
TOP = ROOT / 'fpga/ypcb_conv_simple_top.sv'
XDC = ROOT / 'fpga/ypcb_conv_simple.xdc'
ROM = ROOT / 'rtl/cmac/rk_conv_simple_demo_rom.sv'
GEN = ROOT / 'tools/conv/gen_conv_demo.py'
BOARD_RUNNER = ROOT / 'tools/conv/run_conv_board.py'
FIXTURE = ROOT / 'tests/conv/fixtures/conv_simple_fp16_3x3_c4_h8_w8_oc16'


def code_only(path: Path) -> str:
    return '\n'.join(line.split('//', 1)[0] for line in path.read_text().splitlines())


class ConvBoardImageContractTests(unittest.TestCase):
    def test_generated_conv_rom_is_current_and_matches_the_fixture(self) -> None:
        result = subprocess.run([sys.executable, str(GEN), '--check'], cwd=ROOT,
                                text=True, capture_output=True, check=False, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((FIXTURE / 'manifest.json').read_text())
        self.assertEqual(manifest['command_stream']['qwords'], 52)
        self.assertEqual(manifest['command_stream']['address_qwords'], [18, 24, 32])
        text = ROM.read_text()
        self.assertIn("assign command_base = 32'h10000000;", text)
        self.assertIn("assign input_base = 32'h10001000;", text)
        self.assertIn("assign weight_base = 32'h10002000;", text)
        self.assertIn("assign output_base = 32'h10003000;", text)
        self.assertIn("assign start_amount = 32'd52;", text)
        record = json.loads((ROOT / 'tests/conv_simple_demo_fixture.json').read_text())
        self.assertEqual(record['weight_halfwords'], 1152)
        self.assertEqual(record['expected_halfwords'], 576)

    def test_self_test_checks_every_output_halfword(self) -> None:
        code = code_only(SELF_TEST)
        self.assertIn('OUTPUT_HALFWORDS = 576', code)
        self.assertIn('host_rdata !== expected_data', code)
        self.assertIn('ST_CHECK', code)
        # No zero-fill allowance: the captured BO is fully defined.
        self.assertNotIn("expected_halfword =", code)
        # The command stream is replayed from ROM, not re-read from memory.
        self.assertIn('assign cmd_valid = state_q == ST_SEND', code)
        self.assertIn('assign command_index = send_index_q', code)
        # Error codes are explicit: 0x51 compare, 0x52 watchdog, 0x53 bus.
        for token in ("8'h51", "8'h52", "8'h53"):
            self.assertIn(token, code)

    def test_profile_binds_an_explicit_source_list(self) -> None:
        spec = json.loads(SPEC.read_text())
        self.assertEqual(spec['top'], 'ypcb_conv_simple_top')
        self.assertEqual(spec['part'], 'xc7k480tffg1156-2')
        self.assertEqual(spec['clock_period_ns'], 20)
        self.assertEqual(spec['constraints'], 'fpga/ypcb_conv_simple.xdc')
        self.assertEqual(len(spec['sources']), len(set(spec['sources'])))
        for name in spec['sources'] + [spec['constraints']]:
            self.assertTrue((ROOT / name).is_file(), name)
        self.assertEqual(len(spec['generated']), 1)
        self.assertEqual(spec['generated'][0]['path'],
                         'rtl/cmac/rk_conv_simple_demo_rom.sv')
        # The include path must cover the generated header's own directory.
        renderer = RENDERER.read_text()
        self.assertIn("('rtl', 'rtl/vendor/nvdla')", renderer)
        template = TEMPLATE.read_text()
        self.assertIn('@INCLUDE_DIRS@', template)
        self.assertIn('RK_EMIT_BITSTREAM', template)

    def test_board_top_has_only_the_audited_pins(self) -> None:
        xdc = XDC.read_text()
        self.assertIn('PACKAGE_PIN AA28 [get_ports SYS_CLK]', xdc)
        for pin, index in (('P30', 0), ('M30', 1), ('N30', 2)):
            self.assertIn(f'PACKAGE_PIN {pin} [get_ports {{led_3bits_tri_o[{index}]}}]', xdc)
        self.assertIn('create_clock -name sys_clk -period 20.000', xdc)
        self.assertNotIn('SYS_RSTN', xdc)
        top = TOP.read_text()
        self.assertIn('rk_startup_reset', top)
        self.assertIn('rk_conv_simple_self_test', top)
        self.assertNotIn('SYS_RSTN', top)

    def test_board_runner_requires_rejection_not_just_pass(self) -> None:
        code = BOARD_RUNNER.read_text()
        self.assertIn('board conv self-test FAILED code=51', code)
        self.assertIn('negative_controls', code)
        self.assertIn('REJECTED_WITH_CODE_51', code)
        self.assertIn('wrongly passed', code)
        self.assertIn('did not fail with code 0x51', code)
        self.assertIn('vivado_executed', code)
        self.assertIn('bitstream_emitted', code)

    def test_vivado_wrapper_gates_on_reports_not_exit_status(self) -> None:
        code = RENDERER.read_text()
        for token in ('parse_reports', 'report_gate_ok',
                      'Missing required implementation report', 'timing_met',
                      'ramb36e1', 'CFGBVS-1'):
            self.assertIn(token, code)
        self.assertIn('if bitstream and any(', code)


if __name__ == '__main__':
    unittest.main()
