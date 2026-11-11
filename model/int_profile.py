"""Narrow, fail-closed decoder for the captured RK3588 integer EW streams.

Evidence: ``build/rk3588-example-captures/ew-int`` (15 READY bundles, 3
BLOCKED) and the two source examples
``~/rk3588/examples/kernel_6_18/elementwise_int.py`` and
``~/rk3588/examples/expt/elementwise_int.py``. Every accepted register value is
transcribed from those captures (see the generator
``build/rk3588-example-captures/ew-int/tools/gen_bundles.py`` and the source
line references in the manifest). Anything else fails with an explicit code;
nothing is silently coerced or ignored.

This module is additive: it does not import or change the FP16 profile in
``model/profile.py`` except for the shared command encoding and error codes.
"""
from __future__ import annotations
import struct
from dataclasses import dataclass

from model.profile import ProfileError, decode, encode

DPU, RDMA, PC, PC_REG, VERSION = 0x1001, 0x2001, 0x0081, 0x0101, 0x0041

# ---------------------------------------------------------------------------
# Register map (byte offsets taken from the source examples; see manifest
# source_refs and the capture README tables).
# ---------------------------------------------------------------------------
S_POINTER = (DPU, 0x4004)
FEATURE_MODE_CFG = (DPU, 0x400C)
DATA_FORMAT = (DPU, 0x4010)
DST_BASE_ADDR = (DPU, 0x4020)
DST_SURF_STRIDE = (DPU, 0x4024)
DATA_CUBE_WIDTH = (DPU, 0x4030)
DATA_CUBE_HEIGHT = (DPU, 0x4034)
DATA_CUBE_NOTCH = (DPU, 0x4038)
DATA_CUBE_CHANNEL = (DPU, 0x403C)
BS_CFG = (DPU, 0x4040)
BS_ALU_CFG = (DPU, 0x4044)
BS_MUL_CFG = (DPU, 0x4048)
BS_OW_CFG = (DPU, 0x4050)
WDMA_SIZE_0 = (DPU, 0x4058)
WDMA_SIZE_1 = (DPU, 0x405C)
BN_CFG = (DPU, 0x4060)
BN_ALU_CFG = (DPU, 0x4064)
BN_MUL_CFG = (DPU, 0x4068)
EW_CFG = (DPU, 0x4070)
EW_CVT_OFFSET = (DPU, 0x4074)
EW_CVT_SCALE = (DPU, 0x4078)
OUT_CVT_OFFSET = (DPU, 0x4080)
OUT_CVT_SCALE = (DPU, 0x4084)
OUT_CVT_SHIFT = (DPU, 0x4088)
SURFACE_ADD = (DPU, 0x40C0)
RDMA_S_POINTER = (RDMA, 0x5004)
RDMA_DATA_CUBE_WIDTH = (RDMA, 0x500C)
RDMA_DATA_CUBE_HEIGHT = (RDMA, 0x5010)
RDMA_DATA_CUBE_CHANNEL = (RDMA, 0x5014)
RDMA_SRC_BASE_ADDR = (RDMA, 0x5018)
RDMA_BRDMA_CFG = (RDMA, 0x501C)
RDMA_NRDMA_CFG = (RDMA, 0x5028)
RDMA_ERDMA_CFG = (RDMA, 0x5034)
RDMA_EW_BASE_ADDR = (RDMA, 0x5038)
RDMA_EW_SURF_STRIDE = (RDMA, 0x5040)
RDMA_FEATURE_MODE_CFG = (RDMA, 0x5044)
RDMA_SRC_DMA_CFG = (RDMA, 0x5048)
RDMA_SURF_NOTCH = (RDMA, 0x504C)
RDMA_WEIGHT = (RDMA, 0x5068)
RDMA_EW_SURF_NOTCH = (RDMA, 0x506C)
PC_BASE_ADDRESS = (PC_REG, 0x0010)
PC_REGISTER_AMOUNTS = (PC_REG, 0x0014)
VERSION_MARKER = (VERSION, 0x0000)
OPERATION_ENABLE = (PC, 0x0008)

ENABLE_VALUE = 0x18

# ---------------------------------------------------------------------------
# Source constants. PRECISION/ELEMENT_SIZE are the captured RK codes; the ALU
# codes are the source TRM mapping (MAX=0 MIN=1 ADD=2 DIV=3 MINUS=4 ...).
# ---------------------------------------------------------------------------
PRECISION = {'INT8': 0, 'INT16': 1, 'FP16': 2, 'INT32': 4}
ELEMENT_SIZE = {'INT8': 1, 'INT16': 2, 'INT32': 3}
ITEM_SIZE = {'INT8': 1, 'INT16': 2, 'INT32': 4}
DTYPE_FROM_PRECISION = {0: 'INT8', 1: 'INT16', 4: 'INT32'}
ALU_ALGORITHM = {'MAX': 0, 'MIN': 1, 'ADD': 2, 'MINUS': 4}
# Explicitly unsupported (no trustworthy integer oracle / not integer ops).
UNSUPPORTED_ALU = {3: 'DIV', 5: 'ABS', 6: 'NEG', 7: 'FLOOR', 8: 'CEIL'}
OP_TYPE_MUL = 1

# Integer ops with a source-defined oracle. MUL is the separate EW_OP_TYPE lane.
OPS = ('ADD', 'MINUS', 'MUL', 'MAX', 'MIN')

SIMPLE_KEYS = frozenset((
    FEATURE_MODE_CFG, DATA_FORMAT, DATA_CUBE_CHANNEL, DATA_CUBE_WIDTH,
    EW_CFG, EW_CVT_SCALE, RDMA_DATA_CUBE_WIDTH, RDMA_DATA_CUBE_HEIGHT,
    RDMA_DATA_CUBE_CHANNEL, RDMA_ERDMA_CFG, DST_BASE_ADDR, RDMA_SRC_BASE_ADDR,
    RDMA_EW_BASE_ADDR, RDMA_FEATURE_MODE_CFG, PC_BASE_ADDRESS,
    PC_REGISTER_AMOUNTS, VERSION_MARKER,
))
LAYOUT_KEYS = frozenset((
    S_POINTER, RDMA_S_POINTER, RDMA_BRDMA_CFG, RDMA_NRDMA_CFG,
    FEATURE_MODE_CFG, DATA_FORMAT, DST_SURF_STRIDE, DATA_CUBE_WIDTH,
    DATA_CUBE_HEIGHT, DATA_CUBE_NOTCH, DATA_CUBE_CHANNEL, BS_CFG, BS_ALU_CFG,
    BS_MUL_CFG, BS_OW_CFG, WDMA_SIZE_0, WDMA_SIZE_1, BN_CFG, BN_ALU_CFG,
    BN_MUL_CFG, EW_CFG, EW_CVT_SCALE, SURFACE_ADD, RDMA_DATA_CUBE_WIDTH,
    RDMA_DATA_CUBE_HEIGHT, RDMA_DATA_CUBE_CHANNEL, RDMA_ERDMA_CFG,
    RDMA_EW_SURF_STRIDE, RDMA_SRC_DMA_CFG, RDMA_SURF_NOTCH, RDMA_EW_SURF_NOTCH,
    DST_BASE_ADDR, RDMA_SRC_BASE_ADDR, RDMA_EW_BASE_ADDR, RDMA_FEATURE_MODE_CFG,
    RDMA_WEIGHT, PC_BASE_ADDRESS, PC_REGISTER_AMOUNTS, VERSION_MARKER,
))
REGROUP_KEYS = frozenset((
    FEATURE_MODE_CFG, DATA_FORMAT, DST_SURF_STRIDE, DATA_CUBE_WIDTH,
    DATA_CUBE_HEIGHT, DATA_CUBE_NOTCH, DATA_CUBE_CHANNEL, BS_CFG, BS_OW_CFG,
    WDMA_SIZE_0, WDMA_SIZE_1, BN_CFG, EW_CFG, EW_CVT_OFFSET, EW_CVT_SCALE,
    OUT_CVT_OFFSET, OUT_CVT_SCALE, OUT_CVT_SHIFT, SURFACE_ADD,
    RDMA_DATA_CUBE_WIDTH, RDMA_DATA_CUBE_HEIGHT, RDMA_DATA_CUBE_CHANNEL,
    RDMA_ERDMA_CFG, DST_BASE_ADDR, RDMA_SRC_BASE_ADDR, RDMA_EW_BASE_ADDR,
    RDMA_FEATURE_MODE_CFG, PC_BASE_ADDRESS, PC_REGISTER_AMOUNTS,
    VERSION_MARKER,
))
KNOWN_KEYS = SIMPLE_KEYS | LAYOUT_KEYS | REGROUP_KEYS
MODE_KEYS = {'simple': SIMPLE_KEYS, 'layout': LAYOUT_KEYS, 'regroup': REGROUP_KEYS}

# DWARF: captured-only geometry and numeric contracts.
# Captured simple-path channel counts (manifest coverage.lane_shapes): INT8 and
# INT16 use eight channels, INT32 four. This is a capture fact, not a TRM rule.
SIMPLE_CHANNELS = {'INT8': 8, 'INT16': 8, 'INT32': 4}
CUBE_HEIGHT = 0
FEATURE_MODE = 0x000001E5         # burst_len=15, output_mode=2, flying_mode=1
BS_CFG_VALUE = 0x00000053
BN_CFG_VALUE = 0x00000053
BS_OW_LAYOUT = 2
BS_OW_REGROUP = 0x00000126        # SIZE_E_0/1/2=1: regroup all eight INT16 lanes
RDMA_WEIGHT_VALUE = 0x01010101
DST_SURF_STRIDE_REGROUP = 1 << 4
SURFACE_ADD_REGROUP = 2 << 4
REGROUP_CHANNELS = 8
REGROUP_COUNT = 8
MAX_COUNT = 64000

LAYOUT_SURFACE_WIDTH = 1          # captured layout streams are all width=1


@dataclass(frozen=True)
class IntConfig:
    mode: str            # 'simple' | 'layout' | 'regroup'
    op: str              # 'ADD' | 'MINUS' | 'MUL' | 'MAX' | 'MIN'
    dtype: str           # input dtype
    out_dtype: str       # destination dtype (differs only for regroup)
    count: int           # logical lanes
    width: int
    channels: int
    layout: str          # 'contiguous' | 'surface'
    src_a: int
    src_b: int
    dst: int
    in_bytes: int
    out_bytes: int

    @property
    def in_item(self) -> int:
        return ITEM_SIZE[self.dtype]

    @property
    def out_item(self) -> int:
        return ITEM_SIZE[self.out_dtype]


def grid_count(width: int, channels: int) -> int:
    return width * channels


def surface_bytes(width: int, channels: int, item: int) -> int:
    atom = 16 // item
    surfaces = (channels + atom - 1) // atom
    return surfaces * width * 16


def ew_cfg_value(dtype: str, op: str, converter_bypass: bool) -> int:
    """Reconstruct the exact captured DPU.EW_CFG word for dtype x op."""
    if dtype not in ELEMENT_SIZE:
        raise ValueError(f'unsupported integer dtype: {dtype!r}')
    if op not in OPS:
        raise ValueError(f'unsupported integer op: {op!r}')
    value = ((1 << 28) | (ELEMENT_SIZE[dtype] << 22) | (1 << 9) | (1 << 7) | (1 << 6))
    if op == 'MUL':
        value |= OP_TYPE_MUL << 2
    else:
        value |= ALU_ALGORITHM[op] << 16
    if op in ('MAX', 'MIN'):
        value |= 1 << 21      # EW_EQUAL_EN, matching RKNN min/max captures
    if converter_bypass:
        value |= 1 << 8       # INT32 bypasses the integer output converter
    return value


def erdma_cfg_value(dtype: str) -> int:
    return (1 << 30) | (ELEMENT_SIZE[dtype] << 2)


def rdma_mode_value(dtype: str) -> int:
    precision = PRECISION[dtype]
    return (precision << 15) | (15 << 11) | (precision << 5) | 1


def data_format_value(in_dtype: str, out_dtype: str, proc_dtype: str) -> int:
    return ((PRECISION[out_dtype] << 29) | (PRECISION[in_dtype] << 26)
            | PRECISION[proc_dtype])


def make_commands(*args, **kwargs):  # pragma: no cover - captures are the builder
    raise NotImplementedError(
        'The ew-int family is register-capture driven; use the captured '
        'regcmd.bin bundles. The FP16 builder in model/profile.py is unrelated.')


class IntDecoder:
    """Order-independent set decoder with an exact per-mode register contract."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.values: dict[tuple[int, int], int] = {}
        self.keys: set[tuple[int, int]] = set()
        self.fault: ProfileError | None = None

    def feed(self, word: int) -> IntConfig | None:
        if self.fault:
            raise self.fault
        try:
            return self._feed(word)
        except ProfileError as error:
            self.fault = error
            raise

    def _set(self, key: tuple[int, int], value: int, name: str) -> None:
        previous = self.values.get(key)
        if previous is not None and previous != value:
            raise ProfileError(2, f'conflicting writes to {name}: '
                                  f'{previous:#010x} then {value:#010x}')
        self.values[key] = value
        self.keys.add(key)

    def _feed(self, word: int) -> IntConfig | None:
        target, offset, value = decode(word)
        key = (target, offset)
        if key == OPERATION_ENABLE:
            if value != ENABLE_VALUE:
                raise ProfileError(2, f'only DPU+RDMA enable mask {ENABLE_VALUE:#04x} '
                                      'is implemented')
            return self.finalize()
        if key not in KNOWN_KEYS:
            raise ProfileError(1, f'target={target:#06x} offset={offset:#06x}')
        name = _name(key)
        self._set(key, value, name)
        return None

    # -- validation ---------------------------------------------------------
    def _expect(self, key: tuple[int, int], expected: int) -> None:
        value = self.values[key]
        if value != expected:
            raise ProfileError(2, f'{_name(key)} is {value:#010x}; '
                                  f'captured value is {expected:#010x}')

    def _dtype(self) -> tuple[str, str]:
        value = self.values[DATA_FORMAT]
        out_precision = (value >> 29) & 0x7
        in_precision = (value >> 26) & 0x7
        proc_precision = value & 0x7
        for code in (out_precision, in_precision, proc_precision):
            if code not in DTYPE_FROM_PRECISION:
                raise ProfileError(2, f'DATA_FORMAT precision code {code} is not an '
                                      'evidenced integer dtype (INT8/INT16/INT32)')
        return (DTYPE_FROM_PRECISION[in_precision],
                DTYPE_FROM_PRECISION[out_precision],
                DTYPE_FROM_PRECISION[proc_precision])

    def _op(self) -> str:
        value = self.values[EW_CFG]
        if (value >> 2) & 1:
            if (value >> 16) & 0xF:
                raise ProfileError(2, 'EW_CFG sets both the MUL lane and an ALU code')
            return 'MUL'
        alu = (value >> 16) & 0xF
        for name, code in ALU_ALGORITHM.items():
            if code == alu:
                return name
        if alu in UNSUPPORTED_ALU:
            raise ProfileError(2, f'{UNSUPPORTED_ALU[alu]} is not an evidenced '
                                  'integer op (no captured oracle)')
        raise ProfileError(2, f'EW ALU code {alu} is not a captured integer op')

    def finalize(self) -> IntConfig:
        mode = self._mode()
        required = MODE_KEYS[mode]
        if not self.values:
            raise ProfileError(3, 'stream ended without any register write')
        extra = sorted(self.keys - required)
        if extra:
            raise ProfileError(2, 'register not in the captured ' + mode +
                                  ' contract: ' + ', '.join(_name(k) for k in extra))
        missing = sorted(required - self.keys)
        if missing:
            raise ProfileError(3, ', '.join(_name(k) for k in missing))
        in_dtype, out_dtype, proc_dtype = self._dtype()
        op = self._op()
        if mode == 'regroup':
            if (in_dtype, out_dtype, proc_dtype) != ('INT16', 'INT32', 'INT16'):
                raise ProfileError(2, 'regroup stream requires INT16 input, INT16 '
                                      'process and INT32 output precision')
            if op != 'ADD':
                raise ProfileError(2, f'{op} has no captured INT16->INT32 regroup stream')
            dtype = 'INT16'
            bypass = False
        else:
            if not (in_dtype == out_dtype == proc_dtype):
                raise ProfileError(2, 'simple/layout streams require one dtype for '
                                      'input, process and output precision')
            dtype = in_dtype
            bypass = dtype == 'INT32'
        expected_ew = ew_cfg_value(dtype, op, bypass)
        if mode == 'regroup':
            expected_ew = ew_cfg_value('INT16', 'ADD', False)
        self._expect(EW_CFG, expected_ew)
        self._expect(FEATURE_MODE_CFG, FEATURE_MODE)
        self._expect(RDMA_ERDMA_CFG, erdma_cfg_value(dtype))
        self._expect(RDMA_FEATURE_MODE_CFG, rdma_mode_value(dtype))
        self._expect(VERSION_MARKER, 0)
        self._expect(PC_BASE_ADDRESS, 0)
        self._expect(PC_REGISTER_AMOUNTS, 0)
        channels = self._channels(dtype)
        width = self._width()
        self._mode_contract(mode, dtype, op, width, channels)
        count = grid_count(width, channels)
        if not 1 <= count <= MAX_COUNT:
            raise ProfileError(6, f'element count {count} outside 1..{MAX_COUNT}')
        if mode == 'regroup':
            count = REGROUP_COUNT
            channels = REGROUP_CHANNELS
            width = LAYOUT_SURFACE_WIDTH
        layout = 'surface' if mode == 'layout' else 'contiguous'
        in_item = ITEM_SIZE[dtype]
        out_item = ITEM_SIZE[out_dtype]
        if layout == 'surface':
            in_bytes = surface_bytes(width, channels, in_item)
            out_bytes = surface_bytes(width, channels, out_item)
        else:
            in_bytes = count * in_item
            out_bytes = count * out_item
        src_a = self.values[RDMA_SRC_BASE_ADDR]
        src_b = self.values[RDMA_EW_BASE_ADDR]
        dst = self.values[DST_BASE_ADDR]
        self._address('dst', dst, out_bytes)
        self._address('a', src_a, in_bytes)
        self._address('b', src_b, in_bytes)
        self._no_partial_overlap('a', src_a, dst, in_bytes, out_bytes)
        self._no_partial_overlap('b', src_b, dst, in_bytes, out_bytes)
        for value, name in ((self.values[PC_BASE_ADDRESS], 'next_address'),
                            (self.values[PC_REGISTER_AMOUNTS], 'next_amount')):
            if value:
                raise ProfileError(7, f'{name} is non-zero; multi-task PC chains are '
                                      'not evidenced for ew-int')
        result = IntConfig(mode=mode, op=op, dtype=dtype, out_dtype=out_dtype,
                           count=count, width=width, channels=channels,
                           layout=layout, src_a=src_a, src_b=src_b, dst=dst,
                           in_bytes=in_bytes, out_bytes=out_bytes)
        self.reset()
        return result

    def _mode(self) -> str:
        if EW_CVT_OFFSET in self.keys:
            return 'regroup'
        if DST_SURF_STRIDE in self.keys:
            return 'layout'
        return 'simple'

    def _channels(self, dtype: str) -> int:
        value = self.values[DATA_CUBE_CHANNEL]
        low = value & 0xFFFF
        high = (value >> 16) & 0xFFFF
        if low != high:
            raise ProfileError(2, 'DATA_CUBE_CHANNEL ORIG_CHANNEL and CHANNEL differ')
        channels = low + 1
        rdma_channels = self.values[RDMA_DATA_CUBE_CHANNEL] + 1
        if rdma_channels != channels:
            raise ProfileError(6, 'DPU and RDMA channel counts differ')
        if channels < 1 or channels > 8191:
            raise ProfileError(6, 'channel count outside 1..8191')
        return channels

    def _width(self) -> int:
        value = self.values[DATA_CUBE_WIDTH] + 1
        rdma_width = self.values[RDMA_DATA_CUBE_WIDTH] + 1
        if rdma_width != value:
            raise ProfileError(6, 'DPU and RDMA widths differ')
        if not 1 <= value <= 4096:
            raise ProfileError(6, 'width field outside 1..4096')
        return value

    def _mode_contract(self, mode: str, dtype: str, op: str,
                       width: int, channels: int) -> None:
        if mode in ('simple', 'layout'):
            self._expect(RDMA_DATA_CUBE_HEIGHT, 0)
            self._expect(EW_CVT_SCALE, 1)
        if mode == 'simple':
            expected_channels = SIMPLE_CHANNELS[dtype]
            if channels != expected_channels:
                raise ProfileError(6, 'simple stream must use the captured '
                                      f'{expected_channels}-channel geometry for '
                                      f'{dtype}, got {channels}')
            return
        if mode == 'layout':
            if width != LAYOUT_SURFACE_WIDTH:
                raise ProfileError(6, 'surface layout is only captured at width=1')
            stride = width << 4
            self._expect(S_POINTER, 0xE)
            self._expect(RDMA_S_POINTER, 0xE)
            self._expect(RDMA_BRDMA_CFG, 1)
            self._expect(RDMA_NRDMA_CFG, 1)
            self._expect(DST_SURF_STRIDE, stride)
            self._expect(DATA_CUBE_HEIGHT, CUBE_HEIGHT)
            self._expect(DATA_CUBE_NOTCH, 0)
            self._expect(BS_CFG, BS_CFG_VALUE)
            self._expect(BS_ALU_CFG, 0)
            self._expect(BS_MUL_CFG, 0)
            self._expect(BS_OW_CFG, BS_OW_LAYOUT)
            self._expect(WDMA_SIZE_0, channels - 1)
            self._expect(WDMA_SIZE_1, width - 1)
            self._expect(BN_CFG, BN_CFG_VALUE)
            self._expect(BN_ALU_CFG, 0)
            self._expect(BN_MUL_CFG, 0)
            self._expect(SURFACE_ADD, stride)
            self._expect(RDMA_EW_SURF_STRIDE, stride)
            self._expect(RDMA_SRC_DMA_CFG, 0)
            self._expect(RDMA_SURF_NOTCH, 0)
            self._expect(RDMA_EW_SURF_NOTCH, 0)
            self._expect(RDMA_WEIGHT, RDMA_WEIGHT_VALUE)
            return
        # regroup: distinct 16-to-32 writeback contract, captured only for 8 lanes.
        if (width, channels) != (LAYOUT_SURFACE_WIDTH, REGROUP_CHANNELS):
            raise ProfileError(6, 'regroup contract is captured only for 8 lanes')
        self._expect(DST_SURF_STRIDE, DST_SURF_STRIDE_REGROUP)
        self._expect(DATA_CUBE_HEIGHT, 0)
        self._expect(DATA_CUBE_NOTCH, 0)
        self._expect(BS_CFG, BS_CFG_VALUE)
        self._expect(BS_OW_CFG, BS_OW_REGROUP)
        self._expect(WDMA_SIZE_0, REGROUP_CHANNELS - 1)
        self._expect(WDMA_SIZE_1, 0)
        self._expect(BN_CFG, BN_CFG_VALUE)
        self._expect(EW_CVT_OFFSET, 0)
        self._expect(EW_CVT_SCALE, 1)
        self._expect(OUT_CVT_OFFSET, 0)
        self._expect(OUT_CVT_SCALE, 1)
        self._expect(OUT_CVT_SHIFT, 0)
        self._expect(SURFACE_ADD, SURFACE_ADD_REGROUP)
        self._expect(RDMA_DATA_CUBE_HEIGHT, 0)
        self._expect(RDMA_DATA_CUBE_CHANNEL, REGROUP_CHANNELS - 1)
        self._expect(RDMA_DATA_CUBE_WIDTH, 0)

    def _address(self, name: str, base: int, size: int) -> None:
        if base % 16:
            raise ProfileError(4, f'{name} base {base:#010x} is not 16-byte aligned')
        if base + size > 1 << 32:
            raise ProfileError(4, f'{name} range {base:#010x}+{size} wraps the '
                                  '32-bit device address space')

    def _no_partial_overlap(self, name: str, base: int, dst: int,
                            in_bytes: int, out_bytes: int) -> None:
        if base == dst:
            return
        if base < dst + out_bytes and dst < base + in_bytes:
            raise ProfileError(4, f'partial output/{name} alias; exact in-place is '
                                  'the only supported overlap')


_NAMES = {value: name.lower() for name, value in list(globals().items())
          if isinstance(value, tuple) and len(value) == 2 and
          all(isinstance(part, int) for part in value)}


def _name(key: tuple[int, int]) -> str:
    return _NAMES.get(key, f'{key[0]:#06x}:{key[1]:#06x}')


def decode_regcmd(raw: bytes) -> list[IntConfig]:
    """Decode one captured regcmd BO; returns the executed task list."""
    if len(raw) % 8:
        raise ValueError('register stream must be an integral number of QWORDs')
    decoder = IntDecoder()
    configs = []
    for (word,) in struct.iter_unpack('<Q', raw):
        config = decoder.feed(word)
        if config is not None:
            configs.append(config)
    if decoder.values:
        raise ProfileError(3, 'stream ended without operation-enable')
    if not configs:
        raise ProfileError(3, 'stream contains no operation-enable')
    return configs


def patch_value32(raw: bytes, target: int, offset: int, value32: int) -> bytes:
    """Apply the capture-format value32 patch to exactly one QWORD."""
    if not 0 <= value32 <= 0xFFFFFFFF:
        raise ValueError('value32 out of range')
    data = bytearray(raw)
    matches = 0
    for index in range(0, len(data), 8):
        word = int.from_bytes(data[index:index + 8], 'little')
        if word >> 48 == target and word & 0xFFFF == offset:
            word = (word & 0xFFFF_0000_0000_FFFF) | (value32 << 16)
            data[index:index + 8] = word.to_bytes(8, 'little')
            matches += 1
    if matches != 1:
        raise ValueError(f'expected exactly one write to {target:#06x}:{offset:#06x}, '
                         f'found {matches}')
    return bytes(data)
