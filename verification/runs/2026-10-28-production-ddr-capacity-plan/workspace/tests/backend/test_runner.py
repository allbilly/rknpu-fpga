"""Runner selection controls with fake compiler scripts; no RTL build or network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.backend import run
import test_runtime


class RunnerSelectionTests(unittest.TestCase):
    def probe_main_until_unit_tests(self, directory):
        root = Path(directory)
        selected = root / 'explicit-backend'; (selected / '.git').mkdir(parents=True)
        binary = root / 'ccache'
        binary.write_text(f'#!{sys.executable}\nimport os,sys\n'
                          'print("MOCK GCC via c++" if os.path.basename(sys.argv[0]) == "c++" else "MOCK ccache")\n')
        binary.chmod(0o755)
        launcher = root / 'c++'; launcher.symlink_to(binary)
        verilator = root / 'verilator'
        verilator.write_text(f'#!{sys.executable}\nprint("MOCK Verilator")\n'); verilator.chmod(0o755)
        original_run = subprocess.run
        captured = []
        def execute(argv, **kwargs):
            captured.append((argv, dict(kwargs['env'])))
            if argv[-1] == '--version':
                return original_run(argv, **kwargs)
            raise RuntimeError('INTENTIONAL CONTROL STOP: no unit corpus or RTL build launched')
        def git(argv, **kwargs):
            return run.PIN if argv[-2:] == ['rev-parse', 'HEAD'] else ''
        with patch.object(run, 'ROOT', root), patch.object(run, 'source_revision', return_value={'files':{},'sha256':'MOCK'}), \
             patch.object(run, 'fingerprint', return_value={'files':{},'sha256':'MOCK'}), \
             patch.object(run.shutil, 'which', side_effect=lambda name: str(verilator if name == 'verilator' else launcher)), \
             patch.object(run.subprocess, 'check_output', side_effect=git), \
             patch.object(run.subprocess, 'run', side_effect=execute), \
             patch.object(sys, 'argv', ['run.py', '--backend', str(selected)]), \
             patch.dict(os.environ, {'TINYGRAD_ROOT':'/wrong/canonical', 'RKNPU_TINYGRAD':'/wrong/legacy'}):
            self.assertEqual(run.main(), 1)
        report = json.loads(next((root / 'build/backend-rtl').glob('*/report.json')).read_text())
        self.assertIn('INTENTIONAL CONTROL STOP', report['reason'])
        self.assertEqual(report['status'], 'FAIL')  # This control must never resemble numerical qualification.
        return report, captured, launcher, binary, selected

    def test_real_main_probes_compiler_through_original_symlink_argv0(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-compiler-launcher-') as directory:
            report, captured, launcher, target, _ = self.probe_main_until_unit_tests(directory)
            self.assertEqual(report['cxx']['path'], str(launcher))
            self.assertEqual(report['cxx']['resolved_target'], str(target))
            self.assertEqual(report['cxx_version'], 'MOCK GCC via c++')
            self.assertEqual(captured[1][0], [str(launcher), '--version'])
            # The original bug would invoke this target and report ccache.
            direct = subprocess.check_output([str(target), '--version'], text=True).strip()
            self.assertEqual(direct, 'MOCK ccache')

    def test_nondefault_cli_backend_reaches_runtime_unit_environment(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-backend-selection-') as directory:
            report, captured, _, _, selected = self.probe_main_until_unit_tests(directory)
            self.assertEqual(report['backend_root'], str(selected))
            argv, env = captured[-1]
            self.assertEqual(argv[1:], ['-m','unittest','discover','-s','tests/backend','-p','test_runtime.py','-v'])
            self.assertEqual(env['TINYGRAD_ROOT'], str(selected))
            self.assertEqual(env['RKNPU_TINYGRAD'], str(selected))
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(test_runtime.selected_backend(), selected)
        with patch.dict(os.environ, {'TINYGRAD_ROOT':'/canonical','RKNPU_TINYGRAD':'/legacy'}, clear=True):
            self.assertEqual(run.argument_parser().parse_args([]).backend, Path('/canonical'))
            self.assertEqual(test_runtime.selected_backend(), Path('/canonical'))
        with patch.dict(os.environ, {'RKNPU_TINYGRAD':'/legacy'}, clear=True):
            self.assertEqual(run.argument_parser().parse_args([]).backend, Path('/legacy'))
            self.assertEqual(test_runtime.selected_backend(), Path('/legacy'))


if __name__ == '__main__': unittest.main()
