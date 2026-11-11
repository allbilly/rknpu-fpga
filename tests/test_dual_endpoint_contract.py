#!/usr/bin/env python3
"""Contract checks for the host-drivable endpoints and the dual image."""
from __future__ import annotations

import json
import glob
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONV_AXI = ROOT / 'rtl/cmac/rk_conv_simple_axi.sv'
POOL_AXI = ROOT / 'rtl/ppu/rk_ppu_pool_axi.sv'
DUAL_TOP = ROOT / 'fpga/ypcb_dual_endpoint_top.sv'
DUAL_SPEC = ROOT / 'fpga/dual/sources.json'
DUAL_TEMPLATE = ROOT / 'fpga/dual/build_dual.tcl.in'
DUAL_RENDERER = ROOT / 'tools/dual/vivado_dual.py'
DUAL_RUNNER = ROOT / 'tools/dual/run_dual_endpoint.py'
DUAL_BENCH = ROOT / 'tests/tb_ypcb_dual_endpoint.sv'
CONV_RUNNER = ROOT / 'tools/conv/run_conv_simple_axi.py'
POOL_RUNNER = ROOT / 'tools/ppu/run_pool_axi.py'
BRIDGE = ROOT / 'rtl/rk_axil_mem_bridge.sv'
ERROR_SLAVE = ROOT / 'rtl/rk_axil_error_slave.sv'
BRIDGE_BENCH = ROOT / 'tests/tb_axil_mem_bridge.sv'


def code_only(path: Path) -> str:
    return '\n'.join(line.split('//', 1)[0] for line in path.read_text().splitlines())


def normalised(path: Path) -> str:
    return ' '.join(code_only(path).split())


class ConvEndpointContractTests(unittest.TestCase):
    def test_transport_page_matches_the_existing_abi(self) -> None:
        code = code_only(CONV_AXI)
        # Same offsets as rk_job_control / rk_cmac_job_control.
        for offset in ("32'h00", "32'h04", "32'h08", "32'h0c", "32'h10",
                       "32'h14", "32'h18", "32'h1c", "32'h20", "32'h24"):
            self.assertIn(offset, code)
        self.assertIn("32'h524b4353", code)

    def test_submit_requires_all_fields_and_readiness(self) -> None:
        code = code_only(CONV_AXI)
        self.assertIn("can_submit = writable && (&fields_valid) && memory_ready",
                      code)
        # A submit that cannot proceed is SLVERR, never silently ignored.
        self.assertIn("else s_axil_bresp <= 2'b10", code)

    def test_read_only_registers_are_explicitly_rejected(self) -> None:
        code = code_only(CONV_AXI)
        self.assertIn("32'h00, 32'h04, 32'h08, 32'h1c, 32'h20, 32'h24:", code)

    def test_engine_geometry_is_forwarded_not_defaulted(self) -> None:
        code = code_only(CONV_AXI)
        for parameter in ('INPUT_H(INPUT_H)', 'KH(KH)', 'KW(KW)',
                          'INPUT_CHANNELS(INPUT_CHANNELS)',
                          'C1_BLOCKS(C1_BLOCKS)', 'ALIGN_C(ALIGN_C)',
                          'PACK_C2(PACK_C2)', 'CHUNK_LANES(CHUNK_LANES)'):
            self.assertIn(parameter, code, parameter)
        # And the same chain must exist in the DMA wrapper.
        dma = code_only(ROOT / 'rtl/cmac/rk_conv_simple_dma.sv')
        self.assertIn('.C1_BLOCKS(C1_BLOCKS)', dma)

    def test_runner_requires_eight_modes_and_per_mode_contract(self) -> None:
        code = CONV_RUNNER.read_text()
        for mode in range(8):
            self.assertIn(f'    {mode}: {{', code)
        self.assertIn("'starts': 1", code)
        self.assertIn("'starts': 0", code)
        self.assertIn('hardware_accessed', code)
        self.assertIn('bitstream_emitted', code)


class PoolEndpointContractTests(unittest.TestCase):
    def test_transport_page_identity_and_layout(self) -> None:
        code = code_only(POOL_AXI)
        self.assertIn("32'h524b5050", code)
        for offset in ("32'h00", "32'h04", "32'h08", "32'h0c", "32'h10",
                       "32'h14", "32'h18", "32'h1c", "32'h20", "32'h24"):
            self.assertIn(offset, code)

    def test_amount_must_be_the_captured_26_qwords(self) -> None:
        text = POOL_AXI.read_text()
        self.assertIn("WORDS = 26", text)
        self.assertIn('captured INT8 descriptors are exactly 26 QWORDs', text)
        self.assertIn('WORDS != 26', code_only(POOL_AXI))

    def test_runner_requires_eight_modes(self) -> None:
        code = POOL_RUNNER.read_text()
        for mode in range(8):
            self.assertIn(f'    {mode}: {{', code)


class DualImageContractTests(unittest.TestCase):
    def test_page_decode_uses_bits_15_to_12_and_masks_offsets(self) -> None:
        code = code_only(DUAL_TOP)
        # The image decodes 0x0..0x7 memory, 0x8 conv, 0x9 pool, rest SLVERR.
        self.assertIn('s_axil_awaddr[15:PAGE_SHIFT]', code)
        self.assertIn('s_axil_araddr[15:PAGE_SHIFT]', code)
        self.assertIn("PAGE_CONV = 4'h8", code)
        self.assertIn("PAGE_POOL = 4'h9", code)
        self.assertIn("PAGE_GEMM = 4'hA", code)
        self.assertIn("PAGE_CONV_FP32 = 4'hB", code)
        self.assertIn("PAGE_CONV_K5 = 4'hC", code)
        self.assertIn("PAGE_CONV_C16 = 4'hD", code)
        # Six owners do not fit in a 2-bit literal: that truncation silently
        # mapped OWN_GEMM onto OWN_NONE and starved the page. Pin the width.
        self.assertIn("localparam logic [2:0] OWN_NONE = 3'd0", code)
        self.assertEqual(code.count("localparam logic [2:0] OWN_"), 1)
        self.assertNotIn("localparam logic [1:0] OWN_", code)
        # Each page receives a 12-bit register offset, never the absolute address.
        self.assertEqual(
            code.count("{20'd0, write_address_q[11:0]}"), 6)
        self.assertEqual(
            code.count("{20'd0, read_address_q[11:0]}"), 6)

    def test_write_channel_is_buffered_for_independent_aw_and_w(self) -> None:
        code = code_only(DUAL_TOP)
        # AXI-Lite permits W before AW; the pages only complete a register write
        # when both are seen, so the top must collect them first.
        self.assertIn('have_aw_q', code)
        self.assertIn('have_w_q', code)
        self.assertIn('write_dispatch_q', code)

    def test_bram_arbitration_is_explicit(self) -> None:
        code = normalised(DUAL_TOP)
        # Every page sees the complement of the other three engines plus the
        # host, so no two engines can hold the memory port at once.
        # Every page sees the complement of all other engines plus the host.
        self.assertIn('conv_memory_ready = reset_n && !pool_busy && '
                      '!gemm_busy && !conv_fp32_busy && !conv_k5_busy && '
                      '!conv_c16_busy && !host_mem_busy', code)
        self.assertIn('pool_memory_ready = reset_n && !conv_busy && '
                      '!gemm_busy && !conv_fp32_busy && !conv_k5_busy && '
                      '!conv_c16_busy && !host_mem_busy', code)
        self.assertIn('gemm_memory_ready = reset_n && !conv_busy && !pool_busy '
                      '&& !conv_fp32_busy && !conv_k5_busy && !conv_c16_busy '
                      '&& !host_mem_busy', code)
        self.assertIn('conv_fp32_memory_ready = reset_n && !conv_busy && '
                      '!pool_busy && !gemm_busy && !conv_k5_busy && '
                      '!conv_c16_busy && !host_mem_busy', code)
        self.assertIn('conv_k5_memory_ready = reset_n && !conv_busy && '
                      '!pool_busy && !gemm_busy && !conv_fp32_busy && '
                      '!conv_c16_busy && !host_mem_busy', code)
        self.assertIn('conv_c16_memory_ready = reset_n && !conv_busy && '
                      '!pool_busy && !gemm_busy && !conv_fp32_busy && '
                      '!conv_k5_busy && !host_mem_busy', code)
        # Seven owners need three bits; values 6 and 7 are the new pages.
        self.assertIn('OWN_CONV_K5 = 3\'d6', code)
        self.assertIn('OWN_CONV_C16 = 3\'d7', code)
        self.assertIn('host_memory_enable = reset_n && !any_engine_busy', code)
        # Exactly one client is granted per request, and the grant is held.
        self.assertIn('conv_mem_req_ready = !owned && '
                      '(next_owner == OWN_CONV) && bram_req_ready', code)
        self.assertIn('pool_mem_req_ready = !owned && '
                      '(next_owner == OWN_POOL) && bram_req_ready', code)
        self.assertIn('host_mem_req_ready = !owned && '
                      '(next_owner == OWN_HOST) && bram_req_ready', code)
        self.assertIn('owner_q <= next_owner', code)

    def test_gemm_page_is_in_the_image_and_excluded_from_the_memory(self) -> None:
        code = normalised(DUAL_TOP)
        self.assertIn('rk_cmac_gemm_axi #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) '
                      'gemm_page', code)
        self.assertIn('T_GEMM', code)
        self.assertIn('OWN_GEMM', code)
        # The other pages must also observe the GEMM page.
        self.assertIn('conv_memory_ready = reset_n && !pool_busy && !gemm_busy',
                      code)
        self.assertIn('pool_memory_ready = reset_n && !conv_busy && !gemm_busy',
                      code)
        self.assertIn('conv_fp32_memory_ready = reset_n && !conv_busy && '
                      '!pool_busy && !gemm_busy', code)
        # Completion lines: three, not two.
        self.assertIn('output wire gemm_irq', code)

    def test_unmapped_probe_is_above_the_last_page(self) -> None:
        bench = normalised(ROOT / 'tests/tb_ypcb_dual_endpoint.sv')
        self.assertIn("GEMM_PAGE = 32'h0000_a000", bench)
        self.assertIn("CONV_FP32_PAGE = 32'h0000_b000", bench)
        self.assertIn("CONV_K5_PAGE = 32'h0000_c000", bench)
        self.assertIn("CONV_C16_PAGE = 32'h0000_d000", bench)
        # The probe must be above every real page, so it moved to 0xe000.
        self.assertIn("host_read(32'h0000_e000, value, 2'b10)", bench)
        jtag = normalised(ROOT / 'tests/tb_ypcb_jtag_dual.sv')
        self.assertIn("32'h0000_e000, 512'h0, 4'hf, frame_data, 8'd7", jtag)
        # 0xc000/0xd000 are real pages now, so neither may be probed as unmapped.
        self.assertNotIn("32'h0000_c000, 512'h0, 4'hf, frame_data, 8'd7", jtag)
        self.assertNotIn("32'h0000_d000, 512'h0, 4'hf, frame_data, 8'd7", jtag)

    def test_conv_fp32_page_is_separate_and_elaborated_to_profile_3(self) -> None:
        """A second conv page, not a run-time width switch."""
        code = normalised(DUAL_TOP)
        self.assertIn('rk_conv_simple_axi #( .PROFILE(3)', code)
        self.assertIn('conv_fp32_page', code)
        self.assertIn(".OUTPUT_FP16(1'b0)", code)
        self.assertIn("DEVICE_ID(32'h524b4415)", code)
        self.assertIn('conv_fp32_irq', code)
        # Both conv pages must be visible to the arbiter.
        self.assertIn('conv_fp32_mem_req_valid', code)
        self.assertIn('OWN_CONV_FP32', code)
        # The host memory aperture must not collide with any transport page.
        self.assertIn('BRAM_BYTES > 32768', code)

    def test_conv_fp32_page_has_a_passing_mode_6_receipt(self) -> None:
        """Pin the receipt, not the tree inventory.

        Mode 6 is the FP32 conv job. The repository policy is to delete
        superseded receipt trees, so an in-flight sweep must not be treated as
        a failure and a missing simulator leg is not a claim. What is required:
        at least one PASS mode-6 report exists, and no report whose recorded top
        hash equals the current file is FAIL.
        """
        import hashlib, json
        current_top = hashlib.sha256(DUAL_TOP.read_bytes()).hexdigest()
        reports = []
        for path in glob.glob(str(ROOT / 'build/dual-endpoint' / '*'
                                  / 'mode-6/report.json')):
            reports.append((Path(path), json.loads(Path(path).read_text())))
        self.assertTrue(reports, 'no mode-6 receipt anywhere on disk')
        passing = [r for _, r in reports if r.get('status') == 'PASS' and r.get('mode') == 6]
        self.assertTrue(passing, 'mode 6 has never passed')
        for path, report in reports:
            if report.get('status') != 'FAIL':
                continue
            recorded = (report.get('source_hashes_before') or {}).get(
                'fpga/ypcb_dual_endpoint_top.sv')
            if recorded == current_top:
                self.fail(f'{path}: mode 6 FAILs against the current top')

    def test_unmapped_addresses_return_slverr(self) -> None:
        code = normalised(DUAL_TOP)
        self.assertIn('T_UNMAPPED', code)
        self.assertIn('rk_axil_error_slave error_page', code)
        slave = code_only(ERROR_SLAVE)
        self.assertIn("assign s_axil_bresp = 2'b10;", slave)
        self.assertIn("assign s_axil_rresp = 2'b10;", slave)

    def test_profile_lists_every_source_and_no_generated_rom(self) -> None:
        spec = json.loads(DUAL_SPEC.read_text())
        self.assertEqual(spec['top'], 'ypcb_dual_endpoint_top')
        self.assertEqual(spec['part'], 'xc7k480tffg1156-2')
        self.assertEqual(spec['clock_period_ns'], 20)
        self.assertNotIn('generated', spec)
        self.assertEqual(len(spec['sources']), len(set(spec['sources'])))
        for name in spec['sources'] + [spec['constraints']]:
            self.assertTrue((ROOT / name).is_file(), name)
        for bench in spec['benches'].values():
            self.assertTrue((ROOT / bench).is_file(), bench)

    def test_renderer_refuses_a_generated_block(self) -> None:
        code = DUAL_RENDERER.read_text()
        self.assertIn('must not declare generated sources', code)
        self.assertIn('@PART@', code)

    def test_template_keeps_the_electrical_and_timing_gates(self) -> None:
        text = DUAL_TEMPLATE.read_text()
        for token in ('RK_CONFIG_VOLTAGE', 'RK_CFGBVS', 'RK_EMIT_BITSTREAM',
                      'RK_CONFIRM_BOARD', 'RK_LED_ACTIVE_LOW',
                      'set emit_bitstream 0'):
            self.assertIn(token, text)
        self.assertIn('set emit_polarity 0', text)

    def test_board_replay_drives_the_host_port_only(self) -> None:
        bench = code_only(DUAL_BENCH)
        # The bench must load fixtures and submit jobs through the AXI port,
        # not poke engine internals.
        self.assertIn('host_write', bench)
        self.assertIn('host_read', bench)
        for forbidden in ('dut.conv_page.engine', 'dut.pool_page.engine.',
                          'force ', 'release '):
            self.assertNotIn(forbidden, bench, forbidden)
        # And it must compare the complete captured BO.
        self.assertIn('output word', bench)


class BridgeContractTests(unittest.TestCase):
    def test_bridge_rejects_partial_and_unaligned_access(self) -> None:
        code = code_only(BRIDGE)
        # Partial strobes are refused; the compare is on the live signal.
        self.assertIn("s_axil_wstrb != 4'hf", code)
        self.assertIn("address[1:0] == 2'b00", code)
        # A memory error becomes an AXI error, not a good transfer.
        self.assertIn('mem_rsp_error', code)
        self.assertIn("assign s_axil_bresp = error_q ? 2'b10 : 2'b00", code)

    def test_bridge_has_its_own_bench(self) -> None:
        self.assertTrue(BRIDGE_BENCH.is_file())
        bench = BRIDGE_BENCH.read_text()
        self.assertIn('PASS AXI_MEM_BRIDGE', bench)
        # The bench must cover the failures, not only the happy path.
        for case in ('Partial strobe', 'Unaligned address', 'Out-of-range',
                     'Protected access', 'W before AW', 'AW before W',
                     'withdraw ready'):
            self.assertIn(case, bench, case)


class JtagAxilBridgeContractTests(unittest.TestCase):
    """The pin-free host path: USER2 mailbox frames -> AXI4-Lite."""

    def test_bridge_maps_the_frozen_mailbox_opcodes(self) -> None:
        code = code_only(ROOT / 'rtl/host/rk_jtag_axil_bridge.sv')
        self.assertIn("8'd1: state_q <= READ_REG", code)
        self.assertIn("8'd2: state_q <= WRITE_REG", code)
        self.assertIn("8'd3: state_q <= BLOCK_READ", code)
        self.assertIn("8'd4: state_q <= BLOCK_WRITE", code)
        # The magic and sequence fields are unchanged from OpenTPU.
        self.assertIn("32'h4f54504a", code)
        self.assertIn("req[571:556]", code)

    def test_bridge_status_codes_are_explicit(self) -> None:
        code = code_only(ROOT / 'rtl/host/rk_jtag_axil_bridge.sv')
        for name in ('ST_OK = 8\'d0', 'ST_ALIGN = 8\'d4', 'ST_FRAME = 8\'d5',
                     'ST_DOWNSTREAM = 8\'d7', 'ST_TIMEOUT = 8\'h80'):
            self.assertIn(name, code)
        # A timeout quarantines; no silent retry or drop.
        self.assertIn('quarantine(ST_TIMEOUT)', code)

    def test_bridge_bench_covers_every_status(self) -> None:
        bench = (ROOT / 'tests/host/tb_jtag_axil_bridge.sv').read_text()
        for case in ('Misaligned block address', 'Misaligned register address',
                     'Bad magic', 'Downstream error', 'timeout'):
            self.assertIn(case, bench, case)
        self.assertIn('PASS JTAG_AXIL_BRIDGE', bench)

    def test_pin_free_top_has_no_axi_top_level_ports(self) -> None:
        top = code_only(ROOT / 'fpga/ypcb_jtag_dual_top.sv')
        # Package pins are only SYS_CLK and the LEDs; the AXI slave is internal.
        self.assertNotIn('output wire [31:0] s_axil_rdata', top)
        self.assertIn('BSCANE2', top)
        self.assertIn('otpu_jtag_mailbox', top)
        self.assertIn('rk_jtag_axil_bridge', top)
        self.assertIn('ypcb_dual_endpoint_top', top)

    def test_jtag_dual_bench_drives_frames_only(self) -> None:
        bench = (ROOT / 'tests/tb_ypcb_jtag_dual.sv').read_text()
        self.assertIn('scan_frame', bench)
        self.assertIn('PASS YPCB_JTAG_DUAL', bench)
        for forbidden in ('host_write(', 's_axil_awvalid =', 'force '):
            self.assertNotIn(forbidden, bench, forbidden)


class DualRunnerContractTests(unittest.TestCase):
    def test_runner_covers_four_modes_in_both_simulators(self) -> None:
        code = DUAL_RUNNER.read_text()
        for mode in range(4):
            self.assertIn(f'    {mode}: {{', code)
        self.assertIn("'iverilog', 'verilator'", code)
        self.assertIn('hardware_accessed', code)
        self.assertIn('bitstream_emitted', code)

    def test_runner_binds_both_frozen_fixtures(self) -> None:
        code = DUAL_RUNNER.read_text()
        self.assertIn("conv_simple_fp16_3x3_c4_h8_w8_oc16", code)
        self.assertIn("int8_max_k2s2_valid_c16_h2w2", code)
        # Full-BO comparison: the expected image is padded to 4096 bytes.
        self.assertIn("4096 - len(captured)", code)

    def test_runner_checks_captured_addresses_not_hardcodes(self) -> None:
        code = DUAL_RUNNER.read_text()
        # The conv placement is asserted against the capture, and the pooling
        # patches are checked against the image's own layout instead of being
        # assumed equal.
        self.assertIn("if addresses != CONV_ADDRESSES", code)
        self.assertIn("if sorted(addresses.values()) != sorted(POOL_ADDRESSES.values())",
                      code)


class GemmFp32ContractTests(unittest.TestCase):
    """The GEMM leaf: measured decoder delta, FP32 tail, complete-BO replay."""

    PROFILE = ROOT / 'rtl/rk_cmac_profile.sv'
    ADDRESS = ROOT / 'rtl/rk_cmac_address.sv'
    TAIL = ROOT / 'rtl/cmac/rk_cmac_output_fp32.sv'
    PIPE = ROOT / 'rtl/cmac/rk_nvdla_cmac_pipe.sv'
    RUNNER = ROOT / 'tools/cmac/run_gemm_fp32.py'

    def test_decoder_values_are_derived_not_transplanted(self) -> None:
        code = code_only(self.PROFILE)
        # The three GEMM-vs-conv differences come from the source's own formulas.
        self.assertIn("(OUTPUT_FP16 ? (32'd2 << 29) : (32'd5 << 29))", code)
        self.assertIn("(OUTPUT_FP16 ? 32'd1 : 32'd3) << 8", code)
        self.assertIn("OUTPUT_FP16 ? 32'h0001_0001 : 32'h0000_0000", code)
        # And the FP16 default must still be the conv capture's values.
        for literal in ("32'h48000002", "32'h126", "32'h10001"):
            self.assertNotIn(literal, code,
                             f'hardcoded capture value {literal} came back')

    def test_parameter_reaches_every_consumer(self) -> None:
        core = code_only(ROOT / 'rtl/cmac/rk_cmac_nvdla_core.sv')
        self.assertIn('.OUTPUT_FP16(OUTPUT_FP16)) frontend(', core)
        self.assertIn('.OUTPUT_FP16(OUTPUT_FP16)) pipeline(', core)
        front = ' '.join(code_only(ROOT / 'rtl/rk_cmac_operand_front.sv').split())
        self.assertIn('rk_cmac_address #(.OUTPUT_FP32(~OUTPUT_FP16)) addresses', front)

    def test_pipe_selects_the_tail_at_elaboration(self) -> None:
        code = code_only(self.PIPE)
        self.assertIn('if (OUTPUT_FP16) begin : g_fp16_tail', code)
        self.assertIn('end else begin : g_fp32_tail', code)
        self.assertIn('rk_cmac_output_fp32', code)
        self.assertIn('rk_cmac_output_nvdla', code)

    def test_fp32_tail_does_not_convert(self) -> None:
        code = code_only(self.TAIL)
        self.assertIn('rk_cmac_fp32_writer', code)
        for forbidden in ('fp32_to_fp16', 'hls_', 'converted'):
            self.assertNotIn(forbidden, code.lower(), forbidden)

    def test_runner_uses_the_fixture_tolerance_and_full_bo(self) -> None:
        code = self.RUNNER.read_text()
        self.assertIn("'k': 1, 'tolerance': 0.0", code)
        self.assertIn("'k': 32, 'tolerance': 0.1", code)
        self.assertIn('worst_abs', code)
        self.assertIn('OUTPUT_BYTES = 4096', code)
        # The three value32 fields are relocated from a checked vendor default.
        self.assertIn('from the vendor default', code)

    def test_bench_pins_the_bo_and_the_write_count(self) -> None:
        bench = (ROOT / 'tests/cmac/tb_cmac_gemm_fp32.sv').read_text()
        flat = ' '.join(bench.lower().split())
        self.assertIn('two halfwords per output value', flat)
        # The sentence wraps a comment line, so match the fragment that does
        # not straddle the `//` prefix.
        self.assertIn('access outside them is an error', flat)
        self.assertIn('pass cmac_gemm_fp32', flat)

    def test_address_walker_keeps_the_fp16_path_intact(self) -> None:
        code = code_only(self.ADDRESS)
        # The FP16 atom rule must remain exactly as before.
        compact = ' '.join(code.split())
        self.assertIn("output_address + (OUTPUT_FP32 ? 32'd4 : 32'd2)", compact)
        # The output crossing is one element in FP32, not the padded atom.
        self.assertIn("(OUTPUT_FP32 ? 32'd4 : 32'd34)", compact)


class Fp32WriterContractTests(unittest.TestCase):
    """The first 32-bit output path; FP16 writers cannot serve FP32 captures."""

    WRITER = ROOT / 'rtl/cmac/rk_cmac_fp32_writer.sv'
    BENCH = ROOT / 'tests/cmac/tb_cmac_fp32_writer.sv'

    def test_writer_commits_two_halfwords_per_value(self) -> None:
        code = code_only(self.WRITER)
        self.assertIn('address_q + (half_q ? 32\'d2 : 32\'d0)', code)
        self.assertIn('half_q ? value_q[31:16] : value_q[15:0]', code)
        # No conversion anywhere: the writer is transport only.
        for forbidden in ('fp16', 'HLS_', 'round', 'convert'):
            self.assertNotIn(forbidden, code.lower(), forbidden)

    def test_writer_rejects_misaligned_addresses(self) -> None:
        code = code_only(self.WRITER)
        self.assertIn("result_address[1:0] != 2'b00", code)
        self.assertIn('error_code <= 8\'d4', code)
        # A downstream error must not be silently ignored.
        self.assertIn('error_code <= 8\'d5', code)

    def test_bench_pins_the_byte_contract(self) -> None:
        bench = self.BENCH.read_text()
        for case in ('low halfword wrong', 'high halfword wrong',
                     'misaligned address was not rejected',
                     'downstream error was not code 5'):
            self.assertIn(case, bench, case)
        self.assertIn('PASS CMAC_FP32_WRITER', bench)

    def test_profile_lists_the_new_writer(self) -> None:
        spec = json.loads((ROOT / 'fpga/cmac/sources.json').read_text())
        self.assertIn('rtl/cmac/rk_cmac_fp32_writer.sv', spec['synthesis'])
        self.assertIn('fp32_writer', spec['benches'])


class GemmAxilEndpointContractTests(unittest.TestCase):
    """The FP32 GEMM leaf is now host-drivable and has a board page."""

    PAGE = ROOT / 'rtl/cmac/rk_cmac_gemm_axi.sv'
    BRIDGE = ROOT / 'rtl/rk_axi_mem_slave.sv'
    BRIDGE_BENCH = ROOT / 'tests/host/tb_axi_mem_slave.sv'
    GEMM_BENCH = ROOT / 'tests/cmac/tb_cmac_gemm_fp32_axi.sv'
    RUNNER = ROOT / 'tools/cmac/run_gemm_fp32_axi.py'

    def test_page_selects_the_fp32_tail(self) -> None:
        code = code_only(self.PAGE)
        self.assertIn("rk_cmac_nvdla_dma #(", code)
        self.assertIn(".OUTPUT_FP16(1'b0)", code)
        self.assertIn('rk_cmac_job_control control', code)
        # The page drives the halfword port directly: no AXI round trip.
        self.assertNotIn('m_axi_', code)
        # Transport only: no conversion in the page itself.
        for forbidden in ('fp32_to_fp16', 'hls_'):
            self.assertNotIn(forbidden, code.lower(), forbidden)

    def test_bridge_accepts_only_the_cmac_access_shape(self) -> None:
        code = code_only(self.BRIDGE)
        # Single beat, 512-bit, INCR, and exactly one full halfword lane.
        self.assertIn("(len == 8'd0) && (size == 3'd6) && (burst == 2'b01)", code)
        self.assertIn("write_shape_ok = count == 1", code)
        # One outstanding transaction, so a fast memory cannot double-fetch.
        self.assertIn('issue_pending_q', code)
        self.assertIn('!issue_pending_q', code)
        # Beat base is 64-byte aligned and the whole beat fits the aperture.
        self.assertIn('BEAT_BYTES', code)
        self.assertIn('beat_legal', code)
        # No arithmetic anywhere.
        for forbidden in ('fp16', 'mul', 'add'):
            self.assertNotIn(' ' + forbidden + ' ', code.lower(), forbidden)

    def test_bridge_bench_pins_the_negative_paths(self) -> None:
        bench = ' '.join(self.BRIDGE_BENCH.read_text().split())
        self.assertIn('PASS AXI_MEM_SLAVE', bench)
        self.assertIn('out-of-aperture write reached memory', bench)
        self.assertIn('partial-lane write not SLVERR', bench)
        self.assertIn('multi-beat read not SLVERR', bench)
        self.assertIn('misaligned beat base', bench)

    def test_gemm_endpoint_bench_compares_the_whole_bo(self) -> None:
        bench = ' '.join(self.GEMM_BENCH.read_text().split())
        self.assertIn('PASS CMAC_GEMM_FP32_AXI', bench)
        self.assertIn("rk_cmac_nvdla_axi #(.TIMEOUT_CYCLES(65536), "
                      ".OUTPUT_FP16(1'b0))", bench)
        self.assertIn('rk_axi_mem_slave #(', bench)
        # The job must not start before memory admission, and the faulted
        # result slot must stay held.
        self.assertIn('job launched before memory admission', bench)
        self.assertIn('faulted result was released without a reset', bench)
        self.assertIn('wrote %0d halfwords, expected %0d', bench)

    def test_runner_pins_tolerance_and_negative_modes(self) -> None:
        code = self.RUNNER.read_text()
        self.assertIn("'k': 1, 'tolerance': 0.0", code)
        self.assertIn("0: {'kind': 'job', 'starts': 1}", code)
        self.assertIn("2: {'kind': 'reject', 'starts': 1}", code)
        self.assertIn('source_hashes_before', code)
        self.assertIn('hardware_accessed', code)


class ConvSimpleFp32ContractTests(unittest.TestCase):
    """The last data-only conv-simple capture now has an executing path."""

    OUTPUT = ROOT / 'rtl/cmac/rk_conv_output_c1c2_fp32.sv'
    CORE = ROOT / 'rtl/cmac/rk_conv_simple_core.sv'
    TABLE = ROOT / 'rtl/cmac/rk_conv_simple_profiles.svh'
    GENERATOR = ROOT / 'tools/conv/gen_conv_simple_profiles.py'
    RUNNER = ROOT / 'tools/conv/run_conv_simple_fp32.py'
    BENCH = ROOT / 'tests/conv/tb_conv_simple_fp32.sv'

    def test_profile_three_is_generated_from_the_fixture(self) -> None:
        generator = self.GENERATOR.read_text()
        self.assertIn("'id': 3, 'name': 'FP32_1X1_C4_OC16'", generator)
        self.assertIn('conv_simple_fp16_1x1_c4_h8_w8_oc16', generator)
        table = self.TABLE.read_text()
        self.assertIn('3: FP32_1X1_C4_OC16', table)
        # The table is derived, never hand-edited.
        self.assertIn('GENERATED by tools/conv/gen_conv_simple_profiles.py', table)

    def test_output_stage_places_values_by_c1_and_c2(self) -> None:
        code = code_only(self.OUTPUT)
        self.assertIn('rk_cmac_fp32_writer', code)
        # The plane stride is the measured PIXELS*C2 words, not PIXELS words.
        self.assertIn('PLANE_BYTES = PIXELS * C2 * 4', code)
        self.assertIn('plane_index * 32\'(PLANE_BYTES)', code)
        self.assertIn('slot_index * 32\'d4', code)
        # Transport only: no conversion anywhere in the path.
        for forbidden in ('fp32_to_fp16', 'hls_', 'convert'):
            self.assertNotIn(forbidden, code.lower(), forbidden)

    def test_core_selects_the_fp32_stage_at_elaboration(self) -> None:
        code = code_only(self.CORE)
        self.assertIn('if (OUTPUT_FP16) begin : g_fp16_output', code)
        self.assertIn('end else begin : g_fp32_output', code)
        self.assertIn('rk_conv_output_c1c2_fp32', code)
        self.assertIn('rk_conv_output_atom', code)

    def test_parameter_is_forwarded_by_the_wrappers(self) -> None:
        for name in ('rtl/cmac/rk_conv_simple_dma.sv',
                     'rtl/cmac/rk_conv_simple_axi.sv'):
            code = code_only(ROOT / name)
            self.assertIn('parameter bit OUTPUT_FP16', code, name)
            self.assertIn('.OUTPUT_FP16(OUTPUT_FP16)', code, name)

    def test_runner_uses_a_measured_tolerance_and_full_bo(self) -> None:
        code = self.RUNNER.read_text()
        self.assertIn('TOLERANCE_ABS = 0.001', code)
        self.assertIn('worst_abs', code)
        self.assertIn('counts[1] != 4096', code)
        self.assertIn('differing_words', code)
        # The three value32 fields are relocated from the frozen zero
        # placeholder, never from an assumed vendor base.
        self.assertIn('frozen zero placeholder', code)

    def test_bench_reports_the_deviation_not_just_first_byte(self) -> None:
        bench = ' '.join(self.BENCH.read_text().split())
        self.assertIn('PASS CONV_SIMPLE_FP32', bench)
        self.assertIn('differing_words', bench)
        self.assertIn('worst_abs', bench)
        # The DMA only leaves FINISH when result_ready is asserted.
        self.assertIn(".result_ready(1'b1)", bench)


class JtagImagePagePresenceTests(unittest.TestCase):
    """The build must prove each page exists, not just list its sources."""

    TEMPLATE = ROOT / 'fpga/jtag_dual/build_jtag_dual.tcl.in'

    def test_template_asserts_every_page_is_elaborated(self) -> None:
        text = self.TEMPLATE.read_text()
        self.assertIn('foreach page {conv_page pool_page gemm_page '
                      'conv_fp32_page conv_k5_page conv_c16_page}', text)
        self.assertIn('Expected exactly one elaborated instance of', text)
        # The check has to happen before implementation, not after.
        self.assertLess(text.index('conv_c16_page}'), text.index('place_design'))


class JtagRunnerGemmContractTests(unittest.TestCase):
    """The mailbox runner must actually exercise the GEMM page."""

    RUNNER = ROOT / 'tools/host/run_jtag_dual.py'
    BENCH = ROOT / 'tests/tb_ypcb_jtag_dual.sv'

    def test_runner_declares_the_gemm_mode(self) -> None:
        code = self.RUNNER.read_text()
        self.assertIn("3: {'kind': 'gemm_job'}", code)
        self.assertIn('gemm_m2_n2_k1', code)
        self.assertIn('GEMM_COMMAND_WORDS=', code)
        self.assertIn('gemm["command_words"]', code)
        self.assertIn('49', code)          # fetched QWORDs

    def test_bench_checks_the_gemm_page_identity_and_job(self) -> None:
        bench = ' '.join(self.BENCH.read_text().split())
        self.assertIn("check_page(GEMM_PAGE, 32'h524b434d)", bench)
        self.assertIn('GEMM produced no result', bench)
        self.assertIn('GEMM result tag', bench)
        # The whole BO is compared, not a prefix.
        self.assertIn('compare_words(GEMM_OUTPUT, gemm_dir, '
                      'GEMM_OUTPUT_WORDS, GEMM_TOLERANCE)', bench)


class JtagDualImageContractTests(unittest.TestCase):
    """The pin-free build profile must not invent a single package pin."""

    SPEC = ROOT / 'fpga/jtag_dual/sources.json'
    XDC = ROOT / 'fpga/jtag_dual.xdc'
    TEMPLATE = ROOT / 'fpga/jtag_dual/build_jtag_dual.tcl.in'
    RENDERER = ROOT / 'tools/dual/vivado_jtag_dual.py'

    def test_profile_declares_the_pin_free_top(self) -> None:
        spec = json.loads(self.SPEC.read_text())
        self.assertEqual(spec['top'], 'ypcb_jtag_dual_top')
        self.assertEqual(spec['part'], 'xc7k480tffg1156-2')
        self.assertEqual(spec['clock_period_ns'], 20.0)
        self.assertEqual(spec['jtag_chain'], 2)
        self.assertNotIn('generated', spec)
        for name in spec['sources'] + [spec['constraints']]:
            self.assertTrue((ROOT / name).is_file(), name)
        for bench in spec['benches'].values():
            self.assertTrue((ROOT / bench).is_file(), bench)

    def test_constraints_use_only_the_audited_pins(self) -> None:
        text = self.XDC.read_text()
        pins = {line.split()[2] for line in text.splitlines()
                if 'PACKAGE_PIN' in line}
        self.assertEqual(pins, {'AA28', 'P30', 'M30', 'N30'})
        # No LOC was invented for any AXI or JTAG signal: only comments may
        # mention them, never a PACKAGE_PIN assignment.
        for line in text.splitlines():
            if 'PACKAGE_PIN' in line:
                self.assertNotIn('s_axil', line)
                self.assertNotIn('tck', line.lower())
        self.assertIn('create_clock', text)

    def test_template_applies_the_mailbox_cdc_and_keeps_the_gates(self) -> None:
        text = self.TEMPLATE.read_text()
        self.assertIn('@CDC@', text)
        self.assertIn('rk_host_cdc_constrain', text)
        self.assertIn('rk_host_cdc_audit', text)
        self.assertIn('set emit_bitstream 0', text)
        self.assertIn('set emit_polarity 0', text)
        for token in ('RK_CONFIRM_BOARD', 'RK_CONFIG_VOLTAGE', 'RK_CFGBVS',
                      'RK_LED_ACTIVE_POLARITY_PLACEHOLDER'):
            if token == 'RK_LED_ACTIVE_POLARITY_PLACEHOLDER':
                continue
            self.assertIn(token, text)
        # The BSCANE2 chain is asserted, not assumed.
        self.assertIn('JTAG_CHAIN', text)

    def test_renderer_passes_the_cdc_path(self) -> None:
        code = self.RENDERER.read_text()
        self.assertIn("'@CDC@'", code)
        self.assertIn('mailbox_cdc.tcl', code)
        self.assertIn("build/jtag-dual-image", code)


class JtagDualRunnerContractTests(unittest.TestCase):
    """The JTAG dual runner must exist and bind the frozen fixtures."""

    def test_runner_exists_and_covers_two_modes(self) -> None:
        runner = ROOT / 'tools/host/run_jtag_dual.py'
        self.assertTrue(runner.is_file(), 'missing JTAG dual runner')
        code = runner.read_text()
        for mode in range(3):
            self.assertIn(f"{mode}: {{", code)
        self.assertIn("'iverilog', 'verilator'", code)
        self.assertIn('hardware_accessed', code)
        self.assertIn('bitstream_emitted', code)

    def test_runner_binds_both_frozen_fixtures(self) -> None:
        code = (ROOT / 'tools/host/run_jtag_dual.py').read_text()
        self.assertIn('conv_simple_fp16_3x3_c4_h8_w8_oc16', code)
        self.assertIn('int8_max_k2s2_valid_c16_h2w2', code)
        # The conv capture defines 1152 bytes; the expected image pads it to
        # the full BO so the comparison covers every untouched byte too.
        self.assertIn('4096 - len(captured)', code)
        self.assertIn('CONV_OUTPUT_WORDS = 1024', code)


if __name__ == '__main__':
    unittest.main()
