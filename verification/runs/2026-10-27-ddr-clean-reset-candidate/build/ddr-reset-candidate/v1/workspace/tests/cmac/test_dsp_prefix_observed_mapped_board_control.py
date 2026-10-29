"""DSP-profile replay fail-closed controls; these are not full HDL acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_dsp_prefix_observed_mapped_board as runner
import dsp_prefix_unisim_board_models as models


def mapping_report():
    return dict(status=runner.mapping.STATUS, stage='complete', finished_utc='test-fixture-only',
                channels=32, kernels=16, parallel_products=512, mapped_kernel_instances=16,
                retained_cmac_dsps=512, dsp_count=515, shell_cells={'DSP48E1': 3},
                reused_kernel_cells={'DSP48E1': 32}, cells={'RAMB36E1': 6},
                intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
                bindings={name: {} for name in runner.WIDTHS},
                imported_kernel_circuit_identity='PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE',
                original_four_bit_state_preserved=True, original_bench_unchanged=True,
                mapping_diagnostics_accepted=True, actual_ram_port_resizes=54,
                normalization_audit=[{} for _ in range(54)], logged_ram_port_resizes=32,
                commands=[dict(log=name + '.log', status='PASS_TOOL_EXECUTION_ONLY', returncode=0)
                          for name in ('version', 'help', 'datadir', 'mapping')],
                numerical_netlist_acceptance=False, physical_fit_verified=False,
                bitstream_emitted=False, hardware_programmed=False)


def carry_report():
    return dict(status='PASS_PINNED_UNISIM_CARRY_TRUTH_WITH_EXPLICIT_YOSYS_FOUR_STATE_DIFFERENCES_ONLY',
                stage='complete', finished_utc='test-fixture-only', upstream_model_commit=models.COMMIT,
                primitive_fixture_acceptance=True, default_global_startup_preserved=True,
                result=dict(binary_comparisons=1024, four_state_comparisons=1048576,
                            yosys_four_state_differences=415001, first_difference=3,
                            binary_yosys_vendor_equivalence=True, four_state_yosys_vendor_equivalence=False),
                commands=[dict(log=name + '.log', status='PASS', returncode=int(name == 'negative_test'))
                          for name in ('model_commit', 'model_clean', 'version', 'runtime_version',
                                       'compile', 'negative_test', 'positive_test')],
                numerical_netlist_acceptance=False, physical_fit_verified=False,
                bitstream_emitted=False, hardware_programmed=False)


def dsp_fixture():
    primitive = models.primitive
    dsp = dict(type='DSP48E1', parameters={key: format(value, '032b') if type(value) is int else value
                                         for key, value in primitive.PARAMETERS.items()},
               connections={pin: list(reversed(f'{value:0{width}b}'))
                            for pin, (width, value) in primitive.CONSTANTS.items()},
               port_directions={pin: 'input' for pin in primitive.CONSTANTS})
    offset = 2
    for pin, width, direction in (('A', 30, 'input'), ('B', 18, 'input'), ('P', 48, 'output')):
        dsp['connections'][pin] = list(range(offset, offset + width))
        dsp['port_directions'][pin] = direction
        offset += width
    return dict(modules={'kernel': dict(cells={str(i): deepcopy(dsp) for i in range(32)}),
                         runner.TOP: dict(cells={**{str(i): deepcopy(dsp) for i in range(3)},
                                                **{'kernel_' + str(i): dict(type='kernel') for i in range(16)}})})


def result(mode):
    good = mode in (0, 3, 4, 5, 6)
    values = (4096, 196, 6528, 64, 64) if good else ((0, 1, 0, 0, 0) if mode == 1 else
             ((0, 196, 20, 0, 0) if mode == 8 else (1, 196, 6528, 64, 64)))
    checked, commands, reads, writes, acks = values
    return (f'PASS C32 K16 BRAM board RTL mode={mode} success={2 if mode == 6 else int(good)} '
            f'resets={int(mode in (3, 4, 5, 6))} faults={int(not good)} init=4096 check={checked} '
            f'cmd_reads={commands} operand_reads={reads} writes={writes} acks={acks} cycles=100; no physical FPGA test\n')


class PrefixObservedMappedBoardControls(unittest.TestCase):
    def test_completed_own_full_mapping_profile_only(self):
        report = mapping_report()
        runner.verify_mapping_report(report)
        for key, value in (('status', 'PASS_OBSERVABLE_RAW_BOARD_PARTITIONED_XC7_MAPPING_ONLY'),
                           ('stage', 'mapping'), ('finished_utc', None), ('channels', 16), ('kernels', 8),
                           ('parallel_products', 256), ('mapped_kernel_instances', 8), ('retained_cmac_dsps', 256),
                           ('dsp_count', 512), ('shell_cells', {'DSP48E1': 0}),
                           ('reused_kernel_cells', {'DSP48E1': 16}), ('cells', {'RAMB36E1': 1}),
                           ('intended_part', 'xc7a100t'), ('intended_clock_period_ns', 100), ('bindings', {}),
                           ('imported_kernel_circuit_identity', 'COUNTS_ONLY'), ('original_four_bit_state_preserved', False),
                           ('original_bench_unchanged', False), ('mapping_diagnostics_accepted', False),
                           ('normalization_audit', []), ('actual_ram_port_resizes', 32), ('logged_ram_port_resizes', 0),
                           ('commands', []), ('numerical_netlist_acceptance', True), ('physical_fit_verified', True),
                           ('bitstream_emitted', True), ('hardware_programmed', True)):
            changed = deepcopy(report)
            changed[key] = value
            with self.subTest(field=key), self.assertRaises(AssertionError):
                runner.verify_mapping_report(changed)

    def test_partial_failed_or_missing_mapping_commands_rejected(self):
        for key, value in (('status', 'RUNNING'), ('returncode', 1), ('log', 'wrong.log')):
            report = mapping_report()
            report['commands'][-1][key] = value
            with self.subTest(field=key), self.assertRaises(AssertionError):
                runner.verify_mapping_report(report)

    def test_carry_control_preserves_explicit_non_equivalence_and_real_negative(self):
        report = carry_report()
        runner.verify_carry_report(report)
        for key, value in (('status', 'FAIL'), ('stage', 'positive_test'), ('finished_utc', None),
                           ('upstream_model_commit', 'different'), ('primitive_fixture_acceptance', False),
                           ('default_global_startup_preserved', False), ('commands', []),
                           ('numerical_netlist_acceptance', True), ('physical_fit_verified', True),
                           ('bitstream_emitted', True), ('hardware_programmed', True)):
            changed = deepcopy(report)
            changed[key] = value
            with self.subTest(field=key), self.assertRaises(AssertionError):
                runner.verify_carry_report(changed)
        for key, value in (('four_state_yosys_vendor_equivalence', True), ('yosys_four_state_differences', 0),
                           ('binary_comparisons', 1), ('four_state_comparisons', 1)):
            changed = deepcopy(report)
            changed['result'][key] = value
            with self.subTest(field=key), self.assertRaises(AssertionError):
                runner.verify_carry_report(changed)
        changed = deepcopy(report)
        changed['commands'][-2]['returncode'] = 0
        with self.assertRaises(AssertionError):
            runner.verify_carry_report(changed)

    def test_separate_model_inventory_does_not_relax_original(self):
        self.assertNotIn('DSP48E1', models.original.PINS)
        pins = models.selected_models({'DSP48E1', 'CARRY4', 'RAMB36E1'})
        self.assertEqual(pins[models.CACHE / 'verilog/src/unisims/DSP48E1.v'], models.DSP_SHA)
        self.assertEqual(pins[models.CACHE / 'verilog/src/glbl.v'], models.original.GLBL_SHA)
        for kinds in ({'DSP48E1', 'UNKNOWN'}, {'CARRY4'}, set()):
            with self.subTest(kinds=kinds), self.assertRaises(AssertionError):
                models.selected_models(kinds)
        with self.assertRaises(AssertionError):
            models.original.selected_models({'DSP48E1', 'CARRY4'})

    def test_exact_full_dsp_configuration_and_geometry_required(self):
        design = dsp_fixture()
        self.assertEqual(models.verify_configurations(design, runner.TOP, 'kernel')['total_physical_dsps'], 515)
        for module, field, value in (('kernel', 'AREG', '1'), (runner.TOP, 'BREG', '1'),
                                     (runner.TOP, 'USE_MULT', 'NONE')):
            changed = deepcopy(design)
            changed['modules'][module]['cells']['0']['parameters'][field] = value
            with self.subTest(module=module, field=field), self.assertRaises(AssertionError):
                models.verify_configurations(changed, runner.TOP, 'kernel')
        for module, cell in (('kernel', '0'), (runner.TOP, '0'), (runner.TOP, 'kernel_0')):
            changed = deepcopy(design)
            del changed['modules'][module]['cells'][cell]
            with self.subTest(module=module, cell=cell), self.assertRaises(AssertionError):
                models.verify_configurations(changed, runner.TOP, 'kernel')

    def test_changed_actual_kernel_bias_rejected(self):
        design = dsp_fixture()
        design['modules']['kernel']['cells']['0']['connections']['C'][0] = '1'
        with self.assertRaises(AssertionError):
            models.verify_configurations(design, runner.TOP, 'kernel')

    def test_all_original_modes_keep_full_transaction_contracts(self):
        self.assertEqual(runner.MODES, tuple(range(9)))
        for mode in runner.MODES:
            text = result(mode)
            self.assertEqual(runner.simulation_result(text, 0, mode), text.strip())
            for changed, code in ((text.replace('init=4096', 'init=1'), 0), (text, 1),
                                  (text + 'warning: ignored\n', 0), (text + text, 0),
                                  (text + 'FATAL: other failure\n', 0)):
                with self.subTest(mode=mode), self.assertRaises(AssertionError):
                    runner.simulation_result(changed, code, mode)

    def test_only_first_output_negative_and_unchanged_remaining_goldens(self):
        text = 'FATAL: bench: board demo numerical/address mismatch output=0\n'
        runner.simulation_result(text, 1, 0, negative=True)
        for changed, code, mode in ((text, 0, 0), (text, 1, 1), (text.replace('output=0', 'output=1'), 1, 0),
                                    (text + result(0), 1, 0)):
            with self.subTest(text=changed), self.assertRaises(AssertionError):
                runner.simulation_result(changed, code, mode, negative=True)
        original = runner.WRITES.read_text()
        changed = runner.negative_golden(original)
        self.assertEqual(original.splitlines()[1:], changed.splitlines()[1:])
        self.assertEqual(int(original.splitlines()[0], 16) ^ int(changed.splitlines()[0], 16), 1)


if __name__ == '__main__':
    unittest.main()
