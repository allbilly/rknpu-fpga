"""Source-bound controls for explicit physical MIG channel selection."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from tools.ddr.interface import load_json
from tools.ddr.original_binding import WRAPPER_SHA, binding_map, ports
from tools.ddr.original_platform import TOP, render
from tools.ddr.prepare_channel_profile import select_physical_channel

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / 'build/ypcb-ddr-shell/ch1-source-v1'
PACKAGE_REPORT = PACKAGE / 'report.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolved(path):
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def unique_parent_report(source_inputs, suffix):
    found = [resolved(name) for name in source_inputs if name.endswith(suffix)]
    if len(found) != 1:
        raise AssertionError(f'Expected one parent report ending {suffix!r}; got {found}')
    return found[0]


class PhysicalChannelProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = load_json(PACKAGE_REPORT)
        cls.source_inputs = {str(resolved(name)): digest
                             for name, digest in cls.report['source_inputs'].items()}
        cls.board_report_path = unique_parent_report(
            cls.report['source_inputs'], '/snapshot-source-v4/report.json')
        cls.platform_report_path = unique_parent_report(
            cls.report['source_inputs'], '/snapshot-v3/report.json')
        cls.selection_report_path = unique_parent_report(
            cls.report['source_inputs'], '/original-mig-rtl-selection/v4/report.json')
        cls.port_map_report_path = unique_parent_report(
            cls.report['source_inputs'], '/original-mig-port-map/v2/report.json')
        cls.board_report = load_json(cls.board_report_path)
        cls.platform_report = load_json(cls.platform_report_path)
        cls.selection_report = load_json(cls.selection_report_path)
        cls.port_map_report = load_json(cls.port_map_report_path)

        cls.wrapper_path, = [Path(name).resolve()
                             for name in cls.board_report['real_hdl_sources']
                             if Path(name).name == 'top_mig_7series_0_0.v']
        cls.endpoint_path, = [Path(name).resolve()
                              for name in cls.board_report['real_hdl_sources']
                              if Path(name).name == 'rk_jtag_ew_ddr_async.sv']
        cls.mig_ports = ports(cls.wrapper_path.read_text(), 'top_mig_7series_0_0')
        cls.endpoint_ports = ports(cls.endpoint_path.read_text(), 'rk_jtag_ew_ddr_async')
        cls.canonical = binding_map(cls.mig_ports, cls.endpoint_ports)
        cls.selected = select_physical_channel(cls.canonical, 1)

    def test_channel_zero_is_an_independent_unchanged_deep_copy(self):
        before = deepcopy(self.canonical)
        channel0 = select_physical_channel(self.canonical, 0)
        self.assertEqual(channel0, before)
        self.assertIsNot(channel0, self.canonical)
        self.assertIsNot(channel0['sys_rst'], self.canonical['sys_rst'])
        self.assertIsNot(channel0['sys_rst']['binding'], self.canonical['sys_rst']['binding'])
        channel0['sys_rst']['binding']['net'] = 'test mutation'
        self.assertEqual(self.canonical, before)

    def test_channel_one_preserves_physical_buses_and_swaps_only_paired_logical_bindings(self):
        before = deepcopy(self.canonical)
        selected = select_physical_channel(self.canonical, 1)
        self.assertEqual(self.canonical, before, 'The canonical input map must remain unchanged')
        self.assertEqual(set(selected), set(self.canonical))
        self.assertEqual(len(selected), 169)

        for name, item in self.canonical.items():
            kind = item['binding']['kind']
            if name == 'sys_rst' or kind in ('physical_pad', 'external_clock'):
                self.assertEqual(selected[name], item, name)
                continue
            self.assertTrue(name.startswith(('c0_', 'c1_')), name)
            partner = ('c1_' if name.startswith('c0_') else 'c0_') + name[3:]
            self.assertIn(partner, self.canonical)
            paired = self.canonical[partner]
            self.assertEqual((item['direction'], item['width']),
                             (paired['direction'], paired['width']), name)
            expected = deepcopy(item)
            expected['binding'] = deepcopy(paired['binding'])
            self.assertEqual(selected[name], expected, name)

    def test_channel_one_routes_axi_and_control_to_physical_controller_one(self):
        selected = select_physical_channel(self.canonical, 1)
        c1_axi = [name for name in self.canonical if name.startswith('c1_s_axi_')]
        self.assertTrue(c1_axi)
        for name in c1_axi:
            partner = 'c0_' + name[3:]
            self.assertEqual(selected[name]['binding'], self.canonical[partner]['binding'], name)
            self.assertEqual(selected[name]['binding']['kind'], 'endpoint', name)

        c0_inputs = [name for name, item in selected.items()
                     if name.startswith('c0_s_axi_') and item['direction'] == 'in']
        self.assertTrue(c0_inputs)
        for name in c0_inputs:
            self.assertEqual(selected[name]['binding']['kind'], 'inactive_channel_constant', name)
        inactive_handshakes = [name for name in c0_inputs
                               if name.endswith(('valid', 'ready'))]
        self.assertTrue(inactive_handshakes)
        for name in inactive_handshakes:
            self.assertEqual(selected[name]['binding']['value'], 0, name)

        for name in ('c1_ui_clk', 'c1_ui_clk_sync_rst', 'c1_aresetn',
                     'c1_init_calib_complete', 'c1_interrupt'):
            self.assertEqual(selected[name]['binding']['kind'], 'endpoint', name)
            self.assertEqual(selected[name]['binding'],
                             self.canonical['c0_' + name[3:]]['binding'], name)
        self.assertEqual(selected['sys_rst'], self.canonical['sys_rst'])
        self.assertEqual(selected['sys_rst']['binding'],
                         {'kind': 'endpoint', 'net': 'mig_sys_rst_n', 'active_level': 0})

        # ECC error buses remain unqualified diagnostics, but their physical
        # controller roles follow the same exact C0/C1 binding exchange.
        for suffix in ('app_ecc_single_err', 'app_ecc_multiple_err'):
            active = 'c1_' + suffix
            inactive = 'c0_' + suffix
            self.assertEqual(selected[active]['binding'], self.canonical['c0_' + suffix]['binding'])
            self.assertEqual(selected[active]['binding']['kind'], 'diagnostic_output')
            self.assertIs(selected[active]['binding']['validity_qualified'], False)
            self.assertEqual(selected[inactive]['binding'], self.canonical['c1_' + suffix]['binding'])

    def test_address_data_strobe_and_ecc_width_contract_is_unchanged(self):
        for channel in ('c0', 'c1'):
            for name in ('s_axi_awaddr', 's_axi_araddr'):
                self.assertEqual(self.canonical[f'{channel}_{name}']['width'], 31)
            for name in ('s_axi_wdata', 's_axi_rdata'):
                self.assertEqual(self.canonical[f'{channel}_{name}']['width'], 512)
            self.assertEqual(self.canonical[f'{channel}_s_axi_wstrb']['width'], 64)
            self.assertEqual(self.canonical[f'{channel}_ddr3_dq']['width'], 72)

        original_profile = self.port_map_report['original_profile']
        self.assertEqual(original_profile['ecc'], 'ON')
        self.assertEqual(self.report['physical_ecc_data_bits_per_channel'], 72)
        self.assertEqual(self.report['logical_address_window'], {
            'base': 0, 'bytes': 2147483648, 'host_address_bits': 31})
        self.assertIs(self.report['address_or_data_conversion'], False)

    def test_rejects_unsupported_channel_and_malformed_pairs_without_mutating_input(self):
        before = deepcopy(self.canonical)
        for invalid in (2, -1, True, False, 1.0):
            with self.subTest(channel=invalid), self.assertRaises(ValueError):
                select_physical_channel(self.canonical, invalid)

        missing = deepcopy(self.canonical)
        del missing['c1_s_axi_awaddr']
        with self.assertRaisesRegex(ValueError, 'Missing paired MIG port'):
            select_physical_channel(missing, 1)

        wrong_width = deepcopy(self.canonical)
        wrong_width['c1_s_axi_awaddr']['width'] -= 1
        with self.assertRaisesRegex(ValueError, 'interfaces differ'):
            select_physical_channel(wrong_width, 1)

        wrong_direction = deepcopy(self.canonical)
        wrong_direction['c1_ui_clk']['direction'] = 'in'
        with self.assertRaisesRegex(ValueError, 'interfaces differ'):
            select_physical_channel(wrong_direction, 1)
        self.assertEqual(self.canonical, before)

    def test_frozen_ch1_package_binds_all_122_real_sources_and_preserves_board_files(self):
        report = self.report
        self.assertEqual(report['status'], 'PREPARED_EXPLICIT_PHYSICAL_CHANNEL_SNAPSHOT_SOURCE_ONLY')
        self.assertEqual(report['selected_physical_channel'], 1)
        self.assertEqual(report['logical_ui0_physical_channel'], 1)
        self.assertEqual(report['logical_ui1_physical_channel'], 0)
        self.assertEqual(report['top'], self.board_report['top'])
        self.assertEqual(report['part'], self.board_report['part'])
        self.assertEqual(report['all_mig_bindings'], self.selected)
        for source in (self.board_report_path, self.platform_report_path,
                       self.selection_report_path, self.port_map_report_path):
            self.assertEqual(self.source_inputs[str(source)], sha(source))
        self.assertEqual(sha(self.wrapper_path), WRAPPER_SHA)
        self.assertEqual(self.source_inputs[str(self.wrapper_path)], WRAPPER_SHA)

        sources = [Path(name).resolve() for name in report['real_hdl_sources']]
        self.assertEqual(len(sources), 122)
        self.assertEqual(len(set(sources)), 122)
        input_hashes = {str(resolved(name)): digest
                        for name, digest in report['source_inputs'].items()}
        for source in sources:
            self.assertTrue(source.is_file(), str(source))
            self.assertNotIn('interface-only', source.as_posix())
            try:
                relative = source.relative_to(PACKAGE.resolve()).as_posix()
            except ValueError:
                expected = input_hashes.get(str(source))
            else:
                expected = report['artifacts'].get(relative)
            self.assertIsNotNone(expected, f'Unbound real HDL source: {source}')
            self.assertEqual(sha(source), expected, str(source))

        self.assertIs(report['stub_selected_for_real_design'], False)
        self.assertTrue(report['both_mig_controllers_retained'])
        self.assertIs(report['hardware_accessed'], False)
        self.assertIs(report['vivado_executed'], False)
        self.assertIs(report['bitstream_emitted'], False)
        self.assertIs(report['physical_integration_ready'], False)

        board_top, = [Path(name).resolve() for name in self.board_report['real_hdl_sources']
                      if Path(name).name == 'top.sv']
        self.assertEqual((PACKAGE / 'top.sv').read_bytes(), board_top.read_bytes())
        for source in self.board_report['constraint_sources']:
            source = Path(source).resolve()
            self.assertEqual((PACKAGE / source.name).read_bytes(), source.read_bytes())
        self.assertEqual(sha(PACKAGE / 'mig-original.xdc'), self.report['artifacts']['mig-original.xdc'])
        self.assertEqual(sha(PACKAGE / 'board.xdc'), self.report['artifacts']['board.xdc'])
        self.assertIs(report['original_electrical_constraints_unchanged'], True)

        selected_text, _, selected_top = render(self.endpoint_ports, self.selected)
        canonical_text, _, canonical_top = render(self.endpoint_ports, self.canonical)
        self.assertEqual(selected_top, canonical_top)
        actual_ports = ports((PACKAGE / 'platform.sv').read_text(), TOP)
        interface_ports = {name:dict(direction=port['direction'], width=port['width'])
                           for name, port in canonical_top.items()}
        self.assertEqual(actual_ports, interface_ports)
        self.assertEqual((PACKAGE / 'platform.sv').read_text(), selected_text)
        self.assertNotIn('interface-only', '\n'.join(report['real_hdl_sources']))


if __name__ == '__main__':
    unittest.main()
