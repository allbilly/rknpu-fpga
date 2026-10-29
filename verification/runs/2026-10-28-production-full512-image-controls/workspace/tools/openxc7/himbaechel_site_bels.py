"""Read-only generic-to-global BEL labels for pinned Himbaechel v6 XC7 data.

Implements Arch::init_tiles/getBelName and XilinxImpl::get_site_bel_name plus
postRouteArchInfo's no-site fallback. Names alone are not placement legality,
electrical correctness, routing completeness or timing evidence.
"""
import mmap
from pathlib import Path
import re
import struct


class SiteBELMap:
    def __init__(self, database, constids):
        self.stream = Path(database).open('rb')
        try:
            self.data = mmap.mmap(self.stream.fileno(), 0, access=mmap.ACCESS_READ)
        except BaseException:
            self.stream.close()
            raise
        try:
            root = self.pointer(0, 84)
            assert (self.integer(root), self.integer(root + 4)) == (0x00ca7ca7, 6), 'Unsupported chipdb schema'
            assert self.string(self.pointer(root + 16, 1)) == 'xilinx'
            assert self.string(self.pointer(root + 20, 1)) == 'xc7k480t'
            self.width, self.height = self.integer(root + 8), self.integer(root + 12)
            assert 0 < self.width <= 4096 and 0 < self.height <= 4096
            self.types, self.type_count = self.slice(root + 28, 40)
            self.tiles, self.tile_count = self.slice(root + 36, 16)
            assert self.tile_count == self.width * self.height
            self.names = ['']
            for line in Path(constids).read_text().splitlines():
                line = line.strip()
                if line.startswith('X('):
                    assert re.fullmatch(r'X\([A-Za-z0-9_]+\)', line), 'Unexpected ConstID spelling'
                    self.names.append(line[2:-1])
            ids = self.pointer(root + 76, 12)
            assert self.integer(ids) == len(self.names), 'Wrong ConstID enum'
            strings, count = self.slice(ids + 4, 4)
            self.names.extend(self.string(self.pointer(strings + 4 * i, 1)) for i in range(count))
            assert len(set(self.names)) == len(self.names), 'Duplicate ConstID names'
            self.bel_types = {}
        except BaseException:
            self.close()
            raise

    def checked(self, offset, size):
        assert 0 <= offset <= len(self.data) and 0 <= size <= len(self.data) - offset, 'Database range outside blob'
        return offset

    def integer(self, offset):
        return struct.unpack_from('<i', self.data, self.checked(offset, 4))[0]

    def pointer(self, offset, size):
        relative = self.integer(offset)
        assert relative != 0, 'Null required pointer'
        return self.checked(offset + relative, size)

    def slice(self, offset, stride):
        relative, count = struct.unpack_from('<iI', self.data, self.checked(offset, 8))
        assert relative or not count, 'Null nonempty slice'
        return self.checked(offset + relative, count * stride), count

    def string(self, offset):
        self.checked(offset, 1)
        end = self.data.find(b'\0', offset, min(offset + 4096, len(self.data)))
        assert end >= offset, 'Unterminated database string'
        return self.data[offset:end].decode('ascii')

    def name(self, index):
        assert 0 <= index < len(self.names), 'Invalid ConstID index'
        return self.names[index]

    def global_label(self, generic):
        match = re.fullmatch(r'([^/\s]*)X([0-9]+)Y([0-9]+)/([^/\s]+)', generic)
        assert match, 'Invalid generic BEL spelling'
        prefix, x, y, local = match.groups()
        x, y = int(x), int(y)
        assert x < self.width and y < self.height, 'BEL tile outside device'
        tile = self.tiles + 16 * (y * self.width + x)
        assert self.name(self.integer(tile)) == prefix, 'BEL tile-prefix mismatch'
        kind = self.integer(tile + 4)
        assert 0 <= kind < self.type_count, 'Invalid tile type'
        if kind not in self.bel_types:
            start, count = self.slice(self.types + 40 * kind + 4, 36)
            names = {}
            for i in range(count):
                bel = start + 36 * i
                name = self.name(self.integer(bel))
                assert name not in names, 'Duplicate tile-local BEL name'
                names[name] = bel
            self.bel_types[kind] = names
        assert local in self.bel_types[kind], 'Unknown BEL in tile type'
        bel = self.bel_types[kind][local]
        site = (self.integer(bel + 16) >> 8) & 0xffff
        if site >= 0x8000:
            site -= 0x10000
        extra = self.pointer(tile + 12, 16)
        sites, site_count = self.slice(extra + 8, 24)
        if not 0 <= site < site_count:
            # postRouteArchInfo leaves no-site resources in the generic form.
            assert site == -1, 'Unexpected nonnegative BEL site outside tile'
            return generic
        descriptor = sites + 24 * site
        site_x, site_y = struct.unpack_from('<hh', self.data, self.checked(descriptor + 4, 4))
        assert site_x >= 0 and site_y >= 0
        site_name = f'{self.name(self.integer(descriptor))}_X{site_x}Y{site_y}'
        bel_extra = self.pointer(bel + 32, 4)
        return site_name + '/' + self.name(self.integer(bel_extra))

    def close(self):
        self.data.close()
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
