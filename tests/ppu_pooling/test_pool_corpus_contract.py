#!/usr/bin/env python3
"""Contract checks for the multi-case pooling-corpus image.

These tests pin the properties that make the image honest: one page per frozen
pooling fixture (19 READY capture-manifest cases, nothing silently dropped), a
generated strict command gate derived from the frozen captures, per-page
identities, explicit SLVERR for unmapped addresses and refused submits, the
shared 32 KiB memory aperture with the proven single-owner arbitration, the
USER2 mailbox transport, and the build gates that refuse a bitstream on a
missing page, timing miss or blocking DRC.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / 'rtl/ppu/rk_ppu_pool_corpus_axi.sv'
CASE = ROOT / 'rtl/ppu/rk_ppu_pool_corpus_case.sv'
IMAGE = ROOT / 'fpga/ypcb_ppu_corpus_top.sv'
WRAPPER = ROOT / 'fpga/ypcb_ppu_corpus_jtag_top.sv'
XDC = ROOT / 'fpga/ypcb_ppu_corpus.xdc'
SPEC = ROOT / 'fpga/ppu/corpus_sources.json'
TEMPLATE = ROOT / 'fpga/ppu/build_pool_corpus.tcl.in'
BUILDER = ROOT / 'tools/ppu/vivado_pool_corpus.py'
GENERATOR = ROOT / 'tools/ppu/gen_pool_corpus_tables.py'
RUNNER = ROOT / 'tools/ppu/run_pool_corpus.py'
BENCH = ROOT / 'tests/tb_ypcb_ppu_corpus.sv'
CAPTURE_MANIFEST = ROOT / 'build/rk3588-example-captures/pooling/manifest.json'
PAGES = 19


def code_only(path: Path) -> str:
    return '\n'.join(line.split('//', 1)[0] for line in path.read_text().splitlines())


def normalised(path: Path) -> str:
    return ' '.join(code_only(path).split())


class CorpusGeneratorContractTests(unittest.TestCase):
    def test_generator_is_source_bound_and_fresh(self) -> None:
        text = GENERATOR.read_text()
        # The tables come from the frozen capture manifest and the per-fixture
        # files, never from a hand-written value table.
        self.assertIn("build/rk3588-example-captures/pooling/manifest.json", text)
        self.assertIn('def capture_entry(', text)
        self.assertIn('record[\'sha256\']', text)
        self.assertIn("ADDR_MASK = 0x0000_FFFF_FFFF_0000", text)
        result = subprocess.run(
            [sys.executable, str(GENERATOR), '--check'], cwd=ROOT,
            text=True, capture_output=True, check=False, timeout=120)
        self.assertEqual(result.returncode, 0,
                         f'generated case RTL is stale: {result.stdout}{result.stderr}')

    def test_corpus_is_exactly_the_manifest_ready_set(self) -> None:
        if not CAPTURE_MANIFEST.is_file():
            self.skipTest('frozen capture manifest is not present in this tree')
        manifest = json.loads(CAPTURE_MANIFEST.read_text())
        ready = sorted(manifest['ready_cases'])
        blocked = set(manifest['blocked_cases'])
        self.assertEqual(len(ready), PAGES)
        self.assertFalse(set(ready) & blocked)
        fixture_dir = ROOT / 'tests/ppu_pooling/fixtures'
        self.assertTrue(all((fixture_dir / case).is_dir() for case in ready))
        generated = CASE.read_text()
        for page, case in enumerate(ready):
            self.assertIn(f'// page {page}: {case}', generated)
        # The two BLOCKED zero-write captures have no valid oracle and are
        # documented exclusions, not silent drops.
        for case in blocked:
            self.assertNotIn(case, generated)
        # The legacy k16s16 fixture is not part of the capture manifest.
        self.assertNotIn('fp16_max_k16s16_c8_h16w16', generated)

    def test_generated_gate_matches_fixture_command_lengths(self) -> None:
        if not CAPTURE_MANIFEST.is_file():
            self.skipTest('frozen capture manifest is not present in this tree')
        sys.path.insert(0, str(ROOT))
        from tools.ppu import gen_pool_corpus_tables as corpus
        generated = CASE.read_text()
        for page, case in enumerate(corpus.corpus_cases()):
            spec = corpus.load_case(case, page)
            import re as _re
            match = _re.search(
                rf'begin : g_case_{page}\b(.*?)(?=\n        end else if \(CASE ==|'
                rf'\n        end else begin : g_unsupported)', generated, _re.S)
            self.assertIsNotNone(match, case)
            block = match.group(1)
            self.assertIn(f'localparam int unsigned CMD_QWORDS = {spec["qwords"]};',
                          block, case)
            self.assertIn(f'localparam int unsigned IN_ATOMS = {spec["in_atoms"]};',
                          block, case)
            self.assertIn(f'localparam int unsigned OUT_ATOMS = {spec["out_atoms"]};',
                          block, case)
            self.assertIn(f'localparam logic [31:0] CASE_DEVICE_ID = '
                          f'32\'h{spec["device_id"]:08x};', block, case)
            self.assertIn(spec['leaf'] if isinstance(spec['leaf'], str)
                          else spec['leaf'][0], block, case)

    def test_generated_gate_checks_every_captured_word(self) -> None:
        text = CASE.read_text()
        # Every relocation QWORD is compared with the address field wildcarded.
        self.assertIn('(cmd_data & 64\'hffff00000000ffff)', text)
        self.assertIn('cmd_data[47:16]', text)
        # A wrong command length at either end is an explicit profile fault.
        self.assertIn("if (!cmd_last && (word_q == 6'(CMD_QWORDS - 1)))", text)
        self.assertIn("else if (cmd_last && (word_q != 6'(CMD_QWORDS - 1)))", text)


class CorpusPageContractTests(unittest.TestCase):
    def test_page_keeps_the_transport_abi_and_identity_registers(self) -> None:
        code = code_only(PAGE)
        for offset in ("32'h00", "32'h04", "32'h08", "32'h0c", "32'h10",
                       "32'h14", "32'h18", "32'h1c", "32'h20", "32'h24"):
            self.assertIn(offset, code)
        self.assertIn("32'h28: s_axil_rdata <= {27'd0, fixture_index};", code)
        self.assertIn("32'h2c: s_axil_rdata <= fixture_crc32;", code)
        self.assertIn("32'h28, 32'h2c: s_axil_bresp <= 2'b10;", code)
        # A submit that cannot proceed is SLVERR, never silently ignored.
        self.assertIn("end else s_axil_bresp <= 2'b10;", code)

    def test_index_registers_are_read_only_in_the_abi(self) -> None:
        normalised_code = normalised(PAGE)
        self.assertIn("32'h00, 32'h04, 32'h08, 32'h1c, 32'h20, 32'h24, "
                      "32'h28, 32'h2c: s_axil_bresp <= 2'b10;", normalised_code)

    def test_page_identity_comes_from_the_generated_case(self) -> None:
        code = code_only(PAGE)
        self.assertIn('.device_id, .fixture_crc32, .fixture_index', code)
        self.assertIn('32\'h524b5000 + page + 1', BENCH.read_text())
        self.assertIn('CASE_DEVICE_ID', CASE.read_text())

    def test_engine_fetches_the_whole_stream_before_the_strict_gate(self) -> None:
        code = code_only(PAGE)
        # The command gate is released only after the last QWORD is buffered.
        self.assertIn('gate_rst_n_q <= 1\'b1;', code)
        self.assertIn('if (fetch_qword_q == 6\'(case_qwords - 1)) begin', code)
        # The leaf is released only after the operand windows are proven.
        self.assertIn('leaf_rst_n_q <= 1\'b1;', code)
        # Windows must be aligned, in aperture, and disjoint from the command.
        self.assertIn('profile_src_base[3:0] != 4\'d0', code)
        self.assertIn('ranges_overlap(command_base_q, command_end_q,', code)
        # Result atoms are drained before a stalled input atom is retried.
        self.assertIn('else if (out_pending_q) begin', code)

    def test_page_has_no_cpu_arithmetic_or_layout_repair(self) -> None:
        code = code_only(PAGE).lower()
        for forbidden in ('fp16_to_float', 'cpu_', 'float64'):
            self.assertNotIn(forbidden, code, forbidden)

    def test_page_documents_the_captured_index_adapter(self) -> None:
        text = PAGE.read_text()
        self.assertIn('rk_ppu_pool_corpus_index_leaf index_adapter', CASE.read_text())
        self.assertIn('module rk_ppu_pool_corpus_index_leaf', text)
        self.assertIn('leaf_value_atom', text)
        self.assertIn('leaf_index_atom', text)


class CorpusImageContractTests(unittest.TestCase):
    def test_image_has_one_page_per_fixture(self) -> None:
        code = normalised(IMAGE)
        self.assertIn('parameter int unsigned N_PAGES = 19', code)
        self.assertIn('for (g = 0; g < N_PAGES; g = g + 1) begin : g_pages', code)
        self.assertIn('rk_ppu_pool_corpus_axi #( .CASE(g),', code)
        self.assertIn('(* KEEP_HIERARCHY = "TRUE" *)', code)
        self.assertIn('assign page_irq = page_irq_q;', code)
        # The page map: 0x8000 + i*0x1000 over the shared 32 KiB aperture.
        self.assertIn("localparam int unsigned PAGE_FIRST = 8;", code)
        self.assertIn("if (BRAM_BASE != 32'h0000_0000 || BRAM_BYTES != 32768)", code)
        self.assertIn('decode = 6\'(page_code - 12\'(PAGE_FIRST));', code)

    def test_unmapped_addresses_are_explicit_slverr(self) -> None:
        code = normalised(IMAGE)
        self.assertIn('rk_axil_error_slave error_page', code)
        self.assertIn('decode = T_UNMAPPED;', code)
        bench = BENCH.read_text()
        self.assertIn("host_write(32'h0001_b000, 32'hdeadbeef, 2'b10)", bench)
        self.assertIn("host_read(32'hffff_ffff, value, 2'b10)", bench)

    def test_memory_is_one_shared_port_with_one_owner(self) -> None:
        code = normalised(IMAGE)
        self.assertIn('rk_bram #(.BYTES(BRAM_BYTES), .BASE(BRAM_BASE)) memory', code)
        self.assertIn('next_owner = OWN_NONE;', code)
        self.assertIn('owner_q <= next_owner;', code)
        self.assertIn('bram_rsp_ready', code)
        self.assertIn('assign page_memory_ready[g] = reset_n && !any_engine_busy '
                      '&& !host_mem_busy;', code)
        self.assertIn('host_enable(reset_n && !any_engine_busy)', code)

    def test_bench_drives_only_the_axi_port_and_compares_the_whole_bo(self) -> None:
        bench = BENCH.read_text()
        for task in ('host_write(', 'host_read(', 'host_expect('):
            self.assertIn(task, bench)
        for forbidden in ('force ', 'release ', 'dut.g_pages', 'dut.memory.'):
            self.assertNotIn(forbidden, bench, forbidden)
        self.assertIn('localparam integer BO_BYTES = 4096;', bench)
        self.assertIn('for (index = 0; index < BO_BYTES; index = index + 1)', bench)
        # Load-bearing negative controls.
        self.assertIn('cmd_bytes[32] = cmd_bytes[32] ^ 8\'h40;', bench)
        self.assertIn('tampered command stream was accepted', bench)
        self.assertIn('A second page must refuse a submit while this one is active.',
                      bench)


class CorpusBuildProfileContractTests(unittest.TestCase):
    def test_profile_pins_top_part_clock_pages_and_sources(self) -> None:
        spec = json.loads(SPEC.read_text())
        self.assertEqual(spec['top'], 'ypcb_ppu_corpus_jtag_top')
        self.assertEqual(spec['part'], 'xc7k480tffg1156-2')
        self.assertEqual(float(spec['clock_period_ns']), 20.0)
        self.assertEqual(spec['constraints'], 'fpga/ypcb_ppu_corpus.xdc')
        self.assertEqual(spec['cdc'], 'fpga/host/mailbox_cdc.tcl')
        self.assertEqual(spec['pages'], PAGES)
        self.assertEqual(len(spec['sources']), len(set(spec['sources'])))
        for name in spec['sources'] + [spec['constraints'], spec['cdc']]:
            self.assertTrue((ROOT / name).is_file(), name)
        generated = spec['generated']
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0]['path'], 'rtl/ppu/rk_ppu_pool_corpus_case.sv')
        self.assertEqual(generated[0]['generator'],
                         'tools/ppu/gen_pool_corpus_tables.py')
        for bench in spec['benches'].values():
            self.assertTrue((ROOT / bench).is_file(), bench)

    def test_pin_free_wrapper_reuses_the_proven_mailbox(self) -> None:
        normalised_top = normalised(WRAPPER)
        self.assertIn('BSCANE2 #(.JTAG_CHAIN(2)) u_bscan', normalised_top)
        self.assertIn('otpu_jtag_mailbox u_mailbox', normalised_top)
        self.assertIn('rk_jtag_axil_bridge', normalised_top)
        self.assertIn('ypcb_ppu_corpus_top #(', normalised_top)
        # No top-level AXI port: the whole image sits behind the mailbox.
        text = code_only(WRAPPER)
        self.assertNotIn('output wire [31:0] s_axil_rdata', text)
        self.assertIn('input  wire SYS_CLK,', text)
        self.assertIn('output wire [2:0] led_3bits_tri_o', text)

    def test_constraints_use_only_the_audited_pins(self) -> None:
        text = XDC.read_text()
        pins = {line.split()[2] for line in text.splitlines()
                if 'PACKAGE_PIN' in line}
        self.assertEqual(pins, {'AA28', 'P30', 'M30', 'N30'})
        self.assertIn('create_clock -name sys_clk -period 20.000', text)
        for line in text.splitlines():
            if 'PACKAGE_PIN' in line:
                self.assertNotIn('s_axil', line)
                self.assertNotIn('tck', line.lower())

    def test_template_keeps_every_physical_gate(self) -> None:
        text = TEMPLATE.read_text()
        for token in ('RK_CONFIG_VOLTAGE', 'RK_CFGBVS', 'RK_EMIT_BITSTREAM',
                      'RK_CONFIRM_BOARD', 'RK_LED_ACTIVE_LOW',
                      'set emit_bitstream 0', '@N_PAGES@'):
            self.assertIn(token, text)
        self.assertIn('set emit_polarity 0', text)
        self.assertIn('rk_host_cdc_constrain', text)
        self.assertIn('rk_host_cdc_audit', text)
        # Page-presence gate before implementation, plus the unchanged timing
        # and DRC refusals.
        self.assertIn('Expected exactly @N_PAGES@ elaborated corpus pages', text)
        self.assertLess(text.index('page_cells'), text.index('place_design'))
        self.assertIn('Negative $delay_type slack', text)
        self.assertIn('Blocking DRC violation', text)
        self.assertIn('write_bitstream -force', text)

    def test_builder_hashes_sources_and_never_touches_hardware(self) -> None:
        code = BUILDER.read_text()
        self.assertIn('source_hashes_before', code)
        self.assertIn('source_hashes_after', code)
        self.assertIn('source_changed_during_build', code)
        # The CLI declaration wraps across lines, so the parenthesised group in
        # the pattern must be escaped to match a literal '('.
        self.assertRegex(code, r"choices=\('render',\s*'synth',\s*'run',")
        self.assertIn("verify_generated", code)
        self.assertNotIn('open_hw', code)
        self.assertNotIn('program_hw', code)


class CorpusRunnerContractTests(unittest.TestCase):
    def test_runner_covers_every_corpus_case(self) -> None:
        code = RUNNER.read_text()
        self.assertIn('from tools.ppu import gen_pool_corpus_tables as corpus',
                      code)
        self.assertIn('cases = corpus.corpus_cases()', code)
        self.assertIn("'--simulator', choices=('iverilog', 'verilator', 'both')",
                      code)
        self.assertIn('source_hashes_before', code)
        self.assertIn('source_hashes_after', code)
        self.assertIn('hardware_accessed', code)
        self.assertIn('vivado_executed', code)
        self.assertIn('bitstream_emitted', code)

    def test_runner_uses_the_full_bo_and_declared_tolerance(self) -> None:
        code = RUNNER.read_text()
        self.assertIn('BO_BYTES = 4096', code)
        self.assertIn("'files': files", code)
        self.assertIn("tolerance_units = int(round(tolerance * (1 << 24)))", code)
        self.assertIn("+EXPECTED_HEX=", code)
        bench = BENCH.read_text()
        # Full-BO comparison and the exact FP16 fixed-point tolerance check.
        self.assertIn('for (index = 0; index < BO_BYTES; index = index + 1)', bench)
        self.assertIn('fp16_units', bench)
        self.assertIn('diff_units > tol_units', bench)

    def test_bench_replays_through_axi_only(self) -> None:
        bench = BENCH.read_text()
        for forbidden in ('force ', 'release ', 'dut.g_pages', 'dut.pool_page'):
            self.assertNotIn(forbidden, bench, forbidden)
        self.assertIn('`include "tests/axil_host.svh"', bench)


class CorpusDocumentationContractTests(unittest.TestCase):
    def test_image_doc_records_the_page_map_and_exclusions(self) -> None:
        doc = ROOT / 'docs/POOL_CORPUS_IMAGE.md'
        self.assertTrue(doc.is_file(), 'missing docs/POOL_CORPUS_IMAGE.md')
        text = doc.read_text()
        self.assertIn('0x0000_8000', text)
        self.assertIn('19', text)
        for case in ('fp16_max_k3s2_pad1_c8_h4w4',
                     'int8_max_k1s1_valid_c32_h1w1',
                     'int32_max_k2s2_zero_write_c4_h2w2',
                     'fp16_max_k16s16_c8_h16w16'):
            self.assertIn(case, text)


if __name__ == '__main__':
    unittest.main()
