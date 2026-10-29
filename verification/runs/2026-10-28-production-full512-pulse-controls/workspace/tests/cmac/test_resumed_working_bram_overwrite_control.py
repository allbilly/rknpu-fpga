"""Original seven controls plus direct full-source admission/schema controls."""
import inspect
from pathlib import Path
import sys
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'tools/openxc7'),str(Path(__file__).resolve().parent)]
from test_prefix_working_bram_overwrite_control import WorkingBramOverwriteControl
import resume_prefix_working_bram_overwrite as new


class ResumedWorkingBramControl(unittest.TestCase):
    def test_original_admission_reproduces_actual_key_error_and_fixed_actual_complete_admission_passes(self):
        with self.assertRaises(KeyError) as caught:new.previous.admitted_inputs({})
        self.assertEqual(caught.exception.args,('9',))
        bindings={};brams,signals,controls=new.admitted_inputs(bindings)
        self.assertEqual(set(brams),{'rk_mapped_cell_86684','rk_mapped_cell_86685'})
        self.assertEqual(len(signals['demo.memory.host_index']),12)
        self.assertEqual(len(signals['demo.memory.host_rdata']),16)
        self.assertIn('core_fire',controls)
        self.assertGreater(len(bindings),300)
        witness=new.observe_failure()
        self.assertFalse(witness['original_input_bindings_recorded'])
        self.assertFalse(witness['original_executed_source_snapshot_recorded'])

    def test_exact_one_key_type_change_new_directory_and_pre_admission_provenance_only(self):
        self.assertEqual(new.ADMISSION_SOURCE.replace(new.NEW_KEY,new.OLD_KEY),inspect.getsource(new.previous.admitted_inputs))
        old_main=new.MAIN_SOURCE.replace(new.NEW_SAVE,new.OLD_SAVE).replace('prefix-working-bram-overwrite-resume-','prefix-working-bram-overwrite-')
        self.assertEqual(old_main,inspect.getsource(new.previous.main))
        self.assertIs(new.NAMESPACE['validate_result'],new.previous.validate_result)
        self.assertIs(new.NAMESPACE['wrapper'],new.previous.wrapper)
        self.assertIs(new.NAMESPACE['render_bench'],new.previous.render_bench)
        self.assertLess(new.MAIN_SOURCE.index('observed_previous_source_after_failure.py'),new.MAIN_SOURCE.index('before={};brams,signals,controls=admitted_inputs(before)'))


if __name__=='__main__':unittest.main()
