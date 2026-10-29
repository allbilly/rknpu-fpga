"""Retain all original controls and bind the native error source, not observed code alone."""
import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(Path(__file__).parent)]
import probe_source_defined_native_cluster_error as probe
from test_native_pack_cluster_probe_control import ClusterProbeControls


class SourceDefinedNativeErrorControls(unittest.TestCase):
    def test_reversible_own_archives_and_source_defined_failure_only(self):
        source = probe.MAIN_SOURCE
        for old, new in reversed(probe.REPLACEMENTS):
            self.assertEqual(source.count(new), 1)
            source = source.replace(new, old)
        self.assertEqual(source, inspect.getsource(probe.previous.main))
        self.assertIn('expected=1,', inspect.getsource(probe.previous.main))
        self.assertIs(probe.NAMESPACE['candidate_source'], probe.previous.candidate_source)
        self.assertIs(probe.NAMESPACE['read_metadata'], probe.previous.read_metadata)
        self.assertIn('0 warnings, 1 error', probe.MAIN_SOURCE)

    def test_actual_linked_source_objects_and_failed_record(self):
        certificate = probe.validate_error_contract()
        self.assertEqual(certificate['fatal_returncode'], 125)
        self.assertTrue(certificate['fatal_error_remains_rejection'])
        self.assertEqual(certificate['original_failure_preserved'], str(probe.FAILED))

    def test_other_exit_or_exception_or_missing_prefix_rejected(self):
        handler, logging = probe.HANDLER.read_text(), probe.LOG.read_text()
        for bad_handler, bad_log in (
            (handler.replace('return 125;', 'return 1;'), logging),
            (handler, logging.replace('throw log_execution_error_exception();', 'return;')),
            (handler, logging.replace('logv_prefixed("ERROR: ", format, ap, LogLevel::ERROR_MSG);', '/* removed */'))):
            with self.assertRaises(AssertionError):
                probe.error_source_contract(bad_handler, bad_log)


if __name__ == '__main__':
    unittest.main()
