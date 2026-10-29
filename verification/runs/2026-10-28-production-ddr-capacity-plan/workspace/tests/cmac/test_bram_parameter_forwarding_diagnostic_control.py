"""Root/child VVP parameter schema controls and exact preserved failure checks."""
import inspect
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import resume_bram_parameter_forwarding_diagnostic as new


class ForwardingDiagnosticControl(unittest.TestCase):
    def test_root_and_nested_records_and_width_truncation(self):
        text='''S_a .scope module, "top" "top" 3 4;
S_b .scope module, "ram" "RAM" 3 14, 4 1 0, S_a;
P_a .param/l "INIT_A" 0 5 85, C4<000xxxxxxxxx>;
S_c .scope generate, "gen_tdp" "gen_tdp" 5 474, 5 474 0, S_b;
S_d .scope module, "internal" "INT" 5 648, 5 1458 1, S_c;
P_b .param/l "INIT_A" 0 5 1458, C4<xxxxxxxxx>;
'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.vvp';path.write_text(text)
            parsed=new.parameter_tables(path)
        self.assertEqual(parsed,{'top.ram':{'INIT_A':'000xxxxxxxxx'},'top.ram.gen_tdp.internal':{'INIT_A':'xxxxxxxxx'}})

    def test_actual_failed_binary_all_six_instances_all_parameters(self):
        records=new.forwarding_records(new.previous.previous.FAILED.parent/'overwrite.vvp')
        self.assertEqual(len(records),6)
        key='tb_prefix_working_bram_overwrite.mapped.actual_0'
        self.assertEqual(len(records[key]['differences']),144)
        for name,record in records.items():
            self.assertEqual(record['parameters'],148)
            if name!=key:self.assertEqual(record['differences'],{})
        for parameter,record in records[key]['differences'].items():
            self.assertRegex(parameter,r'^INITP?_[0-9A-F]{2}$')
            self.assertEqual(record,{'outer':'x'*256,'internal':'0'*256})

    def test_exact_parser_change_no_hdl_or_comparison_change(self):
        self.assertEqual(new.PARSER_SOURCE.replace(new.NEW_ROOT,new.OLD_ROOT),inspect.getsource(new.previous.parameter_tables))
        self.assertEqual(new.RECORDS_SOURCE.replace(new.NEW_COMPARE,new.OLD_COMPARE),inspect.getsource(new.previous.forwarding_records))

    def test_preserved_source_bound_parser_failure(self):
        observation=new.observe_parser_failure()
        self.assertFalse(observation['native_bench_executed'])
        self.assertTrue(observation['failed_parser_not_relabelled'])


if __name__=='__main__':unittest.main()
