"""Fresh typed-link diagnostic controls; no native or placement acceptance."""
from copy import deepcopy
import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
from test_recursive_mux_analytic_scope_control import AnalyticScopeControls
import audit_typed_recursive_mux_analytic_scope as audit


class TypedScopeControls(unittest.TestCase):
    def test_only_typed_zero_code_link_metadata_is_admitted(self):
        for expected_returncode in (None, 0):
            step = dict(label='link_recursive_mux_feedthrough', status='PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY',
                        returncode=0)
            if expected_returncode is not None:
                step['expected_returncode'] = expected_returncode
            audit.verify_typed_link([step])
            for key, bad in (('label', 'wrong_output_negative'), ('status', 'RUNNING'), ('status', 'FAIL'),
                             ('status', 'PASS_TOOL_EXECUTION_ONLY'), ('returncode', 1), ('expected_returncode', 1)):
                changed = deepcopy(step); changed[key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(AssertionError): audit.verify_typed_link([changed])
        for links in ([], [step, step]):
            with self.subTest(links=links), self.assertRaises(AssertionError): audit.verify_typed_link(links)

    def test_reversible_link_metadata_only_change_preserves_source_worker_and_full_gates(self):
        restored = audit.MAIN_SOURCE
        for old, new in reversed(audit.REPLACEMENTS):
            self.assertEqual(restored.count(new), 1)
            restored = restored.replace(new, old)
        self.assertEqual(restored, inspect.getsource(audit.previous.main))
        for name in ('live_metadata', 'verify_worker', 'source_contract', 'log_observation', 'digest', 'source_revision'):
            self.assertIs(audit.NAMESPACE[name], getattr(audit.previous, name))
        for guard in ('placement.packer.validate_pack(packed)', 'compiles[0][\'returncode\'] == 0',
                      'verify_typed_link([verify_native_link_command(built[\'commands\'], obj, native[\'executable\'][\'path\'])])',
                      'verify_worker(command) == worker_start',
                      'assert source_revision() == production', 'full_cell_membership_verified=False',
                      'replacement_placement_acceptance_prepared=False'):
            self.assertIn(guard, audit.MAIN_SOURCE)
        self.assertIn("argv.count(str(Path(object_path).resolve())) == 1", inspect.getsource(audit.previous.verify_native_link_command))


if __name__ == '__main__':
    unittest.main()
