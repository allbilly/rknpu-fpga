"""HeAP converter/readback guards; neither native nor physical acceptance."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import probe_native_heap_frames as new
from test_corrected_frame_database_control import CorrectedFrameDatabaseControl


class Controls(unittest.TestCase):
    def test_actual_saved_native_has_all64_dsp_features_and_clock_owners(self):
        q=json.loads(new.QUALIFICATION.read_text())
        self.assertEqual(len(new.required_features(q)),64)
        contracts=new.actual_clock_contracts()
        self.assertEqual(len(contracts),2)
        self.assertEqual(sum(len(v['PIPs']) for v in contracts.values()),3)
        self.assertEqual(new.saved_fasm_digest(),new.original.digest(new.NATIVE.parent/'control.fasm'))

    def test_old_full_dsp_requirements_and_frame_main_changes_are_reversible(self):
        self.assertEqual(new.REQUIRED_SOURCE,inspect.getsource(new.original.required_features))
        restored=new.MAIN_SOURCE
        for old,replacement in reversed(new.REPLACEMENTS):restored=restored.replace(replacement,old)
        self.assertEqual(restored,inspect.getsource(new.original.main))
        restored=new.CLOCK_READBACK_SOURCE
        for old,replacement in reversed(new.CLOCK_READBACK_REPLACEMENTS):restored=restored.replace(replacement,old)
        self.assertEqual(restored,inspect.getsource(new.original.readback))

    def test_execution_uses_raw_fasm_and_never_clock_or_dsp_targets(self):
        main=new.MAIN_SOURCE
        self.assertIn("[frame.PYTHON, '-B', frame.__file__, '--worker', fasm, destination]",main)
        self.assertIn("frames = frame.validate_conversion(result, destination)",main)
        self.assertIn("result['counts']['input_lines'] == "+new.NEW_COUNT,main)
        self.assertIn("assert 'XRAY_ALLOW_MISSING_FEATURES' not in env",main)
        self.assertNotIn('worker\', expected',main)
        self.assertIs(new.NAMESPACE['readback'],new.original.readback)
        for field in ('expected_features_used_for_conversion=False','full_board_FASM_conversion_executed=False',
                      'clock_targets_used_for_conversion=False','bitstream_emitted=False','hardware_programmed=False'):
            self.assertIn(field,main)

    def test_raw_clock_requests_require_exact_positive_fanout_not_injection(self):
        key='HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0'
        contracts={key:dict(value=1,PIPs=['one','two'])}
        request=dict(feature=key,value=1,start=None,end=None,kind='input_lines')
        self.assertEqual(new.verify_clock_requests([request,request],contracts)['raw_clock_request_count'],2)
        for requests in ([],[request],[request]*3,[request,dict(request,value=0)],
                         [request,dict(request,kind='injected_lines')],[request,dict(request,start=0)],
                         [request,dict(request,value=True)],[request,dict(request,feature=key.replace('BUFHCLK0','BUFHCLK1'))]):
            with self.subTest(requests=requests),self.assertRaises(AssertionError):new.verify_clock_requests(requests,contracts)

    def test_positive_clock_bits_cannot_alias_or_be_negative_missing_or_corrupt(self):
        one='HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0'
        two='HCLK_R_X22Y286.ENABLE_BUFFER.HCLK_CK_BUFHCLK0'
        good={one:[(0x123,0,14,True)],two:[(0x123,1,14,True)]}
        words={0x123:[1<<14,1<<14]+[0]*99}
        self.assertEqual(new.verify_clock_bit_locations(good,words)['physical_DB_bits_compared'],2)
        for bad in ({},{one:[]},{one:[(0x123,0,14,False)]},{one:[(0x123,0,14,True)]*2},
                    {one:good[one],two:good[one]},{'unknown':good[one]}):
            with self.subTest(bad=bad),self.assertRaises(AssertionError):new.verify_clock_bit_locations(bad,words)
        for action in ('missing','truncated','corrupt'):
            bad=deepcopy(words)
            if action=='missing':bad.clear()
            elif action=='truncated':bad[0x123].pop()
            else:bad[0x123][1]^=1<<14
            with self.subTest(action=action),self.assertRaises(AssertionError):new.verify_clock_bit_locations(good,bad)

    def test_incomplete_or_failed_qualification_remains_refused(self):
        for q in ({},{'status':'RUNNING'},{'status':'FAIL'},json.loads(new.NATIVE.read_text())):
            with self.assertRaises((AssertionError,KeyError)):new.required_features(q)


if __name__=='__main__':unittest.main()
