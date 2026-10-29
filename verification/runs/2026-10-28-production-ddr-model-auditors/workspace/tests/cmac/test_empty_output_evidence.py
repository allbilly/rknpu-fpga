"""Software-only metadata controls; synthetic data is never native evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from verify_empty_output_evidence import verify_metadata, POSITIVE, REASONS, probe, EXPECTED_STATUS


def metadata_fixture():
    # Deliberately synthetic: verify_qualification must still bind/recompute
    # real source/argv/log/JSON/FASM. This only exercises the metadata gate.
    return dict(status=EXPECTED_STATUS, stage='complete', finished_utc='synthetic', full_target_parallel_products=512,
        fresh_old_corruption_rejections=8, fresh_literal_corruption_rejections=8,
        production_source_before={'test_only': True}, production_source_after={'test_only': True},
        commands=[dict(label=name, expected_returncode=125 if name in REASONS else 0,
            returncode=125 if name in REASONS else 0,
            status='PASS_EXPECTED_REJECTION_ONLY' if name in REASONS else 'PASS_TOOL_EXECUTION_ONLY')
            for name in ['software_controls', 'generated_check', 'version', *REASONS, *POSITIVE]],
        valid_routes={name: dict(logical_identity=dict(logical_board=dict(cells=data[0])),
            comparison_only_port_annotations=dict(restored_empty_plain_LUT_outputs=0)) for name, data in POSITIVE.items()},
        **{key: False for key in probe.FLAGS})


class EmptyOutputEvidence(unittest.TestCase):
    def test_complete_metadata_shape_alone_is_only_a_software_fixture(self):
        verify_metadata(metadata_fixture())

    def test_running_failed_build_only_or_missing_completion_is_not_qualified(self):
        for key, value in (('status', 'RUNNING'), ('status', 'FAIL'), ('status', 'BUILT'), ('status', probe.PASS), ('stage', 'admission'), ('finished_utc', None)):
            bad = metadata_fixture(); bad[key] = value
            with self.assertRaises(AssertionError): verify_metadata(bad)

    def test_full_physical_numerical_or_execution_view_escalation_is_not_admitted(self):
        for key in probe.FLAGS:
            bad = metadata_fixture(); bad[key] = True
            with self.assertRaises(AssertionError): verify_metadata(bad)

    def test_skipped_changed_reordered_native_command_or_corruption_is_not_admitted(self):
        for kind in ('skipped', 'reordered', 'wrong_code', 'wrong_status', 'missing_route', 'count'):
            bad = metadata_fixture()
            if kind == 'skipped': bad['commands'].pop()
            elif kind == 'reordered': bad['commands'][3], bad['commands'][4] = bad['commands'][4], bad['commands'][3]
            elif kind == 'wrong_code': bad['commands'][3]['returncode'] = 0
            elif kind == 'wrong_status': bad['commands'][-1]['status'] = 'RUNNING'
            elif kind == 'missing_route': del bad['valid_routes']['v2_50']
            else: bad['fresh_literal_corruption_rejections'] = 7
            with self.assertRaises(AssertionError): verify_metadata(bad)

    def test_output_reconstruction_wrong_size_or_source_change_is_not_admitted(self):
        for kind in ('restored_output', 'size', 'source', 'target'):
            bad = metadata_fixture()
            if kind == 'restored_output': bad['valid_routes']['v2_50']['comparison_only_port_annotations']['restored_empty_plain_LUT_outputs'] = 1
            elif kind == 'size': bad['valid_routes']['v2_50']['logical_identity']['logical_board']['cells'] = 49
            elif kind == 'source': bad['production_source_after']['test_only'] = False
            else: bad['full_target_parallel_products'] = 32
            with self.assertRaises(AssertionError): verify_metadata(bad)


if __name__ == '__main__': unittest.main()
