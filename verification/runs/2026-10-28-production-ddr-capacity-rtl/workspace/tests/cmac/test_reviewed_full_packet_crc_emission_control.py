"""Full CRC emission admission controls, not full native/physical evidence."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import add_reviewed_full_packet_crc_candidate as subject
from test_packet_crc_emission_control import PacketCrcEmissionControl


def steps(labels, status):
    return [dict(label=label, status=status, pid=999999999,
        returncode=1 if label.startswith('negative_') else 0,
        expected_returncode=1 if label.startswith('negative_') else 0) for label in labels]


def frames():
    return dict(decoded_frames=46336, compared_words=4679936, source_frames=45892,
                zero_filled_frames=444, configuration_frame_ecc_compared=True)


def full_fixture():
    return dict(status=subject.producer.PASS, stage='complete', finished_utc='fixture-only',
        channels=32, kernels=16, full_target_parallel_products=512,
        native_target_dsps=515, native_target_brams=6, part=subject.small.reader.PART,
        full_target_seed=3588, saved_native_execution_seed=3588,
        full_target_bitstream_emitted=True, supervisor_pid=999999998,
        production_source_before={'sha256': 'fixture-only'}, production_source_after={'sha256': 'fixture-only'},
        frame_verification=frames(), commands=steps(subject.LABELS, 'PASS_TOOL_OR_CONTROL_ONLY'),
        actual_decoded_bit_negatives=[dict(word=w, rejected=True,
            expected_actual_difference=f'Decoded frame 0x0 word {w} differs:') for w in (0, 50)],
        **dict.fromkeys(subject.producer.FLAGS, False))


def qualification_fixture():
    return dict(status=subject.readback.PASS, stage='complete', finished_utc='fixture-only',
        supervisor_pid=999999998, native_decoded_bytes_identical_to_original=True,
        packet_crc_checks_match=True, fresh_all_frame_ECC_readback_verified=True,
        production_source_before={'sha256': 'fixture-only'}, production_source_after={'sha256': 'fixture-only'},
        frame_verification=frames(), commands=steps(subject.QLABELS, 'PASS_TOOL_OR_EXPECTED_CONTROL_ONLY'),
        actual_candidate_crc_negatives=[dict(role=role, rejected=True, failure='CRC mismatch at payload word 123')
            for role in ('frame_data_bit', 'CRC_word_bit')], **dict.fromkeys(subject.small.FLAGS, False))


class ReviewedFullPacketCrcControl(unittest.TestCase):
    def test_only_literal_full_target_completed_unreviewed_profile(self):
        subject.metadata(full_fixture())
        for field, value in (('status', 'RUNNING'), ('stage', 'native_full_unreviewed_packet_assembly'),
            ('finished_utc', None), ('channels', 16), ('kernels', 8), ('full_target_parallel_products', 256),
            ('native_target_dsps', 4), ('native_target_brams', 3), ('part', 'xc7k480tffg1156-1'),
            ('full_target_seed', 1), ('saved_native_execution_seed', 1), ('full_target_bitstream_emitted', False),
            ('production_source_after', {'sha256': 'different'}), ('supervisor_pid', -1)):
            changed = full_fixture(); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): subject.metadata(changed)

    def test_every_original_physical_scope_guard_is_retained(self):
        self.assertIn('physical_fit_verified', subject.producer.FLAGS)
        for field in subject.producer.FLAGS:
            changed = full_fixture(); changed[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError): subject.metadata(changed)
        self.assertTrue(set(subject.small.FLAGS).issubset(subject.FLAGS))
        self.assertIn('physical_fit_verified', subject.FLAGS)
        self.assertIn('reviewed_full_target_bitstream_emitted', subject.FLAGS)

    def test_exact_original_commands_and_actual_decoded_negatives(self):
        for field, value in (('status', 'RUNNING'), ('returncode', 0), ('expected_returncode', 0), ('pid', 0)):
            changed = full_fixture(); changed['commands'][-1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): subject.metadata(changed)
        changed = full_fixture(); changed['commands'].pop()
        with self.assertRaises(ValueError): subject.metadata(changed)
        changed = full_fixture(); changed['actual_decoded_bit_negatives'][0]['rejected'] = False
        with self.assertRaises(ValueError): subject.metadata(changed)

    def test_exact_original_frame_ECC_extent(self):
        for field, value in (('decoded_frames', 4), ('compared_words', 4679935),
            ('source_frames', 45891), ('zero_filled_frames', 443), ('configuration_frame_ecc_compared', False)):
            changed = full_fixture(); changed['frame_verification'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): subject.metadata(changed)

    def test_completed_small_native_qualification_not_fixture_or_pending_execution(self):
        subject.qualification(qualification_fixture())
        for field, value in (('status', 'RUNNING'), ('finished_utc', None),
            ('native_decoded_bytes_identical_to_original', False), ('packet_crc_checks_match', False),
            ('fresh_all_frame_ECC_readback_verified', False), ('supervisor_pid', False)):
            changed = qualification_fixture(); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): subject.qualification(changed)
        for field in subject.small.FLAGS:
            changed = qualification_fixture(); changed[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError): subject.qualification(changed)
        changed = qualification_fixture(); changed['commands'][-1]['status'] = 'RUNNING'
        with self.assertRaises(ValueError): subject.qualification(changed)
        changed = qualification_fixture(); changed['actual_candidate_crc_negatives'][0]['failure'] = 'not a CRC difference'
        with self.assertRaises(ValueError): subject.qualification(changed)

    def test_closed_workers_and_bound_producer_snapshots(self):
        subject.closed(full_fixture())
        with patch.object(subject.Path, 'exists', return_value=True), self.assertRaises(ValueError):
            subject.closed(full_fixture())
        with tempfile.TemporaryDirectory(prefix='full-crc-snapshot-control-', dir=ROOT / 'build/openxc7') as directory:
            root = Path(directory); path = root / 'report.json'
            texts = {'executed_source.py': Path(subject.producer.__file__).read_text(),
                'executed_control_source.py': subject.producer.CONTROL.read_text(),
                'executed_prepared_main.py': subject.producer.MAIN_SOURCE}
            for name, value in texts.items(): (root / name).write_text(value)
            record = dict(artifacts={str((root / name).relative_to(ROOT)): subject.digest(root / name) for name in texts})
            subject.snapshots(path, record, subject.producer, True)
            item = root / 'executed_prepared_main.py'; item.write_text('removed actual native frame checks')
            record['artifacts'][str(item.relative_to(ROOT))] = subject.digest(item)
            with self.assertRaises(ValueError): subject.snapshots(path, record, subject.producer, True)

    def test_actual_running_and_wrong_owner_CLI_reject_before_output(self):
        before = set((ROOT / 'build/openxc7').glob('full-reviewed-packet-crc-candidate-*'))
        with tempfile.TemporaryDirectory(prefix='full-crc-running-control-', dir=ROOT / 'build/openxc7') as directory:
            root = Path(directory) / 'full-reviewed-recursive-mux-physical-scope-unreviewed-bit-encoding-123'
            root.mkdir(); path = root / 'report.json'; path.write_text('{"status":"RUNNING"}')
            result = subprocess.run([sys.executable, '-B', subject.__file__, '--packet-report', str(path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Require genuinely completed reviewed full packet producer', result.stderr)
        for path in (subject.small.PARENT,
            ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json'):
            result = subprocess.run([sys.executable, '-B', subject.__file__, '--packet-report', str(path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1); self.assertIn('Wrong full packet producer ownership', result.stderr)
        self.assertEqual(set((ROOT / 'build/openxc7').glob('full-reviewed-packet-crc-candidate-*')), before)


if __name__ == '__main__':
    unittest.main()
