"""Synthetic paired-parent/binding controls, not numerical or FPGA evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
sys.path.insert(0,str(ROOT/'tests/cmac'))
import test_paired_mapped_array as runner
import test_fixed_mapped_array_control as baseline_controls
import test_board_lut_pair as pairing_controls


def report_fixture():
    return dict(status='PREPARED_LUT6_2_BOARD_CANDIDATE_ONLY',stage='complete',
        channels=32,kernels=16,parallel_products=512,circuit_pair_verified=True,
        export_circuit_identity=runner.EXPORT_IDENTITY,numerical_netlist_acceptance=False,
        physical_fit_verified=False,bitstream_emitted=False,hardware_programmed=False,
        physical_lut_pairs=2,unique_function_classes=1,expected_four_state_comparisons=32,
        four_state_function_class_result='PASS LUT_PAIR_FOUR_STATE classes=1 comparisons=32',
        commands=[dict(status='PASS',returncode=1 if n=='negative_test' else 0,log='build/synthetic/'+n+'.log') for n in runner.STEPS])


class PairedMappedArrayControls(unittest.TestCase):
    def binding(self):
        array=baseline_controls.fixture()
        kind=runner.partition(array)[1]
        board={'modules':{kind:deepcopy(array['modules'][kind])}}
        board['modules'][kind]['netnames']={'debug':dict(bits=[999999])}
        candidate=deepcopy(board)
        candidate['modules'][kind]['cells']['lut']['parameters']['INIT']='01'
        return array,board,candidate,kind

    def test_completed_parent_metadata_and_real_negative_required(self):
        report=report_fixture()
        self.assertEqual(runner.validate_pair_metadata(report),report['four_state_function_class_result'])
        for code in (0,2,-15):
            altered=deepcopy(report); altered['commands'][5]['returncode']=code
            with self.assertRaises(AssertionError): runner.validate_pair_metadata(altered)

    def test_running_failed_other_status_and_unfinished_stage_rejected(self):
        for status in ('RUNNING','FAIL','PASS_FIXED_CMAC_XC7_AREA_EXPERIMENT_ONLY'):
            report=report_fixture(); report['status']=status
            with self.assertRaises(AssertionError): runner.validate_pair_metadata(report)
        report=report_fixture(); report['stage']='export'
        with self.assertRaises(AssertionError): runner.validate_pair_metadata(report)

    def test_geometry_or_false_structure_gate_rejected(self):
        for key,value in [('channels',8),('kernels',8),('parallel_products',256),
                          ('circuit_pair_verified',False),('export_circuit_identity','partial')]:
            report=report_fixture(); report[key]=value
            with self.assertRaises(AssertionError): runner.validate_pair_metadata(report)

    def test_empty_classes_missing_proof_or_misrepresented_physical_acceptance_rejected(self):
        for key,value in [('physical_lut_pairs',0),('unique_function_classes',0),
                          ('expected_four_state_comparisons',0),('four_state_function_class_result','PASS subset')]:
            report=report_fixture(); report[key]=value
            with self.assertRaises(AssertionError): runner.validate_pair_metadata(report)
        for key in ('numerical_netlist_acceptance','physical_fit_verified','bitstream_emitted','hardware_programmed'):
            report=report_fixture(); report[key]=True
            with self.assertRaises(AssertionError): runner.validate_pair_metadata(report)

    def test_missing_reordered_failed_or_nonzero_positive_tool_rejected(self):
        for label in ('missing','duplicate','reordered','failed','positive'):
            report=report_fixture()
            if label=='missing': report['commands'].pop()
            elif label=='duplicate': report['commands'].append(deepcopy(report['commands'][0]))
            elif label=='reordered': report['commands'].reverse()
            elif label=='failed': report['commands'][0]['status']='FAIL'
            else: report['commands'][-1]['returncode']=1
            with self.assertRaises(AssertionError): runner.validate_pair_metadata(report)

    def proof_metadata(self):
        report=report_fixture(); out=ROOT/'build/synthetic'; final={}
        for key in ('function_class_inputs','function_class_executables'):
            report[key]={}
            for label in ('actual','negative'):
                names=(['paired_hierarchy.json','pair_certificate.json','function_classes.json',
                    'xilinx_functional_models.v',label+'.sv'] if key=='function_class_inputs' else [label+'.vvp'])
                files={str((out/n).relative_to(ROOT)):'1'*64 for n in names}
                report[key][label]=dict(files=files); final.update(files)
        report['artifacts']=dict(files=final)
        return report,out

    def test_both_compilation_input_sets_and_executables_must_match_artifacts(self):
        report,out=self.proof_metadata(); runner.validate_pair_proof_metadata(report,out)
        for label in ('missing','extra','wrong_hash','missing_file','wrong_executable'):
            altered=deepcopy(report)
            if label=='missing': del altered['function_class_inputs']['negative']
            elif label=='extra': altered['function_class_executables']['other']=dict(files={})
            elif label=='wrong_hash': altered['function_class_inputs']['actual']['files']['build/synthetic/actual.sv']='2'*64
            elif label=='missing_file': del altered['function_class_inputs']['negative']['files']['build/synthetic/negative.sv']
            else: altered['function_class_executables']['actual']['files']={'build/synthetic/negative.vvp':'1'*64}
            with self.assertRaises(AssertionError): runner.validate_pair_proof_metadata(altered,out)

    def test_literal_export_bindings_and_any_changed_circuit_rejected(self):
        design,_=pairing_controls.BoardLutPairControls().module_fixture()
        modules,module_aliases=runner.implementation_module_aliases(design)
        exported,instance_aliases=runner.hardware_instance_aliases(modules)
        verilog=runner.structural_board_verilog(exported)
        runner.verify_pair_export(design,module_aliases,instance_aliases,verilog,exported)
        for label in ('module','instance','verilog','circuit'):
            ma,ia=deepcopy(module_aliases),deepcopy(instance_aliases)
            text=verilog; circuit=deepcopy(exported)
            if label=='module': ma[next(iter(ma))]='wrong'
            elif label=='instance': ia['top']['kernel']='wrong'
            elif label=='verilog': text+='// changed\n'
            else: circuit['modules']['top']['cells']['rk_mapped_cell_0']['connections']['inputs']=[2,2]
            with self.assertRaises(AssertionError): runner.verify_pair_export(design,ma,ia,text,circuit)

    def test_array_shell_registers_and_library_retained_exactly(self):
        array,board,candidate,kind=self.binding(); before=deepcopy(array)
        bound=runner.bind_array_kernel(array,board,candidate,kind)
        self.assertEqual(array,before)
        self.assertEqual(bound['modules'][runner.CMAC],array['modules'][runner.CMAC])
        for name in set(array['modules'])-{kind}:
            self.assertEqual(bound['modules'][name],array['modules'][name])
        self.assertEqual(bound['modules'][kind]['cells'],candidate['modules'][kind]['cells'])
        self.assertNotIn('netnames',bound['modules'][kind])

    def test_original_array_debug_aliases_preserved_without_new_hardware(self):
        array,board,candidate,kind=self.binding()
        array['modules'][kind]['netnames']={'original_debug':dict(bits=[77,78])}
        bound=runner.bind_array_kernel(array,board,candidate,kind)
        self.assertEqual(bound['modules'][kind]['netnames'],array['modules'][kind]['netnames'])

    def test_original_kernel_hardware_difference_rejected_not_normalized(self):
        for label in ('cell','wire','default','attribute','port'):
            array,board,candidate,kind=self.binding(); old=board['modules'][kind]
            if label=='cell': old['cells']['lut']['parameters']['INIT']='01'
            elif label=='wire': old['cells']['lut']['connections']['I0']=[70000]
            elif label=='default': old['parameter_default_values']={'ATOMIC_C':'00001000'}
            elif label=='attribute': old['attributes']['keep_hierarchy']='0'
            else: old['ports']['weight']['bits'].pop()
            with self.assertRaises(AssertionError): runner.bind_array_kernel(array,board,candidate,kind)

    def test_candidate_boundary_changed_rejected(self):
        for label in ('port','parameter','module_name','attribute'):
            array,board,candidate,kind=self.binding()
            if label=='port': candidate['modules'][kind]['ports']['result']['bits'].pop()
            elif label=='parameter': candidate['modules'][kind]['parameter_default_values']={'ATOMIC_C':'00001000'}
            elif label=='module_name': candidate['modules']['other']=candidate['modules'].pop(kind)
            else: candidate['modules'][kind]['attributes']['hdlname']='wrong'
            with self.assertRaises(AssertionError): runner.bind_array_kernel(array,board,candidate,kind)

    def test_all_full_bench_assertions_and_negative_golden_contract_retained(self):
        source=(ROOT/'tests/cmac/tb_cmac_fp16_array.sv').read_text()
        mapped=runner.mapped_bench(source)
        self.assertEqual(source.count('$fatal('),mapped.count('$fatal('))
        self.assertEqual(source.count('!=='),mapped.count('!=='))
        text='\n'.join(['12340']*208)+'\n'; negative=runner.negative_vectors(text)
        self.assertEqual(text.splitlines()[1:],negative.splitlines()[1:])
        self.assertEqual(int(text.splitlines()[0],16)^int(negative.splitlines()[0],16),1)
        self.assertIn('held result changed',mapped); self.assertIn('retirement',mapped)
        self.assertIn('reset ownership',mapped); self.assertIn('fault not sticky',mapped)


if __name__=='__main__': unittest.main()
