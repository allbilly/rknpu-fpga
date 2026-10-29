"""Source/declaration candidate controls, not native qualification."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from empty_output_candidate import (FRONTEND, PROFILE, PRE_IMPORT, POST_IMPORT, frontend_source,
                                    checker_template, literal_outputs, OLD_CARRY, NEW_CARRY)
from probe_imported_empty_lut import actual_empty_lut, BASE, fixture, NAME
from route_strict_search_board import SMALL


class EmptyOutputCandidate(unittest.TestCase):
    def test_frontend_addition_is_only_opt_in_literal_metadata(self):
        old = FRONTEND.read_text(); new = frontend_source(old)
        self.assertEqual(new.replace(PRE_IMPORT, '').replace(POST_IMPORT, ''), old)
        self.assertIn('ci->addOutput(pin);', new)
        self.assertIn(PROFILE, PRE_IMPORT)
        self.assertIn('!bits.is_array()', PRE_IMPORT)
        self.assertIn('bits[0].number_value() != bits[0].int_value()', PRE_IMPORT)
        with self.assertRaises(AssertionError): frontend_source(old + '\n')

    def test_checker_keeps_v1_and_all_original_guards_with_null_DI_guard(self):
        r = json.loads(SMALL.read_text())
        old = (Path(r['executable']['path']).parent / 'check_imported_placement.inc').read_text()
        new = checker_template(old)
        self.assertIn('imported_profile != "fixed-lut-v1" && imported_profile != "fixed-lut-v2"', new)
        self.assertNotIn(OLD_CARRY, new); self.assertIn(NEW_CARRY, new)
        for guard in ('isBelLocationValid(ci->bel, true)', 'ctx->check();', 'cell_tags.swap(saved)',
                      'different nets on a shared physical pin', 'wrong paired output/A6 mode contract',
                      'unsupported paired logical LUT kind', 'wrong local carry DI role'):
            self.assertIn(guard, new)
        with self.assertRaises(AssertionError): checker_template(old.replace(OLD_CARRY, ''))

    def test_actual_full_declared_empty_output_and_original_fifty_cell_fixture(self):
        leaf = actual_empty_lut(); before = deepcopy(leaf)
        self.assertEqual(literal_outputs(leaf), ['O6']); self.assertEqual(leaf, before)
        design, _ = fixture(json.loads(BASE.read_text()), leaf)
        cells = next(iter(design['modules'].values()))['cells']
        self.assertEqual([n for n, c in cells.items() if c['type'] == 'SLICE_LUTX' and literal_outputs(c)], [NAME])

    def test_missing_unknown_constant_multibit_malformed_wrong_direction_are_not_empty(self):
        for bits in (['x'], ['0'], ['1'], [0], [1], [2.5], [True], [2, 3], None, {}, ''):
            with self.subTest(bits=bits):
                bad = deepcopy(actual_empty_lut()); bad['connections']['O6'] = bits
                with self.assertRaises(AssertionError): literal_outputs(bad)
        for kind in ('missing', 'direction', 'mapping', 'resource', 'double_output'):
            with self.subTest(kind=kind):
                bad = deepcopy(actual_empty_lut())
                if kind == 'missing': del bad['connections']['O6']
                elif kind == 'direction': bad['port_directions']['O6'] = 'input'
                elif kind == 'mapping': del bad['attributes']['X_ORIG_PORT_O6']
                elif kind == 'resource': bad['attributes']['X_LUT_AS_DRAM'] = '1'
                else:
                    bad['connections']['O5'] = []; bad['port_directions']['O5'] = 'output'; bad['attributes']['X_ORIG_PORT_O5'] = 'O'
                with self.assertRaises(AssertionError): literal_outputs(bad)

    def test_unannotated_disconnected_opposite_pin_is_not_a_logical_output(self):
        good = actual_empty_lut(); good['connections']['O5'] = []; good['port_directions']['O5'] = 'output'
        self.assertEqual(literal_outputs(good), ['O6'])
        good['connections']['O5'] = [192304]
        with self.assertRaises(AssertionError): literal_outputs(good)


if __name__ == '__main__': unittest.main()
