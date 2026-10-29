"""Synthetic harness/shape safety tests, not a mapped numerical or FPGA pass."""
from copy import deepcopy
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/cmac'))
import test_fixed_mapped_array as runner


def fixture():
    kernel = runner.KERNEL+'_actual'
    next_bit = 2

    def ports(shapes):
        nonlocal next_bit
        value = {}
        for name, direction, width in shapes:
            value[name] = dict(direction=direction, bits=list(range(next_bit, next_bit+width)))
            next_bit += width
        return value

    array_ports = ports([('clk','input',1),('rst_n','input',1),('in_valid','input',1),
        ('in_ready','output',1),('in_data','input',512),('in_weight','input',8192),
        ('in_data_mask','input',32),('in_weight_mask','input',512),('in_tag','input',35),
        ('out_valid','output',1),('out_ready','input',1),('out_groups','output',704),
        ('out_tag','output',35),('error','output',1)])
    kernel_ports = ports([('data','input',512),('weight','input',512),
        ('data_mask','input',32),('weight_mask','input',32),('result','output',44),
        ('invalid','output',1)])
    return dict(modules={runner.CMAC:dict(ports=array_ports,
        parameter_default_values={name:format(value,'032b') for name,value in
                                  [('ATOMIC_C',32),('ATOMIC_K',16),('TAG_WIDTH',35)]},
        cells={str(i):dict(type=kernel,parameters={},connections={'data':[i+2]}) for i in range(16)}),
        kernel:dict(ports=kernel_ports,attributes={'hdlname':runner.KERNEL,'keep_hierarchy':'1'},
                    cells={'lut':dict(type='LUT1',parameters={'INIT':'10'},connections={
                        'I0':[kernel_ports['data']['bits'][0]],'O':[kernel_ports['result']['bits'][0]]})}),
        'LUT1':dict(attributes={'blackbox':'1'},cells={}),
        'FDCE':dict(attributes={'blackbox':'1'},cells={})})


class FixedMappedArrayControls(unittest.TestCase):
    def test_only_module_alias_changes(self):
        original = fixture(); before = deepcopy(original)
        result, counts = runner.simulation_partition(original)
        self.assertEqual(original, before)
        self.assertEqual(counts, {'LUT1':1})
        self.assertEqual(set(result['modules']), {runner.CMAC,runner.SIM_KERNEL})
        self.assertEqual(result['modules'][runner.SIM_KERNEL], before['modules'][runner.KERNEL+'_actual'])
        self.assertEqual([c['connections'] for c in result['modules'][runner.CMAC]['cells'].values()],
                         [c['connections'] for c in before['modules'][runner.CMAC]['cells'].values()])
        self.assertEqual(sum(c['type']==runner.SIM_KERNEL for c in result['modules'][runner.CMAC]['cells'].values()),16)

    def test_wrong_geometry_or_kernel_count_rejected(self):
        for label in ('channels','kernels','tag','instance'):
            with self.subTest(label=label):
                design = fixture(); top = design['modules'][runner.CMAC]
                if label == 'instance': top['cells'].pop('15')
                else:
                    key = {'channels':'ATOMIC_C','kernels':'ATOMIC_K','tag':'TAG_WIDTH'}[label]
                    top['parameter_default_values'][key] = format(8,'032b')
                with self.assertRaises(AssertionError): runner.simulation_partition(design)

    def test_truncated_ports_or_constant_output_rejected(self):
        for label in ('result','out_groups','out_tag','constant'):
            with self.subTest(label=label):
                design = fixture()
                if label == 'result': design['modules'][runner.KERNEL+'_actual']['ports'][label]['bits'].pop()
                elif label == 'constant': design['modules'][runner.CMAC]['ports']['out_tag']['bits'][0]='0'
                else: design['modules'][runner.CMAC]['ports'][label]['bits'].pop()
                with self.assertRaises(AssertionError): runner.simulation_partition(design)

    def test_stateful_or_unknown_kernel_rejected(self):
        for kind in ('FDCE','arithmetic_stub'):
            with self.subTest(kind=kind):
                design = fixture()
                design['modules'][runner.KERNEL+'_actual']['cells']['unexpected'] = dict(type=kind)
                with self.assertRaises(AssertionError): runner.simulation_partition(design)

    def test_full_original_bench_assertions_retained(self):
        original = (ROOT/'tests/cmac/tb_cmac_fp16_array.sv').read_text()
        result = runner.mapped_bench(original)
        self.assertEqual(result.count('$fatal('), original.count('$fatal('))
        self.assertEqual(result.count('!=='), original.count('!=='))
        for marker in ('held result changed','configuration warmup','retirement',
                       'reset ownership','unknown input accepted','fault not sticky','count*ATOMIC_K'):
            self.assertIn(marker,result)
        self.assertIn('`ifndef VERILATOR',result)
        self.assertIn('for(integer i=0;i<count;i=i+1)',result)
        with self.assertRaises(AssertionError): runner.mapped_bench(original.replace(' dut(.*);',' broken(.*);'))

    def test_negative_sanity_changes_only_one_golden_bit(self):
        original = '\n'.join(['12340']*208)+'\n'
        result = runner.negative_vectors(original)
        a,b = original.splitlines(), result.splitlines()
        self.assertEqual(a[1:],b[1:])
        self.assertEqual(int(a[0],16)^int(b[0],16),1)
        with self.assertRaises(AssertionError): runner.negative_vectors('\n'.join(a[:207])+'\n')

    def test_structural_export_omits_only_debug_aliases(self):
        design,_ = runner.simulation_partition(fixture())
        source = runner.structural_verilog(design)
        self.assertIn('module \\'+runner.CMAC+' ',source)
        self.assertIn(".\\INIT (2'b10)",source)
        self.assertIn("parameter \\ATOMIC_C = 32'b00000000000000000000000000100000",source)
        self.assertEqual(len(re.findall(r'\\'+runner.SIM_KERNEL+r'\s+\\',source)),16)
        altered = deepcopy(design)
        altered['modules'][runner.SIM_KERNEL]['netnames'] = {'debug':dict(bits=[999999])}
        self.assertEqual(source,runner.structural_verilog(altered))
        self.assertEqual(runner.circuit_signature(design),runner.circuit_signature(altered))

    def test_circuit_signature_is_numbering_independent(self):
        design,_ = runner.simulation_partition(fixture()); altered = deepcopy(design)
        for module in altered['modules'].values():
            for port in module['ports'].values(): port['bits'] = [b+100000 for b in port['bits']]
            for cell in module['cells'].values():
                for pin,bits in cell['connections'].items(): cell['connections'][pin]=[b+100000 for b in bits]
        self.assertEqual(runner.circuit_signature(design),runner.circuit_signature(altered))

    def test_scopeinfo_is_debug_metadata_not_hardware(self):
        design,_ = runner.simulation_partition(fixture()); altered = deepcopy(design)
        altered['modules'][runner.SIM_KERNEL]['cells']['scope'] = dict(type='$scopeinfo',
            parameters={'CELL_NAME':'debug only'},connections={})
        self.assertEqual(runner.structural_verilog(design),runner.structural_verilog(altered))
        self.assertEqual(runner.circuit_signature(design),runner.circuit_signature(altered))
        altered['modules'][runner.SIM_KERNEL]['cells']['scope']['type']='arithmetic_stub'
        self.assertTrue(runner.circuit_signature(design)!=runner.circuit_signature(altered))

    def test_instance_aliasing_is_bijective_even_for_distinct_rtlil_names(self):
        design,_ = runner.simulation_partition(fixture())
        kernel = design['modules'][runner.SIM_KERNEL]
        kernel['cells']['$private'] = deepcopy(kernel['cells']['lut'])
        kernel['cells']['\\$private'] = deepcopy(kernel['cells']['lut'])
        original = deepcopy(design)
        result,maps = runner.hardware_instance_aliases(design)
        self.assertEqual(design,original)
        self.assertNotEqual(maps[runner.SIM_KERNEL]['$private'],maps[runner.SIM_KERNEL]['\\$private'])
        for module,mapping in maps.items():
            self.assertEqual(len(mapping),len(set(mapping.values())))
            for name,alias in mapping.items():
                self.assertEqual(original['modules'][module]['cells'][name],result['modules'][module]['cells'][alias])
                self.assertRegex(alias,r'^rk_mapped_cell_[0-9]+$')

    def test_mapped_constant_output_preserved_but_input_not_constrained(self):
        design,_ = runner.simulation_partition(fixture())
        design['modules'][runner.SIM_KERNEL]['ports']['invalid']['bits']=['0']
        self.assertIn("assign \\invalid  = 1'b0;",runner.structural_verilog(design))
        signature = runner.circuit_signature(design)
        design['modules'][runner.SIM_KERNEL]['ports']['invalid']['bits']=['1']
        self.assertTrue(signature!=runner.circuit_signature(design))
        design['modules'][runner.SIM_KERNEL]['ports']['data']['bits'][0]='0'
        with self.assertRaises(AssertionError): runner.structural_verilog(design)

    def test_circuit_signature_detects_wiring_truth_table_and_dropped_cells(self):
        design,_ = runner.simulation_partition(fixture()); expected = runner.circuit_signature(design)
        for kind in ('wire','parameter','type','drop','constant','port','default'):
            with self.subTest(kind=kind):
                altered = deepcopy(design); kernel = altered['modules'][runner.SIM_KERNEL]
                if kind=='wire': kernel['cells']['lut']['connections']['I0']=[700000]
                elif kind=='parameter': kernel['cells']['lut']['parameters']['INIT']='01'
                elif kind=='type': kernel['cells']['lut']['type']='LUT2'
                elif kind=='drop': kernel['cells'].pop('lut')
                elif kind=='constant': kernel['cells']['lut']['connections']['I0']=['0']
                elif kind=='port': kernel['ports']['result']['bits'].pop()
                else: altered['modules'][runner.CMAC]['parameter_default_values']['ATOMIC_C']='00001000'
                self.assertTrue(expected != runner.circuit_signature(altered), 'Missed circuit mutation: '+kind)

    def test_export_rejects_nonliteral_parameters(self):
        design,_ = runner.simulation_partition(fixture())
        design['modules'][runner.SIM_KERNEL]['cells']['lut']['parameters']['INIT']='arithmetic expression'
        with self.assertRaises(AssertionError): runner.structural_verilog(design)

    def test_counterexample_requires_real_first_frame_failure(self):
        runner.validate_counterexample(-6,'sized array mismatch frame=0 got=1 expected=0')
        for code, text in [(0,'sized array mismatch frame=0'),(1,'missing vectors'),
                           (1,'sized array mismatch frame=2'),(1,'sized array mismatch frame=01'),
                           (1,'sized array mismatch frame=0\nPASS fake')]:
            with self.subTest(code=code,text=text):
                with self.assertRaises(AssertionError): runner.validate_counterexample(code,text)

    def test_result_requires_full_corpus_and_hold_reset_counts(self):
        result = runner.NATIVE_RESULT.replace('PASS sized FP16 CMAC','PASS binary mapped fixed FP16 CMAC')
        self.assertEqual(runner.validate_result(result+'\n'),result)
        for before,after in [('frames=208','frames=32'),('checked_outputs=3328','checked_outputs=512'),
                             ('held_cycles=520','held_cycles=519'),('reset_canceled=16','reset_canceled=0'),
                             ('faults=0','faults=1')]:
            with self.subTest(before=before):
                with self.assertRaises(AssertionError): runner.validate_result(result.replace(before,after))


if __name__ == '__main__':
    unittest.main()
