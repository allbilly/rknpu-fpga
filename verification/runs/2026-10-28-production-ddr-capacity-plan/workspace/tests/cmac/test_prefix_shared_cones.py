"""Synthetic lift/rejection controls; not full numerical or FPGA evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/cmac'),
                str(Path(__file__).resolve().parent)]
import test_shared_kernel_cones as baseline
from prefix_shared_cones import analyze, lift, verify_lift, PRIVATE, SHARED, INSTANCE, NODES


class PrefixSharedControls(baseline.SharedConeControls):
    # Repeat all twelve original strict dependency controls without modifying
    # their expectations or the older analyzer. Only the result key differs.
    def run_fixture(self, modules):
        result = analyze(modules, 'top', 'kernel', 2)
        return dict(result, potentially_removable_cells=result['removable_cells'])

    def dsp_fixture(self):
        modules = self.fixture()
        modules['DSP48E1'] = dict(attributes={'blackbox': '1'}, ports={
            'A': dict(direction='input', bits=[2]),
            'P': dict(direction='output', bits=[3]),
            'CLK': dict(direction='input', bits=[4])})
        modules['kernel']['cells']['dsp'] = dict(type='DSP48E1', parameters={'AREG': '0'},
            port_directions={'A': 'input', 'P': 'output'}, connections={'A': [2], 'P': [8]})
        modules['kernel']['cells']['shared_next']['connections']['I0'] = [8]
        return dict(modules=modules)

    def candidate(self, original=None):
        original = original or dict(modules=self.fixture())
        candidate, certificate = lift(original, 'top', 'kernel', 2)
        return original, candidate, certificate

    def reject_changed(self, change, original=None):
        original, candidate, certificate = self.candidate(original)
        change(candidate, certificate)
        with self.assertRaises(AssertionError):
            verify_lift(original, candidate, certificate)

    def test_dsp_omissions_are_barriers_never_defaulted(self):
        original = self.dsp_fixture()
        before = deepcopy(original)
        candidate, certificate = lift(original, 'top', 'kernel', 2)
        self.assertEqual(original, before)
        self.assertEqual(certificate['analysis']['omitted_DSP_pins_barriered'], {'dsp': ['CLK']})
        self.assertNotIn('dsp', candidate['modules'][SHARED]['cells'])
        self.assertNotIn('shared_next', candidate['modules'][SHARED]['cells'])
        self.assertEqual(candidate['modules'][PRIVATE]['cells']['dsp'], original['modules']['kernel']['cells']['dsp'])
        verify_lift(original, candidate, certificate)

    def test_lift_reverse_expansion_and_no_input_mutation(self):
        original = dict(modules=self.fixture())
        before = deepcopy(original)
        _, candidate, certificate = self.candidate(original)
        self.assertEqual(original, before)
        self.assertEqual(set(candidate['modules'][SHARED]['cells']), {'constant', 'shared', 'shared_next'})
        self.assertEqual(set(candidate['modules'][PRIVATE]['cells']), {'private'})
        verify_lift(original, candidate, certificate)

    def test_non_dsp_state_omission_rejected(self):
        original = self.dsp_fixture()
        modules = original['modules']
        modules['FDRE'] = modules['DSP48E1']
        modules['kernel']['cells']['dsp']['type'] = 'FDRE'
        with self.assertRaises(AssertionError):
            lift(original, 'top', 'kernel', 2)

    def test_shared_function_corruption_rejected(self):
        self.reject_changed(lambda c, _: c['modules'][SHARED]['cells']['shared']['parameters'].update(INIT='01'))

    def test_private_function_corruption_rejected(self):
        self.reject_changed(lambda c, _: c['modules'][PRIVATE]['cells']['private']['parameters'].update(INIT='01'))

    def test_private_dsp_change_rejected(self):
        self.reject_changed(lambda c, _: c['modules'][PRIVATE]['cells']['dsp']['parameters'].update(AREG='1'),
                            self.dsp_fixture())

    def test_private_dsp_removal_rejected(self):
        self.reject_changed(lambda c, _: c['modules'][PRIVATE]['cells'].pop('dsp'), self.dsp_fixture())

    def test_private_caller_input_change_rejected(self):
        self.reject_changed(lambda c, _: c['modules']['top']['cells']['k1']['connections'].update(weight=[200]))

    def test_shared_caller_input_change_rejected(self):
        self.reject_changed(lambda c, _: c['modules']['top']['cells'][INSTANCE]['connections'].update(data=[101]))

    def test_shared_bus_binding_change_rejected(self):
        self.reject_changed(lambda c, _: c['modules']['top']['cells']['k1']['connections'].update({NODES: [900, 901, 902]}))

    def test_shared_node_corruption_rejected(self):
        self.reject_changed(lambda _, cert: cert['original_output_nodes'].__setitem__(0, 900))

    def test_parent_wire_collision_rejected(self):
        def corrupt(candidate, certificate):
            wires = [100, *certificate['shared_parent_wires'][1:]]
            certificate['shared_parent_wires'] = wires
            for cell in candidate['modules']['top']['cells'].values():
                cell['connections'][NODES] = list(wires)
        self.reject_changed(corrupt)

    def test_caller_removal_rejected(self):
        self.reject_changed(lambda c, _: c['modules']['top']['cells'].pop('k1'))

    def test_shell_mutation_rejected(self):
        self.reject_changed(lambda c, _: c['modules']['top'].update(attributes={'changed': '1'}))

    def test_no_eligible_cone_rejected(self):
        original = dict(modules=self.fixture())
        original['modules']['kernel']['cells'].pop('constant')
        original['modules']['top']['cells']['k1']['connections']['data'] = [101]
        with self.assertRaises(AssertionError):
            lift(original, 'top', 'kernel', 2)

    def test_namespace_collision_rejected(self):
        original = dict(modules=self.fixture())
        original['modules'][SHARED] = {}
        with self.assertRaises(AssertionError):
            lift(original, 'top', 'kernel', 2)


if __name__ == '__main__':
    unittest.main()
