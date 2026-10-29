"""Conservative connectivity controls; not full HDL or physical acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import audit_dsp_prefix_initial_driver_cones as audit


class InitialDriverConesControl(unittest.TestCase):
    def fixture(self):
        def cell(kind, ins, outs):
            return dict(type=kind, connections=dict(A=ins, Y=outs),
                        port_directions=dict(A='input', Y='output'))
        body = dict(ports={'result': dict(direction='output', bits=[30])},
                    netnames={'temporary': dict(bits=[10])}, cells={
                        'dead_mux': cell('$mux', [10, 11], [12]),
                        'dead_state': cell('$dff', [12], [13]),
                        'live': cell('$not', [20], [30])})
        before = dict(modules=dict(m=body))
        after = deepcopy(before)
        del after['modules']['m']['cells']['dead_mux']
        del after['modules']['m']['cells']['dead_state']
        notices = audit.capture.driver_notices('Warning: Wire m.temporary is used but has no driver.')
        return before, after, notices

    def test_actual_consumers_in_dead_multistep_state_cone(self):
        result = audit.audit_cones(*self.fixture())[0]
        self.assertEqual(result['dead_cone_cells'], 2)
        self.assertEqual(result['actual_direct_consumers'], 1)
        self.assertTrue(result['no_path_to_any_observable_root'])

    def test_live_output_rejected(self):
        before, after, notices = self.fixture()
        before['modules']['m']['ports']['result']['bits'] = [13]
        with self.assertRaisesRegex(AssertionError, 'observable'):
            audit.audit_cones(before, after, notices)

    def test_future_state_influence_rejected(self):
        before, after, notices = self.fixture()
        before['modules']['m']['cells']['live']['connections']['A'] = [13]
        with self.assertRaisesRegex(AssertionError, 'observable'):
            audit.audit_cones(before, after, notices)

    def test_any_output_bit_and_mux_arm_is_conservative(self):
        before, after, notices = self.fixture()
        before['modules']['m']['cells']['dead_mux']['connections']['Y'] += [30]
        with self.assertRaisesRegex(AssertionError, 'observable'):
            audit.audit_cones(before, after, notices)

    def test_outputless_memory_write_or_assertion_is_root(self):
        for kind in ('$memwr', '$assert', 'unknown_side_effect'):
            before, after, notices = self.fixture()
            before['modules']['m']['cells']['effect'] = dict(type=kind,
                connections={'A': [13]}, port_directions={'A': 'input'})
            with self.assertRaisesRegex(AssertionError, 'observable'):
                audit.audit_cones(before, after, notices)

    def test_constant_output_cell_is_not_assumed_pure(self):
        before, after, notices = self.fixture()
        before['modules']['m']['cells']['effect'] = dict(type='unknown',
            connections={'A': [13], 'Y': ['0']}, port_directions={'A': 'input', 'Y': 'output'})
        with self.assertRaisesRegex(AssertionError, 'observable'):
            audit.audit_cones(before, after, notices)

    def test_kept_cell_or_net_cannot_be_waived(self):
        for target in ('cell', 'net'):
            before, after, notices = self.fixture()
            if target == 'cell':
                before['modules']['m']['cells']['dead_state']['attributes'] = {'keep': '1'}
            else:
                before['modules']['m']['netnames']['kept'] = {'bits': [13], 'attributes': {'dont_touch': '1'}}
            with self.assertRaisesRegex(AssertionError, 'observable'):
                audit.audit_cones(before, after, notices)

    def test_retained_cone_cell_rejected(self):
        before, after, notices = self.fixture()
        after['modules']['m']['cells']['dead_state'] = before['modules']['m']['cells']['dead_state']
        with self.assertRaisesRegex(AssertionError, 'remains after'):
            audit.audit_cones(before, after, notices)

    def test_unknown_pin_and_retention_metadata_rejected(self):
        before, after, notices = self.fixture()
        before['modules']['m']['cells']['dead_state']['port_directions']['Y'] = 'unknown'
        with self.assertRaises(AssertionError):
            audit.audit_cones(before, after, notices)
        with self.assertRaises(AssertionError):
            audit.retained({'keep': 'x'})

    def test_cell_inout_is_observable(self):
        before, after, notices = self.fixture()
        before['modules']['m']['cells']['dead_state']['port_directions']['Y'] = 'inout'
        with self.assertRaisesRegex(AssertionError, 'observable'):
            audit.audit_cones(before, after, notices)

    def test_module_inout_is_observable(self):
        before, after, notices = self.fixture()
        before['modules']['m']['ports']['result'] = dict(direction='inout', bits=[13])
        with self.assertRaisesRegex(AssertionError, 'observable'):
            audit.audit_cones(before, after, notices)

    def test_dead_cycle_is_not_mistaken_for_output(self):
        before, after, notices = self.fixture()
        before['modules']['m']['cells']['dead_mux']['connections']['A'].append(13)
        self.assertEqual(audit.audit_cones(before, after, notices)[0]['dead_cone_cells'], 2)

    def test_unknown_output_bearing_cell_is_not_assumed_pure(self):
        before, after, notices = self.fixture()
        before['modules']['m']['cells']['dead_state']['type'] = 'arbitrary_side_effect'
        with self.assertRaisesRegex(AssertionError, 'Unknown side effects'):
            audit.audit_cones(before, after, notices)

    def test_json_consumer_serialization_is_explicit(self):
        before, _, notices = self.fixture()
        result = audit.normalized_inventory(before, notices)
        self.assertIsInstance(result[0]['consumers'][0], list)
        self.assertEqual(result[0]['consumers'][0], ['cell_pin', 'dead_mux', 'A', 0])
        self.assertEqual(result[0]['direct_consumer_count'], 1)


if __name__ == '__main__':
    unittest.main()
