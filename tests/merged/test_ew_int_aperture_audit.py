"""Contract tests for the Image-B ew-int sparse aperture (task-23).

Pins the aperture literals recorded in `docs/EW_INT_APERTURE_AUDIT.md`, the
Image-B profile decision block and the aperture RTL parameter defaults. Purely
offline: no simulator, no Vivado, no hardware.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.merged import ew_int_aperture_audit as audit  # noqa: E402

APERTURE_RTL = ROOT / 'rtl/rk_ew_int_aperture.sv'
TOP_B = ROOT / 'fpga/ypcb_image_b_top.sv'
SPEC_B = ROOT / 'fpga/image_b/image_b_sources.json'
AUDIT_DOC = ROOT / 'docs/EW_INT_APERTURE_AUDIT.md'
CAPTURES = ROOT / 'build/rk3588-example-captures/ew-int'

BANKS = {
    'A': (0x1100_1000, 4096),
    'B': (0x1100_2000, 4096),
    'D': (0x1100_3000, 4096),
    'command': (0x1100_4000, 4096),
}
HOLES = [(0x1100_0000, 0x1100_1000), (0x1100_5000, 0x1110_0000)]
UNION_SPAN = (0x1100_1000, 0x1100_4160)
PHYSICAL_BYTES = 16384
DENSE_BYTES = 1 << 20
BRAM36_TILE_BYTES = 4096   # 2048 x 16-bit words = 32 Kb = one RAMB36 tile
RKEI = '524b4549'
RKEI_DEC = 0x524b4549


def vhex(value: int) -> str:
    digits = f'{value:08x}'
    return "32'h" + digits[:4] + '_' + digits[4:]


class ApertureAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = audit.run()
        cls.ready = [case for case in cls.audit['cases']]

    def test_verdict_and_family_counts(self):
        self.assertEqual(self.audit['verdict'], 'PASS')
        self.assertEqual(self.audit['problems'], [])
        self.assertEqual(self.audit['families']['ready'], 15)
        self.assertEqual(self.audit['families']['blocked'], 3)
        self.assertEqual(len(self.ready), 15)
        for blocked in self.audit['blocked_cases']:
            self.assertEqual(blocked['status'], 'BLOCKED')
            self.assertEqual(blocked['oracle'], 'none')
            self.assertTrue(blocked['blocked_reason'])

    def test_bank_map_matches_the_pinned_literals(self):
        banks = {bank['name']: bank for bank in self.audit['banks']}
        self.assertEqual(sorted(banks), sorted(BANKS))
        for name, (address, size) in BANKS.items():
            self.assertEqual(banks[name]['address'], address, name)
            self.assertEqual(banks[name]['bytes'], size, name)
        self.assertEqual(self.audit['aperture']['base'], 0x1100_0000)
        self.assertEqual(self.audit['aperture']['decoded_bytes'], DENSE_BYTES)
        self.assertEqual(self.audit['aperture']['physical_bytes'], PHYSICAL_BYTES)
        self.assertEqual(self.audit['aperture']['physical_bram36_tiles'],
                         PHYSICAL_BYTES // BRAM36_TILE_BYTES)
        self.assertEqual(self.audit['aperture']['dense_bram36_tiles'],
                         DENSE_BYTES // BRAM36_TILE_BYTES)
        self.assertEqual(self.audit['aperture']['saved_bram36_tiles'],
                         (DENSE_BYTES - PHYSICAL_BYTES) // BRAM36_TILE_BYTES)

    def test_holes_and_union_span(self):
        holes = [(hole['start'], hole['end']) for hole in self.audit['holes']]
        self.assertEqual(holes, HOLES)
        self.assertEqual(tuple(self.audit['union_span']), UNION_SPAN)
        self.assertEqual(self.audit['union_span_bytes'],
                         UNION_SPAN[1] - UNION_SPAN[0])
        self.assertEqual(self.audit['max_region_count'], 4)
        self.assertEqual(self.audit['buffer_sizes'], [4096])
        self.assertEqual(self.audit['max_command_bytes'], 352)

    def test_every_ready_case_stages_four_regions(self):
        for case in self.ready:
            self.assertEqual(case['region_count'], 4, case['case'])
            names = [region['name'] for region in case['regions']]
            self.assertEqual(sorted(names), ['a', 'b', 'command', 'out'],
                             case['case'])
            for region in case['regions']:
                self.assertEqual(region['bank'],
                                 {'a': 'A', 'b': 'B', 'out': 'D',
                                  'command': 'command'}[region['name']])
                self.assertEqual(region['address'], BANKS[region['bank']][0])
            self.assertEqual(case['problems'], [], case['case'])
            self.assertGreaterEqual(case['required_span'][0], UNION_SPAN[0])
            self.assertLessEqual(case['required_span'][1], UNION_SPAN[1])

    def test_address_fields_are_patched_and_pc_tail_is_zero(self):
        for case in self.ready:
            names = [field['field'] for field in case['address_fields']
                     if field['field'] not in ('pc_next_address', 'pc_next_amount')]
            self.assertEqual(sorted(names), ['dpu_dst', 'rdma_src_a',
                                             'rdma_src_b'], case['case'])
            for field in case['address_fields']:
                if field['field'].startswith('pc_'):
                    self.assertFalse(field['patched'], case['case'])
                    self.assertEqual(field['value'], 0, case['case'])
                else:
                    self.assertTrue(field['patched'], case['case'])
                    self.assertIn(field['patch_buffer'],
                                  {'a', 'b', 'out'}, case['case'])
            self.assertEqual(len(case['patches']), 3, case['case'])
            self.assertEqual(sorted(patch['kind'] for patch in case['patches']),
                             ['value32', 'value32', 'value32'], case['case'])

    def test_layout_geometry_is_not_an_address(self):
        # The audit's register whitelist must cover the layout/regroup streams,
        # and the surface stride registers must stay geometry (0x10), never a
        # staged base address.
        from model.int_profile import decode_regcmd
        from model.int_profile import patch_value32
        layout_case = next(case for case in self.ready
                           if case['mode'] == 'layout')
        raw = (CAPTURES / f'cases/{layout_case["case"]}' / 'regcmd.bin').read_bytes()
        for (target, offset), address in (((0x1001, 0x4020), BANKS['D'][0]),
                                          ((0x2001, 0x5018), BANKS['A'][0]),
                                          ((0x2001, 0x5038), BANKS['B'][0])):
            raw = patch_value32(raw, target, offset, address)
        config = decode_regcmd(raw)[0]
        self.assertEqual(config.mode, 'layout')
        self.assertEqual(config.layout, 'surface')

    def test_audit_binds_the_frozen_capture_manifest(self):
        import hashlib
        manifest = CAPTURES / 'manifest.json'
        self.assertEqual(self.audit['capture_manifest_sha256'],
                         hashlib.sha256(manifest.read_bytes()).hexdigest())
        manifest_doc = json.loads(manifest.read_text())
        self.assertEqual(manifest_doc['counts'], {'READY': 15, 'BLOCKED': 3})

    def test_audit_doc_records_the_verdict(self):
        text = AUDIT_DOC.read_text()
        self.assertIn('PASS', text)
        self.assertIn('0x1100_1000', text)
        self.assertIn('0x1100_4000', text)
        self.assertIn('252 tiles', text)
        self.assertIn('12,640 B', text)
        for blocked in ('int32_div_c8_w2', 'fp16_four_input_sum_c8_w1',
                        'fp16_bs_bn_relu_prelu_c8_w1'):
            self.assertIn(blocked, text)


class ApertureRtlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rtl = APERTURE_RTL.read_text()

    def test_parameter_defaults_match_the_audit(self):
        text = self.rtl
        self.assertRegex(text, r'APERTURE_BASE\s*=\s*32\'h1100_0000')
        self.assertRegex(text, r'APERTURE_BYTES\s*=\s*32\'h0010_0000')
        for name, (address, _size) in BANKS.items():
            pattern = {'A': 'BANK_A_BASE', 'B': 'BANK_B_BASE',
                       'D': 'BANK_D_BASE', 'command': 'BANK_C_BASE'}[name]
            self.assertIn(f'{pattern} = {vhex(address)}', text)

    def test_module_uses_frozen_bridge_and_bram_primitives(self):
        self.assertIn('module rk_ew_int_aperture', self.rtl)
        self.assertIn('rk_axil_mem_bridge', self.rtl)
        self.assertIn('rk_bram', self.rtl)
        self.assertIn('memory_ready', self.rtl)
        self.assertIn('page_busy', self.rtl)
        self.assertIn('engine_req_valid', self.rtl)
        self.assertNotIn('rk_ew_int_page_axi', self.rtl)  # page is separate

    def test_image_b_top_still_decodes_the_placeholder(self):
        top = TOP_B.read_text()
        self.assertIn("16'h1100", top)
        self.assertIn('524b_4549', top)


class ImageBProfileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads(SPEC_B.read_text())

    def test_profile_records_the_confirmed_form(self):
        form = self.spec['decisions']['ew_int_image_b_form']
        self.assertEqual(form['decision'], 'page')
        self.assertTrue('CONFIRMED' in form['status'] or
                        'INTEGRATED' in form['status'], form['status'])
        control = form['control_page']
        self.assertEqual(control['device_id'], RKEI)
        self.assertEqual(control['module'], 'rk_ew_int_page_axi')
        self.assertEqual(control['abi_version'], '00010000')
        self.assertEqual(control['base'], '0002_4000')
        aperture = form['aperture']
        self.assertEqual(aperture['module'], 'rk_ew_int_aperture')
        self.assertEqual(aperture['base'], '1100_0000')
        self.assertEqual(aperture['bytes'], 1 << 20)
        self.assertEqual(aperture['physical_bytes'], PHYSICAL_BYTES)
        self.assertEqual(aperture['bram36_tiles'], 4)
        self.assertEqual(aperture['dense_tiles_avoided'], 252)
        recorded = {bank['name']: bank for bank in aperture['banks']}
        expected_banks = {'A': BANKS['A'], 'B': BANKS['B'], 'C': BANKS['command'],
                          'D': BANKS['D']}
        self.assertEqual(sorted(recorded), sorted(expected_banks))
        for name, (address, size) in expected_banks.items():
            digits = f'{address:08x}'
            self.assertEqual(recorded[name]['base'],
                             digits[:4] + '_' + digits[4:])
            self.assertEqual(recorded[name]['bytes'], size)
        self.assertEqual(aperture['holes'],
                         ['1100_0000..1100_0fff', '1100_5000..110f_ffff'])
        command = form['command_bo']
        self.assertEqual(command['location'], 'aperture bank C')
        self.assertEqual(command['start_address'], '1100_4000')
        self.assertEqual(command['max_bytes'], 352)
        status_bits = form['page_abi']['register_layout']['08']
        self.assertIn('rk_job_control', status_bits)
        pages = {page['name']: page for page in self.spec['pages']}
        self.assertEqual(pages['ew_int_page']['base'], '0002_4000')
        self.assertEqual(pages['ew_int_page']['bytes'], 4096)
        self.assertEqual(pages['ew_int_aperture_page']['base'], '1100_0000')
        self.assertEqual(pages['ew_int_aperture_page']['bytes'], 1 << 20)
        self.assertEqual(pages['ew_int_aperture_page']['target'],
                         'T_EWINT_APERTURE')
        self.assertEqual(pages['ew_int_page']['target'], 'T_EWINT')


if __name__ == '__main__':
    unittest.main()
