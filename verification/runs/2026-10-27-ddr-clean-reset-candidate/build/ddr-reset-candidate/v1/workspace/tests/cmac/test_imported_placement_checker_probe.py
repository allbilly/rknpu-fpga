"""Native-probe admission/log/corruption controls; no native execution."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from probe_imported_placement_checker import (BUILT, NATIVE, REASONS, TAG_SOURCE, OLD_OBJECT,
    verify_build_metadata, corrupt_checkpoint, scan_log)
from audit_postplace_lut_pairs import audit_pairs


class ImportedPlacementCheckerProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads((NATIVE.parent / 'valid-forced-placed.json').read_text())

    def build(self):
        flags = ('native_requalification_executed', 'full_placement_transfer_admitted', 'physical_fit_verified',
                 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed')
        return dict(status=BUILT, stage='complete', finished_utc='software fixture only',
            changed_objects_relative_to_corrected_encoder=1, corrected_parent_relink_byte_identical=True,
            original_source_and_old_assertions_preserved=True, actual_original_source=str(TAG_SOURCE), actual_original_object=str(OLD_OBJECT),
            preexisting_prerouted_loop_index_corrected_to_API_size_t=True, warning_checks_suppressed=False,
            production_source_before={'test': 'same'}, production_source_after={'test': 'same'},
            commands=[dict(label=n, status='PASS_TOOL_EXECUTION_ONLY', returncode=0) for n in
                ('software_controls', 'generated_check', 'compiler_version', 'relink_corrected_parent_identity',
                 'compile_imported_placement_probe', 'link_imported_placement_probe', 'native_version')],
            **{key: False for key in flags})

    def test_build_only_profile_and_command_contract(self):
        verify_build_metadata(self.build())
        for key, value in (('status', 'RUNNING'), ('stage', 'build'), ('changed_objects_relative_to_corrected_encoder', 2),
                           ('corrected_parent_relink_byte_identical', False), ('actual_original_object', '/wrong/object'),
                           ('warning_checks_suppressed', True), ('preexisting_prerouted_loop_index_corrected_to_API_size_t', False)):
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_build_metadata({**self.build(), key: value})

    def test_build_cannot_claim_qualification_or_physical_acceptance(self):
        for key in ('native_requalification_executed', 'full_placement_transfer_admitted', 'physical_fit_verified',
                    'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_build_metadata({**self.build(), key: True})

    def test_missing_or_failed_actual_build_commands_fail(self):
        for change in ('missing', 'returncode', 'status', 'source'):
            built = self.build()
            if change == 'missing': built['commands'].pop()
            elif change == 'returncode': built['commands'][0]['returncode'] = 1
            elif change == 'status': built['commands'][0]['status'] = 'RUNNING'
            else: built['production_source_after'] = {'test': 'different'}
            with self.subTest(change=change), self.assertRaises(AssertionError): verify_build_metadata(built)

    def test_actual_saved_positive_has_nine_pairs_and_known_naive_union(self):
        result = audit_pairs(next(iter(self.original['modules'].values())))
        self.assertEqual(result['logic_pairs_compared'], 9)
        self.assertEqual(result['six_input_naive_tag_unions'], 1)
        self.assertFalse(result['native_validity_rescan_executed'])

    def test_all_corruptions_are_separate_copies_of_the_actual_saved_checkpoint(self):
        saved = deepcopy(self.original)
        for kind in REASONS:
            bad = corrupt_checkpoint(self.original, kind)
            self.assertNotEqual(bad, self.original)
            self.assertEqual(self.original, saved)
            self.assertEqual(set(next(iter(bad['modules'].values()))['cells']), set(next(iter(saved['modules'].values()))['cells']))

    def test_unknown_case_and_routed_stage_fail(self):
        with self.assertRaises(AssertionError): corrupt_checkpoint(self.original, 'unsupported')
        for route in ('1', '00000000000000000000000000000001', 'x'):
            bad = deepcopy(self.original); next(iter(bad['modules'].values()))['settings']['route'] = route
            with self.subTest(route=route), self.assertRaises(AssertionError): corrupt_checkpoint(bad, 'logical_A6')

    def good_log(self):
        return ('Info: RKNPU imported placement scan: begin before clock/general routing.\n'
                'Info: RKNPU imported placement scan: passed 49 bound cells and 9 fixed logic pairs; original tags restored and caches invalidated.\n'
                'Info: Running router1 to check that route is legal...\nInfo: Routing complete.\n'
                'Info: Running post-routing legalisation...\nInfo: Program finished normally.\n')

    def test_success_requires_real_scan_route_markers_counts_and_order(self):
        good = self.good_log(); scan_log(0, good, 49, 9)
        for bad in (good.replace('passed 49', 'passed 48'), good.replace('9 fixed', '8 fixed'),
                    good.replace('original tags restored and caches invalidated.', 'not restored'),
                    good.replace('Running router1 to check that route is legal...', 'omitted'), good + 'WARNING: unexpected\n',
                    good + 'ERROR: unexpected\n', good + good):
            with self.subTest(length=len(bad)), self.assertRaises(AssertionError): scan_log(0, bad, 49, 9)
        with self.assertRaises(AssertionError): scan_log(125, good, 49, 9)

    def test_rejection_must_execute_scan_and_stop_before_routing(self):
        for reason in REASONS.values():
            bad = ('Info: RKNPU imported placement scan: begin before clock/general routing.\n'
                   'ERROR: RKNPU imported placement scan: ' + reason + '.\n')
            scan_log(125, bad, rejection=reason)
            for code, text in ((0, bad), (125, bad + 'Info: Routing complete.\n'),
                               (125, bad + 'Info: Running router2...\n'), (125, bad.replace(reason, 'wrong failure'))):
                with self.subTest(reason=reason, code=code), self.assertRaises(AssertionError): scan_log(code, text, rejection=reason)


if __name__ == '__main__':
    unittest.main()
