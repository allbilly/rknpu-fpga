"""Source and admission controls only; actual native/vendor execution is separate."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools')]
import build_mux_feedthrough_candidate as candidate


def completed():
    report = dict(status=candidate.BUILT, stage='complete', finished_utc='test-only',
        part='xc7k480tffg1156-2', clock_period_ns=20, seed=3588, full_parallel_products=512,
        changed_link_objects=1, actual_original_source=str(candidate.SOURCE), actual_original_object=str(candidate.OBJECT),
        source_change='RECURSE_ONLY_INTO_NEW_FEEDTHROUGH_MUX_BEFORE_CONSTRAINING',
        qualified_parent_relinked_byte_identical=True, production_source_before='test-only', production_source_after='test-only',
        four_state_vectors=16384, four_state_comparisons=32768,
        parent_probe=dict(corrected=False, cell_counts={'SLICE_LUTX': 6}),
        candidate_probe=dict(corrected=True, cell_counts={'SLICE_LUTX': 8}),
        commands=[dict(label=label, returncode=1 if label == 'wrong_output_negative' else 0,
                       status='PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY') for label in candidate.COMMANDS])
    report.update({flag: False for flag in candidate.FLAGS})
    return report


class MuxCandidateControls(unittest.TestCase):
    def test_whole_source_reversible_one_insertion_only(self):
        source = candidate.SOURCE.read_text()
        changed = candidate.candidate_source(source)
        candidate.verify_source_transition(source, changed)
        self.assertEqual(changed.replace(candidate.NEW, candidate.OLD), source)
        self.assertIn('legalise_muxf_tree(feed, mux_roots, seen_leaves);', changed)
        for corrupted in (changed + '\n', changed.replace('NPNR_ASSERT_FALSE', 'REMOVED_ASSERT', 1),
                          changed.replace('seen_leaves.count', 'true || seen_leaves.count', 1), source):
            with self.subTest(corrupted=corrupted[-30:]), self.assertRaises(AssertionError):
                candidate.verify_source_transition(source, corrupted)
        for original in (source.replace(candidate.OLD, ''), source + candidate.OLD, changed):
            with self.assertRaises(AssertionError): candidate.candidate_source(original)

    def test_tool_only_shared_root_fixture_and_unchanged_native_flags(self):
        module = candidate.primitive_fixture()['modules']['mux_probe']
        self.assertEqual(len(module['cells']), 11)
        self.assertEqual(module['cells']['root']['connections']['I0'], [20])
        self.assertEqual(module['cells']['output_pad0']['connections']['I'], [20])
        self.assertEqual(module['cells']['root']['connections']['I1'], [21])
        self.assertEqual(module['cells']['output_pad1']['connections']['I'], [21])
        argv = candidate.pack_argv('tool', 'input', 'xdc', 'output')
        self.assertIn('--pack-only', argv)
        self.assertIn('--Werror', argv)
        self.assertEqual(argv[argv.index('--device') + 1], 'xc7k480tffg1156-2')
        self.assertEqual(argv[argv.index('--seed') + 1], '3588')
        self.assertEqual(argv[argv.index('--freq') + 1], '50')
        self.assertNotIn('--force', argv)
        self.assertIn('create_clock -period 20.000', candidate.fixture_xdc())

    def test_incomplete_or_changed_target_not_accepted(self):
        candidate.verify_metadata(completed())
        for key, value in (('status', 'RUNNING'), ('stage', 'compile'), ('finished_utc', None),
                           ('part', 'xc7a100t'), ('clock_period_ns', 40), ('seed', 0),
                           ('full_parallel_products', 256), ('changed_link_objects', 2),
                           ('actual_original_source', '/changed'), ('actual_original_object', '/changed.o'),
                           ('source_change', 'REMOVE_GUARD'), ('qualified_parent_relinked_byte_identical', False),
                           ('production_source_after', 'changed'), ('four_state_vectors', 0),
                           ('four_state_comparisons', 16384)):
            report = completed(); report[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): candidate.verify_metadata(report)

    def test_no_acceptance_or_warning_electrical_timing_waivers(self):
        for flag in candidate.FLAGS:
            report = completed(); report[flag] = True
            with self.subTest(flag=flag), self.assertRaises(AssertionError): candidate.verify_metadata(report)

    def test_each_fresh_command_and_genuine_negative_required(self):
        for i in range(len(candidate.COMMANDS)):
            report = completed(); report['commands'].pop(i)
            with self.subTest(missing=i), self.assertRaises(AssertionError): candidate.verify_metadata(report)
        for i, step in enumerate(completed()['commands']):
            report = completed(); report['commands'][i]['returncode'] = 0 if step['returncode'] else 1
            with self.subTest(code=i), self.assertRaises(AssertionError): candidate.verify_metadata(report)
        report = completed(); report['candidate_probe']['cell_counts']['SLICE_LUTX'] = 6
        with self.assertRaises(AssertionError): candidate.verify_metadata(report)


if __name__ == '__main__':
    unittest.main()
