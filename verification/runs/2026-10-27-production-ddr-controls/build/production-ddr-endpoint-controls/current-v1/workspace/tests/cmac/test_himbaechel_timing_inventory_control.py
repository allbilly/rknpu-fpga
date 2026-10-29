"""Synthetic parser controls, not native nextpnr or FPGA timing tests."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from audit_himbaechel_timing import timing_inventory

NAMES = ['', 'SLICE_FFX', 'CK', 'D', 'Q', 'DEFAULT', 'DSP48E1_DSP48E1']


def fixture(include_dsp=False):
    data = bytearray(4)

    def allocate(size):
        offset = len(data)
        data.extend(bytes(size))
        return offset

    def number(offset, value):
        struct.pack_into('<i', data, offset, value)

    def pointer(offset, target):
        number(offset, target - offset)

    def string(offset, value):
        target = allocate(len(value) + 1)
        data[target:target + len(value)] = value.encode('ascii')
        pointer(offset, target)

    def array(offset, target, count):
        pointer(offset, target)
        struct.pack_into('<I', data, offset + 4, count)

    root = allocate(84)
    pointer(0, root)
    number(root, 0x00ca7ca7)
    number(root + 4, 6)
    for offset, text in ((16, 'xilinx'), (20, 'xc7k480t'), (24, 'synthetic')):
        string(root + offset, text)
    ids = allocate(12)
    pointer(root + 76, ids)
    number(ids, len(NAMES))
    grade = allocate(32)
    array(root + 68, grade, 1)
    number(grade, 5)
    cells = allocate(24 if include_dsp else 12)
    array(grade + 20, cells, 2 if include_dsp else 1)
    number(cells, 1)
    if include_dsp:
        number(cells + 12, 6)
    pins = allocate(48)
    array(cells + 4, pins, 2)
    for i, pin_name in enumerate((3, 4)):
        pin = pins + 24 * i
        number(pin, pin_name)
        arc = allocate(56)
        array(pin + 16, arc, 1)
        number(arc, 2)
    return data, dict(root=root, grade=grade, cells=cells, pins=pins, ids=ids)


class TimingInventoryControl(unittest.TestCase):
    def test_inventory_does_not_invent_dsp_or_speed_grade(self):
        data, _ = fixture()
        result = timing_inventory(bytes(data), NAMES)
        self.assertEqual(result['schema_version'], 6)
        self.assertEqual([g['name'] for g in result['speed_grades']], ['DEFAULT'])
        cells = result['speed_grades'][0]['cell_types']
        self.assertEqual(cells['SLICE_FFX']['sequential_arcs'], 2)
        self.assertNotIn('DSP48E1_DSP48E1', cells)
        self.assertNotIn('timing_signoff', result)

    def test_present_empty_model_not_hidden(self):
        data, _ = fixture(include_dsp=True)
        cells = timing_inventory(bytes(data), NAMES)['speed_grades'][0]['cell_types']
        self.assertEqual(cells['DSP48E1_DSP48E1']['pins'], {})
        self.assertEqual(cells['DSP48E1_DSP48E1']['sequential_arcs'], 0)

    def test_malformed_schema_and_id_fail(self):
        for where, value in (('version', 7), ('known_count', 99), ('cell_id', 9999)):
            data, offsets = fixture()
            offset = {'version': offsets['root'] + 4,
                      'known_count': offsets['ids'], 'cell_id': offsets['cells']}[where]
            struct.pack_into('<i', data, offset, value)
            with self.subTest(where=where), self.assertRaises(ValueError):
                timing_inventory(bytes(data), NAMES)

    def test_null_and_out_of_range_slices_fail(self):
        for value in (0, -10000, 10000):
            data, offsets = fixture()
            struct.pack_into('<i', data, offsets['cells'] + 4, value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                timing_inventory(bytes(data), NAMES)


if __name__ == '__main__':
    unittest.main()
