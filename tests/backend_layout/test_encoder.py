"""Portable contract tests for the static gather command encoder."""
from __future__ import annotations

import json
import struct
import unittest
from enum import Enum
from pathlib import Path
from typing import NamedTuple

from tools.backend.layout import (
    ABI, AMOUNT, FILL, TARGET, LayoutError, StaticGather, encode, from_backend,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / 'tests/backend_layout/fixtures.json').read_text())
BINDINGS = dict(source_address=0x10010000, destination_address=0x10030000,
                table_address=0x10050000, command_address=0x100e0000,
                aperture_base=0x10000000, aperture_bytes=1 << 20)


def items(value):
    return value['items']


def independently_expected(m, n, k, encoded_m, encoded_n, input_channels, output_channels):
    """Rebuild source indices from logical dense coordinates and packing rules."""
    swapped = m == 1
    lhs = [((col * n + row) if swapped else (row * k + col)) if col < k else -1
           for row in range(encoded_m) for col in range(input_channels)]
    weight = []
    for out_group in range(output_channels // 16):
        for in_group in range(input_channels // 32):
            for out_lane in range(16):
                for in_lane in range(32):
                    oc = out_group * 16 + out_lane
                    ic = in_group * 32 + in_lane
                    weight.append((ic if swapped else ic * n + oc)
                                  if oc < encoded_n and ic < k else -1)
    output = []
    for lane in range(m * n):
        row, col = (lane, 0) if swapped else divmod(lane, n)
        output.append(row * output_channels * 2 + col + (col // 16) * 16)
    return lhs, weight, output


def plan_from_capture(gather):
    f = gather['fields']
    return StaticGather(f['count'], f['base'],
                        tuple(tuple(items(axis)) for axis in items(f['axes'])),
                        tuple(items(f['offsets'])))


def argument_elements(gather, case):
    """Resolve ARG indices against the original logical input/output shapes."""
    f = gather['fields']
    arg = f['src'] if f['src']['fields']['kind']['name'] == 'ARG' else None
    if arg is None:
        return case['scratch_bytes'][f['src']['fields']['index']] // 2
    index = arg['fields']['index']
    dims = case['logical_dimensions']
    if index == 0:
        return dims['m'] * dims['n']
    if index == 1:
        return dims['m'] * dims['k']
    if index == 2:
        return dims['k'] * dims['n']
    raise AssertionError('unexpected source argument role')


def destination_bytes(gather, case):
    f = gather['fields']; dst = f['dst']['fields']
    if f['dst']['fields']['kind']['name'] == 'SCRATCH':
        return case['scratch_bytes'][dst['index']]
    return case['logical_dimensions']['m'] * case['logical_dimensions']['n'] * 2


def bindings_for(gather, case):
    return dict(BINDINGS, source_bytes=argument_elements(gather, case) * 2,
                destination_bytes=destination_bytes(gather, case))


class EncoderFixtureTests(unittest.TestCase):
    def test_all_captured_gathers_against_independent_indices_and_command_abi(self):
        self.assertEqual(FIXTURES['backend_commit'], '078eee94d8f1912bb63ce786c250d2c24984844a')
        self.assertEqual(len(FIXTURES['cases']), 6)
        total = 0
        gather_total = 0
        for case in FIXTURES['cases']:
            dims = case['logical_dimensions']; enc = case['encoded_dimensions']
            expected = independently_expected(dims['m'], dims['n'], dims['k'], enc['m'], enc['n'],
                                              enc['input_channels'], enc['output_channels'])
            self.assertEqual(case['expected_indices'], dict(zip(('input_a', 'weight', 'output'), expected)))
            plans = case['rkgather_plans']
            self.assertEqual(len(plans), 3)
            for gather, independently_computed in zip(plans, expected):
                with self.subTest(case=case['name'], gather=gather['fields']['src']['fields']['index']):
                    plan = plan_from_capture(gather)
                    program = encode(plan, **bindings_for(gather, case))
                    table_values = tuple(x[0] for x in struct.iter_unpack('<I', program.index_bytes))
                    self.assertEqual(table_values, tuple(FILL if x == -1 else x for x in independently_computed))
                    self.assertEqual(len(program.index_bytes), len(independently_computed) * 4)
                    self.assertEqual(len(program.words), 9)
                    values = (ABI, BINDINGS['source_address'], BINDINGS['destination_address'],
                              BINDINGS['table_address'], plan.count, argument_elements(gather, case), 0, 0, 1)
                    for index, (word, value) in enumerate(zip(program.words, values)):
                        self.assertEqual(word >> 48, TARGET)
                        self.assertEqual((word >> 16) & 0xFFFFFFFF, value)
                        self.assertEqual(word & 0xFFFF, index * 4)
                        self.assertEqual(word, (TARGET << 48) | (value << 16) | (index * 4))
                total += len(independently_computed)
                gather_total += 1
        self.assertEqual(gather_total, 18)
        self.assertEqual(total, 16897)
        self.assertEqual(FIXTURES['verified']['gather_indices_exact_match'], total)


class StaticGatherNegativeTests(unittest.TestCase):
    def assert_bad_plan(self, plan, source_elements=8):
        with self.assertRaises(LayoutError):
            plan.indices(source_elements)

    def test_rejects_unsupported_types_booleans_empty_and_count_overflow(self):
        self.assert_bad_plan(StaticGather(1, axes=((1, True, 0),)))
        self.assert_bad_plan(StaticGather(True), 8)
        self.assert_bad_plan(StaticGather(0), 8)
        self.assert_bad_plan(StaticGather(1), True)
        self.assert_bad_plan(StaticGather(0x80000000), 8)
        with self.assertRaises(LayoutError):
            encode(object(), **dict(BINDINGS, source_bytes=16, destination_bytes=2))

    def test_rejects_mutable_ambiguous_or_incomplete_metadata(self):
        self.assert_bad_plan(StaticGather(1, axes=[[1, 1, 0]]))
        self.assert_bad_plan(StaticGather(1, offsets=[0]))
        self.assert_bad_plan(StaticGather(1, axes=((1, 1, 0),), offsets=(0,)))
        self.assert_bad_plan(StaticGather(2, offsets=(0,)))
        self.assert_bad_plan(StaticGather(1, offsets=(0,), base=1))

    def test_rejects_invalid_offsets_and_affine_skips(self):
        self.assert_bad_plan(StaticGather(2, offsets=(-1, -2)))
        self.assert_bad_plan(StaticGather(1, axes=((1, 1, 0),), base=-1))
        self.assert_bad_plan(StaticGather(1, axes=((0, 1, 0),)))

    def test_rejects_bad_alignment_span_wrap_and_overlapping_allocations(self):
        plan = StaticGather(1, offsets=(0,))
        good = dict(BINDINGS, source_bytes=16, destination_bytes=2)
        bad_bindings = (
            dict(good, table_address=0x10050002),
            dict(good, source_address=0x100FFFF0, source_bytes=32),
            dict(good, source_address=0xFFFFFFFF - 15, source_bytes=32),
            dict(good, table_address=0x10010000),
            dict(good, aperture_base=0xFFFFF000, aperture_bytes=0x2000),
        )
        for bindings in bad_bindings:
            with self.subTest(bindings=bindings), self.assertRaises(LayoutError):
                encode(plan, **bindings)


class BufferKind(Enum):
    ARG = 0
    SCRATCH = 1


class Arg(NamedTuple):
    kind: BufferKind
    index: int
    addend: int = 0


class Gather(NamedTuple):
    src: Arg
    dst: Arg
    count: int
    base: int = 0
    axes: tuple = ()
    offsets: tuple = ()
    index: object = None
    values: tuple = ()
    partial: bool = False
    itemsize: int = 2
    index_itemsize: int = 4
    dst_stride: int = 1
    fill_bits: int = 0


class StructuralRenderer:
    RKArg = Arg
    RKBufferKind = BufferKind
    RKGather = Gather


class BackendStructureTests(unittest.TestCase):
    """Mocks preserve the pinned renderer's namedtuple/enum type structure."""
    def valid(self):
        return Gather(Arg(BufferKind.ARG, 1), Arg(BufferKind.SCRATCH, 0), 2,
                      axes=((1, 2, 1),))

    def test_from_backend_structural_conversion(self):
        program = from_backend(self.valid(), StructuralRenderer,
                               **dict(BINDINGS, source_bytes=16, destination_bytes=4))
        self.assertEqual(tuple(x[0] for x in struct.iter_unpack('<I', program.index_bytes)), (0, 1))

    def test_from_backend_rejects_wrong_type_bool_and_unmodeled_modes(self):
        with self.assertRaises(LayoutError):
            from_backend(object(), StructuralRenderer, **dict(BINDINGS, source_bytes=16, destination_bytes=4))
        for bad in (self.valid()._replace(count=True), self.valid()._replace(index=(1,)),
                    self.valid()._replace(values=(2,)), self.valid()._replace(partial=True),
                    self.valid()._replace(itemsize=4), self.valid()._replace(dst_stride=2),
                    self.valid()._replace(src=Arg(BufferKind.ARG, 1, 1))):
            with self.subTest(bad=bad), self.assertRaises(LayoutError):
                from_backend(bad, StructuralRenderer, **dict(BINDINGS, source_bytes=16, destination_bytes=4))

    def test_from_backend_requires_complete_scratch_slot(self):
        gather = self.valid()
        with self.assertRaises(LayoutError):
            from_backend(gather, StructuralRenderer,
                         **dict(BINDINGS, source_bytes=16, destination_bytes=6))


if __name__ == '__main__':
    unittest.main()
