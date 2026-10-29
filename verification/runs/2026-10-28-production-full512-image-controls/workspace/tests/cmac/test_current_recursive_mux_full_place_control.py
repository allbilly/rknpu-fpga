"""Current full recursive-mux placement must consume the current pack/parents."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import place_current_recursive_mux_prefix_shared_board as current
from test_recursive_mux_full_place_control import RecursiveMuxFullPlaceControls


class CurrentRecursiveMuxFullPlaceControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packed = json.loads((ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791562129604551098/report.json').read_text())
        cls.log = ('Info: Checksum: 0x77f1fde0\n'
                   'Info: Creating initial analytic placement for 419259 cells, random placement wirelen = 238678682.\n'
                   'Info: Running main analytical placer, max placement attempts per cell = 2147483646.\n')

    def test_full_pack_is_a_required_runtime_input_and_parent_paths_are_explicit(self):
        self.assertEqual(current.CONTROL.name, 'test_current_recursive_mux_full_place_control.py')
        self.assertIn("parser.add_argument('--packed'", Path(current.__file__).read_text())
        self.assertIn("placement.NAMESPACE['admit_qualification'] = admit_current_qualification",
                      Path(current.__file__).read_text())
        self.assertIn('RECURSIVE_MUX_RESOURCE_CHARACTERIZATION_NOT_PLACED',
                      current.placement.packer.PACKED)
        self.assertEqual(current.placement.NATIVE_TIMEOUT, 43200)
        self.assertIn(2147483646, current.placement.full_log_checks.__code__.co_consts)
        self.assertNotIn('523410', current.placement.full_log_checks.__code__.co_consts)

    def test_current_log_counts_active_roots_and_requires_full_output_separately(self):
        # Partial log fixture, not a completed native placement. Only the
        # completion check is mocked; source/object/link and pack checks run.
        with patch.object(current.placement, 'check_heap_log') as completion:
            checked = current.full_log_checks(self.log, self.packed)
        completion.assert_called_once_with(0, self.log)
        self.assertEqual(checked['actual_full_packed_cells'], 523522)
        self.assertEqual(checked['actual_logged_analytic_active_roots'], 419259)
        self.assertFalse(checked['analytic_marker_used_as_full_census'])
        self.assertTrue(checked['complete_output_membership_required'])
        self.assertFalse(checked['physical_fit_verified'])
        self.assertEqual(checked['native_analytic_scope']['contract']['marker_expression'], 'place_cells.size()')
        # Keep the historical failure and its test target intact.
        with self.assertRaisesRegex(AssertionError, 'Changed complete full analytic cell census'):
            current.placement.full_log_checks(self.log, self.packed)

    def test_changed_checksum_population_marker_or_counter_still_fails(self):
        for changed in (self.log.replace('0x77f1fde0', '0x00000000'),
                        self.log.replace('419259', '0'), self.log.replace('419259', '523523'),
                        self.log.replace('2147483646', '10000'), self.log + self.log,
                        self.log.replace('cells,', 'roots,'), self.log + 'WARNING: invalid placement\n'):
            with self.subTest(log=changed), patch.object(current.placement, 'check_heap_log'), self.assertRaises(AssertionError):
                current.full_log_checks(changed, self.packed)
        changed = deepcopy(self.packed)
        changed['native_census']['cells'] -= 1
        with patch.object(current.placement, 'check_heap_log'), self.assertRaises(AssertionError):
            current.full_log_checks(self.log, changed)

    def test_uncompleted_native_run_cannot_pass_new_scope_checks(self):
        with patch.object(current.placement, 'check_heap_log', side_effect=AssertionError('Missing normal refinement')), \
             patch.object(current, 'analytic_source_contract') as scope:
            with self.assertRaisesRegex(AssertionError, 'Missing normal refinement'):
                current.full_log_checks(self.log, self.packed)
            scope.assert_not_called()

    def test_unsupported_compiled_scope_rejected_during_pack_admission(self):
        with patch.object(current, 'analytic_source_contract', side_effect=AssertionError('Changed active-root selection')):
            with self.assertRaisesRegex(AssertionError, 'Changed active-root selection'):
                current.validate_current_pack(self.packed)

    def test_actual_compiled_scope_source_and_object_must_still_match(self):
        scope = current.analytic_source_contract(self.packed)
        for name in (scope['compiled_source'], scope['compiled_object'], self.packed['encoder_qualification']):
            changed = deepcopy(self.packed)
            changed['source'][name] = '0' * 64
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'Changed analytic-scope input'):
                current.analytic_source_contract(changed)
        changed = deepcopy(self.packed)
        changed['artifacts'][changed['commands'][-1]['log']] = '0' * 64
        with patch.object(current.placement, 'check_heap_log'), self.assertRaisesRegex(AssertionError, 'Changed actual pack log'):
            current.full_log_checks(self.log, changed)

    def test_dispatcher_installs_scope_check_and_keeps_full_output_guards(self):
        arguments = ['current']
        for flag in ('--packed', '--qualification', '--counter-build-report', '--counter-qualification-report',
                     '--strict-build-report', '--strict-qualification-report', '--native-report',
                     '--identity-report', '--arithmetic-report'):
            arguments += [flag, '/test-only/report.json']
        original_guards = {name: current.placement.NAMESPACE[name] for name in
                           ('compare_placement', 'full_inventory', 'verify_corrected_packed',
                            'verify_clock_admission', 'verify_full_argv')}

        def admitted_dispatch():
            self.assertIs(current.placement.NAMESPACE['full_log_checks'], current.full_log_checks)
            self.assertIs(current.placement.NAMESPACE['validate_pack'], current.validate_current_pack)
            for name, guard in original_guards.items():
                self.assertIs(current.placement.NAMESPACE[name], guard)

        with patch.object(sys, 'argv', arguments), patch.object(current, 'report_path', side_effect=Path), \
             patch.object(current, 'packed_report_path', side_effect=Path), \
             patch.object(current, 'bind_current_parent_chain'), \
             patch.object(current.placement, 'CONTROL'), patch.object(current.placement, 'admit_qualification'), \
             patch.dict(current.placement.NAMESPACE), patch.object(current.placement, 'main', side_effect=admitted_dispatch) as run:
            current.main()
            run.assert_called_once_with()

    def test_pack_and_parent_reports_must_be_confined_current_reports(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-current-recursive-place-control-') as directory:
            root = Path(directory)
            good = root / 'build/openxc7/report.json'
            good.parent.mkdir(parents=True)
            good.write_text('{}')
            with patch.object(current, 'ROOT', root):
                self.assertEqual(current.report_path(good), good.resolve())
                packed = root / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-control/report.json'
                packed.parent.mkdir(parents=True)
                packed.write_text('{}')
                self.assertEqual(current.packed_report_path(packed), packed.resolve())
                wrong_pack = root / 'build/openxc7/full-prefix-shared-native-pack-control/report.json'
                wrong_pack.parent.mkdir(parents=True)
                wrong_pack.write_text('{}')
                with self.assertRaises(AssertionError):
                    current.packed_report_path(wrong_pack)
                outside = root / 'report.json'
                outside.write_text('{}')
                with self.assertRaises(AssertionError):
                    current.report_path(outside)


if __name__ == '__main__':
    unittest.main()
