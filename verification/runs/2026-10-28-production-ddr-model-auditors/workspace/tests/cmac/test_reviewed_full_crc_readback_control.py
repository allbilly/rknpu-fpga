"""Prepared full CRC readback controls; metadata fixtures are not FPGA proof."""
import copy
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import check_reviewed_full_crc_native_readback as subject
from test_crc_candidate_native_readback_control import CrcCandidateReadbackControl, fixture as small_fixture


def fixture():
    result = small_fixture()
    result.update(status=subject.EMITTED, native_target_dsps=515, native_target_brams=6,
        parallel_products=512, channels=32, kernels=16, intended_clock_period_ns=20, seed=3588,
        production_source_before={'sha256': 'fixture-only'}, production_source_after={'sha256': 'fixture-only'})
    del result['native_control_dsps'], result['native_control_brams'], result['full_target_parallel_products']
    result.update(dict.fromkeys(subject.full.FLAGS, False))
    return result


class ReviewedFullCrcReadbackControl(unittest.TestCase):
    def test_all_original_native_frame_ECC_crc_and_real_negative_steps_preserved(self):
        for actual, replacements, expected in ((subject.MAIN_SOURCE, subject.REPLACEMENTS, inspect.getsource(subject.previous.main)),
            (subject.METADATA_SOURCE, subject.METADATA_REPLACEMENTS, inspect.getsource(subject.previous.metadata))):
            restored = actual
            for old, new in reversed(replacements):
                self.assertEqual(restored.count(new), 1); restored = restored.replace(new, old)
            self.assertEqual(restored, expected)
        for name in ('comparison', 'corrupt', 'verify_bindings', 'source_revision'):
            self.assertIs(subject.NAMESPACE[name], subject.previous.__dict__[name])
        for marker in ("run('native_crc_candidate_decode'", "digest(decoded) == old['artifacts']",
            "run('fresh_all_frame_data_and_ECC'", "run('fresh_candidate_packet_crc'",
            "(('frame_data_bit', 2), ('CRC_word_bit', 0))", 'corrupt(candidate.read_bytes(), register)',
            "result['error'].startswith('CRC mismatch at payload word ')", 'verify_bindings(before)'):
            self.assertEqual(subject.MAIN_SOURCE.count(marker), inspect.getsource(subject.previous.main).count(marker))
            self.assertGreater(subject.MAIN_SOURCE.count(marker), 0)
        self.assertIn("'Conflicting original source binding'", subject.MAIN_SOURCE)
        self.assertIn('full.snapshots(path, emitted, full)', subject.MAIN_SOURCE)

    def test_only_completed_literal_full_profile_and_source_accepted(self):
        subject.metadata(fixture())
        for field, value in (('status', 'RUNNING'), ('stage', 'crc_only_transform'), ('finished_utc', None),
            ('native_target_dsps', 4), ('native_target_brams', 3), ('parallel_products', 256), ('channels', 16),
            ('kernels', 8), ('intended_clock_period_ns', 40), ('seed', 1), ('packet_crc_checks_match', False),
            ('production_source_after', {'sha256': 'different'})):
            changed = fixture(); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): subject.metadata(changed)

    def test_all_scope_and_complete_packet_guards_retained(self):
        for field in subject.full.FLAGS:
            changed = fixture(); changed[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError): subject.metadata(changed)
        for field, value in (('original_packet_count', 545), ('candidate_payload_bytes', 18735004),
            ('original_payload_projection_byte_identical', False), ('original_header_except_length_byte_identical', False)):
            changed = fixture(); changed['crc_only_byte_transform'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): subject.metadata(changed)
        for field, value in (('fdri_words', 3), ('crc_checks', [{}]), ('test_ready_bitstream', True)):
            changed = fixture(); changed['crc_only_byte_transform']['crc_verification'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): subject.metadata(changed)

    def test_actual_running_or_wrong_owner_cannot_start_native_readback(self):
        pattern = 'full-reviewed-crc-packet-native-readback-*'
        before = set((ROOT / 'build/openxc7').glob(pattern))
        with tempfile.TemporaryDirectory(prefix='full-crc-readback-running-control-', dir=ROOT / 'build/openxc7') as directory:
            root = Path(directory) / 'full-reviewed-packet-crc-candidate-123'
            root.mkdir(); path = root / 'report.json'; path.write_text('{"status":"RUNNING"}')
            result = subprocess.run([sys.executable, '-B', subject.__file__, '--candidate-report', str(path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1); self.assertIn('Require genuinely completed full CRC-only emitter', result.stderr)
        path = ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json'
        result = subprocess.run([sys.executable, '-B', subject.__file__, '--candidate-report', str(path)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1); self.assertIn('Wrong producer ownership', result.stderr)
        self.assertEqual(set((ROOT / 'build/openxc7').glob(pattern)), before)


if __name__ == '__main__':
    unittest.main()
