"""Counter-safe HeAP qualification procedure guards, not native results."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools/cmac'), str(Path(__file__).parent)]
import qualify_counter_safe_heap as qualification
import test_native_heap_early_constraints_control as existing
from test_prefix_shared_heap_build_control import completed
from qualify_native_heap_clock_features import FAILED as SAVED_PARSER_CONTROL

ExistingNativeGuards = existing.Controls


class CounterSafeQualificationControls(unittest.TestCase):
    def test_incomplete_build_refused_before_old_admission_or_native_execution(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-counter-safe-admission-control-') as directory:
            root = Path(directory)
            report_path = root / 'build/openxc7/counter-safe-heap-engine-control/report.json'
            report_path.parent.mkdir(parents=True)
            with patch.object(qualification, 'ROOT', root), patch.object(qualification.first, 'admit') as old_admit:
                for key, value in (('status', 'RUNNING'), ('status', 'FAIL_COUNTER_SAFE_HEAP_BUILD'),
                                   ('stage', 'compile'), ('finished_utc', None),
                                   ('qualified_parent_relinked_byte_identical', False),
                                   ('changed_objects_relative_to_qualified_HeAP_parent', 2),
                                   ('native_requalification_executed', True)):
                    report = completed()
                    report[key] = value
                    report_path.write_text(json.dumps(report))
                    with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                        qualification.admit_build(report_path)
                    old_admit.assert_not_called()

    def test_saved_data_is_feature_parser_control_not_new_native_execution(self):
        original = json.loads(qualification.first.parent.first.NATIVE.read_text())
        result = qualification.compare_features(SAVED_PARSER_CONTROL.parent, original)
        self.assertEqual(len(result['DSP_feature_comparison']), 4)
        self.assertEqual(len(result['BRAM_feature_comparison']), 6)
        self.assertEqual(result['native_control_cell_counts']['DSP48E1_DSP48E1'], 4)
        self.assertEqual(result['native_control_cell_counts']['RAMB36E1_RAMB36E1'], 6)
        self.assertTrue(result['consumer_merge_contract']['conflicting_assignment_rejected'])

    def test_fresh_feature_checker_rejects_stage_membership_and_bram_corruption(self):
        original = json.loads(qualification.first.parent.first.NATIVE.read_text())
        saved = json.loads((SAVED_PARSER_CONTROL.parent / 'routed.json').read_text())
        with tempfile.TemporaryDirectory(prefix='rknpu-counter-safe-feature-control-') as directory:
            out = Path(directory)
            for name in ('control.fasm', 'placement.json'):
                shutil.copyfile(SAVED_PARSER_CONTROL.parent / name, out / name)
            for action in ('static', 'slow_clock', 'unrouted', 'missing_DSP'):
                value = deepcopy(saved)
                module = next(iter(value['modules'].values()))
                if action == 'static':
                    module['settings']['placer'] = 'static'
                elif action == 'slow_clock':
                    module['settings']['target_freq'] = '25000000'
                elif action == 'unrouted':
                    module['settings']['route'] = '0' * 32
                else:
                    dsp = next(n for n, c in module['cells'].items() if c['type'] == 'DSP48E1_DSP48E1')
                    del module['cells'][dsp]
                (out / 'routed.json').write_text(json.dumps(value))
                with self.subTest(action=action), self.assertRaises(AssertionError):
                    qualification.compare_features(out, original)
            (out / 'routed.json').write_text(json.dumps(saved))
            text = (out / 'control.fasm').read_text()
            line = next(line for line in text.splitlines() if '.RAMB18_Y0.INIT_00[255:0]' in line)
            self.assertTrue(line.endswith('0'))
            (out / 'control.fasm').write_text(text.replace(line, line[:-1] + '1', 1))
            with self.assertRaises(AssertionError):
                qualification.compare_features(out, original)

    def test_unowned_or_conflicting_clock_enable_not_an_idempotent_waiver(self):
        original = json.loads(qualification.first.parent.first.NATIVE.read_text())
        with tempfile.TemporaryDirectory(prefix='rknpu-counter-safe-clock-control-') as directory:
            out = Path(directory)
            for name in ('routed.json', 'placement.json'):
                shutil.copyfile(SAVED_PARSER_CONTROL.parent / name, out / name)
            text = (SAVED_PARSER_CONTROL.parent / 'control.fasm').read_text()
            clock = 'HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0'
            self.assertIn(clock, text)
            for suffix in (clock + ' = 0\n', 'HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK9\n', clock + '\n'):
                (out / 'control.fasm').write_text(text + suffix)
                with self.subTest(suffix=suffix), self.assertRaises(AssertionError):
                    qualification.compare_features(out, original)

    def test_procedure_reversible_except_explicit_build_and_decoder_binding(self):
        text = qualification.MAIN_SOURCE
        for old, new in reversed(qualification.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        self.assertEqual(text, qualification.typed.MAIN_SOURCE)
        for marker in ('expected=125', 'validate_placed', 'record_getter(q,r,out,run)', 'timeout=3600',
                       'check_heap_log', 'check_route_log'):
            self.assertIn(marker, qualification.MAIN_SOURCE)

    def test_all_original_positive_refinement_and_actual_negative_guards_remain(self):
        self.assertIs(qualification.NAMESPACE['check_heap_log'], qualification.early.check_heap_log)
        self.assertIs(qualification.NAMESPACE['check_symbol_census'], qualification.typed.check_symbol_census)
        self.assertEqual(qualification.COMMANDS, qualification.typed.COMMANDS)
        self.assertEqual(qualification.FLAGS, qualification.first.FLAGS)
        self.assertIn('parse_clock_bound_features', qualification.compare_features.__code__.co_names)


if __name__ == '__main__':
    unittest.main()
