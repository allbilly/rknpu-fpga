"""Offline contract for the two-image split scaffolding (task-21 update).

Pins Image A (`fpga/ypcb_merged_top.sv`: runtime conv + GEMM + transport) and
Image B (`fpga/ypcb_image_b_top.sv`: pooling corpus + EW) against
`docs/MERGED_INTEGRATION_NOTES.md` / `docs/MERGED_IMAGE_PLAN.md` and against the
RTL text, plus the profile/template gate inventory. Pure Python; one optional
cheap Icarus elaboration check per top with simulation-only primitive stubs.
No Vivado, no synthesis, no hardware.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.merged import vivado_merged_image as tool  # noqa: E402

TOP_A = ROOT / 'fpga/ypcb_merged_top.sv'
TOP_B = ROOT / 'fpga/ypcb_image_b_top.sv'
STUB = ROOT / 'fpga/merged/merged_page_stub.sv'
SPEC = ROOT / 'fpga/merged/merged_sources.json'
TEMPLATE = ROOT / 'fpga/merged/build_merged.tcl.in'
PLAN = ROOT / 'docs/MERGED_IMAGE_PLAN.md'
NOTES = ROOT / 'docs/MERGED_INTEGRATION_NOTES.md'
AUDIT = ROOT / 'docs/EW_APERTURE_AUDIT.md'

# Image A map (docs/MERGED_INTEGRATION_NOTES.md §2). Ranges inclusive.
PAGES_A = {
    'memory': dict(target='T_MEMORY', start=0x0000_0000, end=0x0000_FFFF,
                   bytes=65536, bit=0, id=None, ref='rk_bram'),
    'conv_runtime_page': dict(target='T_RKCV', start=0x0001_0000, end=0x0001_0FFF,
                              bytes=4096, bit=1, id='524b4356',
                              ref='rk_conv_runtime_page_axi'),
    'gemm_page': dict(target='T_RKCM', start=0x0001_1000, end=0x0001_1FFF,
                      bytes=4096, bit=2, id='524b434d', ref='rk_cmac_gemm_axi'),
}
REQUIRED_S1 = {'memory', 'conv_runtime_page'}
PAGE_MASK_A = '0000111'
REQUIRED_MASK_A = '0000011'

# Image B plan (separate top): pooling corpus band + EW control page + EW
# aperture; the EW banks are the ones measured from the production captures.
BAND_BASE = 0x0001_0000
BAND_PAGES = 19
BAND_BYTES = BAND_PAGES * 4096
EW_PAGE_BASE = 0x0002_3000
APERTURE_BASE = 0x1000_0000
APERTURE_END = 0x100F_FFFF
EW_BANKS = [
    (0x1000_1000, 0x1000_1FFF, 4096),   # operand A
    (0x1002_0000, 0x1002_0FFF, 4096),   # operand B
    (0x1004_0000, 0x1004_0FFF, 4096),   # operand D (output)
    (0x1006_0000, 0x1006_1FFF, 8192),   # scratch
    (0x100E_0000, 0x100E_FFFF, 65536),  # command BO
    (0x100F_0000, 0x100F_3FFF, 16384),  # task BO
]

# Probes: address -> Image A target.
A_MAPPED = [
    (0x0000_0000, 'T_MEMORY'), (0x0000_FFFF, 'T_MEMORY'),
    (0x0001_0000, 'T_RKCV'), (0x0001_0FFF, 'T_RKCV'),
    (0x0001_1000, 'T_RKCM'), (0x0001_1FFF, 'T_RKCM'),
]
A_UNMAPPED = [
    0x0001_2000, 0x0002_0000, 0x000F_FFFF, 0x1000_1000, 0x1000_2000,
    0x2000_0000, 0xFFFF_FFFF,
]


def vhex32(value: int) -> str:
    digits = f'{value:08x}'
    return "32'h" + digits[:4] + '_' + digits[4:]


def decode_a(address: int, mask: int = 0b0000111) -> str:
    page = (address >> 16) & 0xFFFF
    if page == 0x0000:
        return 'T_MEMORY' if mask & 0b0000001 else 'T_UNMAPPED'
    if page == 0x0001:
        sub = (address >> 12) & 0xF
        if sub == 0:
            return 'T_RKCV' if mask & 0b0000010 else 'T_UNMAPPED'
        if sub == 1:
            return 'T_RKCM' if mask & 0b0000100 else 'T_UNMAPPED'
    return 'T_UNMAPPED'


@unittest.skipUnless(shutil.which('iverilog'), 'Icarus Verilog not installed')
def elaborates(top: str, extra_sources=()) -> tuple[bool, str]:
    primitives = '''
module BSCANE2 #(parameter integer JTAG_CHAIN = 1) (
    output wire TCK, output wire DRCK, output wire TDI, output wire TMS,
    output wire SEL, output wire CAPTURE, output wire SHIFT, output wire UPDATE,
    output wire RESET, output wire RUNTEST, input wire TDO
);
    assign TCK = 1'b0; assign DRCK = 1'b0; assign TDI = 1'b0; assign TMS = 1'b0;
    assign SEL = 1'b0; assign CAPTURE = 1'b0; assign SHIFT = 1'b0;
    assign UPDATE = 1'b0; assign RESET = 1'b0; assign RUNTEST = 1'b0;
endmodule
module IBUF (input wire I, output wire O); assign O = I; endmodule
module BUFG (input wire I, output wire O); assign O = I; endmodule
'''
    spec = tool.load_spec()
    unique = []
    seen = set()
    for item in [str(ROOT / name) for name in spec['sources']] + list(extra_sources):
        if item not in seen:
            seen.add(item)
            unique.append(item)
    sources = unique
    with tempfile.TemporaryDirectory(prefix='two_image_elab_') as tmp:
        tmp = Path(tmp)
        (tmp / 'primitives.sv').write_text(primitives)
        argv = [shutil.which('iverilog'), '-g2012', '-Itests',
                '-Irtl/vendor/nvdla', '-DDESIGNWARE_NOEXIST', '-t', 'null',
                '-s', top, '-o', str(tmp / 'ignored.out'),
                str(tmp / 'primitives.sv')] + sources
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=180)
        return result.returncode == 0, result.stdout + result.stderr


class ImageAMapContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.top = TOP_A.read_text()
        cls.stub = STUB.read_text()
        cls.spec = json.loads(SPEC.read_text())
        cls.template = TEMPLATE.read_text()
        cls.plan = PLAN.read_text()
        cls.notes = NOTES.read_text()

    # ---- docs ------------------------------------------------------------
    def test_plan_records_the_two_image_decision(self):
        for needle in ('two-image split', 'Image A', 'Image B'):
            self.assertIn(needle, self.plan)
        for needle in ('167,858', '150,000', 'runtime conv engine',
                       'pooling corpus', 'EW FP16/FDIV', 'two-image split'):
            self.assertIn(needle, self.notes)
        self.assertIn('PASS', AUDIT.read_text())

    # ---- Image A RTL ------------------------------------------------------
    def test_rtl_decode_and_page_ids(self):
        for name, meta in PAGES_A.items():
            with self.subTest(page=name):
                self.assertIn(meta['target'], self.top)
                if meta['id'] is not None:
                    self.assertIn(vhex32(int(meta['id'], 16)), self.top)
        # Decode is by high word + 4 KiB subpage: the start addresses appear in
        # the map comment, the routing literals are 16'h0001 / 4'h0 / 4'h1.
        for text in ('0x0001_0000', '0x0001_1000', "16'h0001", "4'h0", "4'h1"):
            self.assertIn(text, self.top, text)
        self.assertIn('T_UNMAPPED', self.top)
        # The EW aperture/pooling pages must NOT be in Image A.
        for bank_lo, _, _ in EW_BANKS:
            self.assertNotIn(vhex32(bank_lo), self.top)
        self.assertNotIn('T_RKPP_BAND', self.top)
        self.assertNotIn('T_EW_APERTURE', self.top)

    def test_rtl_mask_defaults_and_reserved_bits(self):
        self.assertRegex(self.top, r"parameter logic \[6:0\] PAGE_MASK = 7'b000_0111")
        self.assertRegex(self.top, r"parameter logic \[6:0\] REQUIRED_PAGE_MASK = 7'b000_0011")
        self.assertIn('PAGE_MASK[6:3] != 4\'b0000', self.top)
        self.assertIn('$fatal', self.top)

    def test_rtl_unmapped_path_is_explicit(self):
        self.assertIn('rk_axil_error_slave error_page', self.top)
        self.assertIn('T_UNMAPPED', self.top)

    def test_rtl_arbitration_stub_and_todos(self):
        self.assertIn('any_engine_busy', self.top)
        self.assertIn('host_memory_enable = reset_n && !any_engine_busy', self.top)
        self.assertIn('engine_memory_ready', self.top)
        self.assertIn('TODO(S1)', self.top)
        self.assertIn('TODO(S2)', self.top)

    def test_scaffolding_does_not_instantiate_production_pages(self):
        # S1/S2 attached the real conv and GEMM pages, so the guard now rejects
        # only the *production per-profile* pages that Image A must never
        # instantiate (the runtime engine is the Image-A engine by design).
        pattern = (r'^\s*(rk_conv_simple_axi|rk_conv_simple_core|'
                   r'rk_ppu_pool_axi|rk_jtag_ew_bram)\b')
        self.assertIsNone(re.search(pattern, self.top, re.MULTILINE))
        self.assertIn('rk_cmac_gemm_axi', self.top)
        # S1 landed: the runtime slot is the REAL page, not the ABI reference
        # model. The reference model file stays in the tree as documentation.
        self.assertIn('rk_conv_runtime_page_axi', self.top)
        self.assertNotIn('merged_job_stub #(', self.top)

    def test_pin_free_top_matches_adopted_pin_budget_and_cdc_names(self):
        xdc = (ROOT / 'fpga/jtag_dual.xdc').read_text()
        for pin in ('AA28', 'P30', 'M30', 'N30'):
            self.assertIn(pin, xdc)
        for token in ('IBUF u_ibuf50', 'BUFG u_bufg50',
                      'BSCANE2 #(.JTAG_CHAIN(2)) u_bscan',
                      'otpu_jtag_mailbox u_mailbox'):
            self.assertIn(token, self.top, token)

    # ---- decode model ----------------------------------------------------
    def test_decode_model_matches_image_a(self):
        for address, target in A_MAPPED:
            with self.subTest(address=f'0x{address:08x}'):
                self.assertEqual(decode_a(address), target)
        for address in A_UNMAPPED:
            with self.subTest(address=f'0x{address:08x}'):
                self.assertEqual(decode_a(address), 'T_UNMAPPED')
        for name, meta in PAGES_A.items():
            with self.subTest(disabled=name):
                mask = 0b0000111 & ~(1 << meta['bit'])
                self.assertEqual(decode_a(meta['start'], mask), 'T_UNMAPPED')

    # ---- profile / template ---------------------------------------------
    def test_profile_fields_are_pinned(self):
        spec = self.spec
        self.assertEqual(spec['profile'], 'host-jtag-image-a')
        self.assertEqual(spec['top'], 'ypcb_merged_top')
        self.assertEqual(spec['part'], 'xc7k480tffg1156-2')
        self.assertEqual(spec['clock_period_ns'], 20.0)
        self.assertEqual(spec['jtag_chain'], 2)
        self.assertEqual(spec['memory_bytes'], 65536)
        self.assertEqual(spec['memory_base'], '00000000')
        self.assertEqual(spec['constraints'], 'fpga/jtag_dual.xdc')
        self.assertEqual(spec['cdc'], 'fpga/host/mailbox_cdc.tcl')
        self.assertEqual(spec['verilog_define'], ['DESIGNWARE_NOEXIST', 'SYNTHESIS'])
        self.assertEqual(spec['page_mask'], PAGE_MASK_A)
        self.assertEqual(spec['required_page_mask'], REQUIRED_MASK_A)
        self.assertEqual(spec['required_pages'], ['memory', 'conv_runtime_page'])
        self.assertEqual(spec['stage'], 'S1-scaffold')

    def test_profile_pages_match_the_plan(self):
        by_name = {p['name']: p for p in self.spec['pages']}
        self.assertEqual(sorted(by_name), sorted(PAGES_A))
        for name, meta in PAGES_A.items():
            with self.subTest(page=name):
                page = by_name[name]
                self.assertEqual(int(page['base'].replace('_', ''), 16), meta['start'])
                self.assertEqual(page['bytes'], meta['bytes'])
                self.assertEqual(page['target'], meta['target'])
                self.assertEqual(page['ref'], meta['ref'])
                self.assertEqual(page.get('id'), meta['id'])

    def test_required_pages_match_the_s1_minimum(self):
        self.assertEqual(set(self.spec['required_pages']), REQUIRED_S1)
        mask = 0
        for name in self.spec['required_pages']:
            mask |= 1 << PAGES_A[name]['bit']
        self.assertEqual(f'{mask:07b}', self.spec['required_page_mask'])
        self.assertIn("7'b000_0011", self.top)

    def test_decision_and_attach_metadata_are_recorded(self):
        decision = self.spec['decision']
        self.assertEqual(decision['d1_measured_runtime_engine_luts'], 167858)
        self.assertEqual(decision['adopted'], 'two-image split')
        attach = self.spec['s1_attach']
        self.assertEqual(attach['page_wrapper'], 'rk_conv_runtime_page_axi')
        self.assertTrue(attach['real_page_attached'])
        self.assertEqual(attach['engine'], 'rk_conv_runtime_core')
        self.assertIn('parameterised', attach['gate'])
        self.assertIn('rst_n', attach['abi']['rearm'])
        self.assertIn('wrapper owns', attach['abi']['memory_owner'])
        self.assertEqual(len(attach['source_hashes']), 9)
        self.assertEqual(self.spec['sibling_images']['image_b']['top'],
                         'ypcb_image_b_top (scaffold)')

    def test_profile_sources_exist_and_stay_scaffolding(self):
        for name in self.spec['sources']:
            with self.subTest(source=name):
                self.assertTrue((ROOT / name).is_file(), name)
        self.assertIn('fpga/ypcb_merged_top.sv', self.spec['sources'])
        self.assertIn('fpga/merged/merged_page_stub.sv', self.spec['sources'])
        self.assertIn('fpga/merged/merged_job_stub.sv', self.spec['sources'])
        self.assertNotIn('fpga/ypcb_image_b_top.sv', self.spec['sources'])

    def test_template_tokens_and_unweakened_gates(self):
        tokens = set(re.findall(r'@([A-Z_]+)@', self.template))
        expected = {'ROOT', 'OUT', 'PART', 'TOP', 'CONSTRAINTS', 'CDC',
                    'INCLUDE_DIRS', 'READ_SOURCES', 'SOURCE_SHA', 'SOURCE_TAG',
                    'PAGE_LIST', 'PAGE_MASK', 'PAGE_GATES'}
        self.assertEqual(tokens, expected)
        for gate in ('RK_CONFIRM_BOARD', 'RK_CONFIG_VOLTAGE', 'RK_CFGBVS',
                     'RK_LED_ACTIVE_LOW', 'RK_EMIT_BITSTREAM',
                     'RK_MERGED_SOURCE_SHA', 'double($clock_period) == 20.0',
                     'fresh output directory', 'REF_NAME ==',
                     'Expected exactly one', 'rk_host_cdc_audit',
                     'report_timing_summary', 'report_drc', 'check_timing',
                     'write_bitstream', 'BITSTREAM.CONFIG.USR_ACCESS',
                     'ROUTED_FULLY', 'ERRORS_IN_ROUTES',
                     'Waivers are forbidden',
                     'set_property verilog_define {DESIGNWARE_NOEXIST SYNTHESIS}'):
            self.assertIn(gate, self.template, gate)
        for forbidden in ('open_hw', 'program_hw', 'write_cfgmem', 'reset_hw'):
            self.assertNotIn(forbidden, self.template, forbidden)

    def test_stub_is_documented_scaffolding(self):
        self.assertIn('SCAFFOLDING, not an engine', self.stub)
        self.assertIn('PAGE_ID', self.stub)

    def test_runtime_abi_reference_model_matches_the_attach_contract(self):
        job = (ROOT / 'fpga/merged/merged_job_stub.sv').read_text()
        for token in ('DEVICE_ID', 'ABI_VERSION', 'REG_STATUS', 'REG_COMMAND',
                      'REG_START_ADDRESS', 'REG_START_AMOUNT', 'REG_JOB_TAG',
                      'REG_RESULT_TAG', 'REG_RESULT_TASKS', 'REG_RESULT_CODE',
                      'CMD_SUBMIT', 'CMD_ACK', 'can_submit', 'memory_ready',
                      'result_valid', 'ALIGN_BYTES', 'WINDOW_BASE', 'WINDOW_BYTES',
                      'DONE_CYCLES'):
            self.assertIn(token, job, token)
        for code in ("8'd2", "8'd4", "8'd6"):
            self.assertIn(code, job, code)
        attach = self.spec['s1_attach']
        self.assertIn('abi_reference_model', attach)
        self.assertIn('merged_job_stub', attach['abi_reference_model'])
        # The plan named the wrapper `rk_conv_runtime_axi`; the module actually
        # built and contract-verified is `rk_conv_runtime_page_axi` (same page,
        # same ABI). The profile records the real name.
        self.assertEqual(attach['page_wrapper'], 'rk_conv_runtime_page_axi')
        self.assertIn('rk_conv_runtime_axi', attach['plan_name'])

    # ---- Image B scaffolding preserved ----------------------------------
    def test_image_b_top_preserves_pooling_and_ew(self):
        self.assertTrue(TOP_B.is_file())
        text = TOP_B.read_text()
        self.assertIn('module ypcb_image_b_top', text)
        for token in ('T_RKPP_BAND', 'T_RKEW', 'T_EW_APERTURE',
                      'T_EWINT', 'T_EWINT_APERTURE',
                      'pool_band_page', 'ew_page', 'ew_aperture_page',
                      'ew_int_page', 'ew_int_aperture_page'):
            self.assertIn(token, text)
        self.assertIn('output wire [2:0] led_3bits_tri_o', text)
        self.assertNotIn('T_RKCV', text)
        self.assertNotIn('T_RKCM', text)
        # Every measured EW bank boundary is preserved in Image B.
        for lo, hi, _ in EW_BANKS:
            self.assertIn(vhex32(lo), text)
            self.assertIn(vhex32(hi + 1), text)
        # Image B plan literals: map comment + decode high-word/subpage routing.
        for needle in ('0x0001_0000', '0x0002_3000', '0x1000_0000 .. 0x100f_ffff',
                       "16'h0001", "16'h0002", "16'h1000", "16'h100f", "4'h3",
                       '19 x 4 KiB'):
            self.assertIn(needle, text, needle)
        self.assertRegex(text, r"parameter logic \[6:0\] PAGE_MASK = 7'b011_1111")
        self.assertRegex(text, r"parameter logic \[6:0\] REQUIRED_PAGE_MASK = 7'b000_0011")

    @unittest.skipUnless(shutil.which('iverilog'), 'Icarus Verilog not installed')
    def test_both_tops_elaborate_with_primitive_stubs(self):
        ok, log = elaborates('ypcb_merged_top')
        self.assertTrue(ok, log[-2000:])
        b_spec = tool.load_spec(profile='image-b')
        b_sources = [str(ROOT / name) for name in b_spec['sources']]
        ok, log = elaborates('ypcb_image_b_top', extra_sources=b_sources)
        self.assertTrue(ok, log[-2000:])


if __name__ == '__main__':
    unittest.main()
