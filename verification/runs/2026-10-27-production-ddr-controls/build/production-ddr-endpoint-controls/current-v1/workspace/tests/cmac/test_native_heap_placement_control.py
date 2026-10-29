"""HeAP admission/parser controls, not native/full FPGA acceptance."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import qualify_native_heap_placement as q

BASE=['engine','--device','xc7k480tffg1156-2','--freq','50','--seed','3588','--placer','static','--Werror']
PREFIX='Info: Xilinx HeAP effective beta: 0.500000 (architecture default)\nInfo: Creating initial analytic placement for 47 cells, random placement wirelen = 100.\n'
POSITIVE=PREFIX+'Info: HeAP Placer Time: 1.00s\nInfo: Running simulated annealing placer for refinement.\nInfo: Running post-placement legalisation...\nInfo: Program finished normally.\n'
NEGATIVE=PREFIX+"ERROR: post-placement validity check failed for Bel 'A6LUT' (cell 'illegal')\nERROR: Placing design failed.\n"


class Controls(unittest.TestCase):
    def test_only_placer_selection_changes(self):
        changed=q.heap_argv(BASE);self.assertEqual(changed[changed.index('--placer')+1],'heap')
        self.assertEqual(changed[:changed.index('--placer')]+changed[changed.index('--placer')+2:],BASE[:BASE.index('--placer')]+BASE[BASE.index('--placer')+2:])

    def test_clock_part_warnings_and_refinement_shortcuts_are_refused(self):
        for bad in (BASE+['--force'],BASE+['--parallel-refine'],BASE+['--no-pack'],BASE+['--timing-allow-fail'],
                    ['49' if v=='50' else v for v in BASE],['xc7k480tffg1156-1' if v=='xc7k480tffg1156-2' else v for v in BASE]):
            with self.assertRaises(AssertionError):q.heap_argv(bad)

    def test_normal_positive_refinement_and_native_negative_before_postplace(self):
        q.check_heap_log(0,POSITIVE);q.check_heap_log(125,NEGATIVE,True)
        for bad in (NEGATIVE+'Info: Running post-placement legalisation...\n',NEGATIVE+'Assertion failure\n',NEGATIVE+'ERROR: unknown device\n',NEGATIVE.replace('post-placement validity check failed','unrelated error')):
            with self.assertRaises(AssertionError):q.check_heap_log(125,bad,True)

    def test_missing_positive_steps_wrong_beta_or_warnings_refused(self):
        for bad in (POSITIVE.replace('0.500000','0.100000'),POSITIVE.replace('HeAP Placer Time:','Other placer time:'),
                    POSITIVE.replace('Running simulated annealing placer for refinement.','skipped'),POSITIVE+'WARNING: waived\n'):
            with self.assertRaises(AssertionError):q.check_heap_log(0,bad)
        self.assertIn('HeAP Placer Time:',q.ROUTE_SOURCE)
        self.assertIn('Routing complete.',q.ROUTE_SOURCE)


if __name__=='__main__':unittest.main()
