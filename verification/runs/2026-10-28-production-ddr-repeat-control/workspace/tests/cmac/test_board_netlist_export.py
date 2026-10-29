"""Export controls plus real small Yosys roundtrips, not board arithmetic proof."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/cmac'))
from export_board_netlist import BRAM_STRINGS, literal, structural_board_verilog
from test_fixed_mapped_array import circuit_signature, structural_verilog


def fixture():
    return {'modules': {'top': {'ports': {
        'a': {'direction':'input', 'bits':[2]},
        'y': {'direction':'output', 'bits':[3]}},
        'parameter_default_values': {'WIDTH': '00000000000000000000000000000001'},
        'cells': {'ram': {'type':'RAMB36E1', 'parameters': {
            'RAM_MODE':'TDP', 'WRITE_MODE_A':'READ_FIRST', 'INIT_FILE':'NONE',
            'READ_WIDTH_A':'00000000000000000000000000100100',
            'INIT_00':'01xz'*64},
            'connections': {'ADDRARDADDR':[2], 'DOADO':[3]}}}}}}


class BoardNetlistExportTests(unittest.TestCase):
    def test_literal_string_modes_preserved(self):
        for kind in ('RAMB18E1', 'RAMB36E1'):
            for key, values in BRAM_STRINGS.items():
                for value in values:
                    self.assertEqual(literal(value, kind, key), json.dumps(value))
        self.assertEqual(literal('01xz', 'LUT1', 'INIT'), "4'b01xz")

    def test_unknown_modes_files_expressions_and_nonliteral_encodings_rejected(self):
        for value, kind, key in [('arithmetic expression','LUT1','INIT'),
            ('TDP','LUT1','RAM_MODE'), ('NONE','RAMB36E1','UNKNOWN'),
            ('MISSING_MODE','RAMB36E1','RAM_MODE'), ('data.hex','RAMB36E1','INIT_FILE'),
            ('NONE\n','RAMB36E1','INIT_FILE'), (None,'RAMB36E1','RAM_MODE'),
            (True,'LUT1','INIT'), ('','LUT1','INIT')]:
            with self.subTest(value=value,kind=kind,key=key):
                with self.assertRaises(AssertionError): literal(value,kind,key)
        with self.assertRaises(AssertionError): literal('TDP')

    def test_original_binary_array_export_unchanged_in_scope(self):
        design=fixture(); cell=design['modules']['top']['cells']['ram']
        cell['type']='LUT1'; cell['parameters']={'INIT':'10'}
        a=structural_board_verilog(design).splitlines()[1:]
        b=structural_verilog(design).splitlines()[1:]
        self.assertEqual(a,b)

    def test_original_not_mutated_and_invalid_input_or_identifier_rejected(self):
        design=fixture(); before=deepcopy(design)
        structural_board_verilog(design)
        self.assertEqual(design,before)
        design['modules']['top']['ports']['a']['bits']=['0']
        with self.assertRaises(AssertionError): structural_board_verilog(design)
        design=fixture(); design['modules']['top']['cells']['bad name']=design['modules']['top']['cells'].pop('ram')
        with self.assertRaises(AssertionError): structural_board_verilog(design)

    @unittest.skipUnless(shutil.which('yosys'), 'Real Yosys unavailable; no roundtrip pass claimed')
    def test_real_yosys_roundtrip_preserves_strings_bits_defaults_and_wires(self):
        design=fixture()
        with tempfile.TemporaryDirectory(prefix='rk_board_export_',dir=ROOT/'build') as name:
            directory=Path(name)
            sv=directory/'export.v'; sv.write_text(structural_board_verilog(design))
            result=directory/'result.json'
            command=['yosys','-Q','-T','-p','read_verilog -sv '+json.dumps(str(sv))+'; write_json '+json.dumps(str(result))]
            run=subprocess.run(command,text=True,capture_output=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertEqual(circuit_signature(json.loads(result.read_text())),circuit_signature(design))
            altered=deepcopy(design)
            altered['modules']['top']['cells']['ram']['parameters']['RAM_MODE']='SDP'
            self.assertNotEqual(circuit_signature(altered),circuit_signature(design))


if __name__=='__main__':
    unittest.main()
