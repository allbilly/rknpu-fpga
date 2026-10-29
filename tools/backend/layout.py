"""Encode immutable compiler gather metadata for the FPGA layout DMA.

This module never reads tensor/BO contents. The index table is command metadata;
the FPGA reads original source halfwords and writes the destination itself.
This private FPGA extension does not claim an RK3588 register ABI.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

TARGET, ABI, AMOUNT, FILL = 0xFF01, 0x00010002, 9, 0xFFFFFFFF


class LayoutError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise LayoutError(message)


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, 'Unsupported ' + label)
    return value


@dataclass(frozen=True)
class StaticGather:
    count: int
    base: int = 0
    axes: tuple[tuple[int, int, int], ...] = ()
    offsets: tuple[int, ...] = ()

    def indices(self, source_elements):
        integer(self.count, 1, 0x7FFFFFFF, 'layout count')
        integer(source_elements, 1, 0x7FFFFFFF, 'source elements')
        integer(self.base, -0x80000000, 0x7FFFFFFF, 'gather base')
        require(type(self.axes) is tuple and type(self.offsets) is tuple, 'Mutable gather metadata')
        require(not (self.axes and self.offsets), 'Ambiguous axes and offsets')
        for axis in self.axes:
            require(type(axis) is tuple and len(axis) == 3, 'Malformed gather axis')
            integer(axis[0], 1, 0x7FFFFFFF, 'axis divisor')
            integer(axis[1], 1, 0x7FFFFFFF, 'axis limit')
            integer(axis[2], -0x80000000, 0x7FFFFFFF, 'axis stride')
        if self.offsets:
            require(len(self.offsets) == self.count, 'Incomplete static offsets')
            require(self.base == 0, 'Nonzero base with static offsets')
            result = tuple(integer(x, -1, source_elements - 1, 'static source index') for x in self.offsets)
        else:
            result = tuple(self.base + sum((lane // divisor % limit) * stride
                                          for divisor, limit, stride in self.axes)
                           for lane in range(self.count))
            # The original affine path can preserve out-of-range destination
            # lanes. This profile has no partial writes: reject that case.
            require(all(0 <= x < source_elements for x in result), 'Affine gather would skip a lane')
        return tuple(FILL if x == -1 else x for x in result)


@dataclass(frozen=True)
class LayoutProgram:
    words: tuple[int, ...]
    index_bytes: bytes

    @property
    def command_bytes(self):
        return struct.pack('<9Q', *self.words)


def encode(plan: StaticGather, *, source_address, destination_address, source_bytes,
           destination_bytes, table_address, command_address, aperture_base=0x10000000,
           aperture_bytes=1048576):
    """Encode nine final QWORDs and a static index BO, without reading data."""
    require(type(plan) is StaticGather, 'Expected immutable static gather')
    integer(aperture_base, 0, 0xFFFFFFFF, 'aperture base')
    integer(aperture_bytes, 1, 0xFFFFFFFF, 'aperture bytes')
    require(aperture_base + aperture_bytes <= 1 << 32, 'Wrapping aperture')
    integer(source_bytes, 2, aperture_bytes, 'source byte span')
    integer(destination_bytes, 2, aperture_bytes, 'destination byte span')
    require(source_bytes % 2 == destination_bytes % 2 == 0, 'Mis-sized halfword view')
    integer(plan.count, 1, min(destination_bytes // 2, aperture_bytes // 4), 'layout count')
    indices = plan.indices(source_bytes // 2)
    spans = ((source_address, source_bytes, 2), (destination_address, plan.count * 2, 2),
             (table_address, plan.count * 4, 4), (command_address, AMOUNT * 8, 16))
    for address, size, alignment in spans:
        integer(address, 0, 0xFFFFFFFF, 'layout address')
        require(address % alignment == 0 and aperture_base <= address and
                address + size <= aperture_base + aperture_bytes, 'Layout span escapes aperture or is unaligned')
    for i, (address, size, _) in enumerate(spans):
        for other, length, _ in spans[:i]:
            require(address + size <= other or other + length <= address, 'Overlapping layout allocations')
    values = (ABI, source_address, destination_address, table_address, plan.count, source_bytes // 2, 0, 0, 1)
    words = tuple((TARGET << 48) | (value << 16) | (index * 4) for index, value in enumerate(values))
    return LayoutProgram(words, struct.pack('<' + 'I' * len(indices), *indices))


def from_backend(gather, renderer, **bindings):
    """Lower an actual pinned RKGather, never a tensor operation or data view.

    Binding ownership and pin verification belong to the runtime caller. Until
    that integration is qualified, the existing runtime keeps rejecting CMAC.
    """
    require(type(gather) is renderer.RKGather, 'Expected original RKGather')
    for arg in (gather.src, gather.dst):
        require(type(arg) is renderer.RKArg and type(arg.kind) is renderer.RKBufferKind,
                'Invalid compiler buffer reference')
        integer(arg.index, 0, 0x7FFFFFFF, 'buffer index')
        integer(arg.addend, 0, 0xFFFFFFFF, 'buffer addend')
        require(arg.addend % 2 == 0, 'Unaligned compiler buffer reference')
    require(gather.index is None and type(gather.values) is tuple and not gather.values and gather.partial is False,
            'Runtime indices, literal values or partial gathers are unsupported')
    for value, expected, label in ((gather.itemsize, 2, 'item size'), (gather.index_itemsize, 4, 'index size'),
                                   (gather.dst_stride, 1, 'destination stride'), (gather.fill_bits, 0, 'fill bits')):
        require(type(value) is int and value == expected, 'Unsupported ' + label)
    if gather.dst.kind is renderer.RKBufferKind.SCRATCH:
        require(gather.dst.addend == 0 and bindings['destination_bytes'] == gather.count * 2,
                'Scratch gather must overwrite its complete logical slot')
    return encode(StaticGather(gather.count, gather.base, gather.axes, gather.offsets), **bindings)
