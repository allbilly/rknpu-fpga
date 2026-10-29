"""Prepared full unreviewed packet controls, not assembly or FPGA results."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(Path(__file__).parent)]
import assemble_recursive_mux_shared_unreviewed_bits as subject
import test_native_heap_bit_encoding_control as old

ExistingPacketAndCorruptionControls = old.Control


def metadata():
    # Pure metadata-only fabricated fixture, not a full converted frame result.
    clocks = {'HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0': {'host-only': True}}
    readback = dict(features_compared=8240, physical_DB_bits_compared=8240,
        locations={f'host-only-feature-{i}': [] for i in range(8240)},
        actual_frame_bit_corruption_rejected_in_comparison_only=True,
        all_set_and_clear_requirements_matched=True,
        database_consistency_only_not_silicon_or_independent_specification=True)
    clock = dict(readback, features_compared=1, physical_DB_bits_compared=1, locations={next(iter(clocks)): []})
    return dict(status=subject.frames.PASS, stage='complete', finished_utc='host-only metadata',
        channels=32, kernels=16, parallel_products=512, part='xc7k480tffg1156-2',
        intended_clock_period_ns=20, seed=3588, full_board_FASM_conversion_executed=True,
        production_source_before='test-only', production_source_after='test-only',
        source_defined_DSP_features=8240, source_defined_native_statements=9000,
        converter_requests=dict(input_lines=9000, injected_lines=100), clock_contracts=clocks,
        DSP_frame_readback=readback, clock_frame_readback=clock,
        frame_geometry=dict(legal_target_frames=46336, supplied_frames=45892, tilegrid_frames=45892,
                            missing_frames_zero_filled_by_assembler=444),
        commands=[dict(label=label, status='PASS_TOOL_EXECUTION_ONLY', returncode=0, expected_returncode=0)
            for label in ('software_controls','generated_check','parser_runtime_version','strict_full_native_FASM_conversion',
                          'exact_part_frame_geometry','DSP_frame_readback','clock_frame_readback')],
        **dict.fromkeys(subject.frames.FLAGS, False))


class FullUnreviewedPacketControls(unittest.TestCase):
    def test_same_packet_ECC_corruption_gates_and_literal_input(self):
        source = subject.MAIN_SOURCE
        for before, after in reversed(subject.REPLACEMENTS):
            self.assertEqual(source.count(after), 1)
            source = source.replace(after, before)
        self.assertEqual(source, inspect.getsource(subject.previous.main))
        for name in ('verify_comparison', 'corrupt_decoded', 'bind_report', 'verify_bindings'):
            self.assertIs(subject.NAMESPACE[name], getattr(subject.previous, name))
        for marker in ('donor.verified_frame_tools(', "run('native_frames_to_bit'", "'--frm_file', frames",
            "run('native_decode_frames'", "run('all_frame_data_and_ECC'", "(('data_bit', 0), ('ECC_bit', 50))",
            'donor.check_sources(frame.TOOL)', 'verify_bindings(before)', 'configuration_crc_verified'):
            self.assertEqual(subject.MAIN_SOURCE.count(marker), inspect.getsource(subject.previous.main).count(marker))
            if marker != 'configuration_crc_verified': self.assertGreater(subject.MAIN_SOURCE.count(marker), 0)
        self.assertLess(subject.MAIN_SOURCE.index('verify_full_frame_chain('), subject.MAIN_SOURCE.index("run('native_frames_to_bit'"))
        self.assertIn('full-C32K16.NOT_FOR_PROGRAMMING.unverified.bit', subject.MAIN_SOURCE)

    def test_full_metadata_not_small_scope_or_overclaim(self):
        good = metadata(); saved = deepcopy(good)
        subject.verify_full_frame_metadata(good); self.assertEqual(good, saved)
        for field, value in (('status','RUNNING'), ('status',subject.previous.parent.small.PASS),
            ('stage','native_conversion'), ('finished_utc',None), ('parallel_products',256),
            ('kernels',8), ('channels',16), ('part','xc7k480tffg1156-1'), ('seed',1),
            ('intended_clock_period_ns',40), ('full_board_FASM_conversion_executed',False),
            ('production_source_after','changed'), ('source_defined_DSP_features',64), ('clock_contracts',{})):
            wrong = deepcopy(good); wrong[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): subject.verify_full_frame_metadata(wrong)
        for field in subject.frames.FLAGS:
            wrong = deepcopy(good); wrong[field] = True
            with self.subTest(flag=field), self.assertRaises(AssertionError): subject.verify_full_frame_metadata(wrong)

    def test_readback_counts_actual_negatives_geometry_and_commands_required(self):
        good = metadata()
        for field in ('DSP_frame_readback','clock_frame_readback'):
            for key, value in (('features_compared',64), ('physical_DB_bits_compared',64), ('locations',{}),
                ('actual_frame_bit_corruption_rejected_in_comparison_only',False),
                ('all_set_and_clear_requirements_matched',False),
                ('database_consistency_only_not_silicon_or_independent_specification',False)):
                wrong = deepcopy(good); wrong[field][key] = value
                with self.subTest(field=field,key=key), self.assertRaises(AssertionError): subject.verify_full_frame_metadata(wrong)
        for key in good['frame_geometry']:
            wrong = deepcopy(good); wrong['frame_geometry'][key] -= 1
            with self.subTest(key=key), self.assertRaises(AssertionError): subject.verify_full_frame_metadata(wrong)
        for key, value in (('status','RUNNING'), ('returncode',1), ('expected_returncode',1)):
            wrong = deepcopy(good); wrong['commands'][-1][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): subject.verify_full_frame_metadata(wrong)
        wrong = deepcopy(good); wrong['commands'].pop()
        with self.assertRaises(AssertionError): subject.verify_full_frame_metadata(wrong)
        wrong = deepcopy(good); wrong['converter_requests']['input_lines'] += 1
        with self.assertRaises(AssertionError): subject.verify_full_frame_metadata(wrong)

    def test_every_actual_route_request_frame_bit_recheck_precedes_assembly(self):
        source = inspect.getsource(subject.verify_full_frame_chain)
        for marker in ('frames.admission.verify_route(', 'previous.bind_report(', 'required_features',
                       'validate_conversion(', 'verify_requests(', 'verify_clock_requests(',
                       "json.loads(output.read_text()) == saved[label]", 'previous.verify_bindings(before)',
                       "namespace['dsp_readback']", "namespace['small'].clock_readback"):
            self.assertIn(marker, source)
        self.assertIs(subject.NAMESPACE['verify_full_frame_chain'], subject.verify_full_frame_chain)
        self.assertNotIn('full_target_bitstream_emitted', subject.FLAGS)
        for flag in ('test_ready_bitstream','reviewed_full_target_bitstream_emitted','numerical_acceptance',
                     'timing_signoff','electrical_verified','drc_signoff','configuration_crc_verified','hardware_programmed'):
            self.assertIn(flag, subject.FLAGS)
        self.assertIn("report['full_target_bitstream_emitted'] = True", subject.MAIN_SOURCE)

    def test_incomplete_small_or_old_frame_profile_cannot_create_output(self):
        prefix = 'full-recursive-mux-shared-unreviewed-bit-encoding-*'
        before = set((ROOT/'build/openxc7').glob(prefix))
        for path in (subject.previous.SMALL,
            ROOT/'build/openxc7/recursive-mux-feedthrough-qualification-1791497608027018932/report.json'):
            result = subprocess.run([sys.executable,'-B',subject.__file__,'--frames-report',str(path)],
                                    capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,1); self.assertIn('AssertionError',result.stderr)
        with tempfile.TemporaryDirectory(prefix='full-recursive-mux-shared-native-heap-frames-control-',dir=ROOT/'build/openxc7') as directory:
            path = Path(directory)/'report.json'; path.write_text('{"status":"RUNNING"}')
            result = subprocess.run([sys.executable,'-B',subject.__file__,'--frames-report',str(path)],
                                    capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,1); self.assertIn('AssertionError',result.stderr)
        self.assertEqual(set((ROOT/'build/openxc7').glob(prefix)),before)


if __name__ == '__main__':
    unittest.main()
