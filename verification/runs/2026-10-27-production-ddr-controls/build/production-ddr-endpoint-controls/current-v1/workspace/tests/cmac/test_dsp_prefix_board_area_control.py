"""Mock structural/admission controls only, not synthesis or board acceptance."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import map_dsp_prefix_board as runner
from test_dsp_prefix_board_replay_control import marker, commands


def area_report():
    return dict(status='PASS_FULL_C32K16_DSP_PREFIX_ARRAY_XC7_AREA_ONLY', stage='complete',
        finished_utc='CONTROL_ONLY_NOT_EXECUTED', channels=32, kernels=16, parallel_products=512,
        instantiated_lanes=512, mapped_kernel_instances=16, dsp_count=512,
        intended_part='xc7k480tffg1156-2', target_family='xc7', cells={'DSP48E1': 512, 'LUT1': 640, 'FDCE': 742},
        lut_count=640, ff_count=742, original_coarse_stage=runner.array.COARSE,
        executed_coarse_stage=[s.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for s in runner.array.COARSE if s != 'share'],
        commands=commands(('version', 'help', 'mapping')),
        source_bound_array_mapping_diagnostics=dict(abc_notice=runner.array.ABC_NOTICE,
            abc_combinational_cuts=[dict(module=n, gates=12, wires=20, inputs=4, outputs=5)
                for n in runner.array.ABC_MODULES]),
        **{n: False for n in ('numerical_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


def board_report():
    return dict(status='PASS_FULL_C32K16_DSP_PREFIX_RAW_BOARD_FOUR_STATE_FIXTURES_ONLY', stage='complete',
        finished_utc='CONTROL_ONLY_NOT_EXECUTED', channels=32, kernels=16, parallel_products=512,
        modes=list(range(9)), four_state_mode_not_run=None, inherited_compile_only=True,
        native_array_fixture_acceptance=True, source_bound_composed_lane_acceptance=True,
        raw_board_numerical_acceptance=True,
        compiled_hierarchy={'rk_cmac_fp16_array_dsp_prefix': 1, 'rk_cmac_fp16_cell_dsp_prefix': 16,
            'rk_cmac_fp16_lane_dsp_prefix': 512, 'rk_cmac_fp16_discarded_carry': 512},
        prefix_composition_certificate=dict(kind='BINARY_SOURCE_BOUND_DONOR_TO_COMPENSATED_TO_PREFIX_TRANSITIVITY',
            relevant_binary_input_bits=37, compared_binary_output_bits=40, comparator_free_binary_inputs=67,
            **{n: False for n in ('new_positive_monolithic_sat_proof', 'all_x_equivalence',
                'full_array_numerical_acceptance', 'raw_board_numerical_acceptance',
                'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')}),
        commands=commands(('rom_check', 'iverilog_version', 'vvp_version', *(f'mode_{m}' for m in range(9)))),
        tests=[dict(mode=m, status='PASS', result=marker(m)) for m in range(9)],
        **{n: False for n in runner.replay.UNPROVEN})


def fixture():
    kernel = 'CONTROL_' + runner.KERNEL
    ports = {}; bit = 100
    for direction, widths in (('input', runner.array.INPUTS), ('output', runner.array.OUTPUTS)):
        for name, width in widths.items():
            ports[name] = dict(direction=direction, bits=list(range(bit, bit + width))); bit += width
    kernel_ports = {}; bit = 10000
    for name, direction, width in (('data', 'input', 512), ('weight', 'input', 512),
        ('data_mask', 'input', 32), ('weight_mask', 'input', 32),
        ('result', 'output', 44), ('invalid', 'output', 1)):
        kernel_ports[name] = dict(direction=direction, bits=list(range(bit, bit + width))); bit += width
    cell = dict(attributes={'hdlname': runner.KERNEL, 'keep_hierarchy': '1'},
        parameter_default_values={'ATOMIC_C': f'{32:032b}'}, ports=kernel_ports,
        cells={f'dsp{i}': dict(type='DSP48E1', parameters={'AREG': '0', 'USE_MULT': 'MULTIPLY'},
            connections={'A': kernel_ports['data']['bits'][:30], 'B': kernel_ports['weight']['bits'][:18],
                'P': kernel_ports['result']['bits'] + [kernel_ports['invalid']['bits'][0]] * 4},
            port_directions={'A': 'input', 'B': 'input', 'P': 'output'}) for i in range(32)})
    array = dict(ports=ports, parameter_default_values={n: f'{v:032b}' for n, v in
        (('ATOMIC_C', 32), ('ATOMIC_K', 16), ('TAG_WIDTH', 35))},
        cells={f'kernel{i}': dict(type=kernel, parameters={}, connections={}) for i in range(16)})
    design = dict(modules={runner.CMAC: array, kernel: cell,
        'DSP48E1': dict(attributes={'blackbox': '1'}, cells={})})
    top = 'ypcb_cmac_array_top'
    board = deepcopy(design)
    board['modules'][top] = dict(ports={'SYS_CLK': dict(direction='input', bits=[10]),
        'SYS_RSTN': dict(direction='input', bits=[11]), 'led_3bits_tri_o': dict(direction='output', bits=[12, 13, 14])},
        cells={**deepcopy(array['cells']), 'ram': dict(type='RAMB36E1', parameters={}, connections={})})
    board['modules']['RAMB36E1'] = dict(attributes={'blackbox': '1'}, cells={})
    return design, board, top, kernel, cell



def frontend_notices():
    donor = runner.array.SOURCES[0]
    return ('Warning: Replacing memory \\temp_array with list of registers. See '
        f'{donor}:41, {donor}:33\n'
        'Warning: Replacing memory \\input_array with list of registers. See '
        f'{donor}:33, {donor}:28\n'
        'Warning: Replacing memory \\regs with list of registers. See ' +
        str(ROOT / 'rtl/rk_cmac_profile.sv') + ':154\n')


class DspPrefixBoardAreaControls(unittest.TestCase):
    def test_completed_full_array_mapping_and_corrected_stage_contract_required(self):
        original = area_report(); runner.validate_area_metadata(original)
        for field, value in [('status', 'RUNNING'), ('stage', 'mapping'), ('dsp_count', 0),
            ('parallel_products', 32), ('instantiated_lanes', 511), ('mapped_kernel_instances', 1),
            ('intended_part', 'xc7k325tffg900-2'), ('numerical_acceptance', True),
            ('lut_count', 1), ('ff_count', 1), ('executed_coarse_stage', ['share'])]:
            bad = deepcopy(original); bad[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_area_metadata(bad)
        bad = deepcopy(original); bad['commands'][-1]['returncode'] = 1
        with self.assertRaises(AssertionError): runner.validate_area_metadata(bad)

    def test_all_actual_four_state_board_modes_and_native_composed_gates_required(self):
        original = board_report(); runner.validate_board_metadata(original)
        for field, value in [('status', 'RUNNING'), ('parallel_products', 1), ('modes', list(range(8))),
            ('four_state_mode_not_run', 7), ('native_array_fixture_acceptance', False),
            ('source_bound_composed_lane_acceptance', False), ('raw_board_numerical_acceptance', False),
            ('physical_fit_verified', True), ('bitstream_emitted', True)]:
            bad = deepcopy(original); bad[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_board_metadata(bad)
        bad = deepcopy(original); bad['tests'] = [t for t in bad['tests'] if t['mode'] != 7]
        with self.assertRaises(AssertionError): runner.validate_board_metadata(bad)

    def test_actual_partition_copied_without_libraries_or_arithmetic_replacement(self):
        design, _, _, kernel, _ = fixture()
        value, got, counts = runner.partition(design)
        self.assertEqual(got, kernel); self.assertEqual(counts['DSP48E1'], 32)
        self.assertEqual(set(value['modules']), {runner.CMAC, kernel})
        self.assertIs(value['modules'][kernel], design['modules'][kernel])
        self.assertIs(value['modules'][runner.CMAC], design['modules'][runner.CMAC])
        for kind in ('geometry', 'count', 'dsp'):
            bad = deepcopy(design)
            if kind == 'geometry': bad['modules'][runner.CMAC]['parameter_default_values']['TAG_WIDTH'] = f'{34:032b}'
            elif kind == 'count': bad['modules'][runner.CMAC]['cells'].pop('kernel15')
            else: bad['modules'][kernel]['cells'].pop('dsp31')
            with self.subTest(kind=kind), self.assertRaises(AssertionError): runner.partition(bad)

    def test_parameter_wrapper_is_literal_header_guard_and_wire_delegate_only(self):
        design, _, _, _, _ = fixture(); part, _, _ = runner.partition(design)
        source = runner.array.DSP_ARRAY.read_text(); bound, shim = runner.parameter_binding(part, source)
        self.assertEqual(bound['modules'][runner.MAPPED_CMAC], part['modules'][runner.CMAC])
        self.assertIn('ATOMIC_C!=32 || ATOMIC_K!=16 || TAG_WIDTH!=35', shim)
        self.assertEqual(shim.count('actual_partition(.*)'), 1)
        self.assertNotIn('always', shim); self.assertNotIn('output logic', shim)
        for bad in (source + source, source.replace('wire [ATOMIC_K*44-1:0] groups;', 'wire [ATOMIC_K*32-1:0] groups;')):
            with self.assertRaises(AssertionError): runner.parameter_binding(part, bad)

    def test_identity_accepts_wire_renumbering_but_not_pin_or_primitive_changes(self):
        _, _, _, kernel, cell = fixture()
        original = runner.kernel_identity(cell, kernel)
        renumbered = deepcopy(cell)
        renumbered['ports']['data']['bits'][0] = 999
        for c in renumbered['cells'].values(): c['connections']['A'][0] = 999
        self.assertEqual(runner.kernel_identity(renumbered, kernel), original)
        for change in ('pin', 'parameter', 'primitive', 'cell'):
            bad = deepcopy(cell)
            if change == 'pin': bad['cells']['dsp0']['connections']['A'] = ['0']
            elif change == 'parameter': bad['cells']['dsp0']['parameters']['AREG'] = '1'
            elif change == 'primitive': bad['cells']['dsp0']['type'] = 'LUT1'
            else: bad['cells'].pop('dsp0')
            self.assertNotEqual(runner.kernel_identity(bad, kernel), original)

    def test_full_board_requires_16_unchanged_kernels_bram_and_nonconstant_io(self):
        _, board, top, kernel, cell = fixture(); counts = Counter(DSP48E1=32)
        total, shell, _ = runner.validate_mapped(board, top, kernel, cell, counts)
        self.assertEqual(total['DSP48E1'], 512); self.assertEqual(shell['RAMB36E1'], 1)
        extra = deepcopy(board)
        extra['modules'][top]['cells']['shell_dsp'] = dict(type='DSP48E1', parameters={}, connections={})
        self.assertEqual(runner.validate_mapped(extra, top, kernel, cell, counts)[0]['DSP48E1'], 513)
        for change in ('kernel', 'bram', 'io', 'hardware', 'identity'):
            bad = deepcopy(board)
            if change == 'kernel': bad['modules'][top]['cells'].pop('kernel15')
            elif change == 'bram': bad['modules'][top]['cells'].pop('ram')
            elif change == 'io': bad['modules'][top]['ports']['led_3bits_tri_o']['bits'][0] = '0'
            elif change == 'hardware': bad['modules'][top]['cells']['ram']['type'] = '$mul'
            else: bad['modules'][kernel]['cells']['dsp0']['connections']['A'] = ['0']
            with self.subTest(change=change), self.assertRaises(AssertionError): runner.validate_mapped(bad, top, kernel, cell, counts)

    def test_mapping_executes_dsp_stage_before_coarse_and_retains_early_kernel_gate(self):
        spec = json.loads(runner.replay.preparation.SPEC.read_text())
        coarse = area_report()['executed_coarse_stage']
        text = runner.mapping_script(spec, [ROOT / 'CONTROL_ONLY.sv'], ROOT / 'CONTROL_ONLY.json', ROOT / 'build/CONTROL_ONLY', coarse)
        self.assertIn('-run begin:coarse', text); self.assertNotIn('begin:map_dsp', text)
        self.assertLess(text.index('-run begin:coarse'), text.index('select -assert-count 32'))
        self.assertLess(text.index('select -assert-count 32'), text.index('techmap -map +/cmp2lut'))
        self.assertIn('select -assert-count 16', text); self.assertNotIn(';\nshare;', text)
        with self.assertRaises(AssertionError): runner.mapping_script(spec, [], ROOT / 'CONTROL_ONLY', ROOT / 'build/CONTROL_ONLY', ['share'])

    def test_surrounding_synthesis_sources_are_original_with_only_join_and_partition_wrapper(self):
        spec = json.loads(runner.replay.preparation.SPEC.read_text())
        join, shim = ROOT / 'build/CONTROL_ONLY_JOIN.sv', ROOT / 'build/CONTROL_ONLY_SHIM.sv'
        actual = runner.synthesis_sources(spec, join, shim)
        expected = [ROOT / n for n in spec['synthesis'] if n not in {
            runner.replay.preparation.ORIGINAL_CELL, runner.replay.preparation.ORIGINAL_ARRAY, runner.replay.preparation.JOIN}]
        self.assertEqual(actual[:-1], [join if n == runner.replay.preparation.JOIN else ROOT / n
            for n in spec['synthesis'] if n not in {runner.replay.preparation.ORIGINAL_CELL, runner.replay.preparation.ORIGINAL_ARRAY}])
        self.assertEqual(set(actual) - set(expected), {join, shim})
        for path in (runner.array.DSP_CELL, runner.array.DSP_ARRAY, runner.array.FIXED_CELL, runner.array.FIXED_ARRAY):
            self.assertNotIn(path, actual)

    def test_full_prefix_kernel_ports_masks_and_combinational_body_are_required(self):
        for change in ('port', 'mask', 'sequential'):
            design, _, _, kernel, _ = fixture()
            if change == 'port': design['modules'][kernel]['ports']['result']['bits'].pop()
            elif change == 'mask': design['modules'][kernel]['ports']['data_mask']['direction'] = 'output'
            else:
                design['modules'][kernel]['cells']['ff'] = dict(type='FDCE', parameters={}, connections={})
                design['modules']['FDCE'] = dict(attributes={'blackbox': '1'}, cells={})
            with self.subTest(change=change), self.assertRaises(AssertionError): runner.partition(design)

    def test_composition_domain_cannot_claim_all_x_or_board_acceptance(self):
        original = board_report()
        for field, value in [('kind', 'OLD_DSP_ONLY'), ('relevant_binary_input_bits', 1),
            ('compared_binary_output_bits', 1), ('comparator_free_binary_inputs', 66),
            ('all_x_equivalence', True), ('full_array_numerical_acceptance', True),
            ('raw_board_numerical_acceptance', True), ('bitstream_emitted', True)]:
            bad = deepcopy(original); bad['prefix_composition_certificate'][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_board_metadata(bad)

    def test_frontend_requires_exact_donor_and_original_profile_register_lowering_notices(self):
        good = frontend_notices()
        self.assertEqual(sum(runner.frontend_diagnostics(good).values()), 3)
        for text in ('', good + good, good.replace(':41', ':42'), good + 'Warning: RAM width changed\n',
            good.replace(':154', ':155'), good.replace('\\regs', '\\different_regs'),
            good + 'ABC: Warning: altered result\n', good + 'ERROR: broken\n', good + 'sorry: unsupported\n'):
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.frontend_diagnostics(text)

    def test_full_mapping_requires_frozen_zero_cut_and_exact_completed_native_shell_cut(self):
        _, _, top, kernel, _ = fixture()
        good = frontend_notices() + ('Executing XILINX_DSP pass\n'
            f"21.13.1. Extracting gate netlist of module {chr(96)}{kernel}' to '<abc-temp-dir>/input.blif'..\n"
            'Extracted 0 gates and 0 wires to a netlist network with 0 inputs and 0 outputs.\n'
            "Don't call ABC as there is nothing to map.\n"
            f"21.13.2. Extracting gate netlist of module {chr(96)}\\{top}' to '<abc-temp-dir>/input.blif'..\n"
            'Extracted 12 gates and 20 wires to a netlist network with 4 inputs and 5 outputs.\n'
            + runner.array.ABC_CONTEXT + '\nABC: YOSYS_ABC_DONE \n'
            '21.13.2. Re-integrating ABC results.\n')
        result = runner.audit_board_mapping_log(good, top, kernel)
        self.assertEqual(result['frozen_kernel_abc_gates'], 0)
        self.assertEqual(result['shell_abc_network'], dict(gates=12, wires=20, inputs=4, outputs=5))
        for bad in (good + 'Warning: unknown\n', good + 'Executing SHARE pass\n',
            good.replace('YOSYS_ABC_DONE ', 'INCOMPLETE '), good.replace('dc2', 'dc2 -v'),
            good.replace('0 gates and 0 wires', '1 gates and 0 wires'),
            good.replace(top, 'wrong_shell'), good.replace(kernel, 'wrong_kernel'),
            good.replace(runner.array.ABC_NOTICE, ''), good.replace('4 inputs and 5 outputs', '0 inputs and 5 outputs')):
            with self.subTest(text=bad), self.assertRaises(AssertionError): runner.audit_board_mapping_log(bad, top, kernel)


if __name__ == '__main__': unittest.main()
