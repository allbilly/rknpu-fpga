from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import audit_native_mux_cluster_geometry as subject


class Control(unittest.TestCase):
    def bels(self):
        return {z:dict(name=str(z), type='SELMUX2_1' if z in (7, 8, 39) else 'SLICE_LUTX')
                for z in (0, 7, 8, 16, 32, 39, 48)}

    def rows(self):
        return [dict(name=str(z), type='SELMUX2_1' if z in (0, 31, -1) else 'SLICE_LUTX', z=z)
                for z in (0, 31, -1, -8, 8, 24, 40)]

    def test_valid_f8_geometry_has_candidate(self):
        compatible = [c for c in subject.candidate_geometry(self.rows(), self.bels()) if not c['missing']]
        self.assertEqual([c['root_z'] for c in compatible], [8])

    def test_extra_mux_level_is_not_geometry(self):
        rows = self.rows() + [dict(name='extra', type='SELMUX2_1', z=47)]
        self.assertFalse(any(not c['missing'] for c in subject.candidate_geometry(rows, self.bels())))

    def test_duplicate_offset_not_silently_accepted(self):
        with self.assertRaises(AssertionError):
            subject.candidate_geometry(self.rows() + [dict(name='alias', type='SLICE_LUTX', z=40)], self.bels())

    def test_actual_snapshot_and_changed_claims(self):
        original = subject.SNAPSHOT.read_text()
        self.assertEqual(len(subject.snapshot_rows(original)), 9)
        for bad in (original.replace('children=8', 'children=7'),
                    original.replace('abs_z=false', 'abs_z=true', 1),
                    original.replace('relative=(0,0,31)', 'relative=(1,0,31)'),
                    original.replace('[Inferior 1 (process 1467616) detached]', 'not detached')):
            with self.assertRaises(AssertionError): subject.snapshot_rows(bad)


if __name__ == '__main__':
    unittest.main()
