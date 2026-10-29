"""Read-only necessary capacity bound for a complete plain-LUT packed census.

Retain the original logical_lut and matching guards. Six CONNECTED inputs
consume a full physical LUT position even if their net IDs repeat. Other
single-output ordinary LUTs enter an optimistic input-sharing relaxation.
No placement assignment, circuit transform or physical acceptance is produced.
"""
from collections import Counter
from pathlib import Path
import re

from route_prefix_board import logical_lut
from lut_sharing_bound import sharing_bound

RULE = Path('/home/fedora/soDLA/build/ypcb/lut-pair-engine-1791377260734986151/himbaechel/uarch/xilinx/xilinx_place.cc')
TAGS = Path('/home/fedora/soDLA/build/ypcb/heap-beta-engine-1791307049291727187/himbaechel/uarch/xilinx/xilinx.cc')
POLICY_DIGESTS = {
    str(RULE): '59eee3c32886ddc4c3697485556cca2ad16d9c5ac2d933b6c93bf461fe2e4172',
    str(TAGS): '0c755e0b6107636ba14da965b8c0936a5c9e3d9311fabdde6de70f4175049ae0',
}


def physical_positions(log, actual_luts):
    matches = re.findall(r'(?m)^Info:\s+SLICE_LUTX:\s+(\d+)/\s*(\d+)\s+\d+%', log)
    assert len(matches) == 1, 'Missing/duplicate actual LUT capacity report'
    used, bel_slots = map(int, matches[0])
    assert used == actual_luts and bel_slots == 597200, 'Changed actual LUT count/device capacity'
    return bel_slots // 2


class LUTInputs:
    def __init__(self):
        self.groups, self.widths, self.whole = Counter(), Counter(), 0

    def observe(self, cell):
        logical_lut(cell)  # Entire source-defined INIT/pin/annotation contract.
        assert not any(k in cell['attributes'] for k in ('X_LUT_AS_DRAM', 'X_LUT_AS_SRL'))
        pins = [cell['connections'].get('A' + str(i), []) for i in range(1, 7)]
        assert all(len(pin) <= 1 and all(type(bit) is int and bit >= 2 for bit in pin) for pin in pins)
        outputs = sum(bool(cell['connections'].get(port)) for port in ('O5', 'O6'))
        assert outputs <= 1, 'Dual-output LUT is outside this bound profile'
        count = sum(bool(pin) for pin in pins)
        assert 1 <= count <= 6, 'Unsupported disconnected ordinary LUT'
        self.widths[count] += 1
        if count == 6:
            self.whole += 1
        else:
            self.groups[frozenset(bit for pin in pins for bit in pin)] += 1

    def bound(self, actual_luts, positions):
        assert self.whole + sum(self.groups.values()) == sum(self.widths.values()) == actual_luts
        measured = sharing_bound(self.groups, self.whole, positions)
        assert measured['lut_cells'] == actual_luts
        return dict(measured, input_pin_count_census=dict(self.widths), cached_input_groups=len(self.groups),
                    placement_assignment_generated=False, hardware_execution_input_changed=False)
