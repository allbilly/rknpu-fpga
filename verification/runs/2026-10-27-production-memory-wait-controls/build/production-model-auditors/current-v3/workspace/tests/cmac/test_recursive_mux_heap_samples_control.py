"""Bounded observed-state controls, never full native/FPGA acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools')]
import audit_recursive_mux_heap_samples as subject

FIRST = ROOT / 'build/recursive_mux_full_heap_state_actual_20261009.log'
SECOND = ROOT / 'build/recursive_mux_full_heap_state_second_actual_20261009.log'
PID = 1485021


class HeapSampleControls(unittest.TestCase):
    def state(self):
        return subject.parse_snapshot(FIRST.read_text(), PID)

    def text(self, state):
        return 'READ_ONLY_HEAP_STATE_JSON ' + json.dumps(state) + f'\n[Inferior 1 (process {PID}) detached]\n'

    def test_actual_samples_pin_detach_bounds_and_native_state(self):
        first = self.state(); second = subject.parse_snapshot(SECOND.read_text(), PID)
        self.assertEqual((first['remaining_queued_entries'], second['remaining_queued_entries']), (290432, 279179))
        self.assertEqual(first['children'], 0); self.assertEqual(second['children'], 0)
        self.assertEqual(first['root']['type'], 'SLICE_LUTX'); self.assertEqual(second['root']['type'], 'SLICE_LUTX')
        for text in (FIRST.read_text().replace(f'[Inferior 1 (process {PID}) detached]', ''),
                     FIRST.read_text() + FIRST.read_text(), FIRST.read_text() + '\nPython Exception error\n'):
            with self.assertRaises(AssertionError): subject.parse_snapshot(text, PID)
        with self.assertRaises(AssertionError): subject.parse_snapshot(FIRST.read_text(), PID + 1)

    def test_parser_still_rejects_optimized_out_gdb_frame_annotations(self):
        text = '#0 legalise_cell (this=<optimized out>)\n' + self.text(self.state())
        with self.assertRaises(AssertionError): subject.parse_snapshot(text, PID)

    def test_unknown_duplicate_malformed_or_unbounded_fields_rejected(self):
        value = self.state()
        for field, bad in (('native_pid', 1), ('children', 65), ('identifier_count', 16000001),
                           ('remaining_queued_entries', 600001), ('inferior_calls_or_writes', True),
                           ('members', [{}]), ('counters', {}), ('best_bel', dict(tile=-1, index=0))):
            changed = deepcopy(value); changed[field] = bad
            with self.subTest(field=field), self.assertRaises(AssertionError): subject.parse_snapshot(self.text(changed), PID)
        changed = deepcopy(value); changed['unknown'] = True
        with self.assertRaises(AssertionError): subject.parse_snapshot(self.text(changed), PID)
        text = self.text(value).replace('"children": 0', '"children": 0, "children": 0')
        with self.assertRaisesRegex(AssertionError, 'Duplicate snapshot'): subject.parse_snapshot(text, PID)
        for field, bad in (('radius', True), ('total_iters_noreset', -1), ('unknown', 0)):
            changed = deepcopy(value); changed['counters'][field] = bad
            with self.subTest(field=field), self.assertRaises(AssertionError): subject.parse_snapshot(self.text(changed), PID)

    def test_individual_relative_roles_never_silently_ignore_constraints(self):
        value = self.state(); rows = subject.relative_roles(value)
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['z'], 0)
        for field, bad in (('x', 1), ('y', 1), ('z', 1), ('absolute_z', True), ('cluster', 'unsupported-singleton')):
            changed = deepcopy(value); changed['root'][field] = bad
            with self.subTest(field=field), self.assertRaises(AssertionError): subject.relative_roles(changed)
        changed = deepcopy(value); child = dict(changed['root'], name='fixture-child')
        changed['root']['cluster'] = changed['root']['name']; child['cluster'] = changed['root']['name']
        changed['members'] = [child]
        with self.assertRaisesRegex(AssertionError, 'Aliased observed'): subject.relative_roles(changed)

    def test_queue_comparison_is_not_percentage_or_convergence_or_fit(self):
        states = [self.state(), subject.parse_snapshot(SECOND.read_text(), PID)]
        result = subject.compare_samples(states)
        self.assertEqual(result['arithmetic_queue_decline'], 11253); self.assertTrue(result['current_cell_changed'])
        for field in ('queue_is_complete_unplaced_cell_census', 'placed_percentage_established', 'convergence_or_completion_time_established'):
            self.assertFalse(result[field])
        increased = deepcopy(states); increased[1]['remaining_queued_entries'] = 300000
        self.assertLess(subject.compare_samples(increased)['arithmetic_queue_decline'], 0)
        # Queue growth is a valid observation, not an expectation edited away.
        with self.assertRaises(AssertionError): subject.compare_samples(states[:1])
        changed = deepcopy(states); changed[1]['native_pid'] += 1
        with self.assertRaises(AssertionError): subject.compare_samples(changed)

    def test_compiled_native_queue_source_semantics_bound(self):
        text = subject.HEAP_SOURCE.read_text(); result = subject.source_contract(text)
        self.assertTrue(result['observed_queue_is_not_independent_full_unplaced_cell_census'])
        for original in ('remaining.pop();', 'for (auto cell : p->solve_cells)', 'remaining.emplace('):
            with self.subTest(fragment=original), self.assertRaises(AssertionError):
                subject.source_contract(text.replace(original, 'unsupported native implementation'))

    def test_script_reads_only_bounded_values_and_detaches_on_error(self):
        text = subject.GDB_SCRIPT.read_text()
        self.assertIn('set may-call-functions off', text)
        self.assertIn('if not 0 <= count <= 64:', text)
        self.assertIn('if not 0 <= length <= 4096:', text)
        self.assertIn("gdb.execute('frame function nextpnr_himbaechel::HeAPPlacer::StrictLegaliser::legalise_cell', to_string=True)", text)
        self.assertIn("finally:\n    gdb.execute('detach')", text)
        self.assertNotIn('set variable', text); self.assertNotIn('gdb.parse_and_eval', text)
        self.assertNotIn('gdb.execute(\'call', text)
        source = Path(subject.__file__).read_text()
        self.assertNotIn('subprocess', source); self.assertNotIn('kill(', source)
        auditor = Path(__file__).parents[2] / 'tools/openxc7/audit_recursive_mux_heap_samples.py'
        self.assertIn('optimized out', auditor.read_text())


if __name__ == '__main__':
    unittest.main()
