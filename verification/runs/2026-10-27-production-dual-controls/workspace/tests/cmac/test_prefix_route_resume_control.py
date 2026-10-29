"""Controls for explicit native checkpoint annotation loss, not routing signoff."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/openxc7'))
from probe_prefix_route_resume import checkpoint_annotation_view, resume_argv, duplicate_bel_rejection
from prepare_prefix_pack_input import TOP, assert_circuit_identity

VERSION = 'native -- Next Generation Place and Route (Version controls-only)'


def fixture():
    ports = dict(SYS_CLK=dict(direction='input', bits=[2]),
        SYS_RSTN=dict(direction='input', bits=[3]), led_3bits_tri_o=dict(direction='output', bits=[4, 5, 6]))
    cells, nets = {}, {}
    for name, spec in ports.items():
        labels = [name] if len(spec['bits']) == 1 else [f'{name}[{i}]' for i in range(3)]
        for label, bit in zip(labels, spec['bits']):
            cells[label] = dict(type='PAD', parameters=dict(),
                attributes=dict(NEXTPNR_BEL=label + '/PAD', LOC=label, IOSTANDARD='LVCMOS18'),
                port_directions={'PAD': 'inout'}, connections={'PAD': [bit]})
            nets[label] = dict(bits=[bit])
    parent = dict(creator='Next Generation Place and Route (Version controls-only)',
                  modules={'top': dict(attributes={}, ports=ports, cells=cells, netnames=nets)})
    checkpoint = deepcopy(parent)
    checkpoint['modules']['top']['ports'] = {}
    return parent, checkpoint


class PrefixRouteResumeControl(unittest.TestCase):
    def test_duplicate_bel_requires_exact_source_specific_abort_not_any_failure(self):
        diagnostic = "nextpnr_himbaechel::assertion_failure\nAssertion failure: entry == nullptr (/qualified/common/kernel/base_arch.h:156)"
        duplicate_bel_rejection(-6, diagnostic)
        for code, text in ((125, diagnostic), (0, diagnostic), (-9, diagnostic),
                           (-6, 'other failure'), (-6, diagnostic.replace('entry == nullptr', 'different assertion'))):
            with self.subTest(code=code, text=text), self.assertRaises(AssertionError):
                duplicate_bel_rejection(code, text)

    def test_annotation_view_preserves_original_artifact_and_circuit(self):
        parent, checkpoint = fixture()
        original = deepcopy(checkpoint)
        view, record = checkpoint_annotation_view(checkpoint, parent, VERSION)
        self.assertEqual(checkpoint, original)
        self.assertEqual(view['modules']['top']['ports'], parent['modules']['top']['ports'])
        assert_circuit_identity(parent, view)
        self.assertFalse(record['artifact_modified'])
        self.assertFalse(record['circuit_data_changed'])
        self.assertEqual(record['comparison_annotations_restored'], 5)

    def test_all_omitted_not_partial_or_wrong_annotation_contract(self):
        for change in ('partial', 'label', 'creator', 'extra_module'):
            parent, checkpoint = fixture()
            if change == 'partial': checkpoint['modules']['top']['ports']['SYS_CLK'] = dict(direction='input', bits=[2])
            elif change == 'label': checkpoint['modules'][TOP] = checkpoint['modules'].pop('top')
            elif change == 'creator': checkpoint['creator'] = 'not-native'
            else: checkpoint['modules']['other'] = deepcopy(checkpoint['modules']['top'])
            with self.subTest(change=change), self.assertRaises(AssertionError):
                checkpoint_annotation_view(checkpoint, parent, VERSION)

    def test_changed_pad_type_properties_parameters_direction_or_connection_rejected(self):
        for change in ('type', 'properties', 'parameters', 'direction', 'connection', 'parent_net'):
            parent, checkpoint = fixture()
            pad = checkpoint['modules']['top']['cells']['SYS_CLK']
            if change == 'type': pad['type'] = 'IOB33_INBUF_EN'
            elif change == 'properties': pad['attributes']['IOSTANDARD'] = 'LVCMOS33'
            elif change == 'parameters': pad['parameters']['changed'] = '1'
            elif change == 'direction': pad['port_directions']['PAD'] = 'input'
            elif change == 'connection': pad['connections']['PAD'] = [3]
            else: parent['modules']['top']['netnames']['SYS_CLK']['bits'] = [3]
            with self.subTest(change=change), self.assertRaises(AssertionError):
                checkpoint_annotation_view(checkpoint, parent, VERSION)

    def test_annotation_only_wire_renaming_still_requires_whole_circuit_identity(self):
        parent, checkpoint = fixture()
        checkpoint['modules']['top']['cells']['SYS_CLK']['connections']['PAD'] = [22]
        checkpoint['modules']['top']['netnames']['SYS_CLK']['bits'] = [22]
        view, _ = checkpoint_annotation_view(checkpoint, parent, VERSION)
        assert_circuit_identity(parent, view)
        # Metadata restoration does not itself assert identity of other logic.
        view['modules']['top']['cells']['extra'] = deepcopy(view['modules']['top']['cells']['SYS_CLK'])
        with self.assertRaises(AssertionError): assert_circuit_identity(parent, view)

    def test_resume_has_no_repack_replace_placement_or_timing_waiver(self):
        for route in (False, True):
            argv = resume_argv('qualified-native', 'placed.json', 'top', 'literal.xdc', 'out.json', route)
            self.assertIn('--no-pack', argv)
            self.assertIn('--no-place', argv)
            self.assertIn('--Werror', argv)
            self.assertEqual(argv[argv.index('--top') + 1], 'top')
            self.assertEqual(argv[argv.index('--freq') + 1], '50')
            self.assertEqual(argv[argv.index('--device') + 1], 'xc7k480tffg1156-2')
            for flag in ('--force', '--timing-allow-fail', '--ignore-loops', '--pack-only', '--fasm'):
                self.assertNotIn(flag, argv)
            self.assertEqual('--no-route' in argv, not route)


if __name__ == '__main__':
    unittest.main()
