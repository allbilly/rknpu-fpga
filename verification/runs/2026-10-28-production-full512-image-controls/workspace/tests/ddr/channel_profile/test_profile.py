"""Portable channel-binding controls using a compact source-derived contract."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from tools.ddr.original_binding import WRAPPER_SHA, binding_map, ports
from tools.ddr.original_platform import TOP, render
from tools.ddr.prepare_channel_profile import select_physical_channel

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = Path(__file__).with_name('channel_profile_contract.json')


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


class PhysicalChannelProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text())
        cls.mig_ports = cls.fixture['mig_port_shapes']
        cls.endpoint_ports = cls.fixture['endpoint_port_shapes']
        cls.canonical = binding_map(cls.mig_ports, cls.endpoint_ports)
        if cls.canonical != cls.fixture['canonical_bindings']:
            raise AssertionError('Frozen port/binding fixture no longer matches binding_map')
        cls.report = {'physical_ecc_data_bits_per_channel':
                      cls.fixture['profile']['physical_ecc_data_bits_per_channel'],
                      'logical_address_window': cls.fixture['profile']['logical_address_window'],
                      'address_or_data_conversion': cls.fixture['profile']['address_or_data_conversion']}
        cls.port_map_report = {'original_profile': cls.fixture['profile']['original_profile']}

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

    def test_fixture_provenance_regenerates_exact_frozen_ch1_platform(self):
        fixture=self.fixture
        self.assertEqual(fixture['schema'],'ch1-physical-channel-binding-fixture-v1')
        self.assertEqual(len(fixture['canonical_bindings']),169)
        self.assertEqual(fixture['profile']['normal_mig_port_count'],169)
        self.assertEqual(fixture['profile']['selected_physical_channel'],1)
        sources=fixture['provenance']['source_files']
        self.assertIn('original_mig_wrapper',sources)
        self.assertIn('async_endpoint',sources)
        self.assertEqual(sources['original_mig_wrapper']['sha256'],WRAPPER_SHA)
        for item in sources.values():
            self.assertEqual(len(item['sha256']),64)
            self.assertTrue(all(c in '0123456789abcdef' for c in item['sha256']))
        manifest=''.join(item['sha256']+'  '+item['path']+'\n'
                         for _,item in sorted(sources.items()))
        self.assertEqual(fixture['provenance']['sha256'],sha256_bytes(manifest.encode()))
        current_sources={
            'original_binding_py':ROOT/'tools/ddr/original_binding.py',
            'original_platform_py':ROOT/'tools/ddr/original_platform.py',
            'prepare_channel_profile_py':ROOT/'tools/ddr/prepare_channel_profile.py',
        }
        for name,path in current_sources.items():
            self.assertEqual(sha256_bytes(path.read_bytes()),sources[name]['sha256'],name)
        ch1=select_physical_channel(self.canonical,1)
        self.assertEqual(sha256_bytes(render(self.endpoint_ports,ch1)[0].encode()),
                         fixture['profile']['actual_ch1_platform_sha256'])
        _,_,top0=render(self.endpoint_ports,self.canonical)
        _,_,top1=render(self.endpoint_ports,ch1)
        self.assertEqual(top0,top1)
        emitted_ports=ports(render(self.endpoint_ports,ch1)[0],TOP)
        self.assertEqual(emitted_ports,{name:{'direction':port['direction'],'width':port['width']}
                                        for name,port in top1.items()})


if __name__ == '__main__':
    unittest.main()
