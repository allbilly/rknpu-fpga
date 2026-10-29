"""Pinned-model gate controls plus real small UNISIM/Icarus tests, not board proof."""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_lut_pair_unisim as runner
from test_board_lut_pair import fixture, lut


class LutPairUnisimControls(unittest.TestCase):
    def test_exact_vendor_hash_set_and_license(self):
        models, license_path = runner.pinned_models(ROOT / 'build/reference/xilinx-unisim')
        self.assertEqual({p.name for p in models}, {'LUT1.v', 'LUT2.v', 'LUT3.v', 'LUT4.v', 'LUT5.v', 'LUT6_2.v'})
        self.assertEqual(license_path.name, 'LICENSE')
        self.assertEqual(runner.COMMIT, '1c8e05fd1e9a79ceb8b996a0996674122eed086f')

    def test_changed_vendor_model_and_license_rejected(self):
        originals, license_path = runner.pinned_models(ROOT / 'build/reference/xilinx-unisim')
        with tempfile.TemporaryDirectory(prefix='rk_unisim_hash_', dir=ROOT / 'build') as name:
            directory = Path(name)
            dest = directory / 'verilog/src/unisims'
            dest.mkdir(parents=True)
            for path in originals: (dest / path.name).write_bytes(path.read_bytes())
            (directory / 'LICENSE').write_bytes(license_path.read_bytes())
            for path in [*(dest / p.name for p in originals), directory / 'LICENSE']:
                before = path.read_bytes()
                path.write_bytes(before + b'\n')
                with self.assertRaises(AssertionError): runner.pinned_models(directory)
                path.write_bytes(before)
            runner.pinned_models(directory)

    def test_only_exact_positive_count_and_marker_accepted(self):
        marker = 'PASS LUT_PAIR_FOUR_STATE classes=2 comparisons=2080\n'
        self.assertEqual(runner.validate_result(marker, 0, 2, 2080), marker.strip())
        for text, code in [(marker, 1), (marker + marker, 0), (marker.replace('2080', '2078'), 0),
                           ('', 0), ('FATAL: failure\n' + marker, 0), ('warning: drift\n' + marker, 0)]:
            with self.subTest(text=text, code=code), self.assertRaises(AssertionError):
                runner.validate_result(text, code, 2, 2080)

    def test_negative_requires_actual_first_pattern_assertion_not_crash(self):
        text = 'FATAL: bench.sv: LUT_PAIR_MISMATCH class=0 pattern=0\n'
        runner.validate_result(text, 1, 2, 2080, True)
        for bad, code in [(text, 0), (text, -11), (text, 2), (text.replace('pattern=0', 'pattern=1'), 1),
                          (text.replace('class=0', 'class=1'), 1), (text + 'PASS forged\n', 1), ('', 1)]:
            with self.subTest(code=code, text=bad), self.assertRaises(AssertionError):
                runner.validate_result(bad, code, 2, 2080, True)

    def test_function_domain_count_duplicates_and_fanin_mutation_rejected(self):
        # Use the actual pairing constructor, not a handwritten truth table.
        import pair_board_luts
        _, _, classes = pair_board_luts.pair(fixture(), {'top'})
        report = dict(unique_function_classes=1, expected_four_state_comparisons=32)
        self.assertEqual(len(runner.validate_classes(report, classes)), 1)
        for label in ('empty', 'duplicate', 'count', 'fanin'):
            values, metadata = deepcopy(classes), deepcopy(report)
            if label == 'empty': values = []
            elif label == 'duplicate': values *= 2; metadata.update(unique_function_classes=2, expected_four_state_comparisons=64)
            elif label == 'count': metadata['expected_four_state_comparisons'] = 30
            else: values[0]['fanins'] = 6
            with self.subTest(label=label), self.assertRaises(AssertionError): runner.validate_classes(metadata, values)

    def test_only_startup_initialization_changes_not_assertions_patterns_or_pins(self):
        import pair_board_luts
        _, _, classes = pair_board_luts.pair(fixture(), {'top'})
        for negative in (False, True):
            original = runner.four_state_bench(classes, negative)
            actual = runner.unisim_bench(classes, negative)
            self.assertEqual(actual.replace("reg [4:0] c0_inputs=5'bx;", 'reg [4:0] c0_inputs=0;'), original)
            self.assertEqual(actual.count('$fatal('), original.count('$fatal('))
        classes[0]['fanins'] = 0
        with self.assertRaisesRegex(AssertionError, 'requires a driven input'):
            runner.unisim_bench(classes)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus unavailable; no HDL pass claimed')
    def test_real_unmodified_unisim_four_state_and_actual_init_bit_negative(self):
        import pair_board_luts
        _, _, classes = pair_board_luts.pair(fixture(), {'top'})
        a = lut('LUT5', [2, 3, 4, 5, 6], 7, '01' * 16)
        b = lut('LUT5', [6, 5, 4, 3, 2], 8, '0011' * 8)
        fanins = [2, 3, 4, 5, 6]
        cell = pair_board_luts.paired_cell(a, b, fanins)
        classes.append(dict(fanins=5, first=pair_board_luts.spec(a, fanins),
            second=pair_board_luts.spec(b, fanins), init=cell['parameters']['INIT']))
        models, _ = runner.pinned_models(ROOT / 'build/reference/xilinx-unisim')
        with tempfile.TemporaryDirectory(prefix='rk_unisim_actual_', dir=ROOT / 'build') as name:
            directory = Path(name)
            for negative in (False, True):
                bench, executable = directory / 'bench.sv', directory / 'test.vvp'
                bench.write_text(runner.unisim_bench(classes, negative))
                compile = subprocess.run(['iverilog', '-g2012', '-s', runner.BENCH, '-o', str(executable),
                    *(str(p) for p in models), str(bench)], text=True, capture_output=True, timeout=60)
                self.assertEqual(compile.returncode, 0, compile.stdout + compile.stderr)
                self.assertEqual(compile.stderr, '')
                result = subprocess.run(['vvp', str(executable)], text=True, capture_output=True, timeout=60)
                runner.validate_result(result.stdout + result.stderr, result.returncode, 2, 2080, negative)


if __name__ == '__main__': unittest.main()
