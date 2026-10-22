"""Same packet controls, with a source-evidenced explicit false physical gate."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import assemble_physical_scope_reviewed_recursive_mux_unreviewed_bits as physical
from audit_empty_output_pairs import source_shaped

FIRST_CONTROL = ROOT / 'tests/cmac/test_reviewed_recursive_mux_full_bit_control.py'
REPLACEMENTS = (
    ('import assemble_reviewed_recursive_mux_unreviewed_bits as subject',
     'import assemble_physical_scope_reviewed_recursive_mux_unreviewed_bits as subject'),
    ('        self.assertEqual(subject.FLAGS, subject.previous.FLAGS)\n',
     "        self.assertEqual(subject.FLAGS[:-1], subject.previous.FLAGS)\n        self.assertEqual(subject.FLAGS[-1], 'physical_fit_verified')\n"),
    ("pattern = 'full-reviewed-recursive-mux-unreviewed-bit-encoding-*'",
     "pattern = 'full-reviewed-recursive-mux-physical-scope-unreviewed-bit-encoding-*'"),
)
CONTROL_SOURCE = source_shaped(FIRST_CONTROL.read_text(), REPLACEMENTS)
NAMESPACE = dict(__file__=__file__, __name__=__name__)
exec(compile(CONTROL_SOURCE, __file__ + ':same-all-packet-negatives-plus-explicit-physical-scope', 'exec'), NAMESPACE)
ExistingPacketAndCorruptionControls = NAMESPACE['ExistingPacketAndCorruptionControls']
FullUnreviewedPacketControls = NAMESPACE['FullUnreviewedPacketControls']
ReviewedFullUnreviewedPacketControls = NAMESPACE['ReviewedFullUnreviewedPacketControls']


class ExplicitPhysicalScopeControls(unittest.TestCase):
    def test_only_additional_false_report_gate_and_archival_control_identity(self):
        restored = CONTROL_SOURCE
        for old, new in reversed(REPLACEMENTS):
            self.assertEqual(restored.count(new), 1); restored = restored.replace(new, old)
        self.assertEqual(restored, FIRST_CONTROL.read_text())
        self.assertEqual(physical.FLAGS, physical.first.FLAGS + ('physical_fit_verified',))
        for name in ('verify_full_frame_metadata', 'verify_full_frame_chain', 'verify_comparison',
                     'corrupt_decoded', 'bind_report', 'verify_bindings'):
            self.assertIs(physical.NAMESPACE[name], physical.first.NAMESPACE[name])
        self.assertEqual(physical.CHAIN_SOURCE, physical.first.CHAIN_SOURCE)
        self.assertIn('**dict.fromkeys(FLAGS, False)', physical.MAIN_SOURCE)
        self.assertIn('assert all(report[key] is False for key in FLAGS)', physical.MAIN_SOURCE)
        self.assertIn('physical_fit_verified', physical.frames.FLAGS)


if __name__ == '__main__':
    unittest.main()
