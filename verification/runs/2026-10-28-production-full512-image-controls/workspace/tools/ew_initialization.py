"""Synthetic profile fixtures, NOT captured backend commands or silicon goldens.

Keep literal reviewed wire values independent of the decoder's whitelist so a
whitelist edit alone cannot silently change both the implementation and fixtures.
"""
import struct

from model.profile import encode, make_commands


def initialization_words(count):
    width = (count + 7) // 8 - 1
    return [encode(0x1001, address, value) for address, value in (
        (0x4040, 0x53), (0x4060, 0x53), (0x4044, 0), (0x4048, 0),
        (0x4050, 2), (0x4058, 7), (0x405c, width), (0x4068, 0),
        (0x406c, 0), (0x4078, 1), (0x4080, 0), (0x4088, 0), (0x40c0, 0x40))]


def initialized_commands(op, count, a, b, dst, init=None):
    # Synthetic terminal framing remains zero/zero. Never use this helper to
    # normalize the current backend's nonzero PC guard address or linked tasks.
    raw = make_commands(op, count, a, b, dst)
    words = initialization_words(count) if init is None else init
    return raw[:-8] + struct.pack('<' + 'Q' * len(words), *words) + raw[-8:]
