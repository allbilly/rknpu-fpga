"""Clock flag grammar/fanout contracts; no frame conversion or physical pass."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import clock_bound_native_features as new
from probe_prefix_native_config import parse_native_features

DIRECTORY=new.ROOT/'build/openxc7/native-heap-typed-inspection-1791459029556778888'
FEATURE='HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0'


class Controls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module=next(iter(json.loads((DIRECTORY/'routed.json').read_text())['modules'].values()))
        cls.text=(DIRECTORY/'control.fasm').read_text();cls.contracts=new.clock_contracts(cls.module)

    def test_actual_emitter_and_consumer_preserve_original_parser_failure(self):
        new.source_contract();self.assertTrue(new.consumer_merge_check()['conflicting_assignment_rejected'])
        with self.assertRaisesRegex(AssertionError,'Unsupported repeated native FASM feature'):parse_native_features(self.text)

    def test_actual_clock_fanout_and_exact_native_feature_counts(self):
        value=self.contracts[FEATURE]
        self.assertEqual(value['net'],'$frontend$22');self.assertEqual(value['relative_positive_bit'],'00_14')
        self.assertEqual([p['pip_index'] for p in value['PIPs']],[1,7])
        self.assertEqual([p['generic_pip'] for p in value['PIPs']],
                         ['X22Y182/HCLK_LEAF_CLK_B_BOT0/HCLK_CK_BUFHCLK0','X22Y182/HCLK_LEAF_CLK_B_TOP0/HCLK_CK_BUFHCLK0'])
        features,io,clock=new.parse_clock_bound_features(self.text,self.contracts)
        self.assertEqual(len(features),7869);self.assertEqual(len(io),5);self.assertEqual(clock,{FEATURE:[9060,9061]})

    def test_missing_extra_changed_or_noncanonical_clock_emission_refused(self):
        for text in (self.text.replace(FEATURE+'\n','',1),self.text+FEATURE+'\n',
                     self.text.replace(FEATURE,FEATURE+' = 1\'b0'),self.text.replace(FEATURE,FEATURE+' = 1\'b1'),
                     self.text.replace(FEATURE,'HCLK_R_X22Y235.ENABLE_BUFFER.HCLK_CK_BUFHCLK0'),
                     self.text.replace(FEATURE,FEATURE[:-1]+'8')):
            with self.assertRaises(AssertionError):new.parse_clock_bound_features(text,self.contracts)

    def test_unknown_repetition_conflict_or_io_count_remains_failure(self):
        for extra in ('UNKNOWN.FEATURE\nUNKNOWN.FEATURE\n','DSP_L_X0Y0.PARAM\nDSP_L_X0Y0.PARAM\n',
                      "UNKNOWN.FEATURE = 1'b1\nUNKNOWN.FEATURE = 1'b0\n"):
            with self.assertRaises(AssertionError):new.parse_clock_bound_features(self.text+extra,self.contracts)
        _,io,_=new.parse_clock_bound_features(self.text,self.contracts)
        with self.assertRaises(AssertionError):new.parse_clock_bound_features(self.text+next(iter(io))+'\n',self.contracts)

    def test_actual_route_not_expected_string_determines_repetition_budget(self):
        m=deepcopy(self.module);route=m['netnames']['$frontend$22']['attributes']['ROUTING'];tokens=route.split(';')
        pip=self.contracts[FEATURE]['PIPs'][0]['generic_pip'];i=tokens.index(pip);del tokens[i-1:i+2]
        m['netnames']['$frontend$22']['attributes']['ROUTING']=';'.join(tokens)
        changed=new.clock_contracts(m);self.assertEqual(len(changed[FEATURE]['PIPs']),1)
        with self.assertRaises(AssertionError):new.parse_clock_bound_features(self.text,changed)

    def test_repeated_or_multiple_owner_clock_pips_refused(self):
        route=self.module['netnames']['$frontend$22']['attributes']['ROUTING']
        pip=self.contracts[FEATURE]['PIPs'][0]['generic_pip'];tokens=route.split(';');i=tokens.index(pip)
        triple=';'.join(tokens[i-1:i+2])
        for same in (True,False):
            m=deepcopy(self.module)
            if same:m['netnames']['$frontend$22']['attributes']['ROUTING']+=';'+triple
            else:m['netnames']['wrong-clock-owner']={'attributes':{'ROUTING':triple}}
            with self.assertRaises(AssertionError):new.clock_contracts(m)

    def test_unknown_clock_pip_or_strength_or_tile_profile_refused(self):
        route=self.module['netnames']['$frontend$22']['attributes']['ROUTING'];pip=self.contracts[FEATURE]['PIPs'][0]['generic_pip']
        for bad in (route.replace(pip,pip.replace('BOT0','BOT99')),route.replace(pip,pip+'/INV'),
                    route.replace(pip,pip.replace('HCLK_CK_BUFHCLK0','HCLK_CK_BUFHCLK8')),
                    route.replace(pip,pip.replace('X22Y182','X9999Y182')),route.replace(';5',';9',1)):
            m=deepcopy(self.module);m['netnames']['$frontend$22']['attributes']['ROUTING']=bad
            with self.assertRaises((AssertionError,KeyError)):new.clock_contracts(m)

    def test_contract_or_boolean_value_cannot_be_missing_or_forged(self):
        with self.assertRaises(AssertionError):new.parse_clock_bound_features(self.text,{})
        for action in ('missing','count','value','name'):
            bad=deepcopy(self.contracts)
            if action=='missing':del bad[FEATURE]
            elif action=='count':bad[FEATURE]['PIPs'].pop()
            elif action=='value':bad[FEATURE]['value']=0
            else:bad['unknown']=bad.pop(FEATURE)
            with self.assertRaises(AssertionError):new.parse_clock_bound_features(self.text,bad)


if __name__=='__main__':unittest.main()
