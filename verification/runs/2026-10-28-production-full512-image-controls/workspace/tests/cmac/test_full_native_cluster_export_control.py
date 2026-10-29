"""Optional full diagnostic guards; synthetic metadata is not native evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools')]
import export_full_native_pack_clusters as probe


def synthetic_small():
    return dict(status=probe.small.STATUS, stage='complete', finished_utc='synthetic_not_native',
        target_c=32, target_k=16, full_parallel_products=512, full_target_dsp=515, full_target_bram=6,
        part='xc7k480tffg1156-2', production_source_before={'synthetic': True}, production_source_after={'synthetic': True},
        diagnostic_optional_not_new_acceptance_gate=True, changed_link_objects=1, unchanged_qualified_parent_relink=True,
        parent_off_on_packed_graphs_byte_identical=True, parent_off_on_checksums_identical=True,
        existing_metadata_overwrite_rejected=True, exact_actual_parent_arch_source_retained=True,
        commands=[dict(label=label, expected_returncode=125 if label==probe.LABELS[-1] else 0,
                       returncode=125 if label==probe.LABELS[-1] else 0, status='PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY')
                  for label in probe.LABELS],
        native_error_contract=dict(exception='log_execution_error_exception',fatal_returncode=125,
            fatal_error_remains_rejection=True, does_not_change_hardware_error_expectations=True),
        metadata_checks=dict(cells=21,cluster_roots=3,cluster_children=8,cluster_metadata_exported=True,
                             geometry_fit_checked=False,full_placement_or_timing_acceptance=False),
        **{flag:False for flag in probe.original.FLAGS})


class FullNativeClusterExportControls(unittest.TestCase):
    def test_complete_typed_metadata_only_not_artifact_admission(self):
        probe.validate_small_metadata(synthetic_small())

    def test_incomplete_failed_reduced_target_or_physical_claim_rejected(self):
        for key,value in (('status','RUNNING'),('status','FAIL'),('stage','admitted'),('finished_utc',None),
                          ('target_c',16),('target_k',8),('full_parallel_products',256),('full_target_dsp',259),
                          ('full_target_bram',3),('part','wrong'),('hardware_programmed',True),
                          ('unchanged_qualified_parent_relink',False),('parent_off_on_checksums_identical',False)):
            report=synthetic_small(); report[key]=value
            with self.subTest(key=key,value=value), self.assertRaises(AssertionError):
                probe.validate_small_metadata(report)

    def test_wrong_native_return_contract_command_or_export_rejected(self):
        for case in ('return','expected','missing','contract','census','geometry','source'):
            report=synthetic_small()
            if case=='return': report['commands'][-1]['returncode']=1
            elif case=='expected': report['commands'][-1]['expected_returncode']=1
            elif case=='missing': report['commands'].pop()
            elif case=='contract': report['native_error_contract']['fatal_returncode']=1
            elif case=='census': report['metadata_checks']['cells']=20
            elif case=='geometry': report['metadata_checks']['geometry_fit_checked']=True
            else: report['production_source_after']={'changed':True}
            with self.subTest(case=case), self.assertRaises(AssertionError):
                probe.validate_small_metadata(report)

    def test_running_rejected_before_any_output_native_tool_or_source_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'build/openxc7/source-defined-native-cluster-export-synthetic/report.json'
            path.parent.mkdir(parents=True)
            report=synthetic_small(); report['status']='RUNNING'
            path.write_text(json.dumps(report))
            before=set(root.rglob('*'))
            with (mock.patch.object(probe,'ROOT',root), mock.patch.object(probe,'source_revision') as revision,
                  mock.patch.object(probe.subprocess,'Popen') as native,
                  mock.patch.object(sys,'argv',['probe','--small',str(path)])):
                with self.assertRaises(AssertionError): probe.main()
            revision.assert_not_called(); native.assert_not_called()
            self.assertEqual(before,set(root.rglob('*')))

    def test_conflicting_file_binding_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input'; path.write_text('typed control')
            bindings={str(path):'first'}
            with self.assertRaises(AssertionError): probe.merge(bindings,{str(path):'second'})

    def test_full_command_keeps_real_scope_input_clock_seed_warnings(self):
        parent=json.loads(probe.FULL_PACK.read_text())
        command=probe.full_command(parent,'/own/isolated-engine','/own/literal.xdc','/own/packed.json','/own/clusters.jsonl')
        old=list(parent['commands'][-1]['argv'])
        expected=list(old)
        expected[0]='/own/isolated-engine'
        expected[expected.index('-o')+1]='xdc=/own/literal.xdc'
        expected[expected.index('--write')+1]='/own/packed.json'
        expected+=['-o',probe.original.OPTION+'=/own/clusters.jsonl']
        self.assertEqual(command,expected)
        self.assertIn('--Werror',command)
        self.assertEqual(command[command.index('--json')+1],parent['execution_input'])
        for key,value in (('channels',16),('kernels',8),('parallel_products',256),('seed',1),('intended_clock_period_ns',40)):
            changed=deepcopy(parent); changed[key]=value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                probe.full_command(changed,'/own/engine','/own/xdc','/own/packed','/own/meta')

    def test_actual_small_graph_type_projection_keeps_real_settings(self):
        path=probe.original.ROOT/'build/openxc7/native-pack-cluster-export-1791518825958732551/diagnostic_on-packed.json'
        actual=json.loads(path.read_text())
        projected=probe.packed_type_document(path)
        self.assertEqual(projected['creator'],actual['creator'])
        for name,module in actual['modules'].items():
            self.assertEqual(projected['modules'][name]['settings'],module['settings'])
            self.assertEqual(projected['modules'][name]['ports'],module['ports'])
            self.assertEqual(projected['modules'][name]['cells'],{n:{'type':c['type']} for n,c in module['cells'].items()})

    def test_geometry_conflict_remains_separate_not_silently_accepted(self):
        rows=[dict(kind='cell',name='root',type='R',cluster='root',x=0,y=0,z=0,abs_z=False,children=['child']),
              dict(kind='cell',name='child',type='C',cluster='root',x=0,y=0,z=1,abs_z=False,children=[])]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'typed.jsonl'; path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            grid=probe.geometry.Grid(1,1,(0,),({0:'R'},))
            audit=probe.audit_clusters(path,grid)
            self.assertEqual(audit['zero_candidate_classes'],1)
            self.assertFalse(audit['full_fit_verified'])
            self.assertFalse(audit['joint_occupancy_or_fixed_bels_checked'])
            self.assertNotEqual(probe.CONFLICT,probe.EXPORTED)


if __name__=='__main__': unittest.main()
