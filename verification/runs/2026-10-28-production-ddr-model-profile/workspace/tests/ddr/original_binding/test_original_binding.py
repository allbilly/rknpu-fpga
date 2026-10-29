"""Negative and endpoint-compatibility controls for the original MIG map."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from tools.ddr.original_binding import binding_map, ports


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).with_name('original_mig_normal_ports.json')


def fixture_ports():
    data = json.loads(FIXTURE.read_text())
    return data, {p['name']: {'direction': p['direction'], 'width': p['width']}
                  for p in data['ports']}


class OriginalMigPortParserTests(unittest.TestCase):
    def test_skip_calib_debug_is_excluded_from_normal_port_set(self):
        parsed = ports('''module sample (
          input logic [7:0] payload,
          `ifdef SKIP_CALIB
          input logic [6:0] debug_addr,
          output logic debug_valid,
          `endif
          output logic ready
        ); endmodule
        ''', 'sample')
        self.assertEqual(parsed, {
            'payload': {'direction': 'in', 'width': 8},
            'ready': {'direction': 'out', 'width': 1},
        })

    def test_unrecognized_conditional_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported conditional'):
            ports('module sample (`ifdef OTHER input a, `endif output b); endmodule', 'sample')

    def test_parameterized_port_width_is_rejected(self):
        text = 'module sample #(parameter W=8) (input logic [W-1:0] payload); endmodule'
        with self.assertRaisesRegex(ValueError, 'Unsupported port declaration'):
            ports(text, 'sample')

    def test_duplicate_port_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate module port'):
            ports('module sample (input logic ready, output logic ready); endmodule', 'sample')

    def test_reversed_port_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported port extent'):
            ports('module sample (input logic [0:7] payload); endmodule', 'sample')


class OriginalMigBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture, cls.mig = fixture_ports()
        cls.endpoint = ports((ROOT/'rtl/ddr/rk_jtag_ew_ddr_async.sv').read_text(),
                             'rk_jtag_ew_ddr_async')

    def test_port_fixture_is_only_port_facts_and_pins_actual_generated_identity(self):
        self.assertEqual(set(self.fixture), {
            'schema_version', 'top', 'wrapper_sha256', 'normal_port_count',
            'defines_required_undefined', 'ports'})
        self.assertEqual(self.fixture['top'], 'top_mig_7series_0_0')
        self.assertEqual(self.fixture['normal_port_count'], 169)
        self.assertRegex(self.fixture['wrapper_sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(self.fixture['defines_required_undefined'], ['SKIP_CALIB'])
        self.assertEqual(len(self.fixture['ports']), 169)
        self.assertTrue(all(set(p) == {'name', 'direction', 'width'}
                            for p in self.fixture['ports']))

    def test_all_169_normal_original_mig_ports_map_to_async_endpoint_header(self):
        result = binding_map(self.mig, self.endpoint)
        self.assertEqual(len(result), 169)
        self.assertEqual(set(result), set(self.mig))
        self.assertEqual(result['sys_rst']['binding'], {
            'kind': 'endpoint', 'net': 'mig_sys_rst_n', 'active_level': 0})

    def test_channel0_axi_names_widths_directions_and_endpoint_nets(self):
        mapped = binding_map(self.mig, self.endpoint)
        expected = {
            'c0_s_axi_awaddr': ('m_axi_awaddr', 'in', 31),
            'c0_s_axi_awid': ('m_axi_awid', 'in', 4),
            'c0_s_axi_awsize': ('m_axi_awsize', 'in', 3),
            'c0_s_axi_awburst': ('m_axi_awburst', 'in', 2),
            'c0_s_axi_awready': ('m_axi_awready', 'out', 1),
            'c0_s_axi_wdata': ('m_axi_wdata', 'in', 512),
            'c0_s_axi_wstrb': ('m_axi_wstrb', 'in', 64),
            'c0_s_axi_wready': ('m_axi_wready', 'out', 1),
            'c0_s_axi_bready': ('m_axi_bready', 'in', 1),
            'c0_s_axi_bresp': ('m_axi_bresp', 'out', 2),
            'c0_s_axi_araddr': ('m_axi_araddr', 'in', 31),
            'c0_s_axi_arready': ('m_axi_arready', 'out', 1),
            'c0_s_axi_rdata': ('m_axi_rdata', 'out', 512),
            'c0_s_axi_rready': ('m_axi_rready', 'in', 1),
            'c0_s_axi_ctrl_awaddr': ('m_axi_ctrl_awaddr', 'in', 32),
            'c0_s_axi_ctrl_rdata': ('m_axi_ctrl_rdata', 'out', 32),
        }
        for name, (net, direction, width) in expected.items():
            with self.subTest(port=name):
                self.assertEqual(mapped[name]['direction'], direction)
                self.assertEqual(mapped[name]['width'], width)
                self.assertEqual(mapped[name]['binding'], {'kind': 'endpoint', 'net': net})

    def test_exactly_six_application_requests_are_constant_zero(self):
        request_names = sorted(n for n in self.mig
                               if n.endswith(('_app_sr_req', '_app_ref_req', '_app_zq_req')))
        self.assertEqual(len(request_names), 6)
        mapped = binding_map(self.mig, self.endpoint)
        for name in request_names:
            with self.subTest(port=name):
                self.assertEqual(mapped[name]['direction'], 'in')
                self.assertEqual(mapped[name]['width'], 1)
                self.assertEqual(mapped[name]['binding']['kind'], 'inactive_request_constant')
                self.assertEqual(mapped[name]['binding']['value'], 0)

    def test_channel1_valid_and_response_ready_inputs_are_zero(self):
        mapped = binding_map(self.mig, self.endpoint)
        inactive = sorted(n for n,p in self.mig.items() if n.startswith('c1_s_axi_') and
                          p['direction']=='in' and n.endswith(('valid','ready')))
        self.assertTrue(inactive)
        for name in inactive:
            with self.subTest(port=name):
                self.assertEqual(mapped[name]['binding']['kind'], 'inactive_channel_constant')
                self.assertEqual(mapped[name]['binding']['value'], 0)
        for name, value, width in (
            ('c1_s_axi_awsize',6,3),('c1_s_axi_arsize',6,3),
            ('c1_s_axi_awburst',1,2),('c1_s_axi_arburst',1,2)):
            with self.subTest(port=name):
                self.assertEqual(mapped[name]['direction'], 'in')
                self.assertEqual(mapped[name]['width'], width)
                self.assertEqual(mapped[name]['binding']['value'], value)

    def test_ecc_and_temperature_outputs_remain_unqualified_diagnostics(self):
        mapped = binding_map(self.mig, self.endpoint)
        expected = [f'c{c}_{suffix}' for c in (0,1)
                    for suffix in ('app_ecc_single_err','app_ecc_multiple_err','device_temp')]
        self.assertEqual(len(expected), 6)
        for name in expected:
            with self.subTest(port=name):
                self.assertEqual(mapped[name]['direction'], 'out')
                self.assertEqual(mapped[name]['binding']['kind'], 'diagnostic_output')
                self.assertIs(mapped[name]['binding']['validity_qualified'], False)

    def test_same_count_unknown_port_is_rejected(self):
        altered = deepcopy(self.mig)
        altered['c0_mystery'] = altered.pop('c0_app_sr_req')
        self.assertEqual(len(altered), 169)
        with self.assertRaisesRegex(ValueError, 'Unmodeled MIG port'):
            binding_map(altered, self.endpoint)

    def test_changed_axi_width_or_direction_is_rejected(self):
        for field, value in (('width', 511), ('direction', 'out')):
            altered = deepcopy(self.mig)
            altered['c0_s_axi_wdata'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'direction or width differs'):
                binding_map(altered, self.endpoint)

    def test_missing_endpoint_port_is_rejected(self):
        altered = dict(self.endpoint)
        del altered['m_axi_awaddr']
        with self.assertRaisesRegex(ValueError, 'Missing logical endpoint port: m_axi_awaddr'):
            binding_map(self.mig, altered)

    def test_changed_physical_pad_shape_is_rejected(self):
        altered = deepcopy(self.mig)
        altered['c0_ddr3_dq']['width'] = 71
        with self.assertRaisesRegex(ValueError, 'Unsupported DDR pad shape'):
            binding_map(altered, self.endpoint)


if __name__ == '__main__':
    unittest.main()
