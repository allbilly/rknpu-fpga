"""Software functional emulator for the captured integer EW streams.

Companion of ``rtl/rk_ew_int_dma``/``rtl/rk_ew_int_engine``: it executes the
decoded register stream against a byte-addressed device memory image, one
integer lane at a time, and never substitutes host tensor operations for the
hardware path. The same 4096-byte BO images used by the RTL replay are loaded
here, so the two executes must agree byte-for-byte on the asserted mask.
"""
from __future__ import annotations

import struct

from model.int_alu import alu, decode_item, encode_item, signed16
from model.int_profile import IntConfig, ProfileError, decode_regcmd


class IntMemory:
    """Flat byte-addressed device memory; overlapping maps are rejected."""

    def __init__(self) -> None:
        self.regions: dict[int, bytearray] = {}

    def map(self, base: int, data: bytes | bytearray) -> bytearray:
        if base < 0 or base + len(data) > 1 << 32 or not data:
            raise ValueError('invalid 32-bit device memory region')
        if any(base < b + len(v) and b < base + len(data)
               for b, v in self.regions.items()):
            raise ValueError('overlapping memory mappings')
        result = bytearray(data)
        self.regions[base] = result
        return result

    def locate(self, address: int, size: int) -> tuple[bytearray, int]:
        for base, data in self.regions.items():
            if base <= address and address + size <= base + len(data):
                return data, address - base
        raise ProfileError(5, f'unmapped address {address:#010x}, size {size}')

    def read(self, address: int, size: int) -> bytes:
        data, offset = self.locate(address, size)
        return bytes(data[offset:offset + size])

    def write(self, address: int, payload: bytes) -> None:
        data, offset = self.locate(address, len(payload))
        data[offset:offset + len(payload)] = payload


class IntEmulator:
    def __init__(self, memory: IntMemory) -> None:
        self.memory = memory
        self.completed = 0
        self.memory_transactions = 0
        self.fault: ProfileError | None = None

    def execute(self, cfg: IntConfig) -> None:
        for lane in range(cfg.count):
            in_item = cfg.in_item
            out_item = cfg.out_item
            a_raw = self.memory.read(cfg.src_a + lane * in_item, in_item)
            self.memory_transactions += 1
            # Captured INT32-MUL limitation: only the low signed INT16 of the
            # separate EW operand takes part in the multiply.
            b_raw = self.memory.read(cfg.src_b + lane * in_item, in_item)
            self.memory_transactions += 1
            a = decode_item(a_raw, cfg.dtype)
            b = decode_item(b_raw, cfg.dtype)
            if cfg.op == 'MUL' and cfg.dtype == 'INT32':
                b = signed16(struct.unpack_from('<H', b_raw, 0)[0])
            result = alu(cfg.op, cfg.out_dtype, a, b)
            self.memory.write(cfg.dst + lane * out_item,
                              encode_item(result, cfg.out_dtype))
            self.memory_transactions += 1
        self.completed += 1

    def submit(self, raw_regcmd: bytes) -> None:
        if self.fault:
            raise self.fault
        try:
            for cfg in decode_regcmd(raw_regcmd):
                self.execute(cfg)
        except ProfileError as error:
            self.fault = error
            raise


def masked_compare(actual: bytes, expected: bytes, mask: bytes) -> dict:
    """Byte-counted masked comparison: the capture oracle policy."""
    if not (len(actual) == len(expected) == len(mask)):
        raise ValueError('actual/expected/mask must have equal length')
    asserted = 0
    mismatches = []
    for index, (a, e, m) in enumerate(zip(actual, expected, mask)):
        if not m:
            continue
        asserted += 1
        if (a & m) != (e & m):
            mismatches.append({'byte': index, 'actual': a, 'expected': e, 'mask': m})
    return {'asserted_bytes': asserted, 'mismatch_count': len(mismatches),
            'mismatches': mismatches[:16], 'exact': not mismatches,
            'bytes': len(actual)}
