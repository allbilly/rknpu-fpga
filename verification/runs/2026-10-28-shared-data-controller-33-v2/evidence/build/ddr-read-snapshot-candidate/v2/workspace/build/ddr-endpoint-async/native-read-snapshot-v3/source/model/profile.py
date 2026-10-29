"""Narrow, fail-closed profile of allbilly/rk3588/examples/elementwise.py.

These are software-interface facts, not borrowed implementation code. Shape is
8*(WIDTH+1), NOT WIDTH and NOT the logical, unpadded tinygrad tensor length.
No unsupported register or mode is silently ignored.
"""
from __future__ import annotations
import struct
from dataclasses import dataclass

DPU, RDMA, PC, PC_REG, VERSION = 0x1001, 0x2001, 0x0081, 0x0101, 0x0041
OPS = {'ADD': 0x108202c0, 'SUB': 0x108402c0, 'MUL': 0x108003c4}
# target, byte offset, name, fixed value (None means a validated dynamic field)
REGISTERS = (
    (DPU, 0x4004, 'dpu_pointer', 0x0000000e),
    (DPU, 0x400c, 'dpu_mode', 0x000001e5),
    (DPU, 0x4010, 'data_format', 0x48000002),
    (DPU, 0x4030, 'width', None),
    (DPU, 0x4034, 'height', 0),
    (DPU, 0x4038, 'notch', 0),
    (DPU, 0x403c, 'channels', 0x00070007),
    (DPU, 0x4070, 'ew_config', None),
    (DPU, 0x4084, 'out_convert', 0x00010001),
    (RDMA, 0x5004, 'rdma_pointer', 0x0000000e),
    (RDMA, 0x500c, 'rdma_width', None),
    (RDMA, 0x5010, 'rdma_height', 0),
    (RDMA, 0x5014, 'rdma_channels', 7),
    (RDMA, 0x5034, 'erdma_config', 0x40000008),
    (DPU, 0x4020, 'dst', None),
    (RDMA, 0x5018, 'src_a', None),
    (RDMA, 0x5038, 'src_b', None),
    (RDMA, 0x5044, 'rdma_mode', 0x00017849),
    (PC_REG, 0x0010, 'next_address', 0),
    (PC_REG, 0x0014, 'next_amount', 0),
    (VERSION, 0x0000, 'version_marker', 0),
)
# Current tinygrad BOUNDED FP16 initialization group. Either absent (legacy
# profile) or complete for this task; never inherit partial state from a prior
# task. Exact bypass/unity values only. See docs/EW_INITIALIZATION.md for pins,
# register evidence, and the still unsupported current-runtime PC tail.
INITIALIZATION_REGISTERS = (
    (DPU, 0x4040, 'bs_config', 0x53),
    (DPU, 0x4060, 'bn_config', 0x53),
    (DPU, 0x4044, 'bs_alu', 0),
    (DPU, 0x4048, 'bs_mul', 0),
    (DPU, 0x4050, 'bs_ow', 2),
    (DPU, 0x4058, 'wdma_channels', 7),
    (DPU, 0x405c, 'wdma_width', None),
    (DPU, 0x4068, 'bn_mul', 0),
    (DPU, 0x406c, 'bn_relux', 0),
    (DPU, 0x4078, 'ew_scale', 1),
    (DPU, 0x4080, 'out_offset', 0),
    (DPU, 0x4088, 'out_shift', 0),
    (DPU, 0x40c0, 'surface_add', 0x40),
)
REG_INDEX = {(t, a): (i, name, fixed)
             for i, (t, a, name, fixed) in enumerate(REGISTERS + INITIALIZATION_REGISTERS)}
ENABLE = (PC, 0x0008)
ERRORS = {1: 'unknown register/target', 2: 'unsupported register value',
          3: 'incomplete configuration', 4: 'invalid address or overlap',
          5: 'memory bus error', 6: 'shape mismatch', 7: 'unsupported or invalid PC chain',
          8: 'memory timeout'}


class ProfileError(ValueError):
    def __init__(self, code: int, detail: str = ''):
        self.code = code
        super().__init__(f"E{code}: {ERRORS[code]}" + (f": {detail}" if detail else ''))


def encode(target: int, offset: int, value: int) -> int:
    if not (0 <= target <= 0xffff and 0 <= offset <= 0xffff and 0 <= value <= 0xffffffff):
        raise ValueError('command fields out of range')
    return (target << 48) | (value << 16) | offset


def decode(word: int) -> tuple[int, int, int]:
    if not 0 <= word < 1 << 64:
        raise ValueError('command is not a uint64')
    return word >> 48, word & 0xffff, (word >> 16) & 0xffffffff


@dataclass(frozen=True)
class Config:
    op: str
    count: int
    src_a: int
    src_b: int
    dst: int
    next_address: int = 0
    next_amount: int = 0


class Decoder:
    def __init__(self, *, pc_dma: bool = False) -> None:
        self.pc_dma = pc_dma
        self.values: dict[str, int] = {}
        self.fault: ProfileError | None = None

    def feed(self, word: int) -> Config | None:
        if self.fault:
            raise self.fault
        try:
            return self._feed(word)
        except ProfileError as error:
            self.fault = error
            raise

    def _feed(self, word: int) -> Config | None:
        target, addr, value = decode(word)
        if (target, addr) != ENABLE:
            entry = REG_INDEX.get((target, addr))
            if entry is None:
                raise ProfileError(1, f'target={target:#06x} offset={addr:#06x}')
            _, name, fixed = entry
            if self.pc_dma and name.startswith('next_'):
                if name == 'next_address' and value % 16 or name == 'next_amount' and value > 65535:
                    raise ProfileError(7, name)
            elif fixed is not None and value != fixed:
                raise ProfileError(7 if name.startswith('next_') else 2, name)
            if name in ('width', 'rdma_width', 'wdma_width') and value > 7999:
                raise ProfileError(2, 'width profile is 0..7999')
            if name == 'ew_config' and value not in OPS.values():
                raise ProfileError(2, 'only ADD/SUB/MUL are implemented')
            self.values[name] = value
            return None
        if value != 0x18:
            raise ProfileError(2, 'only DPU+RDMA enable mask 0x18 is implemented')
        initialized = any(n in self.values for _, _, n, _ in INITIALIZATION_REGISTERS)
        required = REGISTERS + (INITIALIZATION_REGISTERS if initialized else ())
        missing = [n for _, _, n, _ in required if n not in self.values]
        if missing:
            raise ProfileError(3, ', '.join(missing))
        v = self.values
        if v['width'] != v['rdma_width'] or initialized and v['width'] != v['wdma_width']:
            raise ProfileError(6)
        if self.pc_dma and v['next_amount'] and not v['next_address']:
            raise ProfileError(7, 'nonterminal null next address')
        count = 8 * (v['width'] + 1)
        size = count * 2
        for name in ('src_a', 'src_b', 'dst'):
            base = v[name]
            if base % 16 or base + size > 1 << 32:
                raise ProfileError(4, name)
        for name in ('src_a', 'src_b'):
            a, d = v[name], v['dst']
            if a != d and a < d + size and d < a + size:
                raise ProfileError(4, 'partial output/input alias; exact in-place is supported')
        result = Config(next(k for k, x in OPS.items() if x == v['ew_config']),
                        count, v['src_a'], v['src_b'], v['dst'], v['next_address'], v['next_amount'])
        self.values = {}  # Each task must supply a complete configuration.
        return result


def make_commands(op: str, logical_count: int, a: int, b: int, dst: int) -> bytes:
    """Test-workload builder, not a replacement for tinygrad's RK compiler.

    Captured final regcmd bytes can be sent to Decoder/the RTL unchanged.
    This helper is only for standalone, hardware-independent smoke tests.
    """
    if op not in OPS or not 1 <= logical_count <= 64000:
        raise ValueError('op must be ADD/SUB/MUL and count must be 1..64000')
    dynamic = {'width': (logical_count + 7) // 8 - 1,
               'rdma_width': (logical_count + 7) // 8 - 1,
               'ew_config': OPS[op], 'src_a': a, 'src_b': b, 'dst': dst}
    words = [encode(t, addr, fixed if fixed is not None else dynamic[name])
             for t, addr, name, fixed in REGISTERS]
    words.append(encode(*ENABLE, 0x18))
    return struct.pack('<' + 'Q' * len(words), *words)
