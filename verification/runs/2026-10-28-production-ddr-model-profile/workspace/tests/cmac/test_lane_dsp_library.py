"""Strict DSP timing-qualifier classification controls; no FPGA signoff."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
from lane_dsp_library import timing_only_view


def fixture():
    ports = {'CEP': dict(direction='input', bits=[2]), 'CLK': dict(direction='input', bits=[3]),
        'P': dict(direction='output', bits=list(range(4, 52))),
        'PCOUT': dict(direction='output', bits=list(range(52, 100)))}
    cells = {}
    for i, (constant, destination) in enumerate([('1', 'P'), ('0', 'P'), ('1', 'PCOUT'), ('0', 'PCOUT')]):
        cells['qualifier' + str(i)] = dict(type='$logic_and',
            parameters={n: format(v, '032b') for n, v in dict(A_SIGNED=0, B_SIGNED=0,
                A_WIDTH=1, B_WIDTH=1, Y_WIDTH=1).items()},
            port_directions={'A': 'input', 'B': 'input', 'Y': 'output'},
            connections={'A': [constant], 'B': [2], 'Y': [100 + i]})
        cells['timing' + str(i)] = dict(type='$specify3',
            port_directions={n: 'input' for n in ('EN', 'SRC', 'DST', 'DAT')},
            connections=dict(EN=[100 + i], SRC=[3], DST=ports[destination]['bits'].copy(), DAT=['x'] * 48))
    return dict(DSP48E1=dict(attributes={'blackbox': '1'}, ports=ports, cells=cells))


class LaneDspLibraryControls(unittest.TestCase):
    def test_exact_timing_qualifiers_are_excluded_only_in_a_nonmutating_counter_view(self):
        value = fixture(); before = deepcopy(value)
        view, audit = timing_only_view(value)
        self.assertEqual(value, before); self.assertEqual(len(audit), 4)
        self.assertEqual({c['type'] for c in view['DSP48E1']['cells'].values()}, {'$specify3'})
        self.assertEqual(view['DSP48E1']['ports'], value['DSP48E1']['ports'])
        plain = {'DSP48E1': dict(attributes={'blackbox': '1'})}
        self.assertEqual(timing_only_view(plain), (plain, []))

    def test_arithmetic_unknown_cells_port_drivers_or_altered_timing_paths_rejected(self):
        for case in ('functional', 'extra', 'width', 'input', 'constant', 'port_driver',
                'duplicate_driver', 'no_sink', 'wrong_sink', 'extra_sink', 'clock', 'data',
                'destination', 'role', 'nonblackbox'):
            value = fixture(); module = value['DSP48E1']; cells = module['cells']
            qualifier, timing = cells['qualifier0'], cells['timing0']
            if case == 'functional': qualifier['type'] = '$mul'
            elif case == 'extra': cells['unknown'] = dict(type='unmodeled')
            elif case == 'width': qualifier['parameters']['Y_WIDTH'] = '10'
            elif case == 'input': qualifier['connections']['B'] = [3]
            elif case == 'constant': qualifier['connections']['A'] = ['x']
            elif case == 'port_driver': module['ports']['P']['bits'][0] = 100
            elif case == 'duplicate_driver': cells['qualifier1']['connections']['Y'] = [100]
            elif case == 'no_sink': timing['connections']['EN'] = ['1']
            elif case == 'wrong_sink': timing['type'] = '$specrule'
            elif case == 'extra_sink': cells['timing1']['connections']['DAT'][0] = 100
            elif case == 'clock': timing['connections']['SRC'] = [2]
            elif case == 'data': timing['connections']['DAT'][0] = '0'
            elif case == 'destination': timing['connections']['DST'][0] = 104
            elif case == 'role': qualifier['connections']['A'] = ['0']
            else: module['attributes']['blackbox'] = '0'
            with self.subTest(case=case), self.assertRaises(AssertionError): timing_only_view(value)


if __name__ == '__main__': unittest.main()
