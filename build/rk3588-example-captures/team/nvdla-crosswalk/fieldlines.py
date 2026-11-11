#!/usr/bin/env python3
"""Emit `header:line macro` for selected NVDLA registers/fields, for citation."""
import re
import sys

ADDR = re.compile(r'^#define\s+(NVDLA_[A-Z0-9_]+)\s+_MK_ADDR_CONST')
FIELD = re.compile(r'^#define\s+(NVDLA_[A-Z0-9_]+)_(SHIFT|FIELD)\s+_MK_(SHIFT|FIELD)_CONST')


def main(prefixes, paths):
    for path in paths:
        for ln, line in enumerate(open(path), 1):
            m = ADDR.match(line)
            if m and any(m.group(1) == p for p in prefixes):
                print(f'{path}:{ln}: {line.rstrip()}')
                continue
            m = FIELD.match(line)
            if m and any(m.group(1).startswith(p + '_') or m.group(1) == p for p in prefixes):
                print(f'{path}:{ln}: {line.rstrip()}')


if __name__ == '__main__':
    main(sys.argv[1].split(','), sys.argv[2:])
