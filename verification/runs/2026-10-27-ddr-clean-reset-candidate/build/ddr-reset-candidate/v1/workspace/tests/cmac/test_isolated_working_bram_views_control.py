"""Exact diagnostic-only instance isolation and unchanged probe corpus controls."""
import inspect
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import diagnose_isolated_working_bram_views as new


class IsolatedViewControl(unittest.TestCase):
    def test_views_keep_exact_selected_model_and_transactions(self):
        original=new.base.BENCH.read_text()
        for view in ('mapped','zero','one'):
            text=new.isolated_bench(view)
            self.assertEqual(text.count('actual_working_bram_'),1)
            self.assertIn('actual_working_bram_'+view+' mapped(',text)
            self.assertEqual(text[text.index('    task automatic observe'):],original[original.index('    task automatic observe'):])
            self.assertNotIn('force ',text)
            self.assertNotIn('assign ',text)
            self.assertIn('wait(glbl.GSR===1\'b0)',text)

    def test_unsupported_view_stays_failure(self):
        for view in ('','mixed','baseline',None):
            with self.assertRaises(AssertionError):new.isolated_bench(view)

    def test_minimal_typed_example_changes_only_outer_unsigned_width(self):
        text=new.typed_bench()
        self.assertEqual(text.replace(new.TYPED_NEW,new.TYPED_OLD),new.UNTYPED.read_text())
        self.assertEqual(text.count(new.TYPED_NEW),1)
        self.assertIn('module diagnostic_forwarded #(parameter INIT_00=256\'h0)',text)

    def test_bounded_main_reversible_no_old_gate_or_corpus_changes(self):
        original=new.MAIN_SOURCE.replace(new.NEW_EXECUTION,new.OLD_EXECUTION).replace(new.NEW_GENERATED,new.OLD_GENERATED).replace(new.NEW_BIND,new.OLD_BIND).replace('isolated-working-bram-views-diagnostic-','prefix-working-bram-cold-diagnostic-')
        self.assertEqual(original,inspect.getsource(new.base.main))
        self.assertIn('timeout_seconds=180',new.MAIN_SOURCE)
        self.assertIn('working_BRAM_model_overwrite_fixture_acceptance=False',new.MAIN_SOURCE)


if __name__=='__main__':unittest.main()
