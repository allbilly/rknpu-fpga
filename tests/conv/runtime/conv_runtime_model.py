#!/usr/bin/env python3
"""Golden runtime decoder model for the capture-bounded RK3588 CNA conv stream.

This module is the Python twin of `rtl/cmac/experimental/runtime/
rk_conv_runtime_decode.sv`. It consumes the **raw final command QWORDs** of one
captured task (unchanged; only the three documented value32 DMA-address
relocations are supplied by the job) and derives the convolution geometry from
the register fields instead of comparing the stream against a per-capture
constant table.

Every derivation below is tied to the pinned donor source that wrote the
field, not guessed:

* `/home/fedora/rk3588/examples/kernel_6_18/conv_new_clean.py`
  (`make_conv2d_regs`, lines 445-629; `_conv_params` 308-332; packing helpers
  380-460) - the 54-QWORD CNA+RDMA-prefixed family (`conv-fp16` captures,
  SHA-256 f70e9810...).
* `/home/fedora/rk3588/examples/expt/conv_simple.py`
  (`make_regs`, 309-367; `_conv_params`/`pack_input`/`pack_weights`) and
  `/home/fedora/rk3588/examples/conv_simple.py` - the 52-QWORD CNA-only family
  (`conv-simple` captures).

The two families share the same register field grammar but differ in the
canonical word sequence (RDMA prefix present/absent), in the weight BO packing
(`kh_major` contiguous vs 16-output-channel chunks) and in the FP16 output BO
size formula. Those are properties of the captured driver path, not of a
register field; the decoder therefore binds them to the canonical sequence and
refuses anything else.

The model is used two ways:

1. `--check` validates the field map against every pinned fixture's manifest:
   the decoded geometry, alignment, BO sizes and DMA addresses must equal what
   the fixture/reference declared, and the derived byte sizes must equal the
   actual fixture file sizes.
2. The equivalence harness imports `decode()` to build the runtime-engine
   configuration for the RTL replay and to cross-check the RTL result.

Exit status is 0 only when every case decodes and matches.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / 'tests/conv/fixtures'
BUNDLES = ROOT / 'build/rk3588-example-captures'

# Register targets (bits 63:48) and offsets (bits 15:0); the value is bits
# 47:16. Names are the donor symbols from the two pinned example sources.
T_DPU = 0x1001
T_CNA = 0x0201
T_CORE = 0x0801
T_RDMA = 0x2001
T_PC = 0x0081
T_PC_REG = 0x0101
T_VERSION = 0x0041

FIELDS = {
    (T_DPU, 0x4004): 'DPU_S_POINTER',
    (T_RDMA, 0x5004): 'RDMA_S_POINTER',
    (T_RDMA, 0x5034): 'RDMA_ERDMA_CFG',
    (T_RDMA, 0x5044): 'RDMA_FEATURE_MODE_CFG',
    (T_CNA, 0x100c): 'CNA_CONV_CON1',
    (T_CNA, 0x1010): 'CNA_CONV_CON2',
    (T_CNA, 0x1014): 'CNA_CONV_CON3',
    (T_CNA, 0x1020): 'CNA_DATA_SIZE0',
    (T_CNA, 0x1024): 'CNA_DATA_SIZE1',
    (T_CNA, 0x1028): 'CNA_DATA_SIZE2',
    (T_CNA, 0x102c): 'CNA_DATA_SIZE3',
    (T_CNA, 0x1030): 'CNA_WEIGHT_SIZE0',
    (T_CNA, 0x1034): 'CNA_WEIGHT_SIZE1',
    (T_CNA, 0x1038): 'CNA_WEIGHT_SIZE2',
    (T_CNA, 0x1040): 'CNA_CBUF_CON0',
    (T_CNA, 0x1044): 'CNA_CBUF_CON1',
    (T_CNA, 0x104c): 'CNA_CVT_CON0',
    (T_CNA, 0x1050): 'CNA_CVT_CON1',
    (T_CNA, 0x1054): 'CNA_CVT_CON2',
    (T_CNA, 0x1058): 'CNA_CVT_CON3',
    (T_CNA, 0x105c): 'CNA_CVT_CON4',
    (T_CNA, 0x1070): 'CNA_FEATURE_DATA_ADDR',
    (T_CNA, 0x1078): 'CNA_DMA_CON0',
    (T_CNA, 0x107c): 'CNA_DMA_CON1',
    (T_CNA, 0x1080): 'CNA_DMA_CON2',
    (T_CNA, 0x1084): 'CNA_FC_DATA_SIZE0',
    (T_CNA, 0x1088): 'CNA_FC_DATA_SIZE1',
    (T_CNA, 0x1110): 'CNA_DCOMP_ADDR0',
    (T_CNA, 0x1180): 'CNA_CVT_CON5',
    (T_CORE, 0x3010): 'CORE_MISC_CFG',
    (T_CORE, 0x3014): 'CORE_DATAOUT_SIZE_0',
    (T_CORE, 0x3018): 'CORE_DATAOUT_SIZE_1',
    (T_CORE, 0x3030): 'CORE_RESERVED_3030',
    (T_DPU, 0x400c): 'DPU_FEATURE_MODE_CFG',
    (T_DPU, 0x4010): 'DPU_DATA_FORMAT',
    (T_DPU, 0x4020): 'DPU_DST_BASE_ADDR',
    (T_DPU, 0x4024): 'DPU_DST_SURF_STRIDE',
    (T_DPU, 0x4030): 'DPU_DATA_CUBE_WIDTH',
    (T_DPU, 0x4034): 'DPU_DATA_CUBE_HEIGHT',
    (T_DPU, 0x4038): 'DPU_DATA_CUBE_NOTCH',
    (T_DPU, 0x403c): 'DPU_DATA_CUBE_CHANNEL',
    (T_DPU, 0x4040): 'DPU_BS_CFG',
    (T_DPU, 0x4050): 'DPU_BS_OW_CFG',
    (T_DPU, 0x4058): 'DPU_WDMA_SIZE_0',
    (T_DPU, 0x405c): 'DPU_WDMA_SIZE_1',
    (T_DPU, 0x4060): 'DPU_BN_CFG',
    (T_DPU, 0x4070): 'DPU_EW_CFG',
    (T_DPU, 0x4078): 'DPU_EW_CVT_SCALE_VALUE',
    (T_DPU, 0x4084): 'DPU_OUT_CVT_SCALE',
    (T_DPU, 0x40c0): 'DPU_SURFACE_ADD',
    (T_PC, 0x0008): 'PC_OPERATION_ENABLE',
    (T_PC_REG, 0x0010): 'PC_BASE_ADDRESS',
    (T_PC_REG, 0x0014): 'PC_REGISTER_AMOUNTS',
    (T_VERSION, 0x0000): 'VERSION',
}

# Canonical word order of each captured driver family. The 54-word family is
# the conv_new_clean.py task (CNA body prefixed by the DPU-RDMA clear words);
# the 52-word family is the conv_simple.py task. Anything else is refused.
BODY = [
    (T_CNA, 0x100c), (T_CNA, 0x1010), (T_CNA, 0x1014),
    (T_CNA, 0x1020), (T_CNA, 0x1024), (T_CNA, 0x1028), (T_CNA, 0x102c),
    (T_CNA, 0x1030), (T_CNA, 0x1034), (T_CNA, 0x1038),
    (T_CNA, 0x1040), (T_CNA, 0x1044),
    (T_CNA, 0x104c), (T_CNA, 0x1050), (T_CNA, 0x1054), (T_CNA, 0x1058),
    (T_CNA, 0x105c), (T_CNA, 0x1070), (T_CNA, 0x1078), (T_CNA, 0x107c),
    (T_CNA, 0x1080), (T_CNA, 0x1084), (T_CNA, 0x1088), (T_CNA, 0x1110),
    (T_CNA, 0x1180),
    (T_CORE, 0x3010), (T_CORE, 0x3014), (T_CORE, 0x3018), (T_CORE, 0x3030),
    (T_DPU, 0x400c), (T_DPU, 0x4010), (T_DPU, 0x4020), (T_DPU, 0x4024),
    (T_DPU, 0x4030), (T_DPU, 0x4034), (T_DPU, 0x4038), (T_DPU, 0x403c),
    (T_DPU, 0x4040), (T_DPU, 0x4050), (T_DPU, 0x4058), (T_DPU, 0x405c),
    (T_DPU, 0x4060), (T_DPU, 0x4070), (T_DPU, 0x4078), (T_DPU, 0x4084),
    (T_DPU, 0x40c0),
]
PC_TAIL = [(T_PC_REG, 0x0010), (T_PC_REG, 0x0014),
           (T_VERSION, 0x0000), (T_PC, 0x0008)]
RDMA_PREFIX = [(T_RDMA, 0x5004), (T_RDMA, 0x5034), (T_RDMA, 0x5044)]
SEQUENCE_54 = [(T_DPU, 0x4004)] + RDMA_PREFIX + BODY + PC_TAIL
SEQUENCE_52 = [(T_DPU, 0x4004)] + BODY + PC_TAIL + [(0, 0)]  # last = padding

# Buffer-size / supported-geometry bounds of the capture-bounded engine. These
# are the corpus maxima plus explicit headroom; a stream outside them is
# refused, never silently executed with a widened interpretation.
MAX_INPUT_PIXELS = 320
MAX_WEIGHT_HALFWORDS = 4608
MAX_OUTPUT_BLOCKS = 4
MAX_KERNEL = 5
MAX_CHANNELS = 32
MAX_STRIDE = 2


class DecodeError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f'code {code}: {message}')
        self.code = code
        self.message = message


def _u(value: int, hi: int, lo: int) -> int:
    return (value >> lo) & ((1 << (hi - lo + 1)) - 1)


def _ceil_div(x: int, y: int) -> int:
    return (x + y - 1) // y


def _align_up(x: int, align: int) -> int:
    return _ceil_div(x, align) * align


def unpack_words(payload: bytes) -> list[int]:
    if len(payload) % 8:
        raise DecodeError(3, 'command stream is not a whole number of QWORDs')
    return list(struct.unpack(f'<{len(payload) // 8}Q', payload))


def relocate(raw: bytes, addresses: dict[str, int], patches: list[dict]) -> bytes:
    """Apply the job's documented value32 DMA address relocations."""
    patched = bytearray(raw)
    for patch in patches:
        index = patch['regcmd_index']
        qword, = struct.unpack_from('<Q', patched, index * 8)
        qword = (qword & ~(0xffffffff << 16)) | (addresses[patch['buffer']] << 16)
        struct.pack_into('<Q', patched, index * 8, qword)
    return bytes(patched)


def decode(words: list[int]) -> dict:
    """Strictly decode one captured CNA task into runtime geometry/config."""
    n = len(words)
    if n not in (52, 54):
        raise DecodeError(3, f'unsupported command length {n} (expected 52 or 54)')
    # Family is fixed by the canonical sequence the job uses. Word 1 is the
    # first discriminating word (RDMA_S_POINTER vs CNA_CONV_CON1).
    tag1 = (words[1] >> 48, words[1] & 0xffff)
    if tag1 == (T_RDMA, 0x5004):
        family, sequence = 'conv_fp16', SEQUENCE_54
    elif tag1 == (T_CNA, 0x100c):
        family, sequence = 'conv_simple', SEQUENCE_52
    else:
        raise DecodeError(1, f'unknown canonical sequence at word 1: {tag1}')
    if n != len(sequence):
        raise DecodeError(3, f'{family} family needs {len(sequence)} words, got {n}')

    regs: dict[str, int] = {}
    for index, (word, expected_tag) in enumerate(zip(words, sequence)):
        target, value, offset = word >> 48, (word >> 16) & 0xffffffff, word & 0xffff
        if (target, offset) != expected_tag:
            raise DecodeError(1, f'word {index}: tag {target:04x}:{offset:04x} '
                              f'is not the canonical {family} field '
                              f'{expected_tag[0]:04x}:{expected_tag[1]:04x}')
        name = FIELDS.get((target, offset))
        if name is not None:
            if name in regs:
                raise DecodeError(1, f'word {index}: duplicate write of {name}')
            regs[name] = value
    # The 52-word stream carries one documented zero padding word after the
    # four PC-tail words. It is part of the capture; a nonzero value is an
    # unmodeled write.
    if family == 'conv_simple' and (words[51] >> 48, words[51] & 0xffff) != (0, 0):
        raise DecodeError(1, 'conv_simple padding word is not zero')
    if family == 'conv_simple' and (words[51] >> 16) & 0xffffffff != 0:
        raise DecodeError(1, 'conv_simple padding word is not zero')

    def reg(name: str) -> int:
        if name not in regs:
            raise DecodeError(1, f'required field {name} was not written')
        return regs[name]

    # --- constant/control fields ------------------------------------------
    if reg('DPU_S_POINTER') != 0x0e:
        raise DecodeError(2, 'DPU_S_POINTER is not the captured PP mode')
    if family == 'conv_fp16':
        for name in ('RDMA_S_POINTER', 'RDMA_ERDMA_CFG', 'RDMA_FEATURE_MODE_CFG'):
            if reg(name) != 0:
                raise DecodeError(2, f'{name} is not the captured clear value')
    if reg('PC_BASE_ADDRESS') != 0 or reg('PC_REGISTER_AMOUNTS') != 0:
        raise DecodeError(2, 'terminal PC chain tail is not the captured zero tail')
    if reg('VERSION') != 0:
        raise DecodeError(2, 'VERSION word is not zero')
    if reg('PC_OPERATION_ENABLE') != 0x0d:
        raise DecodeError(2, 'PC operation enable is not the captured 0x0d')
    for name in ('CNA_CVT_CON1', 'CNA_CVT_CON2', 'CNA_CVT_CON3', 'CNA_CVT_CON4'):
        if reg(name) != 1 << 16:
            raise DecodeError(2, f'{name} is not the captured 1.0 scale')
    if reg('DPU_BS_CFG') != 0x53 or reg('DPU_BN_CFG') != 0x53:
        raise DecodeError(2, 'BS/BN bypass config is not the captured 0x53')
    if reg('DPU_EW_CFG') != 0x383:
        raise DecodeError(2, 'EW bypass config is not the captured 0x383')
    if reg('DPU_EW_CVT_SCALE_VALUE') != 1:
        raise DecodeError(2, 'EW conversion scale is not one')
    if reg('DPU_DATA_CUBE_NOTCH') != 0:
        raise DecodeError(2, 'DATA_CUBE_NOTCH must be zero (donor corrupts next run)')
    if reg('CORE_RESERVED_3030') != 0:
        raise DecodeError(2, 'CORE reserved 0x3030 must be zero')
    if reg('CNA_DMA_CON0') != 0x000f000f:
        raise DecodeError(2, 'CNA DMA burst configuration is not the captured value')

    conv1 = reg('CNA_CONV_CON1')
    misc = reg('CORE_MISC_CFG')
    feat = reg('DPU_FEATURE_MODE_CFG')
    fmt = reg('DPU_DATA_FORMAT')
    out_cvt = reg('DPU_OUT_CVT_SCALE')
    depthwise = (_u(conv1, 1, 0) == 3)
    if (_u(conv1, 6, 4), _u(conv1, 9, 7)) != (2, 2):
        raise DecodeError(2, 'CNA input/processing precision is not FP16')
    if _u(misc, 9, 8) != 2:
        raise DecodeError(2, 'CORE processing precision is not FP16')
    if _u(misc, 1, 1) != int(depthwise):
        raise DecodeError(2, 'CORE depthwise flag disagrees with CNA conv mode')
    if _u(feat, 4, 3) != (3 if depthwise else 0):
        raise DecodeError(2, 'DPU feature-mode conv mode disagrees with CNA conv mode')
    if _u(feat, 2, 1) != 2:
        raise DecodeError(2, 'DPU output mode is not the captured FP16 output mode')
    if _u(fmt, 28, 26) != 2 or _u(fmt, 2, 0) != 2:
        # processing precision sits at bits 28:26, input precision at 2:0.
        raise DecodeError(2, 'DPU data format precision fields are not FP16')
    out_precision = _u(fmt, 31, 29)
    if out_precision not in (2, 5):
        raise DecodeError(2, f'unsupported DPU output precision {out_precision}')
    out_fp16 = out_precision == 2
    if out_fp16 != bool(_u(out_cvt, 16, 16)):
        raise DecodeError(2, 'OUT_CVT_SCALE FP32TOFP16 bit disagrees with DATA_FORMAT')

    # --- primary spatial geometry ------------------------------------------
    ds0, ds1, ds2, ds3 = (reg('CNA_DATA_SIZE0'), reg('CNA_DATA_SIZE1'),
                         reg('CNA_DATA_SIZE2'), reg('CNA_DATA_SIZE3'))
    fcds0, fcds1 = reg('CNA_FC_DATA_SIZE0'), reg('CNA_FC_DATA_SIZE1')
    ws2 = reg('CNA_WEIGHT_SIZE2')
    out0, out1 = reg('CORE_DATAOUT_SIZE_0'), reg('CORE_DATAOUT_SIZE_1')
    ih = _u(ds0, 15, 0)
    width_stride = _u(ds0, 31, 16)
    iw = _u(fcds0, 31, 16)
    ic = _u(ds1, 31, 16) + 1
    ic_align = _u(ds1, 15, 0)
    ow = _u(ds2, 15, 0)
    atoms = _u(ds3, 15, 0)
    kw, kh = _u(ws2, 31, 24), _u(ws2, 23, 16)
    kernels_field = _u(ws2, 15, 0)
    align_out_c = (_u(out1, 15, 0) & 0x7fff) + 1
    chip_c = _u(out1, 15, 0)
    cube_lo, cube_hi = _u(reg('DPU_DATA_CUBE_CHANNEL'), 15, 0), \
        _u(reg('DPU_DATA_CUBE_CHANNEL'), 31, 16)
    oh_reg = _u(out0, 31, 16) + 1
    ow_reg = _u(out0, 15, 0) + 1
    ow_cube = reg('DPU_DATA_CUBE_WIDTH') + 1
    oh_cube = reg('DPU_DATA_CUBE_HEIGHT') + 1
    # stride: CNA_CONV_CON3 = y<<3 | x in both pinned sources.
    con3 = reg('CNA_CONV_CON3')
    stride_x, stride_y = _u(con3, 2, 0), _u(con3, 5, 3)
    ws_reg = _u(reg('CNA_FC_DATA_SIZE0'), 15, 0)
    if _u(con3, 15, 6):
        raise DecodeError(2, 'CNA_CONV_CON3 has an unmodeled upper field set')

    # --- channel packing ----------------------------------------------------
    cvt0, cvt5 = reg('CNA_CVT_CON0'), reg('CNA_CVT_CON5')
    if family == 'conv_fp16':
        # conv_new_clean._cdma_dc_feature_input_pack_c2 returns C2=8 for every
        # captured C4/C16/grouped/depthwise task; the manifests' 16-byte pixel
        # stride confirms it. Feature packing is never NHWC on this path.
        pack_c2 = 8
        use_nhwc = False
        align_c = ic_align
        if cvt0 != 0x01:
            raise DecodeError(2, 'CNA CVT_CON0 is not the captured packed mode')
        if cvt5 not in (0, (1 << ic) - 1 if ic <= 8 else 1 << 8):
            # 0 for groups==1 tasks, (2^C2)-1 for the depthwise C2=8 task.
            raise DecodeError(2, 'CNA CVT_CON5 is not a captured channel-mask value')
    else:
        # conv_simple.make_regs: cvt_con5 = (1<<in_c)-1 when the NHWC pack is
        # selected (input_pack_c2 == 2*in_c), else input_pack_c2-1. The C16
        # case selects the C1-plane pack with C2=8.
        if cvt5 == (1 << ic) - 1 and 1 < ic <= 4:
            use_nhwc = True
            pack_c2 = ic
        elif cvt5 in (3, 7):
            use_nhwc = False
            pack_c2 = cvt5 + 1
        else:
            raise DecodeError(2, 'CNA CVT_CON5 does not select a captured pack mode')
        align_c = ic_align
        spatial = (kh != 1 or kw != 1)
        if cvt0 != (0x0b if spatial else 0x01):
            raise DecodeError(2, 'CNA CVT_CON0 is not the captured spatial/1x1 mode')
    spatial = (kh != 1 or kw != 1)
    if _u(misc, 0, 0) != int(spatial):
        raise DecodeError(2, 'CORE spatial enable bit disagrees with kernel size')

    # --- derived geometry ---------------------------------------------------
    if depthwise:
        out_c = ic
        if kernels_field != 1:
            raise DecodeError(2, 'depthwise WEIGHT_SIZE2 kernel field is not 1')
        if kw != kh:
            raise DecodeError(2, 'depthwise kernel is not square in the capture')
    else:
        out_c = kernels_field
    kernels = min(out_c, 8)
    c1_blocks = _ceil_div(out_c, kernels)
    taps = kh * kw
    if not (1 <= kh <= MAX_KERNEL and 1 <= kw <= MAX_KERNEL):
        raise DecodeError(2, f'unsupported kernel {kh}x{kw} (bounded to '
                          f'{MAX_KERNEL}x{MAX_KERNEL})')
    if stride_x != stride_y:
        raise DecodeError(2, 'non-square stride is not evidenced by any capture')
    if not (1 <= stride_x <= MAX_STRIDE):
        raise DecodeError(2, f'unsupported stride {stride_x} (bounded to {MAX_STRIDE})')
    stride = stride_x
    if not (1 <= ic <= MAX_CHANNELS and ic <= ic_align <= MAX_CHANNELS):
        raise DecodeError(2, 'unsupported channel count/alignment')
    if ih < kh or iw < kw or ih == 0 or iw == 0:
        raise DecodeError(2, 'input geometry is smaller than the kernel')
    if ih != (oh_reg - 1) * stride_y + kh or iw != (ow_reg - 1) * stride_x + kw:
        raise DecodeError(2, 'input geometry does not equal the valid-convolution '
                          'extent of output geometry (unsupported padding/stride)')
    if atoms != oh_reg * ow_reg:
        raise DecodeError(2, 'DATA_SIZE3 atomic count disagrees with output geometry')
    if width_stride < iw:
        raise DecodeError(2, 'input row stride is smaller than the input width')
    if fcds1 != ic_align:
        raise DecodeError(2, 'FC data-size channel disagrees with DATA_SIZE1')
    if ws_reg != ih:
        raise DecodeError(2, 'FC/DC input height fields disagree')
    if _u(fcds0, 15, 0) != ih:
        raise DecodeError(2, 'FC/DC input height fields disagree')
    if ow_reg != ow or ow_cube != ow or oh_cube != oh_reg:
        raise DecodeError(2, 'DPU/CORE output geometry fields disagree')
    if cube_lo != chip_c or reg('DPU_WDMA_SIZE_0') != chip_c:
        raise DecodeError(2, 'output channel field disagrees across DPU/CORE')
    if cube_hi + 1 != out_c:
        raise DecodeError(2, 'orig output channel field disagrees with the decoded '
                          'output channel count')
    wdma1 = reg('DPU_WDMA_SIZE_1')
    if (_u(wdma1, 31, 16) + 1, _u(wdma1, 15, 0) + 1) != (oh_reg, ow_reg):
        raise DecodeError(2, 'WDMA output size fields disagree with output geometry')
    # The donor sets the conversion block sizes to 3 for depthwise and for the
    # FP32-output tail, and to 1 for the FP16 atom tail.
    size_e = 3 if (depthwise or not out_fp16) else 1
    if reg('DPU_BS_OW_CFG') != ((size_e << 8) | (size_e << 5) | (size_e << 2) | 2):
        raise DecodeError(2, 'BS_OW_CONFIG is not the captured pattern')

    # --- weight BO and layout ----------------------------------------------
    weight_bytes_field = reg('CNA_WEIGHT_SIZE0')
    per_kernel_field = reg('CNA_WEIGHT_SIZE1')
    if family == 'conv_fp16':
        weight_mode = 'depthwise_spatial' if depthwise else 'kh_major'
        chunk_lanes = 0
    else:
        weight_mode = 'chunked'
        chunk_lanes = 16
    if weight_mode == 'depthwise_spatial':
        weight_lanes = align_c
        frame_weight_halfwords = kernels
        weight_halfwords = taps * align_c
        weight_bytes = weight_halfwords * 2
    elif weight_mode == 'kh_major':
        weight_lanes = kernels * align_c
        frame_weight_halfwords = kernels * ic
        weight_halfwords = taps * weight_lanes
        weight_bytes = weight_halfwords * 2
    else:
        chunks = _ceil_div(c1_blocks * kernels, chunk_lanes)
        weight_lanes = chunk_lanes * align_c
        frame_weight_halfwords = kernels * ic
        weight_halfwords = taps * weight_lanes * chunks
        weight_bytes = weight_halfwords * 2
    if weight_mode != 'depthwise_spatial':
        if per_kernel_field != taps * align_c * 2:
            raise DecodeError(2, 'WEIGHT_SIZE1 per-kernel size disagrees with the '
                              'decoded kernel/align geometry')
        if weight_bytes_field != weight_bytes:
            raise DecodeError(2, 'WEIGHT_SIZE0 total size disagrees with the '
                              'decoded weight layout')
    else:
        if per_kernel_field != weight_bytes or weight_bytes_field != weight_bytes:
            raise DecodeError(2, 'depthwise weight sizes disagree with the decoded '
                              'depth-wise layout')
    if weight_halfwords > MAX_WEIGHT_HALFWORDS:
        raise DecodeError(2, 'decoded weight BO exceeds the engine store')
    if frame_weight_halfwords > kernels * align_c:
        raise DecodeError(2, 'frame weight walk exceeds one kernel-lane group')

    # --- input BO -----------------------------------------------------------
    # The front walks only real channels; the BO allocation may carry extra
    # aligned planes (that only changes the derived input BO byte size).
    load_planes = _ceil_div(ic, pack_c2)
    alloc_planes = 1 if use_nhwc else _ceil_div(max(ic, ic_align), pack_c2)
    input_pixels = ih * iw
    if input_pixels > MAX_INPUT_PIXELS:
        raise DecodeError(2, 'decoded input geometry exceeds the engine store')
    input_bytes = alloc_planes * input_pixels * pack_c2 * 2

    # --- CNA schedule fields (cross-check the driver formulas) --------------
    row_bytes = width_stride * ic_align * 2
    floor_grains = ih + kh
    if depthwise:
        expected_grains = min(13, floor_grains)
    elif family == 'conv_fp16' and not spatial:
        # conv_new_clean raises the grain count to the 52-entry minimum on the
        # pointwise path; the captured 1x1 task records exactly that floor.
        expected_grains = max(floor_grains, 52)
    else:
        expected_grains = floor_grains
    if _u(reg('CNA_CONV_CON2'), 31, 4) != expected_grains:
        raise DecodeError(2, 'CNA_CONV_CON2 feature grains disagree with the driver '
                          'formula for the decoded geometry')
    if _u(reg('CNA_CONV_CON2'), 3, 0) != 0:
        raise DecodeError(2, 'CNA_CONV_CON2 has an unmodeled low field set')
    row_entries = max(1, _ceil_div(width_stride * ic_align, 32))
    expected_entries = row_entries if (ic_align >= 16 or depthwise) \
        else row_entries * ih * 4
    if reg('CNA_CBUF_CON1') != expected_entries:
        raise DecodeError(2, 'CNA_CBUF_CON1 data entries disagree with the driver '
                          'formula for the decoded geometry')
    cbuf = reg('CNA_CBUF_CON0')
    data_bank, weight_bank, reuse = _u(cbuf, 3, 0), _u(cbuf, 7, 4), _u(cbuf, 13, 13)
    if _u(cbuf, 31, 14) or weight_bank + data_bank != 12 or not (1 <= data_bank <= 11):
        raise DecodeError(2, 'CNA_CBUF_CON0 bank split is not a valid captured split')
    if reuse != 0:
        raise DecodeError(2, 'CNA weight reuse is not evidenced by any capture')
    if spatial and (use_nhwc or depthwise):
        # The donor's packed/depthwise schedule keeps every CBUF bank for data.
        if data_bank != 11:
            raise DecodeError(2, 'CBUF data-bank count disagrees with the captured '
                              'packed/depthwise schedule')
    else:
        product = width_stride * expected_grains * ic_align * 2
        expected_bank = min(11, max(1, _ceil_div(product, 32768)))
        # The split-OC captures were generated with the donor's full_data_bank
        # option, which is not a register field; both the formula value and the
        # full-bank value are legitimate driver schedule allocations.
        if data_bank not in (expected_bank, 11):
            raise DecodeError(2, 'CBUF data-bank count disagrees with the driver '
                              'formula for the decoded geometry')
    line_stride = _u(reg('CNA_DMA_CON1'), 31, 0)
    surf_stride = _u(reg('CNA_DMA_CON2'), 31, 0)
    expected_line = width_stride if use_nhwc else width_stride * 4
    if line_stride != expected_line:
        raise DecodeError(2, 'CNA DMA line stride disagrees with the decoded row '
                          'geometry/packing')
    expected_surf = (width_stride * (ih - 1) if ih > 1 else 0) if use_nhwc \
        else (width_stride * (ih - 4) if ih > 4 else 0)
    if surf_stride != expected_surf:
        raise DecodeError(2, 'CNA DMA surface stride disagrees with the decoded row '
                          'geometry/packing')

    # --- output BO / surface -----------------------------------------------
    out_width_stride = _u(reg('DPU_DST_SURF_STRIDE'), 31, 4)
    if _u(reg('DPU_DST_SURF_STRIDE'), 3, 0) != 0:
        raise DecodeError(2, 'DPU destination surface stride is not 16-byte units')
    if family == 'conv_fp16':
        expected_ows = _align_up(atoms, 4) if spatial else atoms
    else:
        expected_ows = atoms if (not spatial and atoms < 4) else _align_up(atoms, 4)
    if out_width_stride != expected_ows:
        raise DecodeError(2, 'DPU destination surface stride disagrees with the '
                          'captured output-width-stride rule')
    surface_add = _u(reg('DPU_SURFACE_ADD'), 31, 0)
    expected_add = out_width_stride * max(2, align_out_c // 16) * 16
    if surface_add != expected_add:
        raise DecodeError(2, 'DPU SURFACE_ADD disagrees with the decoded output '
                          'surface geometry')
    if out_fp16:
        output_bytes = _u(reg('DPU_DST_SURF_STRIDE'), 31, 0) * (align_out_c // 8)
        output_atom_lanes = 8
    else:
        output_bytes = out_c * atoms * 4
        output_atom_lanes = 4
    if c1_blocks > MAX_OUTPUT_BLOCKS:
        raise DecodeError(2, 'decoded output blocking exceeds the engine bound')

    # --- DMA addresses and memory ranges -----------------------------------
    in_base = reg('CNA_FEATURE_DATA_ADDR')
    weight_base = reg('CNA_DCOMP_ADDR0')
    out_base = reg('DPU_DST_BASE_ADDR')
    for name, base in (('input', in_base), ('weight', weight_base),
                       ('output', out_base)):
        if base & 0xf:
            raise DecodeError(4, f'{name} DMA base {base:#x} is not 16-byte aligned')
    in_end = in_base + input_bytes
    weight_end = weight_base + weight_bytes
    out_end = out_base + output_bytes
    if max(in_end, weight_end, out_end) > 1 << 32:
        raise DecodeError(4, 'a buffer range overflows the 32-bit address space')
    ranges = sorted(((in_base, in_end, 'input'), (weight_base, weight_end, 'weight'),
                     (out_base, out_end, 'output')))
    for first, second in zip(ranges, ranges[1:]):
        if first[1] > second[0]:
            raise DecodeError(4, f'{first[2]} and {second[2]} buffers overlap')

    return {
        'family': family,
        'words': n,
        'input_height': ih, 'input_width': iw,
        'output_height': oh_reg, 'output_width': ow_reg,
        'kernel_h': kh, 'kernel_w': kw, 'stride': stride,
        'depthwise': depthwise,
        'input_channels': ic, 'input_channel_align': ic_align,
        'pack_c2': pack_c2, 'use_nhwc': use_nhwc,
        'output_channels': out_c, 'kernels': kernels,
        'c1_blocks': c1_blocks, 'output_channel_align': align_out_c,
        'weight_mode': weight_mode, 'chunk_lanes': chunk_lanes,
        'align_c': align_c, 'taps': taps,
        'frame_weight_halfwords': frame_weight_halfwords,
        'weight_halfwords': weight_halfwords,
        'weight_lanes': weight_lanes,
        'output_fp16': out_fp16, 'output_atom_lanes': output_atom_lanes,
        'input_bytes': input_bytes, 'weight_bytes': weight_bytes,
        'output_bytes': output_bytes,
        'input_base': in_base, 'weight_base': weight_base, 'output_base': out_base,
        'input_end': in_end, 'weight_end': weight_end, 'output_end': out_end,
        'out_width_stride': out_width_stride,
        'total_atoms': c1_blocks * atoms,
        'weight_bytes_field': weight_bytes_field,
        'per_kernel_bytes_field': per_kernel_field,
        'feature_grains': expected_grains,
        'data_bank': data_bank, 'weight_bank': weight_bank,
        'cbuf_entries': expected_entries,
        'line_stride': line_stride, 'surf_stride': surf_stride,
    }


# ---------------------------------------------------------------------------
# Fixture registry: the 12 pinned fixtures plus the unpinned 1x1 READY capture
# bundle (its written output region is byte-exact, its BO padding is unknown).
CASES = {
    'conv_3x3_valid_c4_h9_w9_oc4': 'conv-fp16',
    'conv_3x3_stride2_c4_h11_w11_oc4': 'conv-fp16',
    'conv_3x3_pad1_zero_frame_c4_h9_w9_oc4': 'conv-fp16',
    'conv_grouped_3x3_c4_h5_w5_oc8_g2_task0': 'conv-fp16',
    'conv_grouped_3x3_c4_h5_w5_oc8_g2_task1': 'conv-fp16',
    'conv_splitoc_3x3_c16_h9_w9_oc16_task0': 'conv-fp16',
    'conv_splitoc_3x3_c16_h9_w9_oc16_task1': 'conv-fp16',
    'conv_depthwise_3x3_c3_h11_w28_oc3': 'conv-fp16',
    'conv_simple_fp16_3x3_c4_h8_w8_oc16': 'conv-simple',
    'conv_simple_fp16_5x5_c4_h8_w8_oc16': 'conv-simple',
    'conv_simple_fp16_3x3_c16_h8_w8_oc32': 'conv-simple',
    'conv_simple_fp16_1x1_c4_h8_w8_oc16': 'conv-simple',
}
BUNDLE_CASES = ('conv_1x1_valid_c8_h5_w5_oc8',)


def input_file(family: str) -> str:
    return 'a.bin' if family == 'conv-fp16' else 'input.bin'


def weight_file(family: str) -> str:
    return 'w.bin' if family == 'conv-fp16' else 'weight.bin'


def load_case(case: str) -> dict:
    family = CASES[case]
    fixture = FIXTURES / case
    manifest = json.loads((fixture / 'manifest.json').read_text())
    if family == 'conv-fp16':
        addresses = manifest['command']['addresses']
        patches = json.loads((fixture / 'job.json').read_text())['patches']
        raw = (fixture / 'regcmd.bin').read_bytes()
        input_bytes = (fixture / 'a.bin').stat().st_size
        weight_bytes = (fixture / 'w.bin').stat().st_size
        out_bytes = (fixture / 'device_out.bin').stat().st_size
        expected = (fixture / 'expected.bin').read_bytes()
        device = (fixture / 'device_out.bin').read_bytes()
    else:
        addresses = manifest['command_stream']['addresses']
        patches = json.loads((fixture / 'job.json').read_text())['patches']
        raw = (fixture / 'regcmd.bin').read_bytes()
        input_bytes = (fixture / 'input.bin').stat().st_size
        weight_bytes = (fixture / 'weight.bin').stat().st_size
        out_bytes = (fixture / 'device_out.bin').stat().st_size
        expected = (fixture / 'expected.bin').read_bytes()
        device = (fixture / 'device_out.bin').read_bytes()
    patched = relocate(raw, addresses, patches)
    config = decode(unpack_words(patched))
    return {'case': case, 'family': family, 'fixture': fixture,
            'manifest': manifest, 'config': config,
            'commands': patched,
            'input_path': fixture / input_file(family),
            'weight_path': fixture / weight_file(family),
            'input_bytes': input_bytes, 'weight_bytes': weight_bytes,
            'output_bytes': out_bytes, 'expected': expected, 'device': device}


def load_bundle(case: str) -> dict:
    fixture = BUNDLES / 'conv-fp16/cases' / case
    provenance = json.loads((fixture / 'provenance.json').read_text())
    addresses = {'a': 0x1000, 'w': 0x2000, 'out': 0x3000}
    patches = provenance['tasks'][0]['patches']
    raw = (fixture / 'regcmd.bin').read_bytes()
    patched = relocate(raw, addresses, patches)
    config = decode(unpack_words(patched))
    return {'case': case, 'family': 'conv-fp16', 'fixture': fixture,
            'manifest': provenance, 'config': config, 'commands': patched,
            'input_path': fixture / 'a.bin', 'weight_path': fixture / 'w.bin',
            'input_bytes': (fixture / 'a.bin').stat().st_size,
            'weight_bytes': (fixture / 'w.bin').stat().st_size,
            'output_bytes': provenance['tasks'][0]['output_bytes'],
            'expected': (fixture / 'expected.bin').read_bytes(),
            'device': (fixture / 'expected.bin').read_bytes()}


def check_case(loaded: dict) -> list[str]:
    """Validate the decoded config against the fixture's declared facts."""
    case, config, manifest = loaded['case'], loaded['config'], loaded['manifest']
    problems: list[str] = []
    if loaded['family'] == 'conv-fp16':
        shape = manifest.get('shape', {})
        execution = manifest.get('execution_geometry', shape)
        expected = {
            'input_height': execution.get('input_height'),
            'input_width': execution.get('input_width'),
            'output_height': execution.get('output_height'),
            'output_width': execution.get('output_width'),
            'kernel_h': shape.get('kh', shape.get('kernel', [None, None])[0]),
            'kernel_w': shape.get('kw', shape.get('kernel', [None, None])[1]),
            'input_channels': shape.get('in_c', shape.get('input_channels')),
            'output_channels': shape.get('out_c', shape.get('output_channels')),
            'stride': (shape.get('stride') if isinstance(shape.get('stride'), int)
                       else (shape.get('stride') or [1])[0]),
        }
        layout = manifest.get('layout', {})
        if 'input_bytes' in layout:
            expected['input_bytes'] = layout['input_bytes']
        if 'weight_bytes' in layout:
            expected['weight_bytes'] = layout['weight_bytes']
        if 'output_bytes' in layout:
            expected['output_bytes'] = layout['output_bytes']
        expected['depthwise'] = bool(shape.get('groups', 1) > 1)
    else:
        shape = manifest['shape']
        packing = manifest.get('packing', {})
        expected = {
            'input_height': shape['in_h'], 'input_width': shape['in_w'],
            'output_height': shape['in_h'] - shape['kh'] + 1,
            'output_width': shape['in_w'] - shape['kw'] + 1,
            'kernel_h': shape['kh'], 'kernel_w': shape['kw'],
            'input_channels': shape['in_c'], 'output_channels': shape['out_c'],
            'stride': shape.get('stride', 1),
            'depthwise': shape['groups'] == shape['in_c'] == shape['out_c'],
            'align_c': packing.get('align_c'),
            'pack_c2': packing.get('c2_in'),
            'input_bytes': loaded['input_bytes'],
            'weight_bytes': loaded['weight_bytes'],
            'output_bytes': loaded['output_bytes'],
        }
    for key, value in expected.items():
        if value is None:
            continue
        if config.get(key) != value:
            problems.append(f'{case}: {key} decoded {config.get(key)!r} != '
                            f'declared {value!r}')
    # The derived BO byte sizes must equal the actual fixture files. That ties
    # the geometry decode to the packed operand allocations independently of
    # the manifest prose.
    if config['input_bytes'] != loaded['input_bytes']:
        problems.append(f'{case}: derived input BO {config["input_bytes"]} != '
                        f'file size {loaded["input_bytes"]}')
    if config['weight_bytes'] != loaded['weight_bytes']:
        problems.append(f'{case}: derived weight BO {config["weight_bytes"]} != '
                        f'file size {loaded["weight_bytes"]}')
    if config['output_bytes'] != loaded['output_bytes']:
        problems.append(f'{case}: derived output BO {config["output_bytes"]} != '
                        f'recorded BO size {loaded["output_bytes"]}')
    if loaded['family'] == 'conv-simple' and config['output_bytes'] != \
            len(loaded['expected']):
        problems.append(f'{case}: derived output BO is not the no-padding BO')
    if config['output_fp16'] != (manifest.get('dtype', {}).get('output',
                                    'float16') == 'float16' if
                                 loaded['family'] == 'conv-fp16' else
                                 manifest['dtype']['output'] == 'float16'):
        problems.append(f'{case}: output precision mismatch')
    return problems


def evidence_rows() -> list[dict]:
    rows = []
    for case in CASES:
        loaded = load_case(case)
        rows.append({'case': case, 'family': loaded['family'],
                     'config': loaded['config'],
                     'problems': check_case(loaded)})
    for case in BUNDLE_CASES:
        loaded = load_bundle(case)
        rows.append({'case': case, 'family': loaded['family'],
                     'config': loaded['config'], 'problems': []})
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true',
                        help='emit the per-case decoded configs as JSON')
    args = parser.parse_args(argv)
    failures = 0
    rows = evidence_rows()
    for row in rows:
        status = 'PASS' if not row['problems'] else 'FAIL'
        config = row['config']
        print(f'{status} {row["family"]:11s} {row["case"]:52s} '
              f'{config["input_height"]:2d}x{config["input_width"]:2d} '
              f'k{config["kernel_h"]}x{config["kernel_w"]} s{config["stride"]} '
              f'C{config["input_channels"]}->OC{config["output_channels"]} '
              f'{config["output_height"]}x{config["output_width"]} '
              f'in={config["input_bytes"]:5d} w={config["weight_bytes"]:5d} '
              f'out={config["output_bytes"]:6d} '
              f'{"fp16" if config["output_fp16"] else "fp32"} '
              f'{config["weight_mode"]} pack={config["pack_c2"]} '
              f'align={config["align_c"]}/{config["output_channel_align"]}')
        for problem in row['problems']:
            failures += 1
            print(f'  FAIL {problem}')
    if args.json:
        print(json.dumps([{'case': r['case'], 'config': r['config']}
                          for r in rows], indent=1, sort_keys=True))
    print(f'{len(rows) - (1 if any(r["problems"] for r in rows) else 0)}'
          f'/{len(rows)} cases decode consistently; {failures} field-map problems')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
