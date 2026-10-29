"""Synthetic mapping-input controls, never HDL/physical acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
from map_fixed_board import CMAC, KERNEL, MAPPED_CMAC, count_shell, parameter_binding, partition, verify_area, verify_board
from test_fixed_array_board import ROW_FORMAL


class FixedBoardMappingControls(unittest.TestCase):
    def fixture(self):
        return {'creator': 'SYNTHETIC control fixture, not a synthesized design', 'modules': {
            CMAC: {'parameter_default_values': {name: format(value, '032b') for name, value in
                (('ATOMIC_C', 32), ('ATOMIC_K', 16), ('TAG_WIDTH', 35))},
                'cells': {f'kernel{i}': {'type': KERNEL} for i in range(16)}},
            KERNEL: {'attributes': {'hdlname': KERNEL, 'keep_hierarchy': '1'},
                     'cells': {'lut': {'type': 'LUT1'}}},
            'LUT1': {'attributes': {'blackbox': '1'}, 'cells': {}},
        }}

    def test_only_actual_implementation_modules_copied(self):
        design = self.fixture()
        before = deepcopy(design)
        frozen, kernel, cells = partition(design)
        self.assertEqual(design, before)
        self.assertEqual(set(frozen['modules']), {CMAC, kernel})
        self.assertEqual(frozen['modules'][kernel], design['modules'][kernel])
        self.assertEqual(frozen['modules'][CMAC], design['modules'][CMAC])
        self.assertEqual(cells, {'LUT1': 1})

    def test_reduced_kernel_count_rejected(self):
        design = self.fixture()
        del design['modules'][CMAC]['cells']['kernel15']
        with self.assertRaises(AssertionError): partition(design)

    def test_different_dimensions_rejected(self):
        design = self.fixture()
        design['modules'][CMAC]['parameter_default_values']['ATOMIC_C'] = format(8, '032b')
        with self.assertRaises(AssertionError): partition(design)

    def test_parameter_binding_preserves_mapped_bodies(self):
        design, _, _ = partition(self.fixture())
        before = deepcopy(design)
        source = (ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_array_fixed.sv').read_text()
        renamed, shim = parameter_binding(design, source)
        self.assertEqual(design, before)
        self.assertEqual(renamed['modules'][MAPPED_CMAC], design['modules'][CMAC])
        self.assertEqual(renamed['modules'][KERNEL], design['modules'][KERNEL])
        self.assertNotIn(CMAC, renamed['modules'])
        self.assertIn('ATOMIC_C!=32 || ATOMIC_K!=16 || TAG_WIDTH!=35', shim)
        self.assertIn('$fatal', shim)
        self.assertIn(MAPPED_CMAC+' actual_partition(.*);', shim)
        self.assertNotIn('always', shim)

    def test_parameter_binding_rejects_changed_declarations(self):
        design, _, _ = partition(self.fixture())
        with self.assertRaises(AssertionError): parameter_binding(design, 'module changed; endmodule')

    def test_running_area_report_rejected(self):
        with self.assertRaises(AssertionError): verify_area({'status': 'RUNNING'})

    def test_baseline_board_report_rejected(self):
        with self.assertRaises(AssertionError): verify_board({'status': 'PASS_RAW_ARRAY_BOARD_FULL_RTL_ONLY'}, {})

    def test_partial_fixed_board_report_rejected(self):
        report = dict(status='PASS_FIXED_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_EXPERIMENT_ONLY',
                      suite='fixed-verilator', channels=32, kernels=16, parallel_products=512,
                      row_formal_status_at_start=ROW_FORMAL, tests=[])
        with self.assertRaises(AssertionError): verify_board(report, {})

    def test_unknown_hardware_cell_rejected(self):
        modules = {'top': {'cells': {'bad': {'type': 'fake_arithmetic_blackbox'}}}}
        with self.assertRaises(AssertionError): count_shell(modules, 'top', KERNEL)

    def test_only_blackbox_library_primitives_are_leaves(self):
        modules = {'top': {'cells': {'ram': {'type': 'RAMB36E1'}, 'lut': {'type': 'LUT1'},
                                    'cmac': {'type': KERNEL}, 'scope': {'type': '$scopeinfo'}}},
                   'RAMB36E1': {'attributes': {'blackbox': '1'}, 'cells': {}},
                   'LUT1': {'attributes': {'blackbox': '1'}, 'cells': {'timing': {'type': '$specify2'}}}}
        self.assertEqual(count_shell(modules, 'top', KERNEL), {'RAMB36E1': 1, 'LUT1': 1})
        modules['LUT1']['cells']['logic'] = {'type': 'invented_logic'}
        with self.assertRaises(AssertionError): count_shell(modules, 'top', KERNEL)


if __name__ == '__main__':
    unittest.main()
