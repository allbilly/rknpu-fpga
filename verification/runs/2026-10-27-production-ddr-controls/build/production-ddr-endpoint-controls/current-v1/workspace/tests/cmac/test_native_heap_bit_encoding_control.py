import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import probe_native_heap_bit_encoding as subject


class Control(unittest.TestCase):
    def result(self):
        return dict(status='BITSTREAM_FRAME_DATA_AND_CONFIGURATION_ECC_PASS', inputs_unchanged=True,
                    physical_verified=False, configuration_crc_verified=False,
                    verification=dict(decoded_frames=46336, compared_words=4679936,
                                      source_frames=45892, zero_filled_frames=444,
                                      configuration_frame_ecc_compared=True, nonzero_words_including_ecc=1))

    def test_complete_comparison(self):
        self.assertEqual(subject.verify_comparison(self.result(), 45892)['compared_words'], 4679936)

    def test_incomplete_and_overclaims_rejected(self):
        good = self.result()
        for key, value in (('status', 'RUNNING'), ('inputs_unchanged', False),
                           ('physical_verified', True), ('configuration_crc_verified', True)):
            with self.subTest(key=key):
                bad = copy.deepcopy(good); bad[key] = value
                with self.assertRaises(AssertionError): subject.verify_comparison(bad, 45892)
        for key in good['verification']:
            with self.subTest(key=key):
                bad = copy.deepcopy(good); bad['verification'][key] = 0
                with self.assertRaises(AssertionError): subject.verify_comparison(bad, 45892)
        with self.assertRaises(AssertionError): subject.verify_comparison(good, 1)

    def test_actual_copy_changes_only_selected_bit(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'actual.frames'
            original = '.frame 0x80\n' + ' '.join(['00000000'] * 101) + '\n'
            source.write_text(original)
            for index in (0, 50):
                target = Path(folder) / f'negative-{index}.frames'
                prefix = subject.corrupt_decoded(source, target, index)
                self.assertEqual(prefix, f'Decoded frame 0x80 word {index} differs:')
                wanted = [0] * 101; wanted[index] = 1
                self.assertEqual([int(w, 16) for w in target.read_text().splitlines()[1].split()], wanted)
                self.assertEqual(source.read_text(), original)
            with self.assertRaises(AssertionError): subject.corrupt_decoded(source, source, 0)
            with self.assertRaises(AssertionError): subject.corrupt_decoded(source, Path(folder) / 'bad', 51)

    def test_parent_failure_or_incomplete_cannot_admit(self):
        saved = json.loads(subject.SMALL.read_text())
        subject.parent.verify_small_metadata(saved)
        for key, value in (('status', 'FAIL'), ('finished_utc', None), ('stage', 'RUNNING'),
                           ('native_control_dsps', 515), ('part', 'xc7a200t')):
            with self.subTest(key=key):
                bad = copy.deepcopy(saved); bad[key] = value
                with self.assertRaises(AssertionError): subject.parent.verify_small_metadata(bad)


if __name__ == '__main__':
    unittest.main()
