"""Unchanged diagnostic native scope, with exact reversible comment isolation."""
import inspect
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import resume_isolated_working_bram_views as new


class ResumedIsolationControl(unittest.TestCase):
    def test_all_views_exact_selected_type_and_unchanged_transactions_probes(self):
        original=new.previous.base.BENCH.read_text()
        for view in ('mapped','zero','one'):
            text=new.isolated_bench(view)
            self.assertEqual(text.count('actual_working_bram_'),1)
            self.assertIn('actual_working_bram_'+view+' mapped(',text)
            self.assertIn('DIAGNOSTIC_ONLY unselected_zero_view_not_instantiated',text)
            self.assertIn('DIAGNOSTIC_ONLY unselected_one_view_not_instantiated',text)
            self.assertEqual(text[text.index('    task automatic observe'):],original[original.index('    task automatic observe'):])
            self.assertNotIn('force ',text);self.assertNotIn('assign ',text)

    def test_exact_one_reversible_edit_change_preserves_old_failure(self):
        self.assertEqual(new.ISOLATION_SOURCE.replace(new.NEW,new.OLD),inspect.getsource(new.previous.isolated_bench))
        with self.assertRaises(AssertionError):new.previous.isolated_bench('mapped')

    def test_unsupported_view_stays_failure(self):
        for view in ('','mixed','baseline',None):
            with self.assertRaises(AssertionError):new.isolated_bench(view)

    def test_typed_example_changes_only_outer_unsigned_width(self):
        old=new.previous.UNTYPED.read_text();typed=new.previous.typed_bench()
        self.assertEqual(typed.replace(new.previous.TYPED_NEW,new.previous.TYPED_OLD),old)
        self.assertEqual(typed.count(new.previous.TYPED_NEW),1)

    def test_same_tool_limits_native_transactions_and_absent_acceptance(self):
        for literal in ('timeout_seconds=180',"for view in ('mapped','zero','one')",'working_BRAM_model_overwrite_fixture_acceptance=False',"'-g2012'","'-Ttyp'","'bitstream_emitted'"):
            if literal=="'bitstream_emitted'":self.assertIn('bitstream_emitted=False',new.MAIN_SOURCE)
            else:self.assertIn(literal,new.MAIN_SOURCE)
        self.assertIs(new.NAMESPACE['parameter'],new.previous.parameter)


if __name__=='__main__':unittest.main()
