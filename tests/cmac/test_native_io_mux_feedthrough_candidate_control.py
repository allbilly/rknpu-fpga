"""All previous candidate controls plus source-evidenced native buffer naming."""
from copy import deepcopy
import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import build_native_io_mux_feedthrough_candidate as build
import mux_native_io_probe as probe
from test_explicit_mux_feedthrough_candidate_control import ExplicitMuxBenchControls, MuxCandidateControls


def synthetic_packed(corrected):
    cells = {}
    def add(name, kind, orig, ports, init=None):
        cells[name] = dict(type=kind, attributes={'X_ORIG_TYPE': orig},
            parameters={} if init is None else {'INIT': init}, connections={p: [b] for p, b in ports.items()},
            port_directions={p: 'output' if p in ('OUT', 'O6') else 'input' for p in ports})
    add('left', 'SELMUX2_1', 'MUXF7', {'OUT': 20})
    add('right', 'SELMUX2_1', 'MUXF7', {'OUT': 21})
    add('root', 'SELMUX2_1', 'MUXF8', {'0': 30, '1': 31, 'OUT': 22})
    for i, (foreign, bit) in enumerate((('left', 20), ('right', 21))):
        add('wrapper' + str(i), 'SELMUX2_1', 'MUXF7', {'0': 40 + i if corrected else bit, 'OUT': 30 + i})
        if corrected:
            add('identity' + str(i), 'SLICE_LUTX', 'LUT1', {'A1': bit, 'O6': 40 + i}, '10')
    for i, bit in enumerate((20, 21, 22)):
        add('output_pad' + str(i) + '$intcell$OBUF', 'IOB33_OUTBUF', 'OBUF', {'IN': bit, 'OUT': 3 + i})
    return {'modules': {'top': {'cells': cells, 'settings': {'pack': '1', 'place': '0', 'route': '0'}}}}


class NativeIoProbeControls(unittest.TestCase):
    def test_only_name_lookup_changes_in_comparison_procedure(self):
        source = probe.PROBE_SOURCE
        for old, new in reversed(probe.REPLACEMENTS):
            self.assertEqual(source.count(new), 1)
            source = source.replace(new, old)
        self.assertEqual(source, inspect.getsource(probe.original.packed_probe))
        source = build.MAIN_SOURCE
        for old, new in reversed(build.REPLACEMENTS):
            self.assertEqual(source.count(new), 1)
            source = source.replace(new, old)
        self.assertEqual(source, build.previous.MAIN_SOURCE)
        self.assertIs(build.NAMESPACE['candidate_source'], probe.original.candidate_source)
        self.assertIs(build.NAMESPACE['verify_metadata'], probe.original.verify_metadata)
        self.assertIs(build.NAMESPACE['packed_probe'], probe.packed_probe)
        self.assertEqual(build.NAMESPACE['BENCH'], build.previous.BENCH)

    def test_real_native_io_source_contract(self):
        contract = probe.validate_source_contract()
        self.assertEqual(contract['decomposition_suffix'], '$intcell$OBUF')
        self.assertFalse(contract['is_hierarchy'])
        self.assertTrue(contract['comparison_only'])

    def test_old_and_corrected_trees_both_keep_actual_output_exports(self):
        for corrected in (False, True):
            packed = synthetic_packed(corrected)
            result = probe.packed_probe(packed, corrected)
            self.assertEqual(result['corrected'], corrected)
            self.assertTrue(result['original_shared_mux_exports_preserved'])
            with self.assertRaises(KeyError): probe.original.packed_probe(packed, corrected)

    def test_wrong_export_identity_or_stage_still_rejected(self):
        for action in ('export', 'identity', 'foreign', 'stage', 'old_name'):
            packed = synthetic_packed(True)
            module = packed['modules']['top']; cells = module['cells']
            if action == 'export': cells['output_pad0$intcell$OBUF']['connections']['IN'] = [21]
            elif action == 'identity': cells['identity0']['parameters']['INIT'] = '00'
            elif action == 'foreign': cells['identity0']['connections']['A1'] = [21]
            elif action == 'stage': module['settings']['place'] = '1'
            else: cells['output_pad0'] = cells.pop('output_pad0$intcell$OBUF')
            with self.subTest(action=action), self.assertRaises((AssertionError, KeyError)):
                probe.packed_probe(packed, True)


if __name__ == '__main__':
    unittest.main()
