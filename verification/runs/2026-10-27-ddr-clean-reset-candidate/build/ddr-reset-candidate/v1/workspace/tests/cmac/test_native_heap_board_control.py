"""Full HeAP runner guards only; no native result or full FPGA acceptance."""
from copy import deepcopy
import inspect
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import place_native_heap_board as new
from test_native_heap_placement_control import POSITIVE


def module():
    return {'settings':{'pack':'0'*31+'1','place':'0'*31+'1','placer':'heap','target_freq':'50000000'},
            'cells':{'a':{'type':'SLICE_LUTX','attributes':{'NEXTPNR_BEL':'X0Y0/A6LUT'}},
                     'b':{'type':'SLICE_FFX','attributes':{'NEXTPNR_BEL':'X0Y0/AFF'}}}}


class Controls(unittest.TestCase):
    def test_only_algorithm_changes_in_exact_full_target_arguments(self):
        args=('isolated','original-prepared-input','literal.xdc','placed.json')
        old=new.parent.placement_argv(*args);actual=new.placement_argv(*args);new.verify_full_argv(actual)
        i=actual.index('--placer')+1
        self.assertEqual(actual[:i]+['static']+actual[i+1:],old)
        for key,value in (('--device','xc7k480tffg1156-1'),('--freq','25'),('--seed','1'),('--placer','static'),
                          ('--chipdb','another-db'),('--top','smaller-design')):
            bad=list(actual);bad[bad.index(key)+1]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):new.verify_full_argv(bad)

    def test_shortcuts_or_unknown_duplicate_or_missing_fields_refused(self):
        actual=new.placement_argv('isolated','original-input','literal.xdc','placed.json')
        for flag in ('--force','--timing-allow-fail','--no-pack','--no-place','--parallel-refine',
                     '--placer-static-refine-max-iterations','--placer-heap-alpha','--placer-heap-beta','--unknown'):
            with self.subTest(flag=flag),self.assertRaises(AssertionError):new.verify_full_argv(actual+[flag])
        for bad in (actual+['--freq','50'],[v for v in actual if v!='--Werror'],[v for v in actual if v!='--no-route']):
            with self.assertRaises(AssertionError):new.verify_full_argv(bad)

    def test_unchanged_membership_unique_bels_and_stage_gates(self):
        expected={'SLICE_LUTX':1,'SLICE_FFX':1};m=module()
        self.assertEqual(new.verify_placed_module(m,expected)['bound_cells'],2)
        for action in ('duplicate','missing_bel','changed_type','static','routed','no_pack','slow_clock'):
            bad=deepcopy(m)
            if action=='duplicate':bad['cells']['b']['attributes']['NEXTPNR_BEL']=bad['cells']['a']['attributes']['NEXTPNR_BEL']
            elif action=='missing_bel':bad['cells']['a']['attributes'].clear()
            elif action=='changed_type':bad['cells']['a']['type']='other'
            elif action=='static':bad['settings']['placer']='static'
            elif action=='routed':bad['settings']['route']='0'*31+'1'
            elif action=='no_pack':bad['settings']['pack']='0'*32
            else:bad['settings']['target_freq']='25000000'
            with self.subTest(action=action),self.assertRaises(AssertionError):new.verify_placed_module(bad,expected)

    def test_full512_kernel_scope_and_native_completion_are_required(self):
        with self.assertRaises(AssertionError):new.verify_placed_module(module(),{'SLICE_LUTX':1,'SLICE_FFX':1},{'small':32})
        new.qualified.check_heap_log(0,POSITIVE)
        for marker in ('HeAP Placer Time:','Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...','Program finished normally.'):
            with self.assertRaises(AssertionError):new.qualified.check_heap_log(0,POSITIVE.replace(marker,''))

    def test_completed_qualification_not_incomplete_report_is_admitted(self):
        for value in ({'status':'RUNNING'},{'status':'FAIL'},{'status':'PLACED'},{}):
            with self.assertRaises((AssertionError,KeyError)):new.qualified.verify_metadata(value)
        self.assertIs(new.NAMESPACE['verify_qualification'],new.qualified.verify_qualification)

    def test_source_shape_retains_original_full_runner_resource_and_binding_gates(self):
        self.assertEqual(new.NATIVE_TIMEOUT,43200)
        for marker in ('verify_previous_failure(previous)','verify_bindings(before)','verify_prepared_metadata(prepared)',
                       'original_prepared_input_repacked=True','resource.RLIMIT_AS, (12 * 1024 ** 3, 12 * 1024 ** 3)',
                       'retained_cmac_dsps=512, retained_shell_dsps=3','intended_clock_period_ns=20, seed=3588',
                       'run(\'native_place\', argv, NATIVE_TIMEOUT)','verify_placed_module(module, packed[\'native_packed_cell_counts\']'):
            self.assertIn(marker,new.MAIN_SOURCE)
        original=inspect.getsource(new.parent.main)
        reconstructed=new.MAIN_SOURCE.replace('full-prefix-native-heap-place-','full-prefix-bounded-search-place-').replace(new.NEW_NATIVE_BLOCK,new.OLD_NATIVE_BLOCK).replace(
            "placement_algorithm='heap', native_source_or_executable_changed=False, corrected_DSP_encoder_preserved=True, native_legality_guards_preserved=True",
            'changed_static_placer_object=1, corrected_DSP_encoder_preserved=True, native_legality_guards_preserved=True')
        self.assertEqual(reconstructed,original)
        self.assertEqual(new.FLAGS,new.parent.FLAGS)


if __name__=='__main__':unittest.main()
