"""Model inventory/freeze checks, not mapped-board numerical acceptance."""
import hashlib
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import unisim_board_models as models
import check_unisim_board_models as runner


class UnisimBoardModelsControls(unittest.TestCase):
    def test_exact_model_result_and_finish_diagnostic_only(self):
        bench = Path('/tmp/frozen-control.sv')
        finish = next(i + 1 for i, line in enumerate(runner.BENCH.read_text().splitlines()) if line.strip() == '$finish;')
        text = runner.MARKER + f'\n{bench}:{finish}: $finish called at 352000 (1ps)\n'
        runner.validate_model_result(text, bench)
        for changed in (text.replace('default_gsr=100ns', 'default_gsr=0ns'),
                        text.replace('352000', '1'), text + 'PASS unexpected\n',
                        text + 'warning: ignored\n', text.replace(str(bench), '/tmp/other.sv')):
            with self.subTest(output=changed), self.assertRaises(AssertionError): runner.validate_model_result(changed, bench)

    def test_explicit_pins_license_startup_and_unknown_primitive_rejection(self):
        pins = models.selected_models({'FDPE', 'RAMB36E1', 'LUT6_2'})
        self.assertEqual({p.name for p in pins}, {'LICENSE','glbl.v','FDPE.v','RAMB36E1.v','LUT6_2.v'})
        self.assertTrue(all(re.fullmatch('[0-9a-f]{64}', sha) for sha in pins.values()))
        for kinds in (set(), {'UNSUPPORTED'}, {'FDPE','DSP48E1'}):
            with self.subTest(kinds=kinds), self.assertRaises(AssertionError): models.selected_models(kinds)

    def test_real_frozen_model_bytes_are_exact_and_not_synthesis_stubs(self):
        with tempfile.TemporaryDirectory(prefix='unisim-freeze-control-', dir=ROOT / 'build') as directory:
            original, frozen = models.freeze_models(Path(directory) / 'models', {'FDPE','RAMB36E1'})
            for path in frozen:
                source = next(p for p in original if p.name == path.name)
                self.assertEqual(path.read_bytes(), source.read_bytes())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original[source])
            ram = next(p for p in frozen if p.name == 'RAMB36E1.v').read_text()
            self.assertIn('module RB36_INTERNAL_VLOG', ram)
            self.assertIn('tri0 GSR = glbl.GSR;', ram)
            startup = next(p for p in frozen if p.name == 'glbl.v').read_text()
            self.assertIn('parameter ROC_WIDTH = 100000;', startup)


if __name__ == '__main__': unittest.main()
