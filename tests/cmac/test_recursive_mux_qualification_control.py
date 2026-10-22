"""Recursive mux qualification controls, not actual native placement results."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import qualify_recursive_mux_feedthrough as qualification
from test_mux_feedthrough_candidate_control import completed
from test_native_io_mux_feedthrough_candidate_control import synthetic_packed
from test_prefix_shared_heap_qualification_control import CounterSafeQualificationControls, ExistingNativeGuards


def placed_control():
    module = synthetic_packed(True)['modules']['top']
    module['settings'].update(pack='1', place='1', route='0', placer='heap', target_freq='50000000')
    cells = module['cells']
    cells['ground'] = dict(type='PSEUDO_GND', attributes={}, parameters={},
                           connections={'Y': [99]}, port_directions={'Y': 'output'})
    for i in (0, 1):
        cells['wrapper' + str(i)]['connections']['S0'] = [99]
        cells['wrapper' + str(i)]['port_directions']['S0'] = 'input'
        cells['identity' + str(i)]['attributes'].update(X_ORIG_PORT_A1='I0', X_ORIG_PORT_O6='O')
    for i, cell in enumerate(cells.values()): cell['attributes']['NEXTPNR_BEL'] = 'CONTROL_BEL_' + str(i)
    expected = dict(candidate_probe=dict(cell_counts=dict(Counter(c['type'] for c in cells.values())),
        paths=[dict(root_port=str(i), wrapper='wrapper' + str(i), immediate_driver='identity' + str(i),
                    original_shared_mux=foreign) for i, foreign in enumerate(('left', 'right'))]))
    return module, expected


class RecursiveMuxQualificationControls(unittest.TestCase):
    def test_failed_or_incomplete_build_rejected_before_parent_admission(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-mux-native-admission-control-') as directory:
            root = Path(directory)
            path = root / 'build/openxc7/recursive-mux-feedthrough-native-io-engine-control/report.json'
            path.parent.mkdir(parents=True)
            with patch.object(qualification, 'ROOT', root), patch.object(qualification.base, 'verify_qualification') as parent:
                for key, value in (('status', 'RUNNING'), ('status', 'FAIL_RECURSIVE_MUX_FEEDTHROUGH_BUILD_OR_PACK_PROBE'),
                                   ('stage', 'compile'), ('finished_utc', None), ('changed_link_objects', 2),
                                   ('qualified_parent_relinked_byte_identical', False), ('full_parallel_products', 256)):
                    report = completed(); report[key] = value
                    path.write_text(json.dumps(report))
                    with self.subTest(key=key), self.assertRaises(AssertionError): qualification.admit_build(path)
                    parent.assert_not_called()

    def test_all_original_native_gates_and_exact_reversible_procedure(self):
        text = qualification.MAIN_SOURCE
        for old, new in reversed(qualification.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        self.assertEqual(text, qualification.base.MAIN_SOURCE)
        self.assertEqual(qualification.COMMANDS[:-1], qualification.base.COMMANDS)
        self.assertEqual(qualification.COMMANDS[-1], 'mux_feedthrough_native_place')
        self.assertIs(qualification.NAMESPACE['check_heap_log'], qualification.base.early.check_heap_log)
        self.assertIs(qualification.NAMESPACE['compare_features'], qualification.base.compare_features)
        self.assertEqual(qualification.FLAGS, qualification.base.FLAGS)
        for marker in ('expected=125', 'record_getter(q,r,out,run)', 'validate_placed', 'timeout=3600'):
            self.assertIn(marker, qualification.MAIN_SOURCE)

    def test_mux_placement_truth_exports_census_and_unique_bels_required(self):
        module, expected = placed_control()
        result = qualification.validate_mux_module(module, expected)
        self.assertEqual(result['identity_truth_comparisons'], 4)
        self.assertTrue(result['shared_original_mux_exports_preserved'])
        self.assertFalse(result['native_routing_executed'])
        for action in ('clock', 'placer', 'stage', 'route', 'missing_bel', 'alias_bel', 'identity',
                       'export', 'foreign', 'select', 'census'):
            value = deepcopy(module); cells = value['cells']
            if action == 'clock': value['settings']['target_freq'] = '25000000'
            elif action == 'placer': value['settings']['placer'] = 'static'
            elif action == 'stage': value['settings']['place'] = '0'
            elif action == 'route': value['settings']['route'] = '1'
            elif action == 'missing_bel': cells['root']['attributes'].pop('NEXTPNR_BEL')
            elif action == 'alias_bel': cells['root']['attributes']['NEXTPNR_BEL'] = cells['left']['attributes']['NEXTPNR_BEL']
            elif action == 'identity': cells['identity0']['parameters']['INIT'] = '00'
            elif action == 'export': cells['output_pad0$intcell$OBUF']['connections']['IN'] = [21]
            elif action == 'foreign': cells['identity0']['connections']['A1'] = [21]
            elif action == 'select': cells['wrapper0']['connections']['S0'] = [20]
            else: cells.pop('output_pad2$intcell$OBUF')
            with self.subTest(action=action), self.assertRaises(AssertionError):
                qualification.validate_mux_module(value, expected)


if __name__ == '__main__':
    unittest.main()
