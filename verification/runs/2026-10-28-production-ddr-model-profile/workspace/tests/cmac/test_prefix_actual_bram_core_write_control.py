"""Proof continuation controls; Python results do not establish native proof."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import resume_prefix_actual_bram_barrier_core_write as new


class Controls(unittest.TestCase):
    def test_frozen_failure_and_actual_completed_binary_parents_revalidated(self):
        before = {}
        cone, library = new.admit(before)
        self.assertIn(str(new.FAILED), before)
        self.assertEqual(len(cone['controller_registers']), 50)
        self.assertEqual(len(cone['cells']), 1328)
        self.assertTrue(library)

    def test_property_strengthens_actual_core_write_without_fold_or_ghost_changes(self):
        cone = json.loads((new.FAILED.parent / 'actual-BRAM-pin-controller-cone.json').read_text())
        old = new.previous.clock_model(cone)
        text = new.strengthened_model(cone)
        self.assertIn('wire core_request_write=t0_61792;', text)
        self.assertIn('physical_read_barrier&&physical_core_write_equivalence;', text)
        self.assertIn('((bram_core_enable&&bram_core_we)==(core_fire&&core_request_write))', text)
        self.assertEqual(text.count('reg [49:0] storage_state;'), 1)
        self.assertEqual(text.count(' ? 1\'b0 : next_clock['), old.count(' ? 1\'b0 : next_clock['))
        self.assertIn('else if(bram_host_enable&&bram_host_we)', text)
        self.assertNotIn('keep', text)
        self.assertNotIn('storage_state=', text)

    def test_native_flags_limits_and_original_actual_cell_graph_retained(self):
        script = new.previous.script(Path('/library.v'), Path('/model.v'), False, Path('/witness.json'))
        for flags in ('-seq 1 -tempinduct-def -maxsteps 4', '-set-def-inputs -set-init-def -verify -prove ok 1 -timeout 120'):
            self.assertIn(flags, script)
        self.assertIn('-show bram_core_we', script)
        for flags in ('-set-init-zero', '-set-assumes', '-prove-x', '-tempinduct-skip', '-ignore-unknown-cells'):
            self.assertNotIn(flags, script)

    def test_original_validator_rejects_frontend_as_negative(self):
        with self.assertRaises(AssertionError):
            new.previous.completed.previous.validate(new.FRONTEND_ERROR + '\n', 1, True)
        old = new.previous.completed.previous
        text = 'Base case for induction length 1 proven.\n' + old.SUCCESS + '\n'
        self.assertEqual(old.validate(text, 0, False), 1)
        with self.assertRaises(AssertionError):
            old.validate(text + 'Warning: waived\n', 0, False)


if __name__ == '__main__':
    unittest.main()
