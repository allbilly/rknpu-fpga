"""Diagnostic-control tests; these are not HDL, mapped-array or FPGA tests."""
from collections import Counter
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import dsp_prefix_compile_admission as admission


class CompileAdmissionControl(unittest.TestCase):
    def setUp(self):
        self.warning = '%Warning-UNUSEDPARAM: /exact/model.v:12:3: Parameter is not used: \'P\'\n'
        self.entries = admission.inventory.diagnostics(self.warning)
        self.admitted = Counter(admission.key(entry) for entry in self.entries)

    def test_exact_subset_and_clean_output(self):
        self.assertEqual(admission.validate_followup(self.warning, self.admitted), self.entries)
        self.assertEqual(admission.validate_followup('Compile complete\n', self.admitted), [])

    def test_unknown_source_site_message_and_kind_fail(self):
        for text in (self.warning.replace('/exact/', '/other/'), self.warning.replace(':12:', ':13:'),
                self.warning.replace("'P'", "'Q'"), self.warning.replace('UNUSEDPARAM', 'WIDTHTRUNC')):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                admission.validate_followup(text, self.admitted)

    def test_duplicate_and_unparsed_diagnostics_fail(self):
        for text in (self.warning * 2, '%Warning-unparsed\n', '%Error: failed\n', 'warning: ignored\n'):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                admission.validate_followup(text, self.admitted)

    def test_unobserved_alias_and_observed_pin_failure(self):
        with tempfile.TemporaryDirectory(prefix='prefix-admission-') as directory:
            path = Path(directory) / 'mapped.v'
            path.write_text('wire [3:0] alias;\n')
            entry = dict(kind='UNDRIVEN', source=str(path), line=1, column=1,
                message="Bits of signal are not driven: 'alias'[3:2]")
            module = dict(ports={'I': {'bits': [10]}}, cells={},
                netnames={'alias': {'bits': [10, 11, 12, 13]}})
            self.assertEqual(admission.unobserved_aliases([entry], module, path), 2)
            module['cells']['real'] = {'connections': {'I': [13]}}
            with self.assertRaisesRegex(AssertionError, 'real port or cell pin'):
                admission.unobserved_aliases([entry], module, path)

    def test_alias_span_bounds_and_duplicates_fail(self):
        with tempfile.TemporaryDirectory(prefix='prefix-admission-') as directory:
            path = Path(directory) / 'mapped.v'
            path.write_text('wire [3:0] alias;\n')
            module = dict(ports={}, cells={}, netnames={'alias': {'bits': [10, 11, 12, 13]}})
            for span in ('4:2', '1:3', '3,3', 'unknown'):
                entry = dict(source=str(path), line=1,
                    message=f"Bits of signal are not driven: 'alias'[{span}]")
                with self.subTest(span=span), self.assertRaises(AssertionError):
                    admission.unobserved_aliases([entry], module, path)


if __name__ == '__main__':
    unittest.main()
