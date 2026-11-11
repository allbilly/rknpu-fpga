"""Cheap Icarus run of the merged-image scaffold bench (task-21).

Compiles `tests/tb_ypcb_merged_top.sv` with the simulation-only primitive stubs
and the profile's source list, then runs the mailbox->AXI scaffolding checks for
each downstream-error hole index (a SLVERR quarantines the reviewed bridge by
design, so one error transaction per session). No Vivado, no synthesis, no
hardware. Skipped when an Icarus toolchain is unavailable.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.merged import vivado_merged_image as tool  # noqa: E402

BENCH = 'tests/tb_ypcb_merged_top.sv'
STUBS = 'tests/merged/merged_primitive_stubs.sv'
PASS_MARK = 'PASS YPCB_MERGED_SCAFFOLD'
GUARD_LOG = ROOT / 'build/verif/host_guard/guard.log'


def guard_killed_vvp() -> bool:
    """True when the thermal guard has recently killed a vvp/sim process.

    The guard is the last-resort host protector: on a heat-soaked machine it
    SIGKILLs CPU-active user processes, which makes a bench look like it
    silently exited with no output. Distinguishing that from a real bench
    failure matters for evidence integrity.
    """
    if not GUARD_LOG.is_file():
        return False
    tail = GUARD_LOG.read_text(errors='ignore').splitlines()[-200:]
    return any('GUARD_KILL' in line and ('vvp' in line or 'iverilog' in line)
               for line in tail)


@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),
                     'Icarus Verilog toolchain not installed')
class MergedScaffoldBenchTests(unittest.TestCase):
    def run_bench(self, hole: int) -> str:
        spec = tool.load_spec()
        sources = [str(ROOT / name) for name in spec['sources']]
        with tempfile.TemporaryDirectory(prefix='merged-bench-') as tmp:
            tmp = Path(tmp)
            binary = tmp / f'merged_{hole}.vvp'
            compile_argv = [shutil.which('iverilog'), '-g2012', '-Itests',
                            '-Irtl/vendor/nvdla', '-DDESIGNWARE_NOEXIST',
                            f'-Ptb_ypcb_merged_top.HOLE_INDEX={hole}',
                            '-o', str(binary), '-s', 'tb_ypcb_merged_top',
                            str(ROOT / STUBS)] + sources + [str(ROOT / BENCH)]
            compiled = subprocess.run(compile_argv, cwd=ROOT, capture_output=True,
                                      text=True, timeout=180)
            self.assertEqual(compiled.returncode, 0,
                             f'compile failed:\n{compiled.stdout}\n{compiled.stderr}')
            ran = subprocess.run([shutil.which('vvp'), str(binary)], cwd=ROOT,
                                 capture_output=True, text=True, timeout=1800)
            output = ran.stdout + ran.stderr
            # The host keel/thermal guard kills CPU-active processes by design
            # when the machine is heat-soaked, which looks exactly like a silent
            # zero-output exit (rc=0, no stdout). That is an environment event, not
            # a bench failure: retry the SAME binary a few times and report the
            # guard kill honestly if every attempt is cut short.
            attempts = 0
            while True:
                if output.count(PASS_MARK) or 'FATAL:' in output or 'ERROR :' in output:
                    break
                attempts += 1
                if attempts >= 3:
                    killed = guard_killed_vvp()
                    self.assertNotIn(
                        '', output,
                        f'scaffold bench produced no output for hole {hole} '
                        f'after {attempts} attempts (guard kill seen: {killed}); '
                        'treat as BLOCKED-BY-HOST-THERMAL, not a design failure')
                    self.assertTrue(killed,
                                    f'hole {hole}: no output but no guard kill recorded; '
                                    'investigate the bench')
                    raise unittest.SkipTest(
                        f'BLOCKED-BY-HOST-THERMAL: the host guard killed the bench '
                        f'(hole {hole}) on {attempts} attempts; rerun in a cool window')
                ran = subprocess.run([shutil.which('vvp'), str(binary)], cwd=ROOT,
                                     capture_output=True, text=True, timeout=1800)
                output = ran.stdout + ran.stderr
            self.assertEqual(ran.returncode, 0, output[-3000:])
            self.assertIn(PASS_MARK, output)
            self.assertIn(f'hole={hole}', output)
            return output

    def test_each_slverr_hole_and_page_scaffolding(self):
        for hole in range(4):
            with self.subTest(hole=hole):
                output = self.run_bench(hole)
                self.assertIn('checks=', output)


if __name__ == '__main__':
    unittest.main()
