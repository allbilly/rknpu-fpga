"""Admission/corruption controls, not native frame execution or physical evidence."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import check_crc_candidate_native_readback as checked
import add_packet_crc_candidate as emitter
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_packet_crc_control import wrap
from test_packet_crc_emission_control import native


def fixture():
    result = dict(status=checked.EMITTED, stage='complete', finished_utc='fixture-only',
        part=emitter.reader.PART, native_control_dsps=4, native_control_brams=6,
        full_target_parallel_products=512, packet_crc_checks_match=True,
        all_parent_packet_sources_revalidated=True, **dict.fromkeys(emitter.FLAGS, False))
    result['crc_only_byte_transform'] = dict(original_packet_count=546,
        original_payload_bytes=18735004, candidate_payload_bytes=18735020,
        crc_insertions=[{}, {}], original_payload_projection_byte_identical=True,
        original_header_except_length_byte_identical=True,
        crc_verification=dict(status='PASS_SOFTWARE_PACKET_CRC_ONLY_NOT_SIGNOFF_OR_TEST_READY',
            part=emitter.reader.PART, idcode=emitter.reader.IDCODE, fdri_words=emitter.WORDS,
            crc_checks=[{}, {}], packet_crc_checks_match=True,
            **dict.fromkeys(('physical_configuration_crc_verified', 'timing_signoff', 'electrical_verified',
                'drc_signoff', 'numerical_acceptance', 'full_target_acceptance', 'test_ready_bitstream',
                'hardware_accessed', 'input_modified'), False)))
    return result


class CrcCandidateReadbackControl(unittest.TestCase):
    def test_metadata_only_valid_fixture(self):
        checked.metadata(fixture())

    def test_incomplete_or_other_profile_rejected(self):
        for key, value in (('status', 'RUNNING'), ('stage', 'crc_only_transform'),
                           ('finished_utc', None), ('native_control_dsps', 515),
                           ('part', '7a50tfgg484'), ('packet_crc_checks_match', False)):
            record = fixture(); record[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): checked.metadata(record)

    def test_every_physical_or_acceptance_flag_stays_false(self):
        for key in emitter.FLAGS:
            record = fixture(); record[key] = True
            with self.subTest(key=key), self.assertRaises(ValueError): checked.metadata(record)

    def test_full_extent_and_projection_guards(self):
        for key, value in (('original_packet_count', 545), ('candidate_payload_bytes', 18735004),
                           ('original_payload_projection_byte_identical', False),
                           ('original_header_except_length_byte_identical', False)):
            record = fixture(); record['crc_only_byte_transform'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): checked.metadata(record)

    def test_crc_reader_scope_flags_and_complete_extent(self):
        for key, value in (('test_ready_bitstream', True), ('fdri_words', 3), ('crc_checks', [{}]),
                           ('physical_configuration_crc_verified', True)):
            record = fixture(); record['crc_only_byte_transform']['crc_verification'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): checked.metadata(record)

    def test_frame_census_and_physical_flags(self):
        record = dict(status='BITSTREAM_FRAME_DATA_AND_CONFIGURATION_ECC_PASS', inputs_unchanged=True,
            physical_verified=False, configuration_crc_verified=False,
            verification=dict(decoded_frames=46336, compared_words=4679936, source_frames=45892,
                zero_filled_frames=444, configuration_frame_ecc_compared=True))
        checked.comparison(record)
        for key, value in (('decoded_frames', 4), ('compared_words', 4679935), ('source_frames', 45891),
                           ('configuration_frame_ecc_compared', False)):
            broken = copy.deepcopy(record); broken['verification'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): checked.comparison(broken)

    def test_only_real_data_or_crc_bit_changed(self):
        raw, _ = emitter.inject(wrap(native()), 3)
        for register in (0, 2):
            broken = checked.corrupt(raw, register)
            self.assertEqual(len(raw), len(broken))
            self.assertEqual(sum((a ^ b).bit_count() for a, b in zip(raw, broken)), 1)
            with self.subTest(register=register), self.assertRaisesRegex(ValueError, 'CRC mismatch'):
                emitter.reader.verify(broken)
        with self.assertRaises(ValueError): checked.corrupt(raw, 1)


if __name__ == '__main__':
    unittest.main()
