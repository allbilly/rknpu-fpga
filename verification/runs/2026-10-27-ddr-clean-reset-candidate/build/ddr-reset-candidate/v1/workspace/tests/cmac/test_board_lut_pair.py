"""Pairing safety controls and real small Icarus model tests, not board proof."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
import pair_board_luts as runner


def lut(kind,inputs,output,init):
    return dict(type=kind,parameters={'INIT':init},attributes={'keep':'1'},
        port_directions={**{'I'+str(i):'input' for i in range(len(inputs))},'O':'output'},
        connections={**{'I'+str(i):[v] for i,v in enumerate(inputs)},'O':[output]})


def fixture():
    definition=dict(attributes={'blackbox':'1'},ports={
        **{'I'+str(i):dict(direction='input',bits=[i+2]) for i in range(6)},
        'O5':dict(direction='output',bits=[8]),'O6':dict(direction='output',bits=[9])},cells={})
    return dict(modules={'top':dict(ports={'inputs':dict(direction='input',bits=[2,3]),
        'outputs':dict(direction='output',bits=[4,5])},
        cells={'a':lut('LUT2',[2,3],4,'0110'),'b':lut('LUT2',[3,2],5,'1000')},
        netnames={'output_alias':dict(bits=[4,5])}), 'LUT6_2':definition})


class BoardLutPairControls(unittest.TestCase):
    def candidate(self):
        original=fixture(); candidate,certificate,classes=runner.pair(original,{'top'})
        return original,candidate,certificate,classes

    def verify(self,original,candidate,certificate,classes):
        runner.verify(original,candidate,certificate,{json.dumps(c,sort_keys=True,separators=(',',':')):c for c in classes})

    def test_exact_reverse_expansion_and_no_original_mutation(self):
        original=fixture(); before=deepcopy(original)
        candidate,certificate,classes=runner.pair(original,{'top'})
        self.assertEqual(original,before)
        self.verify(original,candidate,certificate,classes)
        cell=candidate['modules']['top']['cells']['rk_lut_pair_0']
        self.assertEqual(cell['connections']['O5'],[4]); self.assertEqual(cell['connections']['O6'],[5])
        self.assertEqual(cell['connections']['I5'],['1'])
        self.assertEqual(len(classes),1)
        for x in range(4):
            self.assertEqual((int(cell['parameters']['INIT'],2)>>x)&1,(x&1)^((x>>1)&1))
            self.assertEqual((int(cell['parameters']['INIT'],2)>>(32+x))&1,(x&1)&((x>>1)&1))

    def test_permutations_and_constants_use_actual_pin_order(self):
        original=fixture(); original['modules']['top']['cells']['a']=lut('LUT3',['1',3,2],4,'01101001')
        original['modules']['top']['cells']['b']=lut('LUT3',[2,'0',3],5,'10010110')
        candidate,certificate,classes=runner.pair(original,{'top'})
        self.verify(original,candidate,certificate,classes)
        self.assertEqual(classes[0]['first']['pins'],['1',1,0])
        self.assertEqual(classes[0]['second']['pins'],[0,'0',1])

    def test_constant_only_luts_can_be_paired_without_free_input_claim(self):
        original=fixture(); cells=original['modules']['top']['cells']
        cells['a']=lut('LUT1',['0'],4,'10'); cells['b']=lut('LUT1',['1'],5,'10')
        candidate,certificate,classes=runner.pair(original,{'top'})
        self.assertEqual(classes[0]['fanins'],0)
        self.assertEqual(classes[0]['init'],'1'*32+'0'*32)
        self.verify(original,candidate,certificate,classes)

    def test_repeated_correlated_inputs_are_preserved_not_paired(self):
        original=fixture(); cells=original['modules']['top']['cells']
        cells['extra']=lut('LUT2',[2,2],6,'0110')
        candidate,certificate,classes=runner.pair(original,{'top'})
        self.assertEqual(candidate['modules']['top']['cells']['extra'],cells['extra'])
        self.assertEqual(certificate['top']['unpaired_repeated_wire_luts'],1)

    def test_bad_width_unknown_input_extra_pin_and_parameters_rejected(self):
        for label in ('init','unknown','pin','parameter','direction','output'):
            with self.subTest(label=label):
                original=fixture(); cell=original['modules']['top']['cells']['a']
                if label=='init': cell['parameters']['INIT']='010'
                elif label=='unknown': cell['connections']['I0']=['x']
                elif label=='pin': cell['connections']['OTHER']=[8]
                elif label=='parameter': cell['parameters']['OTHER']='0'
                elif label=='direction': cell['port_directions']['I0']='output'
                else: cell['connections']['O']=[2]
                with self.assertRaises(AssertionError): runner.pair(original,{'top'})

    def test_truth_tables_outputs_constants_added_hardware_and_metadata_mutations_rejected(self):
        for label in ('init','output','padding','i5','extra','metadata','primary'):
            with self.subTest(label=label):
                original,candidate,certificate,classes=self.candidate()
                module=candidate['modules']['top']; cell=module['cells']['rk_lut_pair_0']
                if label=='init': cell['parameters']['INIT']='1'*64
                elif label=='output': cell['connections']['O5']=[5]
                elif label=='padding': cell['connections']['I4']=['1']
                elif label=='i5': cell['connections']['I5']=['0']
                elif label=='extra': module['cells']['extra']=deepcopy(cell)
                elif label=='metadata': module['netnames']['output_alias']['bits']=[4,4]
                else: module['ports']['inputs']['bits']=[2,2]
                with self.assertRaises(AssertionError): self.verify(original,candidate,certificate,classes)

    def test_no_alias_collision_no_shared_outputs_and_definition_verified(self):
        for label in ('alias','outputs','definition'):
            original=fixture()
            if label=='alias': original['modules']['top']['cells']['rk_lut_pair_0']=lut('LUT1',[9],10,'10')
            elif label=='outputs': original['modules']['top']['cells']['b']['connections']['O']=[4]
            else: original['modules']['LUT6_2']['ports']['O5']['direction']='input'
            with self.assertRaises(AssertionError): runner.pair(original,{'top'})

    def test_every_pair_function_class_required(self):
        original,candidate,certificate,classes=self.candidate()
        with self.assertRaises(AssertionError): self.verify(original,candidate,certificate,[])
        certificate['top']['pairs'][0]['function_key']='wrong'
        with self.assertRaises(AssertionError): self.verify(original,candidate,certificate,classes)

    def test_correlated_input_certificate_count_checked(self):
        original,candidate,certificate,classes=self.candidate()
        certificate['top']['unpaired_repeated_wire_luts']=99
        with self.assertRaises(AssertionError): self.verify(original,candidate,certificate,classes)

    def module_fixture(self):
        design=fixture(); kind="$paramod\\rk_cmac_fp16_cell_fixed\\ATOMIC_C=32'00000000000000000000000000100000"
        design['modules'][kind]=design['modules'].pop('top')
        design['modules'].pop('LUT6_2')
        design['modules']['top']=dict(ports={'a':dict(direction='input',bits=[2,3]),
            'y':dict(direction='output',bits=[4,5])},cells={'kernel':dict(type=kind,
            parameters={},connections={'inputs':[2,3],'outputs':[4,5]})})
        return design,kind

    def test_module_alias_updates_every_reference_and_is_literal_bijection(self):
        design,kind=self.module_fixture(); before=deepcopy(design)
        aliased,mapping=runner.implementation_module_aliases(design)
        self.assertEqual(design,before)
        self.assertEqual(mapping,{kind:'rk_lut_pair_module_0'})
        self.assertEqual(aliased['modules']['rk_lut_pair_module_0'],design['modules'][kind])
        self.assertEqual(aliased['modules']['top']['cells']['kernel']['type'],'rk_lut_pair_module_0')
        self.assertEqual(set(aliased['modules']),{'top','rk_lut_pair_module_0'})
        clean,mapping=runner.implementation_module_aliases(fixture())
        self.assertEqual(clean,fixture()); self.assertEqual(mapping,{})

    def test_module_alias_collision_rejected(self):
        design,_=self.module_fixture()
        design['modules']['rk_lut_pair_module_0']=dict(ports={},cells={})
        with self.assertRaisesRegex(AssertionError,'Module alias collision'):
            runner.implementation_module_aliases(design)

    @unittest.skipUnless(shutil.which('yosys'), 'Real Yosys unavailable; no module-export pass claimed')
    def test_real_private_module_export_counterexample_and_exact_aliased_roundtrip(self):
        design,kind=self.module_fixture()
        with tempfile.TemporaryDirectory(prefix='rk_pair_module_',dir=ROOT/'build') as name:
            directory=Path(name)
            def exported(value,label):
                sv=directory/(label+'.v'); sv.write_text(runner.structural_board_verilog(value))
                result=directory/(label+'.json')
                command=['yosys','-Q','-T','-p','read_verilog -sv '+json.dumps(str(sv))+'; write_json '+json.dumps(str(result))]
                run=subprocess.run(command,text=True,capture_output=True,timeout=60)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                return json.loads(result.read_text())
            unaliased,_=runner.hardware_instance_aliases(design)
            broken=exported(unaliased,'unaliased')
            self.assertNotEqual(runner.circuit_signature(broken),runner.circuit_signature(unaliased))
            self.assertNotIn(kind,broken['modules']); self.assertIn('\\'+kind,broken['modules'])
            aliased,mapping=runner.implementation_module_aliases(design)
            hardware,_=runner.hardware_instance_aliases(aliased)
            actual=exported(hardware,'aliased')
            self.assertEqual(runner.circuit_signature(actual),runner.circuit_signature(hardware))
            for label in ('init','wire','type','reference'):
                changed=deepcopy(actual)
                if label=='reference': changed['modules']['top']['cells']['rk_mapped_cell_0']['type']='wrong'
                else:
                    cell=changed['modules'][mapping[kind]]['cells']['rk_mapped_cell_0']
                    if label=='init': cell['parameters']['INIT']='0000'
                    elif label=='wire': cell['connections']['I0']=[999]
                    else: cell['type']='LUT3'
                self.assertNotEqual(runner.circuit_signature(changed),runner.circuit_signature(hardware))

    def test_five_input_bench_covers_all_four_state_patterns(self):
        a=lut('LUT5',[2,3,4,5,6],7,'01'*16); b=lut('LUT5',[6,5,4,3,2],8,'0011'*8)
        fanins=[2,3,4,5,6]; cell=runner.paired_cell(a,b,fanins)
        function=dict(fanins=5,first=runner.spec(a,fanins),second=runner.spec(b,fanins),init=cell['parameters']['INIT'])
        text=runner.four_state_bench([function])
        self.assertIn('pattern<1024',text); self.assertIn('comparisons!=2048',text)
        self.assertIn("1'bx",text); self.assertIn("1'bz",text); self.assertIn(' !== ',text)
        self.assertEqual(text.count('$fatal('),3)
        self.assertNotEqual(text,runner.four_state_bench([function],True))

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('yosys-config'), 'HDL tools unavailable; no real model pass claimed')
    def test_real_icarus_unchanged_models_and_actual_negative_golden(self):
        _,_,_,classes=self.candidate()
        a=lut('LUT5',[2,3,4,5,6],7,'01'*16); b=lut('LUT5',[6,5,4,3,2],8,'0011'*8)
        fanins=[2,3,4,5,6]; cell=runner.paired_cell(a,b,fanins)
        classes.append(dict(fanins=5,first=runner.spec(a,fanins),second=runner.spec(b,fanins),init=cell['parameters']['INIT']))
        data=subprocess.run(['yosys-config','--datdir'],text=True,capture_output=True,check=True,timeout=60).stdout.strip()
        model=Path(data)/'xilinx/cells_sim.v'
        with tempfile.TemporaryDirectory(prefix='rk_lut_pair_',dir=ROOT/'build') as name:
            directory=Path(name)
            for negative in (False,True):
                bench=directory/'bench.sv'; bench.write_text(runner.four_state_bench(classes,negative))
                executable=directory/'test.vvp'
                compile=subprocess.run(['iverilog','-g2012','-s',runner.BENCH,'-o',str(executable),str(model),str(bench)],text=True,capture_output=True,timeout=60)
                self.assertEqual(compile.returncode,0,compile.stdout+compile.stderr)
                run=subprocess.run(['vvp',str(executable)],text=True,capture_output=True,timeout=60)
                if negative:
                    self.assertNotEqual(run.returncode,0); self.assertIn('LUT_PAIR_MISMATCH class=0 pattern=0',run.stdout)
                    self.assertNotIn('PASS ',run.stdout)
                else:
                    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                    self.assertIn('PASS LUT_PAIR_FOUR_STATE classes=2 comparisons=2080',run.stdout)


if __name__=='__main__': unittest.main()
