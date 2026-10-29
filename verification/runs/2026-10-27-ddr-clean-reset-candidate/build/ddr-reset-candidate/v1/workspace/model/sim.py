"""Standalone register-command functional emulator; no QEMU or SystemC."""
from __future__ import annotations
import struct
from .half import alu
from .profile import Config, Decoder, ProfileError


class Memory:
    def __init__(self) -> None:
        self.regions: dict[int, bytearray] = {}

    def map(self, base: int, data: bytes | bytearray) -> bytearray:
        if base < 0 or base + len(data) > 1 << 32 or not data:
            raise ValueError('invalid 32-bit device memory region')
        if any(base < b + len(v) and b < base + len(data) for b, v in self.regions.items()):
            raise ValueError('overlapping memory mappings')
        result = bytearray(data)
        self.regions[base] = result
        return result

    def locate(self, address: int, size: int) -> tuple[bytearray, int]:
        for base, data in self.regions.items():
            if base <= address and address + size <= base + len(data):
                return data, address - base
        raise ProfileError(5, f'unmapped address {address:#010x}, size {size}')

    def read16(self, addr: int) -> int:
        if addr & 1:
            raise ProfileError(5, 'unaligned halfword')
        buf, off = self.locate(addr, 2)
        return struct.unpack_from('<H', buf, off)[0]

    def write16(self, addr: int, value: int) -> None:
        if addr & 1:
            raise ProfileError(5, 'unaligned halfword')
        buf, off = self.locate(addr, 2)
        struct.pack_into('<H', buf, off, value)


class RKEmulator:
    def __init__(self, memory: Memory) -> None:
        self.memory = memory
        self.decoder = Decoder()
        self.completed = 0
        self.memory_transactions = 0
        self.fault: ProfileError | None = None

    def execute(self, cfg: Config) -> None:
        for i in range(cfg.count):
            a = self.memory.read16(cfg.src_a + i * 2)
            self.memory_transactions += 1
            b = self.memory.read16(cfg.src_b + i * 2)
            self.memory_transactions += 1
            self.memory.write16(cfg.dst + i * 2, alu(a, b, cfg.op))
            self.memory_transactions += 1
        self.completed += 1

    def submit(self, raw_regcmd: bytes) -> None:
        if self.fault:
            raise self.fault
        if len(raw_regcmd) % 8:
            raise ValueError('register stream must be an integral number of QWORDs')
        try:
            for (word,) in struct.iter_unpack('<Q', raw_regcmd):
                cfg = self.decoder.feed(word)
                if cfg is not None:
                    self.execute(cfg)
            if self.decoder.values:
                raise ProfileError(3, 'stream ended without operation-enable')
        except ProfileError as error:
            self.fault = error
            raise
