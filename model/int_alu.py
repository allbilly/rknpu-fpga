"""Evidenced integer elementwise arithmetic for the ew-int family.

This module is the software counterpart of ``rtl/rk_int_alu.sv``. Both are
derived from the captured ew-int bundles and the source examples
(``kernel_6_18``/``expt`` ``elementwise_int.py``); see ``docs/EW_INT.md`` for
the evidence map, including the fact that the captured oracle only proves
in-range arithmetic and the INT32-MUL signed-INT16 operand limitation.

No FP16 behaviour is changed or re-used here: this is a separate module.
"""
from __future__ import annotations

# ALU op codes shared with rtl/rk_int_alu.sv (cfg_op).
OP_CODES = {'ADD': 0, 'MINUS': 1, 'MUL': 2, 'MAX': 3, 'MIN': 4}
OP_NAMES = {code: name for name, code in OP_CODES.items()}
# Integer dtypes; FP16 (the captured DATA_FORMAT code 2) is explicitly absent.
DTYPE_LIMITS = {'INT8': (-128, 127),
                'INT16': (-32768, 32767),
                'INT32': (-2147483648, 2147483647)}
DTYPE_ITEMS = {'INT8': 1, 'INT16': 2, 'INT32': 4}
DTYPE_CODES = {'INT8': 0, 'INT16': 1, 'INT32': 2}


def signed16(value: int) -> int:
    """Sign-extend the low 16 bits. Captured INT32-MUL operand rule."""
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def saturate(value: int, dtype: str) -> int:
    """Clamp to the destination dtype. The captured vectors never overflow, so
    this is source-formula behaviour (kernel_6_18 ``saturate``), not a
    differentially captured overflow lane; see docs/EW_INT.md caveat 1."""
    low, high = DTYPE_LIMITS[dtype]
    return max(low, min(high, int(value)))


def alu(op: str, dtype: str, a: int, b: int) -> int:
    """One captured integer lane.

    ``dtype`` is the *destination/result* dtype. The engine sign-extends the
    operands to 32 bits before calling this function; for INT32 MUL the
    captured hardware limitation truncates the second operand to signed INT16.
    """
    if op not in OP_CODES:
        raise ValueError(f'unsupported integer op: {op!r}')
    if dtype not in DTYPE_LIMITS:
        raise ValueError(f'unsupported integer dtype: {dtype!r}')
    a = int(a)
    b = int(b)
    if op == 'MUL' and dtype == 'INT32':
        b = signed16(b)
    if op == 'MAX':
        value = max(a, b)
    elif op == 'MIN':
        value = min(a, b)
    elif op == 'ADD':
        value = a + b
    elif op == 'MINUS':
        value = a - b
    else:  # MUL
        value = a * b
    return saturate(value, dtype)


def encode_item(value: int, dtype: str) -> bytes:
    """Little-endian captured encoding (native dtype ``tobytes``/C1WC2)."""
    return int(value).to_bytes(DTYPE_ITEMS[dtype], 'little', signed=True)


def decode_item(data: bytes, dtype: str) -> int:
    return int.from_bytes(data, 'little', signed=True)


def item_code(size: int) -> int:
    """RTL cfg item code: 0 -> 1 byte, 1 -> 2 bytes, 2 -> 4 bytes."""
    if size not in (1, 2, 4):
        raise ValueError(f'unsupported item size: {size}')
    return {1: 0, 2: 1, 4: 2}[size]
