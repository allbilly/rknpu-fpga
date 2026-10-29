"""Combinational cone/proof guard controls; not an actual mapped proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import prove_prefix_bram_address as proof


class PrefixBramAddressControl(unittest.TestCase):
    def cell(self, kind='LUT2'):
        return dict(type=kind, parameters={'INIT': '1000'}, connections={'I0': [2], 'I1': [3], 'O': [4]},
                    port_directions={'I0': 'input', 'I1': 'input', 'O': 'output'})

    def test_literal_complete_LUT_and_binary_wires_only(self):
        proof.validate_cell(self.cell())
        for kind in ('unknown', 'width', 'direction', 'parameter', 'missing', 'short'):
            bad = self.cell()
            if kind == 'unknown': bad['connections']['I0'] = ['x']
            elif kind == 'width': bad['connections']['I0'] = [2, 3]
            elif kind == 'direction': bad['port_directions']['O'] = 'input'
            elif kind == 'parameter': bad['parameters']['extra'] = '0'
            elif kind == 'missing': del bad['connections']['I1']
            else: bad['parameters']['INIT'] = '00'
            with self.assertRaises(AssertionError): proof.validate_cell(bad)

    def test_sequential_memory_unknown_or_unmodeled_primitive_is_not_a_cut(self):
        for kind in ('FDCE', 'RAMB36E1', 'DSP48E1', 'made_up'):
            with self.assertRaisesRegex(AssertionError, 'Unsupported/sequential'):
                proof.validate_cell(self.cell(kind))

    def test_carry_and_mux_shapes_are_exact(self):
        carry = dict(type='CARRY4', parameters={}, connections=dict(CI=['0'], CYINIT=[2], DI=[3,4,5,6], S=[7,8,9,10], CO=[11,12,13,14], O=[15,16,17,18]),
                     port_directions=dict(CI='input', CYINIT='input', DI='input', S='input', CO='output', O='output'))
        proof.validate_cell(carry)
        for mode in ('parameter', 'width'):
            bad = deepcopy(carry)
            if mode == 'parameter': bad['parameters']['LOC'] = 'changed'
            else: bad['connections']['S'].pop()
            with self.assertRaises(AssertionError): proof.validate_cell(bad)

    def signals(self):
        signals = {}; wire = 100
        for name, width in proof.WIDTHS.items():
            signals[name] = list(range(wire, wire + width)); wire += width
        return signals

    def test_missing_driver_cycle_or_aliased_free_input_is_rejected(self):
        signals = self.signals()
        with self.assertRaises(AssertionError):
            proof.trace_cone(signals, lambda w: (_ for _ in ()).throw(AssertionError('missing')))
        def cycle(w):
            cell = dict(type='INV', parameters={}, connections=dict(I=[w], O=[w]), port_directions=dict(I='input', O='output'))
            return 'cycle', cell, 'O', 0
        with self.assertRaisesRegex(AssertionError, 'cyclic'): proof.trace_cone(signals, cycle)
        signals['req_addr'][0] = signals['req_addr'][1]
        with self.assertRaisesRegex(AssertionError, 'independent semantic cut'): proof.trace_cone(signals, cycle)

    def test_reference_preserves_all_four_raw_apertures_alignment_and_error_gating(self):
        text = proof.miter(self.signals(), {'a': self.cell()})
        for literal in ('10010000','100101c0','10020000','10021840','10040000','10040140','100e0000','100e01c0'):
            self.assertIn(literal, text)
        self.assertIn('wire aligned = !req_addr[0]', text)
        self.assertIn('wire expected_ready = rst_n && !rsp_valid', text)
        self.assertIn('req_valid && expected_ready && expected_mapped', text)
        self.assertIn('assign ok = actual == expected', text)
        for forbidden in ('assume','anyseq','anyconst','force'): self.assertNotIn(forbidden, text)

    def test_actual_formal_success_and_exact_real_negative_are_mandatory(self):
        proof.validate_result(proof.SUCCESS, 0, False)
        negative = proof.FAILURE + '\nERROR: Called with -verify and proof did fail!'
        proof.validate_result(negative, 1, True)
        for text, code, mode in ((proof.SUCCESS, 1, False), ('timeout reached', 0, False),
                                 (proof.FAILURE, 0, False), (negative, 0, True), (proof.SUCCESS, 0, True)):
            with self.assertRaises(AssertionError): proof.validate_result(text, code, mode)


if __name__ == '__main__': unittest.main()
