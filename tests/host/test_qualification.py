"""Generated-input identity controls; no HDL, network, or hardware execution."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.host import qualification as q


class StimulusIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='rknpu-stimulus-control-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.out = 'build/host-jtag/mock-run'
        self.names = q.stimulus_names(self.out)
        for name in self.names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('MOCK INPUT CONTROL ONLY: ' + name + '\n')
        self.record = {'output_directory': self.out,
                       'stimuli': q.stimulus_revision(self.out, self.root)}

    def test_exact_inventory_is_nine_pairs_and_one_partial_image(self):
        self.assertEqual(len(self.names), 19)
        self.assertEqual(sum(name.endswith('/upload.txt') for name in self.names), 9)
        self.assertEqual(sum(name.endswith('/expected.txt') for name in self.names), 9)
        self.assertEqual([name for name in self.names if name.endswith('/partial.txt')],
                         [self.out + '/vectors/capture_sub_9/partial.txt'])
        self.assertEqual(q.verify_stimuli(self.record, self.root), self.record['stimuli'])

    def test_changed_content_after_generation_is_rejected(self):
        for suffix in ('upload.txt', 'expected.txt', 'partial.txt'):
            path = self.root / next(name for name in self.names if name.endswith('/' + suffix))
            before = path.read_bytes()
            path.write_bytes(before + b'changed during execution\n')
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'changed after generation'):
                q.verify_stimuli(self.record, self.root)
            path.write_bytes(before)

    def test_missing_and_added_input_files_are_rejected(self):
        path = self.root / self.names[0]
        before = path.read_bytes(); path.unlink()
        with self.assertRaisesRegex(ValueError, 'inventory'):
            q.verify_stimuli(self.record, self.root)
        path.write_bytes(before)
        extra = path.parent / 'unrecorded-input.bin'
        extra.write_bytes(b'unexpected input')
        with self.assertRaisesRegex(ValueError, 'inventory'):
            q.verify_stimuli(self.record, self.root)

    def test_summary_only_and_wrong_artifact_binding_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'changed after generation'):
            q.verify_stimuli({'output_directory': self.out}, self.root)
        record = deepcopy(self.record)
        record['artifacts'] = deepcopy(record['stimuli'])
        q.verify_stimuli(record, self.root)
        record['artifacts']['files'][self.names[0]] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'does not match artifacts'):
            q.verify_stimuli(record, self.root)

    def test_same_corpus_copies_verify_without_original_workspace(self):
        with tempfile.TemporaryDirectory(prefix='rknpu-copied-stimulus-') as directory:
            target = Path(directory)
            for name in self.names:
                path = target / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((self.root / name).read_bytes())
            self.assertEqual(q.verify_stimuli(self.record, target), self.record['stimuli'])


if __name__ == '__main__':
    unittest.main()
