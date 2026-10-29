"""Shape, constant packing and strict input admission; no hardware or inference."""
import math
import struct
import unittest

from tools.tinystories.prepare import (check_model, check_tokenizer, pack_tile,
                                      projection_layout, tensor_layout)


class PreparationTests(unittest.TestCase):
    def test_classic_file_offsets_and_tied_output(self):
        tensors = tensor_layout()
        cursor = 28
        for item in tensors.values():
            self.assertEqual(item['offset'], cursor)
            self.assertEqual(item['bytes'], math.prod(item['shape'])*4)
            cursor += item['bytes']
        self.assertEqual(cursor, 1056540)
        projections = projection_layout(tensors)
        self.assertEqual(len(projections), 36)
        self.assertEqual(projections[-1]['source_offset'], tensors['token_embedding_table']['offset'])
        self.assertEqual(sum((p['outputs']+31)//32 for p in projections), 116)

    def test_full_model_static_tile_budget(self):
        projections = projection_layout()
        total = sum(((p['outputs']+31)//32)*32*((p['inputs']+31)//32*32)*2 for p in projections)
        self.assertEqual(total, 557056)
        self.assertEqual({p['inputs'] for p in projections}, {64, 172})

    def test_constant_oc16_ic32_layout_and_zero_padding(self):
        # A small synthetic source exercises the two partial dimensions and
        # nonzero file offset independently of the pinned trained model.
        rows, columns, offset = 35, 33, 12
        model = b'prefix-bytes'+b''.join(struct.pack('<f', (row*columns+col)/128)
                                       for row in range(rows) for col in range(columns))
        self.assertEqual(len(b'prefix-bytes'), offset)
        projection = dict(inputs=columns, outputs=rows, source_offset=offset)
        for first in (0, 32):
            raw = pack_tile(model, projection, first)
            self.assertEqual(len(raw), 4096)
            for row in range(32):
                for column in range(64):
                    index = (row//16)*1024+(column//32)*512+(row%16)*32+column%32
                    actual = raw[2*index:2*index+2]
                    expected = struct.pack('<e', ((first+row)*columns+column)/128
                                           if first+row < rows and column < columns else 0)
                    self.assertEqual(actual, expected)

    def test_overflow_and_nonfinite_weights_are_explicit_failures(self):
        projection = dict(inputs=1, outputs=1, source_offset=0)
        for value in (float('nan'), float('inf'), -float('inf'), 1.e20):
            with self.subTest(value=value), self.assertRaises(ValueError):
                pack_tile(struct.pack('<f', value), projection, 0)

    def test_invalid_tile_start_is_not_repaired(self):
        projection = dict(inputs=1, outputs=1, source_offset=0)
        for first in (-1, 1, 32, True, 0.0):
            with self.subTest(first=first), self.assertRaises(ValueError):
                pack_tile(struct.pack('<f', 1), projection, first)

    def test_unknown_or_truncated_assets_are_rejected(self):
        for raw in (b'', b'x'*28, b'x'*1056540):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                check_model(raw)
        for raw in (b'', b'not the pinned tokenizer'):
            with self.assertRaises(ValueError):
                check_tokenizer(raw)


if __name__ == '__main__':
    unittest.main()
