"""Frame encoder-control guards, not native conversion or board signoff."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import probe_prefix_frame_database as control


class PrefixFrameDatabaseControl(unittest.TestCase):
    def test_exact_completed_native_feature_parent_required(self):
        parent = json.loads(control.FEATURE_CONTROL.read_text())
        control.verify_feature_control_metadata(parent, parent['native_tool_transition'])
        for key, value in (('status', 'RUNNING'), ('full_target_parallel_products', 32),
                           ('native_control_PNR_FASM_executed', False), ('timing_signoff', True)):
            changed = copy.deepcopy(parent)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                control.verify_feature_control_metadata(changed, parent['native_tool_transition'])

    def test_cached_grid_reuses_exact_original_without_mutating_it(self):
        adapter = control.load_module(control.ADAPTER, 'test_frame_database_adapter')
        class Database:
            def __init__(self):
                self.calls = 0
                self.original = {'actual': ('immutable', 123)}
            def grid(self):
                self.calls += 1
                return self.original
        adapter.cache_database_grids(Database)
        first, second = Database(), Database()
        self.assertIs(first.grid(), first.original)
        self.assertIs(first.grid(), first.original)
        self.assertIs(second.grid(), second.original)
        self.assertEqual((first.calls, second.calls), (1, 1))
        self.assertEqual(first.original, {'actual': ('immutable', 123)})

    def test_bounded_adapter_preserves_all_lines_and_rejects_unsupported_syntax(self):
        adapter = control.load_module(control.ADAPTER, 'test_frame_database_syntax')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'control.fasm'
            text = '# comment\n\nA.B[7:0] = 8\'h01\nC.D\nC.D\n'
            path.write_text(text)
            calls = []
            def parser(chunk):
                calls.append(chunk)
                return chunk.splitlines(keepends=True)
            self.assertEqual(''.join(control.bounded_native_lines(path, parser, adapter.STATEMENT, chunk_lines=2)), text)
            self.assertEqual(len(calls), 3)
            path.write_text('C.D { annotation = 1 }\n')
            with self.assertRaises(ValueError):
                list(control.bounded_native_lines(path, parser, adapter.STATEMENT))

    def test_conversion_requires_current_exact_frame_artifact_and_no_missing_features(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            frames = destination / 'configuration.frames'
            frames.write_text('synthetic-control-data\n')
            result = dict(status='STRICT_NATIVE_FASM_CONVERSION_PASS_FRAME_VALIDATION_PENDING',
                part=control.PART, physical_verified=False, inputs_unchanged=True,
                counts={'input_lines': 10, 'injected_lines': 2}, missing_clock_activity_requests=[],
                frames=str(frames), frame_bytes=frames.stat().st_size, frames_sha256=control.digest(frames))
            self.assertEqual(control.validate_conversion(result, destination), frames)
            for key, value in (('status', 'FAIL'), ('part', 'xc7a35t'), ('physical_verified', True),
                    ('inputs_unchanged', False), ('missing_clock_activity_requests', ['UNKNOWN']),
                    ('missing_features', ['DROPPED']), ('frame_bytes', 0), ('frames_sha256', '0' * 64)):
                changed = copy.deepcopy(result)
                changed[key] = value
                with self.subTest(key=key), self.assertRaises(AssertionError):
                    control.validate_conversion(changed, destination)
            frames.write_text('changed-data\n')
            with self.assertRaises(AssertionError):
                control.validate_conversion(result, destination)


if __name__ == '__main__':
    unittest.main()
