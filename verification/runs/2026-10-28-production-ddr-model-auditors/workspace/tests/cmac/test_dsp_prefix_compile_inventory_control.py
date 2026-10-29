"""Read-only warning-accounting guards; no compiler diagnostic admission."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import audit_dsp_prefix_compile_inventory as audit


def fixture():
    inputs = ['CARRYCASCIN', 'CEA1', 'CEA2', 'CEAD', 'CEALUMODE', 'CEB1', 'CEB2', 'CEC',
        'CECARRYIN', 'CECTRL', 'CED', 'CEINMODE', 'CEM', 'CEP', 'CLK', 'MULTSIGNIN',
        'RSTA', 'RSTALLCARRYIN', 'RSTALUMODE', 'RSTB', 'RSTC', 'RSTCTRL', 'RSTD', 'RSTINMODE', 'RSTM', 'RSTP']
    outputs = ['ACOUT', 'BCOUT', 'CARRYCASCOUT', 'CARRYOUT', 'MULTSIGNOUT', 'OVERFLOW',
        'PATTERNBDETECT', 'PATTERNDETECT', 'PCOUT', 'UNDERFLOW']
    ports = {name: ('input', 1) for name in inputs}
    ports.update({name: ('output', 1) for name in outputs})
    ports.update({name: ('input', width) for name, (width, value) in audit.cone.primitive.CONSTANTS.items()})
    ports.update(A=('input', 30), B=('input', 18), P=('output', 48))
    cells, lines, entries = {}, [], []
    for index in range(32):
        name = 'rk_mapped_cell_' + str(index)
        cells[name] = dict(type='DSP48E1', connections={pin: [] for pin in audit.cone.primitive.CONSTANTS})
        lines.append('  ) ' + name + ' (')
        for pin in inputs + outputs:
            entries.append(dict(kind='PINMISSING', line=index + 1, message="Instance has missing pin: '" + pin + "'"))
    return entries, lines, dict(cells=cells), ports


class CompileInventoryControls(unittest.TestCase):
    def test_exact_32_by_36_bijection(self):
        result = audit.missing_pin_provenance(*fixture())
        self.assertEqual((result['dsp_instances'], result['diagnostic_count'], result['input_diagnostics'],
            result['output_diagnostics']), (32, 1152, 832, 320))

    def test_missing_duplicate_unknown_or_connected_pin_is_rejected(self):
        for mode in ('missing', 'duplicate', 'unknown', 'connected'):
            entries, lines, module, ports = fixture()
            if mode == 'missing': entries.pop()
            elif mode == 'duplicate': entries.append(deepcopy(entries[0]))
            elif mode == 'unknown': entries[0]['message'] = "Instance has missing pin: 'A'"
            else: module['cells']['rk_mapped_cell_0']['connections']['CARRYCASCIN'] = ['0']
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                audit.missing_pin_provenance(entries, lines, module, ports)

    def test_wrong_source_line_instance_type_count_or_kind_is_rejected(self):
        for mode in ('line', 'instance', 'type', 'count', 'kind'):
            entries, lines, module, ports = fixture()
            if mode == 'line': entries[0]['line'] = 999
            elif mode == 'instance': lines[0] = '  ) unknown_cell ('
            elif mode == 'type': module['cells']['rk_mapped_cell_0']['type'] = 'LUT6'
            elif mode == 'count': module['cells'].pop('rk_mapped_cell_31')
            else: entries[0]['kind'] = 'UNDRIVEN'
            with self.subTest(mode=mode), self.assertRaises(AssertionError):
                audit.missing_pin_provenance(entries, lines, module, ports)

    def test_unparsed_warning_tool_error_or_unrecognized_pin_message_is_rejected(self):
        good = "%Warning-PINMISSING: /tmp/mapped.v:1:5: Instance has missing pin: 'CLK'\n"
        self.assertEqual(audit.diagnostics(good)[0]['line'], 1)
        for text in (good + '%Warning-UNKNOWN without location\n', good + '%Error: unrelated\n',
            good + 'warning: unsupported\n', good + 'sorry: unsupported\n'):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                audit.diagnostics(text)
        entries, lines, module, ports = fixture()
        entries[0]['message'] = 'Some other diagnostic'
        with self.assertRaises(AssertionError):
            audit.missing_pin_provenance(entries, lines, module, ports)


if __name__ == '__main__':
    unittest.main()
