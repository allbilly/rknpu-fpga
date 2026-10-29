#!/usr/bin/env python3
"""Build a separate checkpoint checker with verified local carry DI tags.

The earlier checker and its failed qualification stay source-bound and
unchanged. Reuse its build procedure, not its acceptance, with an explicitly
generated supplemental template and separate controls. No circuit, cluster,
placement guard, default executable or SHA256SUMS file is changed.
"""
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_imported_placement_checker as builder

BASE_TEMPLATE = builder.TEMPLATE
CONTROL = builder.ROOT / 'tests/cmac/test_imported_carry_checker_build.py'
ROLE_HOOK = '                    std::set<NetInfo *> shared;\n'
ROLE_BLOCK = '''                    // Imported JSON omits cluster membership. Restore the
                    // carry-only tag ONLY for this physical position's sole
                    // DI sink; other users still require the ordinary OUTMUX.
                    NetInfo *di_feed = lower->getPort(id_O5);
                    CellInfo *local_carry = lt.cells[((z / 4) << 6) | BEL_CARRY4];
                    if (local_carry && di_feed->users.entries() == 1) {
                        const PortRef &sink = *di_feed->users.begin();
                        if (sink.cell == local_carry) {
                            IdString di = ctx->idf("DI%d", z % 4);
                            if (sink.port != di || local_carry->getPort(di) != di_feed)
                                log_error("RKNPU imported placement scan: wrong local carry DI role.\\n");
                            l5.only_drives_carry = true;
                            ++checked_carry_feeds;
                        }
                    }
'''
ROLE_LOG_HOOK = '            for (auto &entry : ctx->cells) {\n'
ROLE_LOG = '''            log_info("RKNPU imported placement scan: verified %d local carry DI roles.\\n",
                     checked_carry_feeds);
'''


def extended_template(original):
    assert original == BASE_TEMPLATE.read_text(), 'Changed frozen first-checker template'
    old_count = '        int checked_cells = 0, checked_pairs = 0;\n'
    new_count = '        int checked_cells = 0, checked_pairs = 0, checked_carry_feeds = 0;\n'
    assert original.count(old_count) == original.count(ROLE_HOOK) == original.count(ROLE_LOG_HOOK) == 1
    result = original.replace(old_count, new_count).replace(ROLE_HOOK, ROLE_BLOCK + ROLE_HOOK).replace(ROLE_LOG_HOOK, ROLE_LOG + ROLE_LOG_HOOK)
    assert result.replace(new_count, old_count).replace(ROLE_BLOCK, '').replace(ROLE_LOG, '') == original
    for forbidden in ('connectPort', 'disconnectPort', 'bindBel', 'unbindBel', '->cluster =', 'NPNR_ASSERT'):
        assert forbidden not in ROLE_BLOCK
    builder.checked_source(builder.TAG_SOURCE.read_text(), result)
    return result


def local_carry_roles(module):
    """Read-only comparison model of the exact sole-user/site/DI predicate."""
    cells = module['cells']; by_bel = {}; users = {}
    for name, cell in cells.items():
        bel = cell['attributes']['NEXTPNR_BEL']
        assert bel not in by_bel, 'Duplicate physical BEL'
        by_bel[bel] = name
        for port, bits in cell['connections'].items():
            if cell['port_directions'][port] not in ('input', 'inout'):
                continue
            for bit in bits:
                if isinstance(bit, int): users.setdefault(bit, []).append((name, port))
    roles = []
    for name, cell in cells.items():
        match = re.fullmatch(r'(.+\.)([A-D])5LUT', cell['attributes']['NEXTPNR_BEL'])
        if cell['type'] != 'SLICE_LUTX' or not match:
            continue
        bits = cell['connections'].get('O5', [])
        assert len(bits) == 1 and isinstance(bits[0], int)
        assert cell['port_directions']['O5'] == 'output' and cell['attributes']['X_ORIG_PORT_O5'] == 'O'
        carry_name = by_bel.get(match[1] + 'CARRY4')
        sinks = users.get(bits[0], [])
        if carry_name is None or len(sinks) != 1 or sinks[0][0] != carry_name:
            continue
        carry = cells[carry_name]; di = 'DI' + str(ord(match[2]) - ord('A'))
        assert carry['type'] == 'CARRY4' and carry['attributes']['X_ORIG_TYPE'] == 'CARRY4'
        assert sinks[0][1] == di and carry['connections'][di] == bits, 'wrong local carry DI role'
        assert carry['port_directions'][di] == 'input'
        roles.append(dict(lut=name, carry=carry_name, di=di, net=bits[0], bel=cell['attributes']['NEXTPNR_BEL']))
    return sorted(roles, key=lambda role: role['lut'])


def main():
    out = builder.ROOT / f'build/openxc7/imported-carry-checker-template-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    template = out / BASE_TEMPLATE.name
    template.write_text(extended_template(BASE_TEMPLATE.read_text()))
    # These are process-local build inputs, not edits to the frozen builder.
    builder.TEMPLATE = template
    builder.CONTROL = CONTROL
    builder.__doc__ = __doc__
    builder.main()


if __name__ == '__main__':
    main()
