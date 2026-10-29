"""Same full-review controls with valid-pack native-refinement negative."""
import inspect
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import test_recursive_mux_completed_placement_review_control as previous
import review_valid_pack_recursive_mux_completed_placement as reviewer


class ValidPackReviewControls(previous.CompletedPlacementReviewControls):
    def test_native_completion_failure_not_masked_by_log_scope(self):
        # Valid fixture reaches the intended guard; no native run is claimed.
        packed = json.loads((ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json').read_text())
        with patch.object(previous.review.placement, 'check_heap_log', side_effect=AssertionError('Missing normal refinement')) as native:
            with self.assertRaisesRegex(AssertionError, 'Missing normal refinement'):
                previous.review.fresh_log_checks('incomplete', packed, {})
            native.assert_called_once_with(0, 'incomplete')

    def test_invalid_pack_still_rejected_before_native_phase_guard(self):
        with patch.object(previous.review.placement, 'check_heap_log') as native:
            with self.assertRaises(KeyError): previous.review.fresh_log_checks('incomplete', {}, {})
            native.assert_not_called()

    def test_valid_pack_fixture_variant_preserves_every_runtime_guard(self):
        restored = reviewer.MAIN_SOURCE
        for old, new in reversed(reviewer.REPLACEMENTS):
            self.assertEqual(restored.count(new), 1); restored = restored.replace(new, old)
        self.assertEqual(restored, inspect.getsource(reviewer.previous.main))
        for name in ('verify_parent_metadata', 'verify_scope_metadata', 'fresh_log_checks',
                     'verify_complete_output', 'bind_report', 'source_revision'):
            self.assertIs(reviewer.NAMESPACE[name], getattr(reviewer.previous, name))
        self.assertEqual(reviewer.REVIEWED, reviewer.previous.REVIEWED)
