"""Keep all native qualification controls; small probe cannot accept failed builds."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import probe_recursive_mux_native_placement as probe
from test_mux_feedthrough_candidate_control import completed
from test_recursive_mux_qualification_control import (RecursiveMuxQualificationControls,
    CounterSafeQualificationControls, ExistingNativeGuards)


class PlacementProbeControls(unittest.TestCase):
    def test_incomplete_or_failed_build_rejected_before_bindings_or_tool(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-mux-probe-admission-control-') as directory:
            root = Path(directory)
            path = root / 'build/openxc7/recursive-mux-feedthrough-native-io-engine-control/report.json'
            path.parent.mkdir(parents=True)
            with patch.object(probe, 'ROOT', root), patch.object(probe.qualification, 'verify_bindings') as bindings:
                for key, value in (('status', 'RUNNING'), ('status', 'FAIL_RECURSIVE_MUX_FEEDTHROUGH_BUILD_OR_PACK_PROBE'),
                                   ('stage', 'compile'), ('finished_utc', None), ('changed_link_objects', 2),
                                   ('qualified_parent_relinked_byte_identical', False), ('part', 'xc7a100t')):
                    value_report = completed(); value_report[key] = value
                    path.write_text(json.dumps(value_report))
                    with self.subTest(key=key), self.assertRaises(AssertionError): probe.admit_completed_build(path)
                    bindings.assert_not_called()


if __name__ == '__main__':
    unittest.main()
