"""Small real export regression; no full-array numerical or physical acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
from test_fixed_mapped_array import circuit_signature


class PrefixFrontendLibraryExportControl(unittest.TestCase):
    def test_real_design_only_export_keeps_native_modules_dsp_ff_parameters_and_pin_incidence(self):
        executable = shutil.which('yosys')
        if not executable: self.skipTest('yosys unavailable: actual library export regression not executed')
        source = ROOT / 'tests/cmac/prefix_frontend_library_export_control.sv'
        top = 'prefix_frontend_library_export_control'
        with TemporaryDirectory(prefix='rknpu-prefix-library-export-control-') as name:
            out = Path(name)
            def run(script, code=0):
                argv = [executable, '-Q', '-T', '-p', script]
                print('REAL_LIBRARY_EXPORT_CONTROL_ONLY argv=' + json.dumps(argv), flush=True)
                result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
                text = result.stdout + result.stderr
                self.assertEqual(result.returncode, code, text[-4000:])
                self.assertNotRegex(text, r'(?im)warning:|sorry:')
                if not code: self.assertNotIn('ERROR:', text)
                return text
            read = 'read_verilog -sv ' + json.dumps(str(source)) + '; '
            prepare = ('read_verilog -lib +/xilinx/cells_sim.v; ' + read +
                'hierarchy -check -top ' + top + '; proc; opt_clean; check -assert; ')
            negative = run(prepare + 'write_json ' + json.dumps(str(out / 'failed.json')), 1)
            expected = ('ERROR: Module FDCE contains processes, which are not supported by JSON backend (run '
                + chr(96) + 'proc' + chr(96) + ' first).')
            self.assertIn(expected, negative)
            self.assertIn('Found and reported 0 problems.', negative)
            # Annotate native hierarchy before opt_clean in both views. Without
            # this, the control's unannotated wire-only bridge is removed.
            run(read + 'hierarchy -top ' + top + '; proc; opt_clean; write_json ' +
                json.dumps(str(out / 'original.json')))
            run(prepare + 'write_json -selected ' + json.dumps(str(out / 'selected.json')))
            original = json.loads((out / 'original.json').read_text())
            selected = json.loads((out / 'selected.json').read_text())
            expected_modules = {top, 'prefix_frontend_library_bridge'}
            self.assertEqual(set(original['modules']), expected_modules)
            self.assertEqual(set(selected['modules']), expected_modules)
            signature = circuit_signature(selected)
            self.assertEqual(signature, circuit_signature(original))
            cells = selected['modules']['prefix_frontend_library_bridge']['cells']
            self.assertEqual({c['type'] for c in cells.values()}, {'DSP48E1', 'FDCE'})
            self.assertEqual(cells['control_dsp']['parameters']['USE_MULT'], 'MULTIPLY')
            self.assertEqual(cells['control_ff']['parameters']['INIT'], '0')
            for change in ('ff_init', 'dsp_mode', 'pin', 'module'):
                bad = deepcopy(selected); body = bad['modules']['prefix_frontend_library_bridge']
                if change == 'ff_init': body['cells']['control_ff']['parameters']['INIT'] = '1'
                elif change == 'dsp_mode': body['cells']['control_dsp']['parameters']['USE_MULT'] = 'NONE'
                elif change == 'pin': body['cells']['control_ff']['connections']['D'] = ['0']
                else: bad['modules'].pop('prefix_frontend_library_bridge')
                with self.subTest(change=change): self.assertNotEqual(signature, circuit_signature(bad))
            print('REAL_LIBRARY_EXPORT_CONTROL_ONLY exact native-module/primitive/wiring identity PASS; '
                'unselected-library negative rc=1, selected export rc=0; no numerical or FPGA acceptance', flush=True)
            print('REAL_LIBRARY_EXPORT_CONTROL_ONLY tool=' +
                subprocess.check_output([executable, '-V'], text=True).strip(), flush=True)


if __name__ == '__main__': unittest.main()
