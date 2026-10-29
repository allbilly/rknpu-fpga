"""Prefix-array source, geometry and admission controls; no HDL numerical claim."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import dsp_prefix_array_contract as contract
import prepare_dsp_prefix_array as preparation
import test_dsp_prefix_array_native as runner


def design():
    ports = {}; bit = 2
    for name, (direction, width) in preparation.PORTS.items():
        ports[name] = dict(direction=direction, bits=list(range(bit, bit + width)))
        bit += width
    cell_type = '$paramod\\rk_cmac_fp16_cell_dsp_prefix\\ATOMIC_C=32'
    kernels = {}
    for k in range(16):
        kernels[f'kernels[{k}].cell_core'] = dict(type=cell_type, connections=dict(
            data=ports['in_data']['bits'][:], data_mask=ports['in_data_mask']['bits'][:],
            weight=ports['in_weight']['bits'][k*512:(k+1)*512],
            weight_mask=ports['in_weight_mask']['bits'][k*32:(k+1)*32],
            result=list(range(bit, bit + 44)), invalid=[bit + 44]))
        bit += 45
    kernel_ports = {name: dict(direction=direction, bits=list(range(width))) for name, direction, width in (
        ('data', 'input', 512), ('weight', 'input', 512), ('data_mask', 'input', 32),
        ('weight_mask', 'input', 32), ('result', 'output', 44), ('invalid', 'output', 1))}
    return dict(modules={preparation.TOP: dict(ports=ports, cells=kernels,
        parameter_default_values={'ATOMIC_C': '100000', 'ATOMIC_K': '10000', 'TAG_WIDTH': '100011'}),
        cell_type: dict(ports=kernel_ports, parameter_default_values={'ATOMIC_C': '100000'},
            cells={f'lanes[{i}].donor': dict(type=preparation.LANE) for i in range(32)}),
        preparation.LANE: dict(cells={})})


def leaf():
    labels = ['yosys_version', 'iverilog_version', 'vvp_version', 'datadir', 'export', 'roundtrip'] + [
        p+'_'+m+'_'+a for p in ('native', 'mapped') for m in ('negative', 'actual') for a in ('compile', 'test')]
    return dict(status='PASS_ISOLATED_ACTUAL_DSP_PREFIX_MAPPED_BINARY_FIXTURES_ONLY', stage='complete',
        isolated_mapped_binary_fixture_acceptance=True, relevant_binary_input_bits=37, compared_binary_output_bits=40,
        expected_comparisons_per_phase=135680, export_circuit_identity='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE',
        mapped_cells={'DSP48E1': 1, 'LUT6': 1}, source_bound_native_binary_lane_equivalence=True,
        four_state_leaf_acceptance=False,
        seed='0x3588d501; original 144 directed plus 4096 random operand pairs, all 16 shifts and both masks',
        results={'native_actual_test': runner.MARKER, 'mapped_actual_test': runner.MARKER},
        commands=[dict(log=n+'.log', status='PASS', returncode=1 if n.endswith('negative_test') else 0) for n in labels],
        **{n: False for n in ('binary_lane_sum_equivalence', 'full_array_numerical_acceptance',
            'raw_board_numerical_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


def prepared():
    return dict(status='PREPARED_FULL_C32K16_DSP_PREFIX_NATIVE_HIERARCHY_ONLY', stage='complete',
        native_hierarchy_prepared=True, channels=32, kernels=16, parallel_products=512,
        geometry=preparation.validate_geometry(design()), commands=[dict(log=n+'.log', status='PASS', returncode=0)
            for n in ('yosys_version', 'native_hierarchy')], **{n: False for n in ('numerical_acceptance',
        'four_state_acceptance', 'mapped_numerical_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


class PrefixArrayControls(unittest.TestCase):
    def test_exact_cell_array_and_bench_derivation_keep_original_assertions(self):
        contract.validate_sources()
        self.assertEqual(contract.CELL.read_text(), contract.expected_cell(contract.original.DSP_CELL.read_text()))
        self.assertEqual(contract.ARRAY.read_text(), contract.expected_array(contract.original.DSP_ARRAY.read_text()))
        old = contract.original.array_bench(contract.original.BENCH.read_text())
        new = contract.array_bench(contract.original.BENCH.read_text())
        self.assertEqual(new.replace('rk_cmac_fp16_array_dsp_prefix #', 'rk_cmac_fp16_array_dsp #'), old)
        for function, text in ((contract.expected_cell, contract.original.DSP_CELL.read_text()),
                (contract.expected_array, contract.original.DSP_ARRAY.read_text()),
                (contract.array_bench, contract.original.BENCH.read_text())):
            for bad in ('', text+text):
                with self.subTest(function=function.__name__), self.assertRaises(AssertionError): function(bad)

    def test_full_512_geometry_and_real_kernel_wiring_are_required(self):
        good = design(); self.assertEqual(preparation.validate_geometry(good)['parallel_products'], 512)
        for change in ('kernel', 'lane', 'c', 'k', 'tag', 'input_alias', 'input_constant', 'weight', 'mask',
                'data', 'result_alias', 'invalid_alias', 'fallback'):
            bad = deepcopy(good); top = bad['modules'][preparation.TOP]; cells = top['cells']
            kernel = bad['modules'][cells['kernels[0].cell_core']['type']]
            if change == 'kernel': cells.pop('kernels[15].cell_core')
            elif change == 'lane': kernel['cells'].pop('lanes[31].donor')
            elif change in ('c', 'k', 'tag'): top['parameter_default_values'][{'c':'ATOMIC_C','k':'ATOMIC_K','tag':'TAG_WIDTH'}[change]] = '1'
            elif change == 'input_alias': top['ports']['in_data']['bits'][1] = top['ports']['in_data']['bits'][0]
            elif change == 'input_constant': top['ports']['in_data']['bits'][0] = '0'
            elif change == 'weight': cells['kernels[1].cell_core']['connections']['weight'] = cells['kernels[0].cell_core']['connections']['weight'][:]
            elif change == 'mask': cells['kernels[1].cell_core']['connections']['weight_mask'] = cells['kernels[0].cell_core']['connections']['weight_mask'][:]
            elif change == 'data': cells['kernels[1].cell_core']['connections']['data'] = list(reversed(top['ports']['in_data']['bits']))
            elif change == 'result_alias': cells['kernels[1].cell_core']['connections']['result'] = cells['kernels[0].cell_core']['connections']['result'][:]
            elif change == 'invalid_alias': cells['kernels[1].cell_core']['connections']['invalid'] = cells['kernels[0].cell_core']['connections']['invalid'][:]
            else: bad['modules']['rk_cmac_fp16_lane_dsp'] = dict(cells={})
            with self.subTest(change=change), self.assertRaises(AssertionError): preparation.validate_geometry(bad)

    def test_native_warning_audit_is_exact_not_a_general_waiver(self):
        donor = contract.leaf.lane.SOURCES[0]
        notices = [f'Warning: Replacing memory \\temp_array with list of registers. See {donor}:41, {donor}:33',
            f'Warning: Replacing memory \\input_array with list of registers. See {donor}:33, {donor}:28']
        good = '\n'.join(notices*3); preparation.native_diagnostics(good)
        for bad in (good+'\n'+notices[0], '\n'.join(notices*2), good.replace(':41', ':42'),
            good+'\nWarning: unknown', good+'\nERROR: failed', good+'\nsorry: unimplemented'):
            with self.subTest(bad=bad[-60:]), self.assertRaises(AssertionError): preparation.native_diagnostics(bad)

    def test_only_this_completed_mapped_prefix_leaf_is_admitted(self):
        good = leaf(); runner.validate_leaf_metadata(good)
        for field, value in (('status', 'RUNNING'), ('status', 'PASS_ISOLATED_ACTUAL_DSP_MAPPED_BINARY_FIXTURES_ONLY'),
            ('stage', 'mapped'), ('source_bound_native_binary_lane_equivalence', False), ('four_state_leaf_acceptance', True),
            ('expected_comparisons_per_phase', 1), ('seed', '0x1'), ('physical_fit_verified', True)):
            bad = deepcopy(good); bad[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_leaf_metadata(bad)
        for mutation in ('state', 'dsp', 'luts', 'negative', 'missing'):
            bad = deepcopy(good)
            if mutation == 'state': bad['mapped_cells']['FDCE'] = 1
            elif mutation == 'dsp': bad['mapped_cells']['DSP48E1'] = 0
            elif mutation == 'luts': bad['mapped_cells']['LUT6'] = 0
            elif mutation == 'negative': bad['commands'][7]['returncode'] = 0
            else: bad['commands'].pop()
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.validate_leaf_metadata(bad)

    def test_only_completed_preparation_without_numerical_or_physical_claims_is_admitted(self):
        good = prepared(); runner.validate_prepared_metadata(good)
        for field, value in (('status', 'RUNNING'), ('stage', 'hierarchy'), ('native_hierarchy_prepared', False),
            ('channels', 8), ('kernels', 1), ('parallel_products', 32), ('numerical_acceptance', True),
            ('four_state_acceptance', True), ('mapped_numerical_acceptance', True), ('physical_fit_verified', True),
            ('bitstream_emitted', True), ('hardware_programmed', True)):
            bad = deepcopy(good); bad[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_prepared_metadata(bad)
        for mutation in ('missing', 'status', 'code'):
            bad = deepcopy(good)
            if mutation == 'missing': bad['commands'].pop()
            elif mutation == 'status': bad['commands'][1]['status'] = 'RUNNING'
            else: bad['commands'][1]['returncode'] = 1
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.validate_prepared_metadata(bad)

    def test_full_native_corpus_marker_and_real_first_frame_negative_remain_required(self):
        self.assertEqual(runner.validate_result(runner.EXPECTED, 0), runner.EXPECTED)
        runner.validate_result('FATAL: sized array mismatch frame=0 got=0', 1, True)
        for text, code, negative in ((runner.EXPECTED.replace('faults=1','faults=0'),0,False),
            (runner.EXPECTED.replace('3328','16'),0,False), (runner.EXPECTED.replace('held_cycles=520','held_cycles=0'),0,False),
            (runner.EXPECTED,1,False), ('missing vectors',1,True), ('sized array mismatch frame=1',1,True),
            ('sized array mismatch frame=0',2,True)):
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.validate_result(text,code,negative)
        vectors = dict(status='PASS_SIZED_CMAC_VECTOR_GENERATION',channels=32,kernels=16,frames=208,outputs=3328,
            seed='0x35883216',categories={'uniform_edges':16,'one_channel':32,'random_bits':64,'random_finite':64,'masked_edges':32})
        runner.validate_vectors(vectors)
        for field in ('channels','kernels','frames','outputs','seed','categories'):
            bad = deepcopy(vectors); bad[field] = {} if field == 'categories' else 1
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_vectors(bad)


if __name__ == '__main__': unittest.main()
