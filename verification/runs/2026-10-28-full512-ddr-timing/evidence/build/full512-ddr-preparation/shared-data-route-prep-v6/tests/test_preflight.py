import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

RUNNER = Path(__file__).resolve().parents[1] / 'run.py'
spec = importlib.util.spec_from_file_location('route_runner', RUNNER)
route_runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route_runner)

class RoutePreflightTamperTests(unittest.TestCase):
    def make_inputs(self, root):
        paths = {
            'helper': root / 'helper.tcl',
            'facts': root / 'facts.tsv',
            'root-review': root / 'root-review.json',
            'vivado-binary': root / 'vivado',
        }
        for label, path in paths.items():
            path.write_bytes(('frozen-' + label).encode())
        expected = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in paths.values()}
        return paths, expected

    def test_unchanged_frozen_inputs_reach_launch_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, expected = self.make_inputs(Path(tmp))
            called = []
            result = route_runner.launch_after_preflight(expected, lambda: called.append('launched') or 'ok')
            self.assertEqual(result, 'ok')
            self.assertEqual(called, ['launched'])

    def test_mutated_helper_facts_review_and_tool_fail_before_launch(self):
        for label in ('helper', 'facts', 'root-review', 'vivado-binary'):
            with self.subTest(input=label), tempfile.TemporaryDirectory() as tmp:
                paths, expected = self.make_inputs(Path(tmp))
                paths[label].write_bytes(('mutated-' + label).encode())
                called = []
                with self.assertRaisesRegex(ValueError, 'frozen expected hashes'):
                    route_runner.launch_after_preflight(expected, lambda: called.append('launched'))
                self.assertEqual(called, [])

if __name__ == '__main__':
    unittest.main()
