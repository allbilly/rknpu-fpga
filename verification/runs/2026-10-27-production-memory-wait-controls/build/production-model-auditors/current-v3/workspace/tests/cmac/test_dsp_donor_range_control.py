"""Admission controls, not actual donor/theorem/FPGA verification."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
import audit_lane_dsp_ranges as runner


def graph():
    ports={};offset=2
    for name,direction,width in [('op_a','input',16),('op_b','input',16),
            ('exp_sft','input',4),('pair_nz','input',1),
            ('res_a','output',32),('res_b','output',32),('res_tag','output',8)]:
        ports[name]=dict(direction=direction,bits=list(range(offset,offset+width)));offset+=width
    sign=[1000];cells={'sign':dict(type='$xor',connections={
        'A':ports['op_a']['bits'][15:],'B':ports['op_b']['bits'][15:],'Y':sign})}
    selected,inverted=[],[];codes=['0']+ports['op_a']['bits'][:15]+['0']
    for i in range(8):
        selected.append(list(range(2000+18*i,2017+18*i)));inverted.append(2017+18*i)
        cells[f'booth[{i}].recode']=dict(type='NV_NVDLA_CMAC_CORE_MAC_booth',parameters={},
            port_directions={'code':'input','is_8bit':'input','sign':'input',
                'src_data':'input','out_data':'output','out_inv':'output'},
            connections={'code':codes[2*i:2*i+3],'is_8bit':['0'],'sign':sign,
                'src_data':ports['op_b']['bits'][:15]+['0'],
                'out_data':selected[i],'out_inv':[inverted[i]]})
    modules={'tree5':dict(parameter_default_values={
        'num_inputs':format(5,'032b'),'input_width':format(24,'032b')}),
        'tree4':dict(parameter_default_values={
        'num_inputs':format(4,'032b'),'input_width':format(32,'032b')}),
        'NV_NVDLA_CMAC_CORE_MAC_booth':{}}
    # Actual module names are source-derived parameterized tree identifiers.
    modules={k.replace('tree','NV_DW02_tree'):v for k,v in modules.items()}
    rows={}
    for i,(name,offset,width) in enumerate([('low_tree',0,24),('high_tree',4,24),('final_tree',None,32)]):
        rows[name]=(list(range(3000+i*100,3000+i*100+width)),
            list(range(3040+i*100,3040+i*100+width)))
        if offset is not None:
            words=runner.packed_words(selected,inverted,offset);bits=[b for word in words for b in word]
        else:
            low_a,low_b=rows['low_tree'];high_a,high_b=rows['high_tree']
            bits=low_a+['0']*8+low_b+['0']*8+['0']*8+high_a+['0']*8+high_b
        cells[name]=dict(type='NV_DW02_tree5' if offset is not None else 'NV_DW02_tree4',
            port_directions={'INPUT':'input','OUT0':'output','OUT1':'output'},
            connections={'INPUT':bits,'OUT0':rows[name][0],'OUT1':rows[name][1]})
    modules[runner.TOP]=dict(ports=ports,cells=cells)
    return dict(modules=modules)


class DonorRangeControls(unittest.TestCase):
    def test_only_exact_source_bound_array_lowering_notices_are_admitted(self):
        donor=str(runner.DONORS[0])
        notice=f'Warning: Replacing memory \\temp_array with list of registers. See {donor}:41, {donor}:33'
        self.assertEqual(runner.audit_lowering_log(notice),[notice])
        for text in (notice.replace(':41',':40'),notice.replace('temp_array','other_array'),
                notice+'\nWarning: Unmodeled register',notice+'\nERROR: tool failure'):
            with self.subTest(text=text),self.assertRaises(AssertionError):runner.audit_lowering_log(text)

    def test_source_wiring_interval_bounds_and_integer_not_modular_sum(self):
        result=runner.validate_wiring(graph())
        self.assertEqual(result['free_binary_input_bits'],37)
        for group in result['groups'].values():
            self.assertEqual(group['input_word_upper_bounds'],[131071,524285,2097140,8388560,64])
            self.assertEqual(group['resulting_row_sum_upper_bound'],11141120)
            self.assertLess(group['resulting_row_sum_upper_bound'],1<<24)
        self.assertEqual(result['final_unsigned_row_sum_upper_bound'],2863267840)
        self.assertLess(result['final_unsigned_row_sum_upper_bound'],1<<32)

    def test_reject_padding_reordering_and_changed_final_shift(self):
        for name,index in [('low_tree',17),('high_tree',0),('final_tree',24),('final_tree',72)]:
            changed=graph();pins=changed['modules'][runner.TOP]['cells'][name]['connections']
            pins['INPUT'][index]=987654
            with self.subTest(name=name,index=index),self.assertRaises(AssertionError):runner.validate_wiring(changed)
        for value in ('1','x','z'):
            with self.subTest(value=value),self.assertRaises(AssertionError):runner.word_bound([0,value])

    def test_reject_changed_recoder_domain_free_bits_and_tree_shape(self):
        for mutation in ('code','source','mode','sign','inputs','shape','extra'):
            changed=graph();module=changed['modules'][runner.TOP]
            pins=module['cells']['booth[0].recode']['connections']
            if mutation=='code':pins['code'][0]=123456
            elif mutation=='source':pins['src_data'][-1]='1'
            elif mutation=='mode':pins['is_8bit']=['1']
            elif mutation=='sign':pins['sign']=[555555]
            elif mutation=='inputs':module['ports']['op_b']['bits'][0]=module['ports']['op_a']['bits'][0]
            elif mutation=='shape':changed['modules']['NV_DW02_tree5']['parameter_default_values']['input_width']=format(23,'032b')
            else:module['cells']['unexpected']=dict(type='$assume')
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):runner.validate_wiring(changed)

    def test_requires_both_completed_real_positive_and_negative_parent_lemmas(self):
        parent=dict(status='PASS_CONDITIONAL_DONOR_TREE_INTEGER_LEMMAS_ONLY',stage='complete',finished_utc='test-only',lemmas={},commands=[])
        parent['commands'].append(dict(log='version.log',status='PASS',returncode=0))
        for top,(inputs,width,conditional) in runner.lemmas.DOMAINS.items():
            parent['lemmas'][top]=dict(status='PASS_COMPONENT_ONLY',free_input_bits=sum(inputs.values()),
                compared_output_bits=width,conditional_on_no_unsigned_row_sum_overflow=conditional)
            for mode in ('negative','actual'):
                for stage in ('lowering','sat'):
                    parent['commands'].append(dict(log=top+'_'+mode+'_'+stage+'.log',status='PASS',
                        returncode=1 if (mode,stage)==('negative','sat') else 0))
        fields=('binary_lane_sum_equivalence','composed_lane_proof','donor_range_bound_proved',
            'multiply_distributivity_proved','full_array_numerical_acceptance',
            'raw_board_numerical_acceptance','physical_fit_verified','bitstream_emitted','hardware_programmed')
        parent.update({field:False for field in fields});runner.validate_parent(parent)
        for mutation in ('running','negative','missing','free_bits','overclaim'):
            changed=deepcopy(parent)
            if mutation=='running':changed['status']='RUNNING'
            elif mutation=='negative':changed['commands'][2]['returncode']=0
            elif mutation=='missing':changed['lemmas'].pop(next(iter(changed['lemmas'])))
            elif mutation=='free_bits':next(iter(changed['lemmas'].values()))['free_input_bits']=119
            else:changed['binary_lane_sum_equivalence']=True
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):runner.validate_parent(changed)


if __name__=='__main__':unittest.main()
