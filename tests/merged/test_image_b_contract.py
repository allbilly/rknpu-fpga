"""Offline contract for Image B (pooling corpus + EW + ew-int) scaffolding.

Pins `fpga/ypcb_image_b_top.sv`, `fpga/image_b/image_b_sources.json` and
`fpga/image_b/build_image_b.tcl.in` against docs/MERGED_INTEGRATION_NOTES.md and
docs/EW_APERTURE_AUDIT.md, and exercises the shared renderer's Image-B profile
(load/validate/render/refusal) without invoking Vivado. No hardware.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.merged import vivado_merged_image as tool  # noqa: E402

TOP_B = ROOT / 'fpga/ypcb_image_b_top.sv'
SPEC_B = ROOT / 'fpga/image_b/image_b_sources.json'
TEMPLATE_B = ROOT / 'fpga/image_b/build_image_b.tcl.in'
NOTES = ROOT / 'docs/MERGED_INTEGRATION_NOTES.md'
AUDIT = ROOT / 'docs/EW_APERTURE_AUDIT.md'

# Image-B map: ranges are [start, end) and bit is the page-mask bit.
PAGES_B = {
    'memory': dict(target='T_MEMORY', start=0x0000_0000, bytes=65536, bit=0,
                   id=None, ref='rk_bram'),
    'pool_band_page': dict(target='T_RKPP_BAND', start=0x0001_0000, bytes=77824, bit=1,
                           id='524b5050', ref='rk_ppu_pool_band_axi'),
    'ew_page': dict(target='T_RKEW', start=0x0002_3000, bytes=4096, bit=2,
                    id='524b4557', ref='rk_ew_axi'),
    'ew_aperture_page': dict(target='T_EW_APERTURE', start=0x1000_0000, bytes=1048576,
                             bit=3, id='524b4557', ref='rk_ew_aperture'),
    'ew_int_page': dict(target='T_EWINT', start=0x0002_4000, bytes=4096, bit=4,
                        id='524b4549', ref='rk_ew_int_page_axi'),
    'ew_int_aperture_page': dict(target='T_EWINT_APERTURE', start=0x1100_0000,
                                 bytes=1048576, bit=5, id='524b4549',
                                 ref='rk_ew_int_aperture'),
}
PAGE_MASK_B = '0111111'
REQUIRED_MASK_B = '0111111'
REQUIRED_B = {'memory', 'pool_band_page', 'ew_int_page', 'ew_int_aperture_page'}
EW_BANKS = [
    (0x1000_1000, 0x1000_1FFF, 4096), (0x1002_0000, 0x1002_0FFF, 4096),
    (0x1004_0000, 0x1004_0FFF, 4096), (0x1006_0000, 0x1006_1FFF, 8192),
    (0x100E_0000, 0x100E_FFFF, 65536), (0x100F_0000, 0x100F_3FFF, 16384),
]


def vhex32(value: int) -> str:
    digits = f'{value:08x}'
    return "32'h" + digits[:4] + '_' + digits[4:]


class ImageBContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.top = TOP_B.read_text()
        cls.spec = json.loads(SPEC_B.read_text())
        cls.template = TEMPLATE_B.read_text()
        cls.cfg = tool.profile_cfg('image-b')

    # ---- profile / renderer integration ---------------------------------
    def test_renderer_loads_image_b_profile(self):
        spec = tool.load_spec(profile='image-b')
        self.assertEqual(spec['profile'], 'host-jtag-image-b')
        self.assertEqual(spec['stage'], 'S3-scaffold')
        self.assertEqual(spec['top'], 'ypcb_image_b_top')
        self.assertEqual(spec['verilog_define'], ['DESIGNWARE_NOEXIST'])
        self.assertEqual(spec['page_mask'], PAGE_MASK_B)
        self.assertEqual(spec['required_page_mask'], REQUIRED_MASK_B)
        # S3/S4 attached every page, so all six are required.
        self.assertEqual(spec['required_pages'],
                         ['memory', 'pool_band_page', 'ew_page',
                          'ew_aperture_page', 'ew_int_page',
                          'ew_int_aperture_page'])
        self.assertEqual(spec['sources'], self.spec['sources'])

    def test_profile_pages_match_the_plan(self):
        by_name = {page['name']: page for page in self.spec['pages']}
        self.assertEqual(sorted(by_name), sorted(PAGES_B))
        for name, meta in PAGES_B.items():
            with self.subTest(page=name):
                page = by_name[name]
                self.assertEqual(int(page['base'].replace('_', ''), 16), meta['start'])
                self.assertEqual(page['bytes'], meta['bytes'])
                self.assertEqual(page['target'], meta['target'])
                self.assertEqual(page['ref'], meta['ref'])
                self.assertEqual(page.get('id'), meta['id'])

    def test_renderer_renders_image_b_tcl_with_ref_name_gates(self):
        out = Path('/tmp/image-b-render-token-test')
        text = tool.render_text(self.spec, out, 'b' * 64, profile='image-b')
        self.assertNotRegex(text, r'@[A-Z_]+@')
        self.assertIn('list memory rk_bram', text)
        # S3 attached the real 19 x 4 KiB pooling band, so the page-presence gate
        # must now require the band wrapper rather than the placeholder stub.
        self.assertIn('list pool_band_page rk_ppu_pool_band_axi', text)
        # S4 attached the real EW control page and the six-bank aperture.
        self.assertIn('list ew_page rk_ew_axi', text)
        self.assertIn('list ew_aperture_page rk_ew_aperture', text)
        self.assertIn('set page_mask 0111111', text)
        # The integrated ew-int page/aperture are now required real modules.
        self.assertIn('list ew_int_page rk_ew_int_page_axi', text)
        self.assertIn('list ew_int_aperture_page rk_ew_int_aperture', text)
        self.assertIn('-generic PAGE_MASK=7\'b$page_mask', text)
        self.assertIn('set_property verilog_define {DESIGNWARE_NOEXIST} [current_fileset]', text)
        self.assertNotIn('DESIGNWARE_NOEXIST SYNTHESIS', text)
        for gate in ('RK_CONFIRM_BOARD', 'RK_CONFIG_VOLTAGE', 'RK_CFGBVS',
                     'RK_LED_ACTIVE_LOW', 'RK_EMIT_BITSTREAM', 'RK_MERGED_SOURCE_SHA',
                     'double($clock_period) == 20.0', 'frish output directory'[:0] or
                     'fresh output directory', 'REF_NAME ==', 'Expected exactly one',
                     'rk_host_cdc_audit', 'report_timing_summary', 'report_drc',
                     'check_timing', 'write_bitstream', 'ROUTED_FULLY',
                     'ERRORS_IN_ROUTES', 'Waivers are forbidden'):
            self.assertIn(gate, text, gate)
        for forbidden in tool.FORBIDDEN_TCL:
            self.assertNotIn(forbidden, text)

    # ---- profile refusals (fail closed) ---------------------------------
    def mutate(self, change):
        spec = json.loads(json.dumps(self.spec))
        change(spec)
        return spec

    def assert_refused(self, spec, fragment):
        with self.assertRaises(tool.ProfileError) as caught:
            tool.validate_spec(spec, ROOT, 'image-b')
        self.assertIn(fragment, str(caught.exception))

    def test_profile_refuses_changed_top_defines_mask_and_pages(self):
        self.assert_refused(self.mutate(lambda s: s.update(top='ypcb_merged_top')), 'top')
        self.assert_refused(self.mutate(lambda s: s.update(
            verilog_define=['DESIGNWARE_NOEXIST', 'SYNTHESIS'])), 'must define')
        self.assert_refused(self.mutate(lambda s: s.update(page_mask='1111111')),
                            'reserved')
        self.assert_refused(self.mutate(lambda s: s.update(
            page_mask='0111101')), 'not enabled by page_mask')
        self.assert_refused(self.mutate(lambda s: s.update(
            required_pages=['memory'], required_page_mask='0000001')), 'must require')

    def test_profile_refuses_changed_page_table(self):
        def change_base(spec):
            spec['pages'][1]['base'] = '0002_0000'
        self.assert_refused(self.mutate(change_base), 'base changed')

        def change_ref(spec):
            spec['pages'][1]['ref'] = 'rk_ppu_pool_axi'
        self.assert_refused(self.mutate(change_ref), 'REF_NAME expectation changed')

        def drop_ew_int(spec):
            spec['pages'] = [p for p in spec['pages'] if p['name'] != 'ew_int_page']
        self.assert_refused(self.mutate(drop_ew_int), 'page table changed')

    # ---- RTL -------------------------------------------------------------
    def test_rtl_decode_and_instances(self):
        for name, meta in PAGES_B.items():
            with self.subTest(page=name):
                self.assertIn(meta['target'], self.top)
                if meta['id'] is not None:
                    self.assertIn(vhex32(int(meta['id'], 16)), self.top)
        for instance in ('pool_band_page', 'ew_page', 'ew_aperture_page',
                         'ew_int_page', 'ew_int_aperture_page'):
            self.assertIn(' ' + instance + ' (', self.top, instance)
        # The ew-int page form is INTEGRATED: real RTL + contract wiring.
        for token in ('rk_ew_int_page_axi', 'rk_ew_int_aperture',
                      'ew_int_engine_req_valid', 'ew_int_engine_rsp_valid',
                      'ew_int_page_mem_ready', 'ew_int_page_busy',
                      'page_busy[3] = ew_int_page_busy',
                      '.page_busy(ew_int_page_busy)',
                      '.memory_ready(ew_int_page_mem_ready)'):
            self.assertIn(token, self.top, token)
        for source in ('rtl/rk_ew_int_page_axi.sv', 'rtl/rk_ew_int_aperture.sv',
                       'rtl/rk_job_control.sv', 'rtl/rk_ew_int_regs.sv',
                       'rtl/rk_ew_int_engine.sv', 'rtl/rk_int_alu.sv'):
            self.assertIn(source, self.spec['sources'], source)
        # ew-int pages must be explicit placeholders, not silently absent.
        self.assertIn('RKEI', self.spec['pages'][4]['status'] + self.top)
        self.assertIn('provisional', self.spec['pages'][4]['status'] + self.top)
        # The EW 1 MiB aperture and its six measured banks are preserved.
        self.assertIn('16\'h1000', self.top)
        for lo, hi, _ in EW_BANKS:
            self.assertIn(vhex32(lo), self.top)
            self.assertIn(vhex32(hi + 1), self.top)
        self.assertIn('16\'h1100', self.top)  # ew-int aperture decode

    def test_rtl_mask_defaults_and_pin_budget(self):
        self.assertRegex(self.top, r"parameter logic \[6:0\] PAGE_MASK = 7'b011_1111")
        self.assertRegex(self.top,
                         r"parameter logic \[6:0\] REQUIRED_PAGE_MASK = 7'b000_0011")
        self.assertIn('PAGE_MASK[6] != 1\'b0', self.top)
        self.assertIn('output wire [2:0] led_3bits_tri_o', self.top)
        for token in ('IBUF u_ibuf50', 'BUFG u_bufg50',
                      'BSCANE2 #(.JTAG_CHAIN(2)) u_bscan',
                      'otpu_jtag_mailbox u_mailbox'):
            self.assertIn(token, self.top, token)

    def test_rtl_does_not_contain_image_a_pages(self):
        for token in ('T_RKCV', 'T_RKCM', 'runner', 'merged_job_stub'):
            self.assertNotIn(token, self.top, token)

    # ---- docs / gates ----------------------------------------------------
    def test_docs_record_the_split_and_gates(self):
        notes = NOTES.read_text()
        for needle in ('Image B', 'pooling corpus band', 'EW 1 MiB aperture',
                       'ew-int', 'D2', 'cool window'):
            self.assertIn(needle, notes, needle)
        self.assertIn('PASS', AUDIT.read_text())
        for gate in ('D2 pooling form', 'cool window', 'replay plan',
                     'REF_NAME presence gate'):
            self.assertIn(gate, ' '.join(self.spec['build_gate']['gated_on']), gate)
        self.assertEqual(self.spec['ew_aperture']['audit'], 'docs/EW_APERTURE_AUDIT.md (PASS)')

    def test_ew_int_comment_only_refresh_and_receipt_policy(self):
        import hashlib
        ew = self.spec['decisions']['ew_int_image_b_form']
        current = hashlib.sha256(
            (ROOT / 'rtl/rk_ew_int_page_axi.sv').read_bytes()).hexdigest()
        # The profile must track the current integration file exactly.
        self.assertEqual(ew['delivered']['rtl/rk_ew_int_page_axi.sv'], current)
        refresh = ew['comment_only_refresh']
        self.assertEqual(refresh['state'], 'COMPLETED')
        self.assertEqual(refresh['sha256_current'], current)
        self.assertNotEqual(refresh['sha256_current'], refresh['sha256_previous'])
        self.assertIn('comment', refresh['change'])
        self.assertIn('LSB-anchored', refresh['change'])
        # Comment-only proof: the 13 changed lines reconstruct the previous hash.
        proof = refresh['comment_only_proof']
        proof_path = ROOT / proof['notes']
        self.assertTrue(proof_path.is_file(), proof['notes'])
        self.assertEqual(hashlib.sha256(proof_path.read_bytes()).hexdigest(),
                         proof['notes_sha256'])
        self.assertIn('13 changed comment lines', proof['method'])
        self.assertIn('fcc88d94', proof['method'])
        # Previous receipt is superseded but remains the logic evidence.
        previous = refresh['receipt']['previous_status']
        self.assertIn('SUPERSEDED', previous)
        self.assertIn('stale_for_current_file=true', previous)
        self.assertIn('logic_evidence_remains=true', previous)
        # Current-file receipt is the fresh both-sim replay.
        receipt = ew['page_replay_receipt']
        self.assertEqual(receipt['path'],
                         'build/ew-int-page/20261110T151749Z/report.json')
        self.assertEqual(receipt['report_sha256'],
                         '4170b0584fb0725e0d34057772cf10378b05fc45c499c79a5aba4e9932daddea')
        report = ROOT / receipt['path']
        self.assertTrue(report.is_file())
        self.assertEqual(hashlib.sha256(report.read_bytes()).hexdigest(),
                         receipt['report_sha256'])
        report_txt = ROOT / receipt['path'].replace('report.json', 'report.txt')
        self.assertTrue(report_txt.is_file())
        self.assertEqual(hashlib.sha256(report_txt.read_bytes()).hexdigest(),
                         receipt['report_txt_sha256'])
        self.assertFalse(receipt['stale_for_current_file'])
        self.assertIn('15/15 READY page-level BO', receipt['verdict'])
        self.assertIn('8/8 fail-closed negatives', receipt['verdict'])
        self.assertIn('both simulators', receipt['verdict'])
        self.assertIn('Not Vivado, timing closure, bitstream',
                      receipt['scope'])
        self.assertEqual(receipt['binds']['rtl/rk_ew_int_page_axi.sv'], current)
        self.assertEqual(refresh['receipt']['host_compliance'],
                         refresh['receipt']['host_compliance'])
        for needle in ('safe_run.sh', 'BENCH_MIN_BATTERY=30', 'global heavy lock',
                       'no build, no bitstream, no hardware'):
            self.assertIn(needle, refresh['receipt']['host_compliance'])
        self.assertIn('current-file evidence', refresh['receipt']['policy'])

    def test_lead_decisions_are_recorded(self):
        decisions = self.spec['decisions']
        ew_int = decisions['ew_int_image_b_form']
        self.assertEqual(ew_int['decision'], 'page')
        self.assertEqual(ew_int['control_page']['base'], '0002_4000')
        self.assertEqual(ew_int['control_page']['device_id'], '524b4549')
        self.assertEqual(ew_int['aperture']['base'], '1100_0000')
        self.assertIn('ewint', ew_int['owner'])
        self.assertIn('standalone mailbox-direct', ew_int['fallback'])
        self.assertTrue(ew_int['aperture']['keep_1mib_decode'])
        self.assertIn('cool window', ew_int['gate'])
        self.assertIn('CONFIRMED', ew_int['status'])
        self.assertIn('PASS', ew_int['aperture']['audit']['verdict'])
        self.assertEqual(ew_int['aperture']['physical_bytes'], 16384)
        self.assertEqual(ew_int['aperture']['bram36_tiles'], 4)
        self.assertEqual(len(ew_int['aperture']['banks']), 4)
        self.assertEqual([b['base'] for b in ew_int['aperture']['banks']],
                         ['1100_1000', '1100_2000', '1100_3000', '1100_4000'])
        self.assertEqual(ew_int['aperture']['banks'][3]['role'], 'raw command BO (bank C)')
        self.assertEqual(ew_int['aperture']['holes'],
                         ['1100_0000..1100_0fff', '1100_5000..110f_ffff'])
        self.assertEqual(ew_int['aperture']['audit']['cases'],
                         '15/15 READY frozen ew-int bundles (3 BLOCKED have no staging requirement)')
        self.assertEqual(ew_int['aperture']['audit']['required_bytes'], 12640)
        self.assertEqual(ew_int['command_bo']['start_address'], '1100_4000')
        self.assertEqual(ew_int['command_bo']['max_bytes'], 352)
        self.assertIn('one 16-bit serialized memory master', ew_int['command_bo']['reason'])
        abi = ew_int['page_abi']
        self.assertEqual(abi['register_layout']['00'], 'DEVICE_ID (R) 0x524b4549')
        self.assertIn('{18,31,44}', abi['register_layout']['14'])
        self.assertIn('sticky until fabric reset', abi['error_policy'])
        self.assertIn('44-entry', abi['raw_stream'])
        self.assertEqual(ew_int['control_page']['module'], 'rk_ew_int_page_axi')
        self.assertEqual(ew_int['aperture']['module'], 'rk_ew_int_aperture')
        # ABI correction: frozen STATUS is LSB-anchored (not [16]/[20:18]).
        bits = abi['status_bits']
        self.assertEqual(bits['can_submit'], 0)
        self.assertEqual(bits['active'], 1)
        self.assertEqual(bits['result_valid'], 2)
        self.assertEqual(bits['result_error'], 3)
        self.assertEqual(bits['memory_ready'], 4)
        self.assertEqual(bits['core_error'], 5)
        self.assertEqual(bits['core_busy'], 6)
        self.assertEqual(bits['fields_valid'], [8, 9, 10])
        self.assertIn('WRONG', ew_int['control_page']['status_layout_authoritative'])
        self.assertIn('LSB', ew_int['control_page']['status_layout_authoritative'])
        self.assertIn('15/15 PASS', ew_int['status'] + ' ' + json.dumps(ew_int))
        delivered = ew_int['delivered']
        for key in ('rtl/rk_ew_int_page_axi.sv', 'rtl/rk_ew_int_aperture.sv',
                    'tests/tb_ew_int_page.sv',
                    'tools/merged/run_ew_int_page_replay.py'):
            self.assertEqual(len(delivered[key]), 64, key)
        self.assertTrue(ew_int['wiring']['top'].startswith('ypcb_image_b_top'))
        self.assertIn('page-level both-simulator replay receipt',
                      ew_int['gate'])
        self.assertIn('page_busy', ew_int['wiring']['page_busy'])
        self.assertIn('memory_ready', ew_int['wiring']['memory_ready'])
        self.assertIn('standalone mailbox-direct', ew_int['fallback'])
        self.assertIn('cool window', ew_int['gate'])
        pending = self.spec['sources_pending_ew_int']
        self.assertIn('rk_ew_int_page_axi', pending['ref_flip']['ew_int_page'])
        self.assertIn('rk_ew_int_aperture', pending['ref_flip']['ew_int_aperture_page'])
        self.assertIn('rtl/rk_ew_int_aperture.sv', pending['files'])
        d2 = decisions['d2_pooling_form']
        self.assertEqual(d2['decision'], 'multi-page band (provisional)')
        self.assertIn('19 x 4 KiB', d2['shape'])
        self.assertIn('share', d2['confirm_with'])
        self.assertTrue(d2['intended'])
        # The scaffold RTL/comments must reflect the decisions.
        self.assertIn('page-form', self.top)
        self.assertIn('D2 provisional', self.top)
        self.assertIn('multi-page band', self.top)
        # The confirmed ew-int bank map/holes are pinned in RTL text too.
        self.assertIn('ew_int_bank', self.top)
        for literal in ('32\'h1100_1000', '32\'h1100_2000', '32\'h1100_3000',
                        '32\'h1100_4000'):
            self.assertIn(literal, self.top)
        self.assertIn('localparam int unsigned NPAGES = 5;', self.top)
        self.assertIn('page_awvalid[4]', self.top)


if __name__ == '__main__':
    unittest.main()
