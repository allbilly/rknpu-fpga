"""Private diagnostic contracts, not native/physical acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools')]
import probe_native_pack_clusters as probe


def fixture():
    rows = [dict(kind='header', schema=1, cells=3, pack_checksum='1234abcd'),
            dict(kind='cell', name='root', type='CARRY4', cluster='root', x=0, y=0, z=0,
                 abs_z=True, children=['child']),
            dict(kind='cell', name='child', type='CARRY4', cluster='root', x=0, y=1, z=0,
                 abs_z=False, children=[]),
            dict(kind='cell', name='singleton', type='SLICE_LUTX', cluster='', x=0, y=0, z=0,
                 abs_z=False, children=[]),
            dict(kind='footer', cells=3, pack_checksum='1234abcd')]
    packed = {'modules': {'test': {'cells': {r['name']: {'type': r['type']} for r in rows[1:-1]},
                                  'settings': {'pack': '1', 'place': '0', 'route': '0'}}}}
    return rows, packed


class ClusterProbeControls(unittest.TestCase):
    def read(self, rows, packed):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'metadata.jsonl'
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            return probe.read_metadata(path, packed)

    def test_preserves_actual_linked_source_not_upstream(self):
        source = probe.ARCH_SOURCE.read_text()
        changed = probe.candidate_source(source)
        probe.verify_source_transition(source, changed)
        self.assertIn('lut-pair-engine-', str(probe.ARCH_SOURCE))
        self.assertEqual(probe.ARCH_OBJECT.name, 'arch.cc.o')
        self.assertIn('O_EXCL', changed)
        self.assertIn('NPNR_ASSERT(before == after', changed)

    def test_unrelated_change_or_missing_anchor_rejected(self):
        source = probe.ARCH_SOURCE.read_text()
        changed = probe.candidate_source(source)
        with self.assertRaises(AssertionError):
            probe.verify_source_transition(source, changed.replace('uarch->pack();', '/* removed */'))
        with self.assertRaises(AssertionError):
            probe.candidate_source(source.replace(probe.OPTION_OLD, ''))

    def test_original_flags_and_typed_recipe_retained(self):
        flags = (probe.CMAKE / 'flags.make').read_text()
        recipe = (probe.CMAKE / 'build.make').read_text()
        argv = probe.compile_argv(Path('/private/arch.cc'), Path('/private/arch.cc.o'), flags, recipe)
        self.assertIn('-O3', argv)
        self.assertIn('-DNO_PYTHON', argv)
        self.assertEqual(argv[-2:], ['-c', '/private/arch.cc'])
        with self.assertRaises(AssertionError):
            probe.compile_argv(Path('/private/arch.cc'), Path('/private/arch.cc.o'), flags,
                               recipe.replace(' -c /home/fedora/tiny-gpu/', ' -c /wrong/'))

    def test_exact_absolute_z_and_nonzero_xy_export(self):
        rows, packed = fixture()
        result = self.read(rows, packed)
        self.assertEqual((result['cells'], result['cluster_roots'], result['cluster_children']), (3, 1, 1))
        self.assertEqual((result['absolute_z_cells'], result['nonzero_xy_cells']), (1, 1))
        self.assertFalse(result['geometry_fit_checked'])
        self.assertFalse(result['full_placement_or_timing_acceptance'])

    def test_bad_census_checksum_schema_and_stage_rejected(self):
        rows, packed = fixture()
        for case in ('census', 'checksum', 'schema', 'stage', 'unknown', 'duplicate', 'missing_cell'):
            modified, graph = deepcopy(rows), deepcopy(packed)
            if case == 'census': modified[-1]['cells'] = 2
            elif case == 'checksum': modified[-1]['pack_checksum'] = 'ffffffff'
            elif case == 'schema': modified[0]['schema'] = 2
            elif case == 'stage': graph['modules']['test']['settings']['place'] = '1'
            elif case == 'unknown': modified[1]['ignored_constraint'] = 1
            elif case == 'duplicate': modified[2]['name'] = 'root'
            else: del graph['modules']['test']['cells']['singleton']
            with self.subTest(case=case), self.assertRaises((AssertionError, KeyError)):
                self.read(modified, graph)

    def test_bad_membership_offsets_and_boolean_policy_rejected(self):
        rows, packed = fixture()
        for case in ('missing_root', 'abs_z', 'x', 'child', 'children', 'self_child', 'unclustered'):
            modified = deepcopy(rows)
            if case == 'missing_root': modified[2]['cluster'] = 'missing'
            elif case == 'abs_z': modified[2]['abs_z'] = 1
            elif case == 'x': modified[2]['x'] = True
            elif case == 'child': modified[1]['children'] = []
            elif case == 'children': modified[1]['children'] = ['child', 'child']
            elif case == 'self_child': modified[1]['children'] = ['root']
            else: modified[1]['cluster'] = ''
            with self.subTest(case=case), self.assertRaises((AssertionError, KeyError)):
                self.read(modified, packed)

    def test_never_promotes_diagnostic_to_acceptance(self):
        self.assertIn('SMALL', probe.STATUS)
        self.assertIn('NOT_FULL_PLACEMENT_OR_SIGNOFF', probe.STATUS)
        for flag in ('full_native_placement_executed', 'native_routing_executed', 'physical_fit_verified',
                     'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
            self.assertIn(flag, probe.FLAGS)


if __name__ == '__main__':
    unittest.main()
