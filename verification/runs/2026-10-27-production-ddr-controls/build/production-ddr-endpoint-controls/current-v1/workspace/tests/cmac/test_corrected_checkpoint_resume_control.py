"""Reader-specific metadata repair controls; preserve the original FAIL gate."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import resume_corrected_dsp_checkpoint as resume


class CorrectedCheckpointResumeControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = json.loads(resume.PARENT.read_text())
        cls.original = json.loads((resume.PARENT.parent / 'placed.json').read_text())
        cls.reload = json.loads((resume.PARENT.parent / 'reloaded.json').read_text())
        cls.q = json.loads(resume.first.NATIVE.read_text())
        cls.selected = json.loads(resume.first.SELECTED.read_text())
        cls.module = next(iter(cls.original['modules'].values()))
        cls.child = next(iter(cls.reload['modules'].values()))

    def test_original_actual_failure_still_rejects_without_new_comparison_view(self):
        with self.assertRaisesRegex(AssertionError, 'Changed pin direction'):
            resume.first.verify_checkpoint(self.original, self.reload, self.selected, self.q['control_origins'], self.q['native_version'])

    def test_actual_1108_empty_inputs_restore_no_execution_artifact_or_endpoint(self):
        snapshot = deepcopy(self.reload)
        view, record = resume.empty_input_view(self.module, self.child)
        self.assertEqual(record['restored_empty_inputs_by_type'],
                         {'DSP48E1_DSP48E1': 540, 'RAMB36E1_RAMB36E1': 372, 'SLICE_LUTX': 196})
        label = next(iter(self.reload['modules']))
        result = resume.first.verify_checkpoint(self.original, dict(self.reload, modules={label: view}),
                         self.selected, self.q['control_origins'], self.q['native_version'])
        self.assertTrue(result['exact_all_cell_bel_reload_identity'])
        self.assertEqual(self.reload, snapshot)

    def test_omitted_connected_input_stays_a_failure(self):
        bad = deepcopy(self.child)
        name, pin = next((n, p) for n, c in self.module['cells'].items() for p, bits in c['connections'].items()
                         if bits and c['port_directions'][p] == 'input')
        del bad['cells'][name]['connections'][pin], bad['cells'][name]['port_directions'][pin]
        with self.assertRaisesRegex(AssertionError, 'Missing connected'):
            resume.empty_input_view(self.module, bad)

    def test_present_direction_change_stays_a_failure(self):
        bad = deepcopy(self.child)
        name, pin = next((n, p) for n, c in bad['cells'].items() for p in c['port_directions'])
        bad['cells'][name]['port_directions'][pin] = 'inout'
        with self.assertRaisesRegex(AssertionError, 'direction changed'):
            resume.empty_input_view(self.module, bad)

    def test_extra_undeclared_pin_stays_a_failure(self):
        bad = deepcopy(self.child)
        cell = next(iter(bad['cells'].values()))
        cell['connections']['UNMODELED'], cell['port_directions']['UNMODELED'] = [], 'input'
        with self.assertRaisesRegex(AssertionError, 'Extra checkpoint pin'):
            resume.empty_input_view(self.module, bad)

    def test_even_empty_outputs_are_not_silently_normalized(self):
        original = deepcopy(self.module)
        name = next(n for n, c in original['cells'].items() if c['type'] == 'DSP48E1_DSP48E1')
        original['cells'][name]['connections']['EMPTY_OUTPUT'] = []
        original['cells'][name]['port_directions']['EMPTY_OUTPUT'] = 'output'
        with self.assertRaisesRegex(AssertionError, 'non-input'):
            resume.empty_input_view(original, self.child)

    def test_only_exact_completed_placement_stage_of_preserved_failure_is_admitted(self):
        resume.verify_parent_metadata(self.parent, self.q)
        for key, value in (('status', 'RUNNING'), ('stage', 'native_placement'), ('error', 'some other error'),
                           ('full_target_parallel_products', 32), ('timing_signoff', True)):
            bad = deepcopy(self.parent)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                resume.verify_parent_metadata(bad, self.q)
        bad = deepcopy(self.parent)
        bad['commands'][-2]['returncode'] = 1
        with self.assertRaises(AssertionError): resume.verify_parent_metadata(bad, self.q)


if __name__ == '__main__':
    unittest.main()
