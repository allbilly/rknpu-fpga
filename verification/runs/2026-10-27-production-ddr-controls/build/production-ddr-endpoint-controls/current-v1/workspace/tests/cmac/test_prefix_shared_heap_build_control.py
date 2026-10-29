"""Counter-safe HeAP build admission controls; no native execution implied."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools/cmac'), str(Path(__file__).parent)]
import build_heap_attempt_limit_candidate as build
import test_prefix_shared_heap_candidate_control as existing

ExistingCandidateControls = existing.HeapLimitCandidateControls


def completed():
    report = dict(status=build.BUILT, stage='complete', finished_utc='test-only', part='xc7k480tffg1156-2',
        full_parallel_products=512, qualified_parent_relinked_byte_identical=True, changed_objects_relative_to_qualified_HeAP_parent=1,
        actual_original_source=str(build.candidate.SOURCE), actual_original_object=str(build.candidate.OBJECT),
        default_actual_full_graph_attempt_limit=2147483646, source_change='ONE_EXPRESSION_WIDE_SQUARE_AND_COUNTER_SAFE_FINITE_SATURATION',
        limit_fixture_cases=[list(c) for c in build.CASES], production_source_before='test-only', production_source_after='test-only',
        commands=[dict(label=n, status='PASS_TOOL_EXECUTION_ONLY', returncode=0) for n in build.COMMANDS])
    report.update({flag: False for flag in build.FLAGS})
    return report


class CounterSafeHeapBuildControls(unittest.TestCase):
    def test_only_completed_one_object_own_host_fixture_build(self):
        report = completed()
        build.verify_metadata(report)
        for key, value in (('status', 'RUNNING'), ('stage', 'compile'), ('finished_utc', None), ('part', 'xc7a100t'),
                           ('full_parallel_products', 256), ('qualified_parent_relinked_byte_identical', False),
                           ('changed_objects_relative_to_qualified_HeAP_parent', 2), ('actual_original_source', '/wrong'),
                           ('actual_original_object', '/wrong.o'), ('default_actual_full_graph_attempt_limit', 0),
                           ('source_change', 'COUNTER_ONLY'), ('limit_fixture_cases', []), ('production_source_after', 'changed')):
            changed = deepcopy(report)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                build.verify_metadata(changed)

    def test_no_warning_waiver_native_or_physical_inheritance(self):
        for flag in build.FLAGS:
            report = completed()
            report[flag] = True
            with self.subTest(flag=flag), self.assertRaises(AssertionError):
                build.verify_metadata(report)

    def test_all_actual_commands_and_sanitized_cases_mandatory(self):
        for i in range(len(build.COMMANDS)):
            report = completed()
            report['commands'].pop(i)
            with self.subTest(missing=i), self.assertRaises(AssertionError):
                build.verify_metadata(report)
        for key, value in (('status', 'RUNNING'), ('returncode', 1), ('label', 'inherited_compile')):
            report = completed()
            report['commands'][-1][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                build.verify_metadata(report)


if __name__ == '__main__':
    unittest.main()
