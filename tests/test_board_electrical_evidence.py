#!/usr/bin/env python3
"""Re-verify the donor configuration-bank evidence recorded in
docs/BOARD_ELECTRICAL_EVIDENCE.md.

These checks assert only what the donor tree says. They do not measure the
card, and they deliberately do not authorise unattended bitstream emission.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DONOR = Path.home() / 'openTPU'
DOC = ROOT / 'docs/BOARD_ELECTRICAL_EVIDENCE.md'

# (path relative to the donor checkout, sha256, what it establishes)
EVIDENCE = (
    ('boards/ypcb-00338/constraints/otpu_top_ld.xdc',
     'b70db3b943d074776dc053f6c622316b84dddf98206f83181f4cfd4961880a13',
     'primary build constraints, CFGBVS GND / CONFIG_VOLTAGE 1.8'),
    ('boards/ypcb-00338/ramtest/ramtest.xdc',
     'ae1c4b0084363bca4633664fa61c025e25737343ae1797df2c00c07d5a5127ea',
     'independent second build with the same pair'),
    ('docs/board.md',
     '9e21448bca3389b669e99a143ceb425fd974147fc63ead871863e203a6da6870',
     'prose record: CFGBVS GND / 1.8 V'),
    ('docs/flash.md',
     'fee9e4af2fa8e60ab97ab51387c8927d3f92c729876752e339985ef43a6daae5',
     'prose record: banks at 1.8 V'),
    ('bitstreams/ch1-pcie-2gb/otpu.bit',
     'c7d3891b58d65ba72a3fc67c27c63c8dca3246db55d6504f7a63b636c876d1cf',
     'image built with that pair and booted from flash'),
    ('bitstreams/ch1-pcie-2gb/evidence/flash-programming-audit.json',
     'a9665b2415128904cd6563cb1d116ade1d1251fc6671a948f6fb8e2b05fe5a01',
     'audit of the flash program/verify/boot'),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BoardElectricalEvidenceTests(unittest.TestCase):
    def test_document_records_the_pair_and_the_gaps(self) -> None:
        text = DOC.read_text()
        self.assertIn('CFGBVS', text)
        self.assertIn('GND', text)
        self.assertIn('CONFIG_VOLTAGE', text)
        self.assertIn('1.8', text)
        # The doc must not overclaim: these gaps are the reason the gate stays.
        for token in ('cold_boot_verified', 'physical_pcie_verified',
                      'No physical strap measurement exists'):
            self.assertIn(token, text)
        self.assertIn('RK_CONFIG_VOLTAGE=1.8', text)
        self.assertIn('RK_CFGBVS=GND', text)

    def test_templates_still_refuse_unattended_bitstream_emission(self) -> None:
        # The electrical gate lives in the rendered Tcl and its Python
        # validator; both must keep requiring an explicit reviewed pair.
        for name in ('fpga/ppu/build_ppu.tcl.in', 'fpga/conv/build_conv.tcl.in'):
            text = (ROOT / name).read_text()
            self.assertIn('RK_CONFIG_VOLTAGE', text, name)
            self.assertIn('RK_CFGBVS', text, name)
            self.assertIn('RK_EMIT_BITSTREAM', text, name)
            # A missing pair is an error, not a silent default.
            self.assertIn('Supply both board-verified', text, name)
            # Emission stays opt-in and off by default.
            self.assertIn('set emit_bitstream 0', text, name)
        for name in ('tools/ppu/vivado_ppu.py', 'tools/conv/vivado_conv.py'):
            code = (ROOT / name).read_text()
            self.assertIn('CFGBVS-1', code, name)
            self.assertIn('bitstream_emitted', code, name)

    @unittest.skipUnless(DONOR.is_dir(), 'donor checkout ~/openTPU is not present')
    def test_donor_status_is_clean_for_the_cited_files(self) -> None:
        import subprocess
        cited = ['boards/ypcb-00338/constraints/otpu_top_ld.xdc',
                 'boards/ypcb-00338/ramtest/ramtest.xdc',
                 'docs/board.md', 'docs/flash.md']
        result = subprocess.run(['git', 'status', '--short', '--'] + cited,
                                cwd=DONOR, text=True, capture_output=True,
                                check=False, timeout=60)
        self.assertEqual(result.stdout.strip(), '',
                         f'donor files changed since the evidence was recorded: {result.stdout}')

    @unittest.skipUnless(DONOR.is_dir(), 'donor checkout ~/openTPU is not present')
    def test_donor_files_still_hash_to_the_recorded_values(self) -> None:
        for name, expected, why in EVIDENCE:
            path = DONOR / name
            self.assertTrue(path.is_file(), f'missing donor file: {name}')
            self.assertEqual(sha(path), expected,
                             f'{name} no longer matches the recorded hash ({why})')

    @unittest.skipUnless(DONOR.is_dir(), 'donor checkout ~/openTPU is not present')
    def test_donor_constraints_really_contain_the_pair(self) -> None:
        for name in ('boards/ypcb-00338/constraints/otpu_top_ld.xdc',
                     'boards/ypcb-00338/ramtest/ramtest.xdc'):
            text = (DONOR / name).read_text()
            self.assertRegex(text, r'set_property CFGBVS GND \[current_design\]', name)
            self.assertRegex(text, r'set_property CONFIG_VOLTAGE 1\.8 \[current_design\]', name)

    @unittest.skipUnless(DONOR.is_dir(), 'donor checkout ~/openTPU is not present')
    def test_donor_audit_confirms_the_boot_but_not_the_gaps(self) -> None:
        audit = json.loads((DONOR / 'bitstreams/ch1-pcie-2gb/evidence/'
                            'flash-programming-audit.json').read_text())
        self.assertTrue(audit['flash_written'])
        self.assertTrue(audit['flash_verified'])
        self.assertTrue(audit['jtag_boot_from_flash_verified'])
        # These must stay false; if a future donor run verifies them, this
        # record needs updating rather than silently becoming stronger.
        self.assertFalse(audit['cold_boot_verified'])
        self.assertFalse(audit['physical_pcie_verified'])

    @unittest.skipUnless(DONOR.is_dir(), 'donor checkout ~/openTPU is not present')
    def test_donor_bitstream_header_names_the_same_part(self) -> None:
        header = (DONOR / 'bitstreams/ch1-pcie-2gb/otpu.bit').read_bytes()[:400]
        text = header.decode('latin-1')
        self.assertIn('7k480tffg1156', text)
        self.assertIn('otpu_fpga_top_ld', text)
        self.assertIn('COMPRESS=TRUE', text)


if __name__ == '__main__':
    unittest.main()
