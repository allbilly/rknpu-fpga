"""Literal address/data alias corruption controls, not board execution."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from audit_prefix_memory_wiring import (TOP, SELECTED, CONSUMER, WIDTHS, lanes,
    netname_region, named_net, translated_signals, verify_wiring)


class PrefixMemoryWiringControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = json.loads(SELECTED.read_text())
        cls.brams = {n: c for n, c in selected.items() if c['type'] == 'RAMB36E1'}
        cls.info = json.loads(CONSUMER.read_text())['BRAM_memory_classification']

    def case(self):
        brams, info = deepcopy(self.brams), deepcopy(self.info)
        roms = {i['source_ROM_slice_match_offset']: n for n, i in info.items() if i['readonly']}
        rams = {len(i['directly_consumed_memory_lanes']): n for n, i in info.items() if not i['readonly']}
        rom = sum((lanes(brams[roms[offset]]['connections'], 'A', 'out')[:min(9, 32 - offset)]
                   for offset in (0, 9, 18, 27)), [])
        first, second = (brams[rams[w]]['connections'] for w in (9, 7))
        signals = {'demo.rom.value': rom, 'demo.initial_value': rom[:16], 'demo.expected_value': rom[16:],
                   'demo.index': first['ADDRARDADDR'][3:15], 'demo.memory.translated': first['ADDRBWRADDR'][3:15],
                   'demo.memory.clk': first['CLKARDCLK']}
        for port, direction, name in (('A', 'in', 'demo.memory.host_wdata'), ('A', 'out', 'demo.memory.host_rdata'),
                                      ('B', 'in', 'demo.mem_req_wdata'), ('B', 'out', 'demo.mem_rsp_rdata')):
            signals[name] = lanes(first, port, direction) + lanes(second, port, direction)[:7]
        signals['demo.rom.index'] = list(signals['demo.index'])
        signals['demo.memory.host_index'] = list(signals['demo.index'])
        return brams, info, signals, roms, rams

    def test_all_rom_and_both_working_ram_channels_with_explicit_startup_gap(self):
        brams, info, signals, _, _ = self.case()
        result = verify_wiring(brams, info, signals)
        self.assertTrue(result['all_32_ROM_data_bits_wired'])
        self.assertTrue(result['all_16_working_RAM_data_bits_wired'])
        self.assertTrue(result['all_12_address_bits_wired'])
        self.assertFalse(result['write_before_read_proved'])
        self.assertFalse(result['observable_startup_reset_independence_proved'])

    def test_rom_signal_order_clock_address_parity_and_write_changes_fail(self):
        for change in ('rom_bits', 'initial', 'index', 'address_lsb', 'address_msb', 'parity', 'clock', 'write', 'slice'):
            brams, info, signals, roms, _ = self.case()
            name = roms[0]; c = brams[name]['connections']
            if change == 'rom_bits': signals['demo.rom.value'][0], signals['demo.rom.value'][1] = signals['demo.rom.value'][1], signals['demo.rom.value'][0]
            elif change == 'initial': signals['demo.initial_value'][0] = 1000000
            elif change == 'index': signals['demo.index'].reverse()
            elif change == 'address_lsb': c['ADDRARDADDR'][0] = '1'
            elif change == 'address_msb': c['ADDRARDADDR'][15] = '0'
            elif change == 'parity': c['DOPADOP'][0] = 1000000
            elif change == 'clock': c['CLKARDCLK'] = [1000000]
            elif change == 'write': c['WEA'][0] = '1'
            else: info[roms[9]]['source_ROM_slice_match_offset'] = 0
            with self.subTest(change=change), self.assertRaises(AssertionError): verify_wiring(brams, info, signals)

    def test_working_ram_all_four_data_channels_address_clock_and_missing_fail(self):
        for port, direction, signal in (('A', 'in', 'demo.memory.host_wdata'), ('A', 'out', 'demo.memory.host_rdata'),
                                        ('B', 'in', 'demo.mem_req_wdata'), ('B', 'out', 'demo.mem_rsp_rdata')):
            brams, info, signals, _, _ = self.case()
            signals[signal][15] = 1000000
            with self.subTest(port=port, direction=direction), self.assertRaises(AssertionError): verify_wiring(brams, info, signals)
        for change in ('core_address', 'core_clock', 'missing', 'extra_signal', 'live_lanes'):
            brams, info, signals, _, rams = self.case(); name = rams[7]
            if change == 'core_address': brams[name]['connections']['ADDRBWRADDR'][3] = 1000000
            elif change == 'core_clock': brams[name]['connections']['CLKBWRCLK'] = [1000000]
            elif change == 'missing': brams.pop(name)
            elif change == 'extra_signal': signals['unmodeled'] = [1000000]
            else: info[name]['directly_consumed_memory_lanes'] = list(range(8))
            with self.subTest(change=change), self.assertRaises(AssertionError): verify_wiring(brams, info, signals)

    def test_literal_alias_selection_scopes_top_and_rejects_offsets_or_bad_translation(self):
        record = lambda bits: dict(hide_name=0, bits=bits, attributes={})
        source_nets = {}; aliases = {}; bit = 2
        for name, width in WIDTHS.items():
            source_nets[name] = record(list(range(bit, bit + width)))
            for wire in range(bit, bit + width): aliases['n_' + str(wire)] = record([wire + 1000])
            bit += width
        original = json.dumps(dict(modules=dict(other_kernel=dict(netnames={'demo.rom.value': record([999])}),
                                                **{TOP: dict(netnames=source_nets)})), indent=2).encode()
        physical = json.dumps(dict(modules={TOP: dict(netnames=aliases)}), indent=2).encode()
        signals, mappings = translated_signals(original, physical)
        self.assertEqual(signals['demo.rom.value'], list(range(1002, 1034)))
        self.assertEqual(len(mappings), sum(WIDTHS.values()))
        for change in ('missing', 'width', 'duplicate_wire', 'offset'):
            bad = deepcopy(aliases)
            if change == 'missing': bad.pop('n_2')
            elif change == 'width': bad['n_2']['bits'] = [1002, 1003]
            elif change == 'duplicate_wire': bad['n_3']['bits'] = [1002]
            else: bad['n_2']['offset'] = 1
            corrupt = json.dumps(dict(modules={TOP: dict(netnames=bad)}), indent=2).encode()
            with self.subTest(change=change), self.assertRaises(AssertionError): translated_signals(original, corrupt)


if __name__ == '__main__': unittest.main()
