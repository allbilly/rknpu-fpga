"""Comparator controls, not a full packed-board or placement result."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import audit_corrected_full_pack_identity as audit
from probe_prefix_native_config import SELECTED


class CorrectedFullPackIdentityControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        small = root / 'build/openxc7/prefix-native-config-control-1791407940428316242'
        cells = next(iter(json.loads((small / 'routed.json').read_text())['modules'].values()))['cells']
        cls.name = 'dsp_rk_mapped_cell_86617'
        cls.original = json.loads(SELECTED.read_text())['rk_mapped_cell_86617']
        cls.old_dsp = cells[cls.name]
        cls.vcc = cells['$PACKER_VCC_DRV']['connections']['Y'][0]
        cls.gnd = cells['$PACKER_GND_DRV']['connections']['Y'][0]
        cls.actual_native_packed = small / 'clock-admitted-packed.json'

    def cells(self):
        old = {
            '$PACKER_VCC_DRV': dict(hide_name=1, type='PSEUDO_VCC', parameters={}, attributes={},
                port_directions={'Y': 'output'}, connections={'Y': [self.vcc]}),
            '$PACKER_GND_DRV': dict(hide_name=1, type='PSEUDO_GND', parameters={}, attributes={},
                port_directions={'Y': 'output'}, connections={'Y': [self.gnd]}),
            'ordinary': dict(hide_name=0, type='SLICE_LUTX', parameters={'INIT': '01'}, attributes={},
                port_directions={'A1': 'input', 'O6': 'output'}, connections={'A1': [41], 'O6': [42]}),
            self.name: deepcopy(self.old_dsp),
        }
        new = deepcopy(old)
        required = audit.requirements(self.original)
        new[self.name]['attributes']['DSP_VCC_PINS'] = ' '.join(required)
        for pin in required: new[self.name]['connections'][pin] = []
        return old, new

    def export(self, cells, vcc=None):
        def record(name, value):
            return '        ' + json.dumps(name) + ': ' + json.dumps(value, indent=2).replace('\n', '\n        ')
        header = '{\n  "creator": "software-control-only",\n  "modules": {\n    "top": {\n'
        header += '      "ports": {},\n\n      "cells": {\n'
        body = ',\n'.join(record(name, value) for name, value in cells.items())
        tail = '\n      },\n      "netnames": {\n'
        nets = {'$PACKER_VCC_NET': dict(hide_name=1, bits=[self.vcc if vcc is None else vcc], attributes={}),
                '$PACKER_GND_NET': dict(hide_name=1, bits=[self.gnd], attributes={})}
        tail += ',\n'.join(record(name, value) for name, value in nets.items())
        return (header + body + tail + '\n      }\n    }\n  }\n}\n').encode()

    def compare(self, old, new):
        return audit.compare_exports(self.export(old), self.export(new), {self.name: self.original})

    def test_exact_eight_pin_delta_and_other_cells(self):
        result = self.compare(*self.cells())
        self.assertEqual(result['cells_compared'], 4)
        self.assertEqual(result['unchanged_non_DSP_cell_records'], 3)
        self.assertEqual(result['source_defined_tile_pin_disconnections_compared'], 8)
        self.assertFalse(result['disconnected_pin_normalization_used'])

    def test_changed_ordinary_wire_or_parameter_rejected(self):
        for key, value in [('connections', {'A1': [99], 'O6': [42]}), ('parameters', {'INIT': '10'})]:
            old, new = self.cells()
            new['ordinary'][key] = value
            with self.assertRaises(AssertionError): self.compare(old, new)

    def test_changed_other_DSP_wire_rejected(self):
        old, new = self.cells()
        new[self.name]['connections']['A0'] = [99]
        with self.assertRaises(AssertionError): self.compare(old, new)

    def test_wrong_tile_pin_disconnect_rejected(self):
        old, new = self.cells()
        new[self.name]['connections']['INMODE1'] = [self.gnd]
        with self.assertRaises(AssertionError): self.compare(old, new)

    def test_changed_named_wire_table_rejected(self):
        old, new = self.cells()
        with self.assertRaises(AssertionError):
            audit.compare_exports(self.export(old), self.export(new, vcc=99), {self.name: self.original})

    def test_missing_cell_and_incomplete_export_rejected(self):
        old, new = self.cells()
        del new['ordinary']
        with self.assertRaises(AssertionError): self.compare(old, new)
        with self.assertRaises(AssertionError): audit.layout(self.export(old)[:-2])

    def test_DSP_parameter_change_rejected(self):
        old, new = self.cells()
        new[self.name]['parameters']['AREG'] = '1'
        with self.assertRaises(AssertionError): self.compare(old, new)

    def test_actual_saved_native_parser_matches_JSON(self):
        data = self.actual_native_packed.read_bytes()
        begin, end = audit.layout(data)
        parsed = {name: audit.cell_value(record) for name, record in audit.records(data, begin, end)}
        expected = next(iter(json.loads(data)['modules'].values()))['cells']
        self.assertEqual(parsed, expected)
        self.assertEqual(sum(cell['type'] == 'DSP48E1_DSP48E1' for cell in parsed.values()), 4)
        self.assertEqual(sum(cell['type'] == 'RAMB36E1_RAMB36E1' for cell in parsed.values()), 6)

    def test_previous_wrong_native_delimiter_rejected(self):
        data = self.export(self.cells()[0])
        data = data.replace(b'\n      },\n      "netnames": {', b'\n      },\n\n      "netnames": {')
        with self.assertRaises(AssertionError): audit.layout(data)


if __name__ == '__main__':
    unittest.main()
