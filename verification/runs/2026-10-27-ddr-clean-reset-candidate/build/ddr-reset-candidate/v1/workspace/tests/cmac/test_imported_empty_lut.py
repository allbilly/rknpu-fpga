"""Diagnostic fixture controls, not a native positive or full input change."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from probe_imported_empty_lut import BASE, NAME, actual_empty_lut, fixture, check_rejection


class ImportedEmptyLUT(unittest.TestCase):
    def test_actual_full_empty_LUT_and_50_cell_fixture_keep_original_logical_cells(self):
        original = json.loads(BASE.read_text()); before = deepcopy(original)
        design, details = fixture(original, actual_empty_lut())
        self.assertEqual(original, before)
        module = next(iter(design['modules'].values()))
        self.assertEqual(len(module['cells']), 50)
        self.assertEqual(module['cells'][NAME]['connections']['O5'], [])
        self.assertEqual(details['original_cells_retained'], 49)
        self.assertFalse(details['original_logical_cells_changed'])
        self.assertFalse(details['fixture_used_as_full_execution_input'])

    def test_duplicate_test_cell_is_not_accepted(self):
        original = json.loads(BASE.read_text()); original['modules'][next(iter(original['modules']))]['cells'][NAME] = {}
        with self.assertRaises(AssertionError): fixture(original, actual_empty_lut())

    def test_only_exact_native_unsupported_rejection_is_expected(self):
        text = 'Info: RKNPU imported placement scan: begin before clock/general routing.\nERROR: RKNPU imported placement scan: changed logical output mapping.'
        check_rejection(125, text)
        for code, log in [(0, text), (-6, text), (125, text.replace('changed logical output mapping.', 'different error.')),
                          (125, text + '\nInfo: Routing complete.'), (125, text + '\nWARNING: ignored')]:
            with self.assertRaises(AssertionError): check_rejection(code, log)


if __name__ == '__main__': unittest.main()
