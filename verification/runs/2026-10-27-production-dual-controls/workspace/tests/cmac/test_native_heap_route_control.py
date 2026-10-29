"""Full HeAP route guard controls plus every original v2/static route control."""
import inspect
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import route_native_heap_board as new
import check_full_heap_clock_features as clock_features
import test_empty_output_full_route as previous_tests
from test_strict_search_route import placement,NATIVE_GOOD

# Retain all original error expectations and saved-small identity controls.
FullImportedExport=previous_tests.FullImportedExport
EmptyOutputFullRoute=previous_tests.EmptyOutputFullRoute


def heap_fixture():
    r=placement();r['status']=new.placement.PLACED
    del r['changed_static_placer_object']
    r.update(placement_algorithm='heap',native_source_or_executable_changed=False)
    r['commands'][-1]['native_heap_completion_checked']=True
    return r


class Controls(unittest.TestCase):
    def test_actual_full_heap_metadata_not_static_or_running_or_small(self):
        r=heap_fixture();new.verify_placed_metadata(r)
        with self.assertRaises(AssertionError):new.previous.original.verify_placed_metadata(r)
        with self.assertRaises(AssertionError):new.verify_placed_metadata(placement())
        for key,value in (('status','RUNNING'),('status','FAIL'),('parallel_products',32),('intended_clock_period_ns',40),
                          ('placement_algorithm','static'),('native_source_or_executable_changed',True),
                          ('native_legality_guards_preserved',False),('physical_fit_verified',True)):
            bad=heap_fixture();bad[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):new.verify_placed_metadata(bad)

    def test_missing_bels_kernel_or_positive_native_completion_refused(self):
        for action in ('duplicate','small','kernel','native'):
            r=heap_fixture()
            if action=='duplicate':r['placement_checks']['unique_bel_slots']-=1
            elif action=='small':r['placement_checks']['bound_cells']=286
            elif action=='kernel':r['placement_checks']['retained_kernel_dsps']={'one':32}
            else:r['commands'][-1]['native_heap_completion_checked']=False
            with self.subTest(action=action),self.assertRaises(AssertionError):new.verify_placed_metadata(r)

    def test_checkpoint_route_cannot_run_heap_or_static_placement(self):
        new.check_full_scan(NATIVE_GOOD,538118,200000,17)
        for marker in ('Running Static placer...','Creating initial analytic placement for ',
                       'HeAP Placer Time:','Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...'):
            with self.assertRaises(AssertionError):new.check_full_scan(NATIVE_GOOD+'\nInfo: '+marker,538118,200000,17)

    def test_source_transition_is_reversible_without_changing_old_route_gate(self):
        restored=new.MAIN_SOURCE
        for old,replacement in reversed(new.REPLACEMENTS):restored=restored.replace(replacement,old)
        self.assertEqual(restored,new.previous.MAIN_SOURCE)
        restored_metadata=new.METADATA_SOURCE.replace(new.NEW_OBJECT,new.OLD_OBJECT)
        self.assertEqual(restored_metadata,inspect.getsource(new.previous.original.verify_placed_metadata))
        self.assertEqual(new.previous.original.PLACED,new.placement.parent.PLACED)

    def test_all_literal_checkpoint_scan_connectivity_feature_identity_gates_remain(self):
        for marker in ('verify_placed_metadata(placed)','verify_placed_native_evidence(placed,placed_path)',
                       'verify_small_evidence(before)','verify_placed_module(',"run('native_scan_and_route', argv, 43200)",
                       'assert_circuit_identity(','verify_routed_footprint(','verify_full_features(',
                       'check_import_count(log,',new.previous.NEW_PROFILE):
            self.assertIn(marker,new.MAIN_SOURCE)
        self.assertIs(new.NAMESPACE['verify_placement_engine'],new.placement.qualified.verify_qualification)
        self.assertIs(new.NAMESPACE['verify_small_evidence'],new.previous.verify_qualification)

    def test_clock_adapter_preserves_the_entire_full_comparison_body_and_census(self):
        self.assertEqual(clock_features.COMPARISON_SOURCE,
                         inspect.getsource(clock_features.original.verify_full_features))
        namespace=clock_features.comparison_namespace({'not executed':'control only'})
        for name in ('full_inventory','routed_primitives','placed_primitives','compare_selected',
                     'compare_corrected_dsp','compare_bram'):
            self.assertIs(namespace[name],getattr(clock_features.original,name))
        self.assertIs(new.NAMESPACE['verify_full_features'],clock_features.verify_full_features)
        self.assertIn('clock_contracts(module)',new.MAIN_SOURCE)
        self.assertIn('for p in clock_feature_sources',new.MAIN_SOURCE)
        self.assertLess(new.MAIN_SOURCE.index('for p in clock_feature_sources'),
                        new.MAIN_SOURCE.index("run('native_scan_and_route'"))

    def test_actual_small_clock_control_cannot_pass_full515_census(self):
        qualification=new.placement.qualified
        directory=qualification.FAILED.parent
        module=next(iter(json.loads((directory/'routed.json').read_text())['modules'].values()))
        contracts=clock_features.clock.clock_contracts(module)
        parent=json.loads(qualification.first.parent.first.NATIVE.read_text())
        selected=json.loads(qualification.first.parent.first.SELECTED.read_text())
        small={name:selected[origin] for name,origin in parent['control_origins'].items()}
        with self.assertRaises(AssertionError):
            clock_features.verify_full_features(directory/'control.fasm',directory/'placement.json',
                                                directory/'routed.json',small,{},contracts)
        self.assertEqual(len(small),10)
        with self.assertRaisesRegex(AssertionError,'Unsupported repeated native FASM feature'):
            clock_features.original.parse_native_features((directory/'control.fasm').read_text())

    def test_clock_parser_admission_remains_strict_in_full_namespace(self):
        key='HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0'
        contracts={key:dict(value=1,PIPs=[{'generic_pip':'control only'}])}
        parser=clock_features.comparison_namespace(contracts)['parse_native_features']
        self.assertEqual(parser(key+'\n')[0],{key:'1'})
        for text in (key+'\n'+key+'\n',key+' = 0\n','unmodeled\nunmodeled\n',
                     key+'\n'+key.replace('BUFHCLK0','BUFHCLK1')+'\n'):
            with self.subTest(text=text),self.assertRaises(AssertionError):parser(text)


if __name__=='__main__':unittest.main()
