from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT=Path('/home/fedora/rknpu-fpga')
V5=ROOT/'build/fpga-bringup/full512-ddr-trained-prep-v5/run_sram_test.py'
V6=Path(__file__).with_name('run_sram_test.py')
PROBE=(
    'import runpy,sys;'
    'runpy.run_path(sys.argv[1],run_name="private_import_check");'
    'import tools.host.native_link,tools.tinystories.native_trace,tools.ddr.dual_transport,tools.ddr.raw_test;'
    'print("PASS_PRIVATE_RUNTIME_IMPORTS")'
)

class RuntimeImportPathTests(unittest.TestCase):
    def run_probe(self,script,cwd):
        env=os.environ.copy();env.pop('PYTHONPATH',None)
        return subprocess.run([sys.executable,'-c',PROBE,str(script)],cwd=cwd,env=env,
                              text=True,capture_output=True,timeout=30)

    def test_v5_reproduces_prelease_import_failure_and_v6_adds_root_for_imports(self):
        with tempfile.TemporaryDirectory(prefix='trained-import-check-') as directory:
            cwd=Path(directory)
            old=self.run_probe(V5,cwd)
            self.assertNotEqual(old.returncode,0)
            self.assertIn("ModuleNotFoundError: No module named 'tools'",old.stderr)
            new=self.run_probe(V6,cwd)
            self.assertEqual(new.returncode,0,new.stderr)
            self.assertIn('PASS_PRIVATE_RUNTIME_IMPORTS',new.stdout)

if __name__=='__main__':unittest.main()
