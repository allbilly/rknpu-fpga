"""Full DSP-area structural controls, not a real full-array mapping result."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import map_dsp_array as runner


def ports():
    result = {}; offset = 2
    for direction, fields in [('input', runner.INPUTS), ('output', runner.OUTPUTS)]:
        for name, width in fields.items():
            result[name] = dict(direction=direction, bits=list(range(offset, offset + width)))
            offset += width
    return result


def elaborated():
    return {'modules': {runner.TOP: dict(ports=ports(), cells={f'k{i}': {'type': 'kernel'} for i in range(16)}),
        'kernel': dict(attributes={'hdlname': runner.CELL, 'keep_hierarchy': '1'},
            cells={f'l{i}': {'type': runner.LANE} for i in range(32)}),
        runner.LANE: {'cells': {}}}}


def mapped():
    modules = {runner.TOP: dict(ports=ports(), cells={f'k{i}': {'type': 'kernel'} for i in range(16)}),
        'kernel': dict(attributes={'hdlname': runner.CELL, 'keep_hierarchy': '1'},
            cells={**{f'd{i}': {'type': 'DSP48E1'} for i in range(32)},
                'lut': {'type': 'LUT6'}, **{f'f{i}': {'type': 'FDCE'} for i in range(35)}})}
    for kind in ('DSP48E1', 'LUT6', 'FDCE'):
        modules[kind] = dict(attributes={'blackbox': '1'}, cells={})
    return {'modules': modules}


class DspArrayAreaControls(unittest.TestCase):
    def test_all_parallel_products_and_kernels_required(self):
        original = elaborated(); runner.validate_elaboration(original)
        for mutation in ('kernel', 'lane', 'hierarchy', 'cycle'):
            design = deepcopy(original)
            if mutation == 'kernel': design['modules'][runner.TOP]['cells'].pop('k15')
            elif mutation == 'lane': design['modules']['kernel']['cells'].pop('l31')
            elif mutation == 'hierarchy': design['modules']['kernel']['attributes']['keep_hierarchy'] = '0'
            else: design['modules']['kernel']['cells']['loop'] = {'type': 'kernel'}
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.validate_elaboration(design)

    def test_exact_full_boundary_and_independent_inputs(self):
        original = elaborated()['modules'][runner.TOP]; runner.validate_ports(original)
        for mutation in ('constant', 'coupled', 'narrow', 'extra', 'output'):
            module = deepcopy(original)
            if mutation == 'constant': module['ports']['in_data']['bits'][0] = '0'
            elif mutation == 'coupled': module['ports']['in_weight']['bits'][0] = module['ports']['in_data']['bits'][0]
            elif mutation == 'narrow': module['ports']['in_weight']['bits'].pop()
            elif mutation == 'extra': module['ports']['tensor_op'] = dict(direction='input', bits=[123456])
            else: module['ports']['out_groups']['bits'][0] = '0'
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.validate_ports(module)

    def test_kernel_dsp_count_and_flattened_counts_must_match(self):
        original = mapped(); counts, audit, kinds = runner.validate_partition(original)
        self.assertEqual(counts, Counter(DSP48E1=512, LUT6=16, FDCE=560)); self.assertEqual(audit, [])
        self.assertEqual(len(kinds), 16)
        flat = deepcopy(original)
        flat['modules'][runner.TOP]['cells'] = {f'{i}_{n}': deepcopy(c) for i in range(16)
            for n, c in original['modules']['kernel']['cells'].items()}
        self.assertEqual(runner.validate_flat(flat, counts)[0], counts)
        changed = deepcopy(original); changed['modules']['kernel']['cells'].pop('d31')
        with self.assertRaises(AssertionError): runner.validate_partition(changed)
        flat['modules'][runner.TOP]['cells'].pop('0_d0')
        with self.assertRaises(AssertionError): runner.validate_flat(flat, counts)

    def test_unknown_hardware_and_nonblackbox_primitives_rejected(self):
        original = mapped()
        for kind in ('$mul', '$memrd', 'native_lane'):
            changed = deepcopy(original); changed['modules']['kernel']['cells']['unknown'] = {'type': kind}
            with self.subTest(kind=kind), self.assertRaises(AssertionError): runner.validate_partition(changed)
        changed = deepcopy(original); changed['modules']['DSP48E1']['attributes']['blackbox'] = '0'
        with self.assertRaises(AssertionError): runner.validate_partition(changed)

    def test_mapping_flow_preserves_full_width_and_omits_only_optional_share(self):
        help_text = "'keep_hierarchy' attribute set will not be\n    coarse:\n" + '\n'.join(runner.COARSE) + '\n    map_memory:\n'
        coarse = runner.unshared_coarse(help_text)
        self.assertEqual(coarse, [c.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for c in runner.COARSE if c != 'share'])
        script = runner.mapping_script([Path('lane.sv')], Path('/tmp/dsp-array-fixture'), coarse)
        self.assertIn('chparam -set ATOMIC_C 32 -set ATOMIC_K 16', script)
        self.assertIn('select -assert-count 16', script)
        self.assertLess(script.index('setattr -mod -set keep_hierarchy'), script.index('synth_xilinx'))
        self.assertLess(script.index('mapped_hierarchy.json'), script.index('setattr -mod -unset keep_hierarchy'))
        self.assertNotIn(';\nshare;', script); self.assertNotIn('-nodsp', script)
        self.assertIn('-run begin:coarse', script)
        self.assertNotIn('-run begin:map_dsp', script)
        self.assertLess(script.index('select -assert-count 32 */t:DSP48E1'), script.index(coarse[0]))
        with self.assertRaises(AssertionError): runner.unshared_coarse(help_text.replace('memory -nomap', 'memory'))

    def test_only_source_bound_donor_array_lowering_notices_allowed(self):
        donor = ROOT / 'rtl/vendor/nvdla/NV_DW02_tree.v'
        warning = f'Warning: Replacing memory \\temp_array with list of registers. See {donor}:41, {donor}:33'
        marker = '6.20. Executing XILINX_DSP pass (packing DSPs).'
        self.assertEqual(runner.audit_mapping_log(marker + '\n' + warning), [warning])
        for text in ('Warning: Resizing RAM port', warning.replace(':41', ':42'),
                'ERROR: missing DSP', 'Executing SHARE pass'):
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.audit_mapping_log(marker + '\n' + text)
        for text in (warning, marker + '\n' + marker):
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.audit_mapping_log(text)


if __name__ == '__main__': unittest.main()
