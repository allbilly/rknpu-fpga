"""Operational archive guards; these are not numerical or FPGA tests."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import dsp_prefix_build_contract as contract


class BuildContractControl(unittest.TestCase):
    def test_actual_generated_hierarchy_changes_only_library_path(self):
        old = ROOT / 'build/rknpu-dsp-prefix-array-generated-top-replay/1791298219484149654/top'
        text = (old / 'Vtb_cmac_fp16_dsp_prefix_mapped_hier.mk').read_text()
        library = ROOT / 'build/rknpu-dsp-prefix-array-mapped-binary/1791283708506179317/cell/librk_cmac_fp16_cell_dsp_prefix_xc7_b.a'
        with tempfile.TemporaryDirectory() as temporary:
            obj = Path(temporary) / 'top'
            changed, result = contract.relative_hierarchy_library(text, obj, library)
            self.assertEqual(changed, 'VM_HIER_LIBS := ' + result['relative_library_path'] + '\n')
            self.assertFalse(result['rtl_or_generated_cpp_changed'])

    def test_extra_library_or_make_text_fails(self):
        library = ROOT / 'build/rknpu-dsp-prefix-array-mapped-binary/1791283708506179317/cell/librk_cmac_fp16_cell_dsp_prefix_xc7_b.a'
        for text in (f'VM_HIER_LIBS := {library} other.a\n', f'VM_HIER_LIBS := {library}\nOTHER := 1\n'):
            with self.assertRaises(AssertionError):
                contract.relative_hierarchy_library(text, ROOT / 'build/new/top', library)

    def test_actual_masked_zero_exit_archive_errors_fail(self):
        log = ROOT / 'build/rknpu-dsp-prefix-array-generated-top-replay/1791298219484149654/top_compile.log'
        with self.assertRaisesRegex(AssertionError, 'Archive/link tool diagnostic'):
            contract.require_clean_build(log.read_text())

    def test_prefixed_tools_and_make_failures_rejected(self):
        for diagnostic in ('/usr/bin/ar: broken', 'x86_64-linux-gnu-ar: broken',
                'ld.lld: error: broken', 'collect2: error: broken', 'ranlib: broken',
                'make: *** [target] Error 2', 'c++: fatal error: broken', 'undefined reference to x'):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(AssertionError):
                contract.require_clean_build(diagnostic + '\n')

    def test_clean_commands_and_archive_members(self):
        contract.require_clean_build('ar -rc top.a a.o\nc++ top.a lib.a -o sim\n')
        result = contract.validate_archive_members('kernel.o\nbridge.o\n',
            'top.o\nkernel.o\nbridge.o\n', ['top.o'])
        self.assertEqual(result['merged_object_count'], 3)

    def test_missing_duplicate_and_foreign_archive_member_fails(self):
        for text in ('top.o\n', 'top.o\nkernel.o\nkernel.o\n', 'top.o\nkernel.o\nforeign.o\n'):
            with self.assertRaises(AssertionError):
                contract.validate_archive_members('kernel.o\n', text, ['top.o'])


if __name__ == '__main__':
    unittest.main()
