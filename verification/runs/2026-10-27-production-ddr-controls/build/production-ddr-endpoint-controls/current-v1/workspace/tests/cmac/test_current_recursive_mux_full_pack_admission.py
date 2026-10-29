"""Admission controls for fresh packing with a historical encoder certificate."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import build_current_recursive_mux_full_pack as current
from test_recursive_mux_full_pack_control import RecursiveMuxFullPackControls


class CurrentRecursiveMuxFullPackAdmission(unittest.TestCase):
    def test_legacy_certificate_binds_only_its_immutable_report(self):
        path = current.packer.previous.QUALIFICATION.resolve(strict=True)
        bindings = current.historical_certificate_binding(path)
        self.assertEqual(bindings, {str(path): current.packer.previous.digest(path)})

    def test_retired_system_python_is_not_a_current_pack_input(self):
        path = current.packer.previous.QUALIFICATION.resolve(strict=True)
        legacy = __import__('json').loads(path.read_text())
        old_python = '/usr/bin/python3.14'
        if old_python in legacy.get('source', {}):
            self.assertNotIn(old_python, current.historical_certificate_binding(path))


if __name__ == '__main__':
    unittest.main()
