"""Prepared full-frame guards only; no actual full route/conversion PASS."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/openxc7'))
import convert_full_heap_frames as new
from test_native_heap_frame_control import Controls as SmallClockControls
from test_corrected_frame_database_control import CorrectedFrameDatabaseControl


def metadata():
    groups={f'kernel{k}':32 for k in range(16)};clocks={'control only':{}}
    return dict(status=new.admission.route.ROUTED,stage='complete',finished_utc='synthetic metadata-only control',
        channels=32,kernels=16,parallel_products=512,intended_part='xc7k480tffg1156-2',intended_clock_period_ns=20,seed=3588,
        native_routing_executed=True,full_native_imported_checkpoint_scan_executed=True,full_native_FASM_emitted=True,
        full_DSP_BRAM_source_defined_features_compared=True,native_v2_literal_LUT_output_declarations_imported=True,
        placement_engine_not_executed_during_route=True,placement_and_route_share_corrected_DSP_base=True,full_bound_cells=538118,
        physical_resource_checks=dict(retained_kernel_dsps=groups,unchanged_physical_bel_assignments=538118),
        original_logical_circuit_identity={'logical_board':dict(cells=538118)},
        full_DSP_BRAM_FASM_feature_comparison=dict(selected_primitives_compared=521,primitive_checks=dict.fromkeys(range(521),{}),
            kernel_dsps=groups,corrected_DSP_tile_pins_compared=4120,clock_contracts_from_actual_routed_module=clocks),
        full_native_clock_fanout_contracts=clocks,production_source_before='control',production_source_after='control',
        constraint_translation=dict(target_period_ns=20.0,signoff_constraint_profile=False),
        commands=[dict(label=name,status='PASS_TOOL_EXECUTION_ONLY',returncode=0,expected_returncode=0)
                  for name in ('software_controls','generated_check','version','linked_router_check','native_scan_and_route')],
        **{k:False for k in new.admission.route.previous.original.FLAGS})


class Controls(unittest.TestCase):
    def test_full_metadata_rejects_running_small_wrong_part_clock_seed_or_signoff(self):
        new.admission.verify_metadata(metadata())
        for key,value in (('status','RUNNING'),('status',new.small.PASS),('stage','native_scan_and_route'),('parallel_products',32),
                          ('intended_part','xc7k480tffg1156-1'),('intended_clock_period_ns',40),('seed',1),
                          ('full_bound_cells',286),('native_routing_executed',False))+tuple(
                                  (k,True) for k in new.admission.route.previous.original.FLAGS):
            r=metadata();r[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):new.admission.verify_metadata(r)

    def test_full_resource_identity_census_command_and_clock_gates_cannot_disappear(self):
        for action in ('bel','kernel','logical','DSP','tilepins','clock','command','returncode','source'):
            r=metadata()
            if action=='bel':r['physical_resource_checks']['unchanged_physical_bel_assignments']-=1
            elif action=='kernel':r['physical_resource_checks']['retained_kernel_dsps'].pop('kernel0')
            elif action=='logical':r['original_logical_circuit_identity']['logical_board']['cells']=286
            elif action=='DSP':r['full_DSP_BRAM_FASM_feature_comparison']['selected_primitives_compared']=10
            elif action=='tilepins':r['full_DSP_BRAM_FASM_feature_comparison']['corrected_DSP_tile_pins_compared']=32
            elif action=='clock':r['full_native_clock_fanout_contracts']={}
            elif action=='command':r['commands'].pop()
            elif action=='returncode':r['commands'][-1]['returncode']=125
            else:r['production_source_after']='changed'
            with self.subTest(action=action),self.assertRaises(AssertionError):new.admission.verify_metadata(r)

    def test_actual_small_frame_parent_has_proper_scope_and_cannot_become_full_route(self):
        r=json.loads(new.SMALL.read_text());new.verify_small_metadata(r)
        with self.assertRaises(AssertionError):new.admission.verify_metadata(r)
        for key,value in (('status','RUNNING'),('native_control_dsps',515),('full_board_FASM_conversion_executed',True),
                          ('production_source_after','changed'))+tuple((k,True) for k in new.FLAGS):
            bad=deepcopy(r);bad[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):new.verify_small_metadata(bad)

    def test_actual_small_selected_primitives_cannot_pass_full8240_feature_gate(self):
        reference=json.loads(new.small.qualification.first.parent.first.NATIVE.read_text())
        selected=json.loads(new.small.qualification.first.parent.first.SELECTED.read_text())
        small={name:selected[origin] for name,origin in reference['control_origins'].items()}
        with self.assertRaisesRegex(AssertionError,'Not full515-DSP'):
            new.required_features(new.small.NATIVE.parent/'control.fasm',new.small.NATIVE.parent/'placement.json',
                                  small,new.small.actual_clock_contracts())

    def test_full_DSP_readback_body_only_scales_count_and_message(self):
        restored=new.DSP_READBACK_SOURCE.replace(
            "assert len(required) == 8240 and set(required.values()) == {'1'}",
            "assert len(required) == 64 and set(required.values()) == {'1'}").replace(
            'PASS actual full corrected DSP frame-bit readback and comparison-only corruption negative',
            'PASS actual corrected DSP frame-bit readback and comparison-only corruption negative')
        self.assertEqual(restored,inspect.getsource(new.small.original.readback))
        self.assertIs(new.DSP_NAMESPACE['check_feature_bits'],new.small.original.check_feature_bits)

    def test_all_source_native_identity_gates_are_recomputed_not_PASS_label_only(self):
        source=inspect.getsource(new.admission.verify_route)
        for text in ('verify_qualification(','verify_placed_native_evidence(','bind_report(','verify_bindings(',
                     "assert c['argv']==argv",'check_full_scan(','check_import_count(','verify_routed_footprint(',
                     'clock_contracts(module)','assert_circuit_identity(','verify_full_features('):
            self.assertIn(text,source)
        main=inspect.getsource(new.main)
        self.assertLess(main.index('admission.verify_metadata('),main.index('out.mkdir('))
        self.assertLess(main.index('admission.verify_route('),main.index("run('strict_full_native_FASM_conversion'"))
        self.assertIn("[frame.PYTHON,'-B',frame.__file__,'--worker',fasm,destination]",main)
        self.assertNotIn("'--worker',expected",main)
        self.assertEqual(new.FRAME_TIMEOUT,43200)

    def test_streaming_request_census_matches_actual_complete_small_converter_output(self):
        q=json.loads(new.SMALL.read_text());directory=new.SMALL.parent
        required=json.loads((directory/'comparison-only-required-DSP-features.json').read_text())
        path=directory/'native-conversion/feature-requests.jsonl'
        self.assertEqual(new.small.original.verify_requests(new.converter_requests(path),required),q['converter_requests'])
        self.assertEqual(new.small.verify_clock_requests(new.converter_requests(path),q['clock_fanout_contracts']),q['clock_converter_requests'])
        with tempfile.TemporaryDirectory() as folder:
            wrong=Path(folder)/'unmodeled.jsonl';wrong.write_text(json.dumps(dict(feature='x',value=1,start=None,end=None,kind='input_lines',unknown=1))+'\n')
            with self.assertRaisesRegex(AssertionError,'Unmodeled'):list(new.converter_requests(wrong))
            wrong.write_text('{"feature":"x","feature":"x","value":1,"start":null,"end":null,"kind":"input_lines"}\n')
            with self.assertRaisesRegex(AssertionError,'Duplicate'):list(new.converter_requests(wrong))

    def test_cli_refuses_actual_live_placement_before_any_conversion(self):
        path=new.ROOT/'build/openxc7/full-prefix-native-heap-place-1791461555717052444/report.json'
        p=subprocess.run([sys.executable,'-B',new.__file__,'--routed',str(path)],capture_output=True,text=True,timeout=30)
        self.assertNotEqual(p.returncode,0);self.assertIn('AssertionError',p.stderr)
        self.assertNotIn('full-native-heap-frames-',p.stdout)


if __name__=='__main__':unittest.main()
