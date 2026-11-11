"""Offline tests for tools/merged/vivado_merged_image.py (task-21).

Pure Python except for two subprocess checks (the CLI dry-run and the synth
fail-closed refusal), which never invoke Vivado. No hardware.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.merged import vivado_merged_image as tool  # noqa: E402


class MergedImageToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = tool.load_spec()

    def test_profile_loads_and_pins_the_scaffolding_state(self):
        spec = self.spec
        self.assertEqual(spec['profile'], 'host-jtag-image-a')
        self.assertEqual(spec['stage'], 'S1-scaffold')
        self.assertEqual(spec['required_pages'], ['memory', 'conv_runtime_page'])
        self.assertEqual(spec['page_mask'], '0000111')
        self.assertEqual(spec['required_page_mask'], '0000011')
        self.assertEqual([p['name'] for p in spec['pages']],
                         ['memory', 'conv_runtime_page', 'gemm_page'])

    def test_rendered_tcl_has_every_token_expanded_and_gated(self):
        out = Path('/tmp') / 'merged-render-token-test'
        source_sha = 'a' * 64
        text = tool.render_text(self.spec, out, source_sha)
        self.assertNotRegex(text, r'@[A-Z_]+@')
        for marker in tool.REQUIRED_GATES:
            self.assertIn(marker, text)
        for forbidden in tool.FORBIDDEN_TCL:
            self.assertNotIn(forbidden, text)
        self.assertIn('set page_mask 0000111', text)
        self.assertIn("-generic PAGE_MASK=7'b$page_mask", text)
        self.assertIn('{memory conv_runtime_page}', text)
        # REF_NAME-checked page gates are rendered for the required pages.
        self.assertIn('list memory rk_bram', text)
        self.assertIn('list conv_runtime_page rk_conv_runtime_page_axi', text)
        self.assertIn('set_property verilog_define {DESIGNWARE_NOEXIST SYNTHESIS}', text)
        self.assertIn(source_sha, text)
        self.assertIn(source_sha[:8], text)
        self.assertIn(str(out / 'implementation'), text)

    def test_source_manifest_and_tag(self):
        files = tool.source_hashes(self.spec)
        self.assertIn('fpga/ypcb_merged_top.sv', files)
        manifest = tool.manifest_sha(files)
        self.assertEqual(len(manifest), 64)
        self.assertEqual(manifest[:8], tool.manifest_sha(dict(reversed(list(files.items()))))[:8])

    # ---- fail-closed profile validation ----------------------------------
    def mutate(self, change):
        spec = json.loads(json.dumps(self.spec))
        change(spec)
        return spec

    def assert_refused(self, spec, fragment):
        with self.assertRaises(tool.ProfileError) as caught:
            tool.validate_spec(spec, ROOT)
        self.assertIn(fragment, str(caught.exception))

    def test_profile_refuses_changed_top_part_clock_or_memory(self):
        self.assert_refused(self.mutate(lambda s: s.update(top='other_top')), 'top')
        self.assert_refused(self.mutate(lambda s: s.update(part='xc7k325t')), 'part')
        self.assert_refused(self.mutate(lambda s: s.update(clock_period_ns=25.0)),
                            'clock_period_ns')
        self.assert_refused(self.mutate(lambda s: s.update(memory_bytes=32768)),
                            'memory_bytes')
        self.assert_refused(self.mutate(lambda s: s.update(constraints='fpga/other.xdc')),
                            'constraints')
        self.assert_refused(self.mutate(lambda s: s.update(cdc='fpga/other.tcl')), 'cdc')

    def test_profile_refuses_changed_page_table(self):
        def change_page(spec):
            spec['pages'][1]['base'] = '0001_2000'
        self.assert_refused(self.mutate(change_page), 'base changed')

        def change_id(spec):
            spec['pages'][1]['id'] = 'deadbeef'
        self.assert_refused(self.mutate(change_id), 'identity changed')

        def change_ref(spec):
            spec['pages'][1]['ref'] = 'rk_conv_runtime_axi'
        self.assert_refused(self.mutate(change_ref), 'REF_NAME expectation changed')

    def test_profile_refuses_changed_verilog_defines(self):
        def drop_synthesis(spec):
            spec['verilog_define'] = ['DESIGNWARE_NOEXIST']
        self.assert_refused(self.mutate(drop_synthesis), 'SYNTHESIS')

    def test_reserved_page_mask_bits_are_refused(self):
        # Image A has three page bits; bits [6:3] are reserved for future images.
        self.assert_refused(self.mutate(lambda s: s.update(page_mask='1000111')),
                            'reserved and must be zero')

    def test_profile_refuses_unsafe_or_missing_sources(self):
        self.assert_refused(self.mutate(lambda s: s['sources'].append('rtl/does-not-exist.sv')),
                            'Missing or unsafe merged input')
        self.assert_refused(self.mutate(lambda s: s['sources'].append(s['sources'][0])),
                            'a source twice')

    def test_page_mask_and_required_page_gates(self):
        self.assert_refused(self.mutate(lambda s: s.update(page_mask='000011')),
                            '7 binary digits')
        # A required page whose mask bit is clear must be refused.
        self.assert_refused(self.mutate(lambda s: s.update(page_mask='0000101')),
                            'not enabled by page_mask')
        # required_page_mask must encode exactly the required pages.
        self.assert_refused(self.mutate(lambda s: s.update(required_page_mask='0000001')),
                            'required_page_mask')
        # The S0 minimum must always be required.
        self.assert_refused(self.mutate(lambda s: s.update(
            required_pages=['memory'], required_page_mask='0000001')),
            'must require at least')

    def test_missing_renderer_inputs_are_refused(self):
        # Build a throwaway copy of the profile inputs, then remove one input and
        # prove the validator refuses it. The repository tree is never modified.
        import tempfile
        names = list(self.spec['sources']) + [
            tool.CONSTRAINTS, tool.CDC, tool.SPEC, tool.TEMPLATE] + list(tool.BUILD_INPUTS)
        with tempfile.TemporaryDirectory(prefix='merged-profile-root-') as tmp:
            root = Path(tmp)
            for name in names:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            # All copied inputs present -> the copied profile validates.
            tool.validate_spec(self.spec, root)
            (root / tool.TEMPLATE).unlink()
            with self.assertRaises(tool.ProfileError) as caught:
                tool.validate_spec(self.spec, root)
            self.assertIn('Missing or unsafe merged input', str(caught.exception))

    # ---- render/verify and fail-closed synth -----------------------------
    def test_cli_check_renders_and_verifies_without_vivado(self):
        stamp = f'_selftest-{id(self)}'
        out = ROOT / 'build/merged-image' / stamp
        if out.exists():
            shutil.rmtree(out)
        try:
            result = subprocess.run([sys.executable, 'tools/merged/vivado_merged_image.py',
                                     'check', '--out', str(out.relative_to(ROOT))],
                                    cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['status'], 'VERIFIED_RENDER_ONLY')
            self.assertEqual(report['source_tag'], report['source_manifest_sha256'][:8])
            self.assertFalse(report['vivado_executed'])
            self.assertFalse(report['bitstream_emitted'])
            record = json.loads((out / 'inputs.json').read_text())
            self.assertEqual(record['status'], 'RENDERED')
            self.assertEqual(record['page_list'], ['memory', 'conv_runtime_page'])
            # verify detects a package whose live inputs no longer match
            tampered = json.loads((out / 'inputs.json').read_text())
            tampered['source_hashes']['fpga/ypcb_merged_top.sv'] = '0' * 64
            (out / 'inputs.json').write_text(json.dumps(tampered))
            verify = subprocess.run([sys.executable, 'tools/merged/vivado_merged_image.py',
                                     'verify', '--out', str(out.relative_to(ROOT))],
                                    cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(verify.returncode, 1)
            self.assertIn('Live sources differ from the package manifest', verify.stderr)
        finally:
            if out.exists():
                shutil.rmtree(out)

    def test_synth_is_fail_closed_without_execute(self):
        out = ROOT / 'build/merged-image' / f'_synth-refusal-{id(self)}'
        result = subprocess.run([sys.executable, 'tools/merged/vivado_merged_image.py',
                                 'synth', '--out', str(out.relative_to(ROOT))],
                                cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 1)
        self.assertIn('fail-closed', result.stderr)
        self.assertFalse(out.exists())

    def test_output_must_be_fresh_and_below_build(self):
        with self.assertRaises(tool.ProfileError):
            tool.check_out_path(ROOT / 'build')  # the build root itself
        with self.assertRaises(tool.ProfileError):
            tool.check_out_path(ROOT / 'docs' / 'x')  # outside build
        existing = ROOT / 'build/merged-image' / f'_existing-{id(self)}'
        existing.mkdir(parents=True)
        try:
            with self.assertRaises(tool.ProfileError):
                tool.check_out_path(existing)
        finally:
            existing.rmdir()


if __name__ == '__main__':
    unittest.main()
