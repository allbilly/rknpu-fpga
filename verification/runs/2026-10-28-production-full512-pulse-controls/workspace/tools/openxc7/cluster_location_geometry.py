#!/usr/bin/env python3
"""Necessary, optimistic native cluster geometry, not placement acceptance.

Mirror BaseArch::getClusterPlacement and Himbaechel getBelByLocation: root
absolute Z, child absolute/relative Z, real tile X/Y and exact primitive types.
Also reject a repeated BEL within one cluster. Ignore occupancy, fixed BELs,
control sets, pin connectivity and timing explicitly; a witness is not a fit.
No external writes, tools, live process access, input repair or FPGA access.
"""
from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    tile_types: tuple
    bels: tuple

    def validate(self):
        assert type(self.width) is int and type(self.height) is int
        assert 0 < self.width <= 4096 and 0 < self.height <= 4096
        assert len(self.tile_types) == self.width * self.height <= 16777216
        assert self.bels and all(type(t) is int and 0 <= t < len(self.bels) for t in self.tile_types)
        for table in self.bels:
            assert isinstance(table, dict)
            assert all(type(z) is int and -(2**15) <= z < 2**15 and isinstance(kind, str) and kind
                       for z, kind in table.items())
        return self

    def bel(self, x, y, z):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return self.bels[self.tile_types[y * self.width + x]].get(z)


def database_grid(data, known):
    # Reuse the frozen version6/device/ConstID/layout validator and BEL tables,
    # not the old auditor's same-tile-only cluster acceptance procedure.
    from audit_native_mux_cluster_geometry import database_bels
    types = list(database_bels(data, known))
    assert types and len({name for name, _ in types}) == len(types)

    def integer(offset):
        assert 0 <= offset <= len(data) - 4
        return struct.unpack_from('<i', data, offset)[0]

    def pointer(offset):
        target = offset + integer(offset)
        assert 0 <= target < len(data)
        return target

    root = pointer(0)
    assert integer(root) == 0x00ca7ca7 and integer(root + 4) == 6
    width, height = integer(root + 8), integer(root + 12)
    # ChipInfoPOD.tile_insts offset36; TileInstPOD stride16/type offset4.
    start = pointer(root + 36)
    count = struct.unpack_from('<I', data, root + 40)[0]
    assert count == width * height and start + count * 16 <= len(data)
    indices = tuple(integer(start + 16 * i + 4) for i in range(count))
    return Grid(width, height, indices,
                tuple({z: item['type'] for z, item in table.items()} for _, table in types)).validate()


def validate_members(members):
    assert isinstance(members, (list, tuple)) and 0 < len(members) <= 600000
    names = set()
    for row in members:
        assert set(row) == {'name', 'type', 'x', 'y', 'z', 'abs_z'}
        assert isinstance(row['name'], str) and row['name'] and row['name'] not in names
        assert isinstance(row['type'], str) and row['type']
        names.add(row['name'])
        assert type(row['abs_z']) is bool
        assert all(type(row[k]) is int and -(2**31) <= row[k] < 2**31 for k in ('x', 'y', 'z'))
    return members


def geometry_key(members):
    validate_members(members)
    root = members[0]
    # Relative root XYZ is ignored by the native placement routine; absolute
    # root Z is not. Child order/names are irrelevant to location/type geometry.
    return (root['type'], root['abs_z'], root['z'] if root['abs_z'] else 0,
            tuple(sorted((c['type'], c['x'], c['y'], c['z'], c['abs_z']) for c in members[1:])))


def candidate_witness(members, grid, x, y, z):
    root = members[0]
    # The caller enumerates root BELs of root type, as the native bucket does.
    if grid.bel(x, y, z) != root['type']:
        return None
    root_z = root['z'] if root['abs_z'] else z
    locations = [(x, y, root_z, root['type'])]
    locations.extend((x + c['x'], y + c['y'], c['z'] if c['abs_z'] else root_z + c['z'], c['type'])
                     for c in members[1:])
    if len({loc[:3] for loc in locations}) != len(locations):
        return None
    if any(grid.bel(a, b, c) != kind for a, b, c, kind in locations):
        return None
    return locations


def find_witness(members, grid):
    validate_members(members)
    grid.validate()
    root_type = members[0]['type']
    tested = 0
    # Same-tile geometry is translationally invariant across instances of one
    # actual used tile type. Nonzero XY must use all real grid instances.
    same_tile = all(c['x'] == c['y'] == 0 for c in members[1:])
    visited = set()
    for tile, kind in enumerate(grid.tile_types):
        if same_tile and kind in visited:
            continue
        visited.add(kind)
        x, y = tile % grid.width, tile // grid.width
        for z, bel_type in grid.bels[kind].items():
            if bel_type != root_type:
                continue
            tested += 1
            witness = candidate_witness(members, grid, x, y, z)
            if witness is not None:
                return dict(compatible=True, locations=witness, root_candidates_tested=tested,
                            zero_proven=False, occupancy_or_fixed_bels_checked=False,
                            control_sets_or_timing_checked=False, physical_fit_verified=False)
    return dict(compatible=False, locations=None, root_candidates_tested=tested,
                zero_proven=True, occupancy_or_fixed_bels_checked=False,
                control_sets_or_timing_checked=False, physical_fit_verified=False)
