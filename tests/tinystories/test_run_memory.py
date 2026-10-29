"""Native qualification failures remain failures with Python assertions disabled."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RegisteredMemoryRunnerTests(unittest.TestCase):
    def test_optimized_runner_rejects_failed_tools_and_missing_completion(self):
        for returncode, expected in ((7, 'return code 7'),
                                     (0, 'Missing Icarus registered-memory completion')):
            with self.subTest(returncode=returncode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                runner = root / 'tools/tinystories/run_memory.py'
                runner.parent.mkdir(parents=True)
                runner.write_bytes((ROOT / 'tools/tinystories/run_memory.py').read_bytes())
                for name in ('rtl/tinystories/rk_shared_bram_regport.sv',
                             'tests/tinystories/tb_shared_bram_regport.sv'):
                    source = root / name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text('// Deliberately nonexecuting tool-control fixture.\n')
                bindir = root / 'bin'
                bindir.mkdir()
                for name in ('iverilog', 'vvp', 'verilator'):
                    tool = bindir / name
                    tool.write_text('#!/bin/sh\nprintf "mock native tool\\n"\n'
                                    f'exit {returncode}\n')
                    tool.chmod(0o755)
                result = subprocess.run([sys.executable, '-O', str(runner)],
                                        env=dict(os.environ, PATH=str(bindir)),
                                        capture_output=True, text=True, timeout=15)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads(next((root / 'build').rglob('report.json')).read_text())
                self.assertEqual(report['status'], 'FAIL')
                self.assertIn(expected, report['error'])
                self.assertNotIn('PASS_SHARED_REGISTERED_MEMORY_BOTH_SIMULATORS', result.stdout)


if __name__ == '__main__':
    unittest.main()
