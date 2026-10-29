"""Read-only packed XC7 database view for the pinned nextpnr-xilinx schema."""
import mmap
import struct

class ChipDB:
    def __init__(self, path, constids):
        self.stream = path.open('rb')
        self.data = mmap.mmap(self.stream.fileno(), 0, access=mmap.ACCESS_READ)
        root = self.pointer(0)
        self.device = self.string(self.pointer(root))
        self.generator = self.string(self.pointer(root+4))
        self.version, self.width, self.height, self.tile_count, self.type_count, self.node_count = struct.unpack_from('<6i', self.data, root+8)
        assert self.version == 1 and self.generator == 'prjxray'
        assert self.width*self.height == self.tile_count and 0 < self.type_count < 1000
        self.types = self.pointer(root+32)
        extra = self.pointer(root+44)
        known, additional, strings = self.integer(extra), self.integer(extra+4), self.pointer(extra+8)
        self.names = ['']
        for line in constids.read_text().splitlines():
            line = line.strip()
            if line.startswith('X('):
                assert line.endswith(')'), line
                self.names.append(line[2:-1])
        assert len(self.names) == known
        self.names += [self.string(self.pointer(strings+4*i)) for i in range(additional)]
    def integer(self, offset):
        assert 0 <= offset <= len(self.data)-4
        return struct.unpack_from('<i', self.data, offset)[0]
    def pointer(self, offset):
        target = offset + 4*self.integer(offset)
        assert 0 <= target < len(self.data)
        return target
    def string(self, offset):
        end = self.data.find(b'\0', offset, min(offset+4096, len(self.data)))
        assert end >= offset
        return self.data[offset:end].decode('ascii')
    def bels(self, type_index):
        assert 0 <= type_index < self.type_count
        descriptor = self.types + type_index*32
        count, start = self.integer(descriptor+4), self.pointer(descriptor+8)
        result = []
        for index in range(count):
            address = start + index*32
            name, kind, native = struct.unpack_from('<3i', self.data, address)
            z, site, variant, routing = struct.unpack_from('<4h', self.data, address+24)
            assert routing in (0, 1)
            result.append(dict(index=index, name=self.names[name], type=self.names[kind], native_type=self.names[native],
                               z=z, site=site, variant=variant, routing=bool(routing), z_byte_offset=address+24))
        return self.names[self.integer(descriptor)], result
    def close(self):
        self.data.close()
        self.stream.close()
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.close()
