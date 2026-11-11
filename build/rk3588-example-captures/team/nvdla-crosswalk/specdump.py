#!/usr/bin/env python3
"""Parse NVDLA generated register headers into (register, offset, field, shift, width).

Read-only helper for the field crosswalk.  It parses the generated `_MK_*`
macros only; it does not interpret RTL behaviour.
"""
import re
import sys

ADDR_RE = re.compile(r'^#define\s+(NVDLA_[A-Z0-9_]+)\s+_MK_ADDR_CONST\((0x[0-9a-fA-F]+)\)')
SHIFT_RE = re.compile(r'^#define\s+(NVDLA_[A-Z0-9_]+)_SHIFT\s+_MK_SHIFT_CONST\((\d+)\)')
FIELD_RE = re.compile(r'^#define\s+(NVDLA_[A-Z0-9_]+)_FIELD\s+_MK_FIELD_CONST\((0x[0-9a-fA-F]+),\s*(NVDLA_[A-Z0-9_]+)_SHIFT\)')


def parse(path):
    regs = {}          # full register macro name -> offset
    order = []
    shifts = {}        # full field macro name -> shift
    widths = {}        # full field macro name -> width
    for line in open(path):
        m = ADDR_RE.match(line)
        if m:
            if m.group(1) not in regs:
                regs[m.group(1)] = int(m.group(2), 16)
                order.append(m.group(1))
            continue
        m = SHIFT_RE.match(line)
        if m:
            shifts[m.group(1)] = int(m.group(2))
            continue
        m = FIELD_RE.match(line)
        if m:
            widths[m.group(1)] = int(m.group(2), 16)
    rows = []
    regs_by_len = sorted(regs, key=len, reverse=True)
    for field, sh in shifts.items():
        for reg in regs_by_len:
            if field.startswith(reg + '_'):
                fname = field[len(reg) + 1:]
                rows.append((reg, regs[reg], fname, sh, widths.get(field)))
                break
    rows.sort(key=lambda r: (r[1], r[3]))
    return rows


if __name__ == '__main__':
    for path in sys.argv[1:]:
        print('#' * 10, path)
        for reg, off, field, sh, w in parse(path):
            print(f'{reg:44s} 0x{off:04x} {field:40s} shift={sh:2d} width={w}')
