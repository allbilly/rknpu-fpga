"""Prepared reviewed packet guards; fabricated metadata is not assembly proof."""
from copy import deepcopy
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import assemble_reviewed_recursive_mux_unreviewed_bits as subject
import test_recursive_mux_full_bit_control as old

ExistingPacketAndCorruptionControls = old.ExistingPacketAndCorruptionControls
FullUnreviewedPacketControls = old.FullUnreviewedPacketControls


class ReviewedFullUnreviewedPacketControls(unittest.TestCase):
    def test_entire_full_frame_chain_packet_and_native_negatives_reversibly_preserved(self):
        for source, replacements, expected in ((subject.MAIN_SOURCE, subject.REPLACEMENTS, subject.previous.MAIN_SOURCE),
            (subject.CHAIN_SOURCE, subject.CHAIN_REPLACEMENTS, inspect.getsource(subject.previous.verify_full_frame_chain))):
            for before, after in reversed(replacements):
                self.assertEqual(source.count(after), 1); source = source.replace(after, before)
            self.assertEqual(source, expected)
        self.assertEqual(subject.METADATA_SOURCE, inspect.getsource(subject.previous.verify_full_frame_metadata))
        for name in ('verify_comparison', 'corrupt_decoded', 'bind_report', 'verify_bindings'):
            self.assertIs(subject.NAMESPACE[name], subject.previous.NAMESPACE[name])
        for marker in ('donor.verified_frame_tools(', "run('native_frames_to_bit'", "'--frm_file', frames",
            "run('native_decode_frames'", "run('all_frame_data_and_ECC'", "(('data_bit', 0), ('ECC_bit', 50))",
            'donor.check_sources(frame.TOOL)', 'verify_bindings(before)'):
            self.assertEqual(subject.MAIN_SOURCE.count(marker), subject.previous.MAIN_SOURCE.count(marker))
            self.assertGreater(subject.MAIN_SOURCE.count(marker), 0)
        for marker in ('frames.admission.verify_route(', 'required_features', 'validate_conversion(', 'verify_requests(',
            'verify_clock_requests(', "namespace['dsp_readback']", "namespace['small'].clock_readback",
            'previous.verify_bindings(before)', 'json.loads(output.read_text()) == saved[label]'):
            self.assertEqual(subject.CHAIN_SOURCE.count(marker), inspect.getsource(subject.previous.verify_full_frame_chain).count(marker))
        self.assertIn('full-C32K16.NOT_FOR_PROGRAMMING.unverified.bit', subject.MAIN_SOURCE)
        self.assertLess(subject.MAIN_SOURCE.index('verify_full_frame_chain('), subject.MAIN_SOURCE.index("run('native_frames_to_bit'"))

    def test_only_complete_new_full_frame_metadata_not_old_scope_or_acceptance_claim(self):
        good = old.metadata(); good['status'] = subject.frames.PASS; saved = deepcopy(good)
        subject.verify_full_frame_metadata(good); self.assertEqual(good, saved)
        for field, bad in (('status', subject.previous.frames.PASS), ('status', 'RUNNING'), ('stage', 'DSP_frame_readback'),
            ('parallel_products', 256), ('channels', 16), ('kernels', 8), ('part', 'xc7k480tffg1156-1'),
            ('intended_clock_period_ns', 40), ('seed', 1), ('source_defined_DSP_features', 64), ('clock_contracts', {})):
            with self.subTest(field=field), self.assertRaises(AssertionError):
                subject.verify_full_frame_metadata(dict(good, **{field: bad}))
        for flag in subject.frames.FLAGS:
            with self.subTest(flag=flag), self.assertRaises(AssertionError):
                subject.verify_full_frame_metadata(dict(good, **{flag: True}))
        self.assertEqual(subject.FLAGS, subject.previous.FLAGS)
        for flag in ('test_ready_bitstream', 'reviewed_full_target_bitstream_emitted', 'numerical_acceptance',
                     'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff',
                     'configuration_crc_verified', 'hardware_programmed'):
            self.assertIn(flag, subject.FLAGS)
        self.assertNotIn('full_target_bitstream_emitted', subject.FLAGS)
        self.assertIn("report['full_target_bitstream_emitted'] = True", subject.MAIN_SOURCE)
        self.assertIn('assert all(report[key] is False for key in FLAGS)', subject.MAIN_SOURCE)

    def test_running_new_full_frame_actual_native_or_old_small_cannot_create_packet_output(self):
        pattern = 'full-reviewed-recursive-mux-unreviewed-bit-encoding-*'
        before = set((ROOT / 'build/openxc7').glob(pattern))
        with tempfile.TemporaryDirectory(prefix='full-reviewed-recursive-mux-native-heap-frames-control-', dir=ROOT / 'build/openxc7') as directory:
            path = Path(directory) / 'report.json'; path.write_text('{"status":"RUNNING"}')
            result = subprocess.run([sys.executable, '-B', subject.__file__, '--frames-report', str(path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1); self.assertIn('AssertionError', result.stderr)
        for path in (subject.previous.previous.SMALL,
            ROOT / 'build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json'):
            result = subprocess.run([sys.executable, '-B', subject.__file__, '--frames-report', str(path)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1); self.assertIn('AssertionError', result.stderr)
        self.assertEqual(set((ROOT / 'build/openxc7').glob(pattern)), before)
        self.assertLess(subject.MAIN_SOURCE.index('verify_full_frame_metadata(saved)'), subject.MAIN_SOURCE.index('out.mkdir'))

    def test_actual_frame_producer_snapshots_and_closed_workers_required(self):
        frames = subject.frames
        with tempfile.TemporaryDirectory(prefix='full-reviewed-recursive-mux-native-heap-frames-snapshot-control-', dir=ROOT / 'build/openxc7') as directory:
            root = Path(directory); path = root / 'report.json'
            texts = {'executed_source.py': Path(frames.__file__).read_text(),
                'executed_control_source.py': frames.CONTROL.read_text(), 'executed_prepared_main.py': frames.MAIN_SOURCE}
            for name, text in texts.items(): (root / name).write_text(text)
            before = {str(root / name): subject.previous.previous.digest(root / name) for name in texts}
            before.update({str(p): subject.previous.previous.digest(p) for p in (Path(frames.__file__).resolve(), frames.CONTROL)})
            saved = dict(commands=[dict(pid=999999999)], supervisor_pid=999999998)
            subject.verify_frame_snapshots(path, saved, before)
            with patch.object(subject.Path, 'exists', return_value=True), self.assertRaises(AssertionError):
                subject.verify_frame_snapshots(path, saved, before)
            item = root / 'executed_prepared_main.py'; item.write_text('missing strict actual raw-FASM and bit readback checks')
            before[str(item)] = subject.previous.previous.digest(item)
            with self.assertRaises(AssertionError): subject.verify_frame_snapshots(path, saved, before)


if __name__ == '__main__':
    unittest.main()
