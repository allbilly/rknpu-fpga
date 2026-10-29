"""nm result grammar versus real diagnostics; all native gates remain strict."""
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import qualify_native_heap_typed_inspection as new
from test_native_heap_placement_control import POSITIVE


class Controls(unittest.TestCase):
    def test_actual_prior_failure_is_preserved_and_symbol_table_is_typed(self):
        r=json.loads(new.FAILED.read_text());self.assertEqual(r['status'],'FAIL')
        c=r['commands'][-1];self.assertEqual(c['returncode'],0);self.assertEqual(c['status'],'FAIL')
        text=Path(c['log']).read_text();new.check_symbol_census(text)
        self.assertTrue(re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):',text))

    def test_real_nm_diagnostics_or_unknown_lines_or_wrong_getter_refused(self):
        r=json.loads(new.FAILED.read_text());text=Path(r['commands'][-1]['log']).read_text()
        for bad in (text+'nm: warning: wrong format\n',text+'ERROR: failed\n',text+'unknown data\n',
                    text+' \n',text[:-1],text.replace('configurePlacerHeap','changedGetter')):
            with self.assertRaises(AssertionError):new.check_symbol_census(bad)

    def test_native_warnings_early_rejection_and_positive_completion_stay_required(self):
        new.check_heap_log(125,new.previous.EARLY+'\n0 warnings, 1 error\n',True)
        new.check_heap_log(0,POSITIVE)
        for bad in (POSITIVE+'WARNING: waived\n',POSITIVE+'ERROR: failed\n',POSITIVE.replace('Program finished normally.','')):
            with self.assertRaises(AssertionError):new.check_heap_log(0,bad)

    def test_source_changes_only_typed_nm_guard_and_output_directory(self):
        restored=new.MAIN_SOURCE.replace('native-heap-typed-inspection-','native-heap-early-constraints-').replace(new.NEW_GENERIC,new.OLD_GENERIC)
        self.assertEqual(restored,new.previous.MAIN_SOURCE)
        for marker in ('timeout=3600','expected=125','validate_placed','compare_features','record_getter(q,r,out,run)'):
            self.assertIn(marker,new.MAIN_SOURCE)
        self.assertNotIn('\x08',new.MAIN_SOURCE)


if __name__=='__main__':unittest.main()
