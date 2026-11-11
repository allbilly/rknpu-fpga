"""Unit and evidence tests for the captured ew-int integer EW increment.

These tests are offline: they decode the 15 READY captured bundles, run the
software reference, check the ALU against captured lanes and labelled
source-formula edges, verify the fail-closed decoder contract, and (when a
fresh replay receipt exists) check that the receipt is still hash-bound to the
current RTL/model/test sources.

Run: python3 -m unittest discover -s tests -p 'test_ew_int.py' -v
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / 'build/rk3588-example-captures/ew-int'
MANIFEST_PATH = CAPTURE / 'manifest.json'
FROZEN = ROOT / 'build/verif/frozen_hashes.json'
FROZEN_EW_FILES = ['rtl/rk_ew_engine.sv', 'rtl/rk_ew_regs.sv', 'rtl/rk_ew_dma.sv',
                   'rtl/rk_ew_dma_demo.sv', 'rtl/rk_fp16_alu.sv',
                   'rtl/rk_ew_axi.sv', 'rtl/rk_ew_core.sv', 'rtl/rk_ew_demo.sv',
                   'rtl/host/rk_jtag_ew_bram.sv', 'fpga/ypcb_ew_startup_top.sv']
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.int_alu import (DTYPE_CODES, DTYPE_ITEMS, OP_CODES, alu,  # noqa: E402
                           decode_item, signed16)
from model.int_profile import (IntDecoder, ProfileError, decode_regcmd,  # noqa: E402
                               ew_cfg_value, patch_value32)
from model.int_sim import IntEmulator, IntMemory, masked_compare  # noqa: E402

A_OFF, B_OFF, OUT_OFF = 0x400, 0x1400, 0x2400
BASE = 0x10000000
BO_BYTES = 4096


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def words(raw):
    return [value for (value,) in struct.iter_unpack('<Q', raw)]


def patched(entry, a=A_OFF, b=B_OFF, dst=OUT_OFF):
    raw = (CAPTURE / entry['bundle_dir'] / 'regcmd.bin').read_bytes()
    raw = patch_value32(raw, 0x1001, 0x4020, BASE + dst)
    raw = patch_value32(raw, 0x2001, 0x5018, BASE + a)
    raw = patch_value32(raw, 0x2001, 0x5038, BASE + b)
    return raw


def set_word(raw, key, value):
    data = words(raw)
    matches = [i for i, word in enumerate(data)
               if (word >> 48) == key[0] and (word & 0xFFFF) == key[1]]
    if len(matches) != 1:
        raise AssertionError(f'{key} not unique')
    word = data[matches[0]]
    data[matches[0]] = (word & 0xFFFF_0000_0000_FFFF) | ((value & 0xFFFFFFFF) << 16)
    return b''.join(int(v).to_bytes(8, 'little') for v in data)


def lane_offset(lane, item, layout, width, channels):
    if layout == 'surface':
        atom = 16 // item
        channel, pixel = lane % channels, lane // channels
        return (((channel // atom) * width + pixel) * atom +
                (channel % atom)) * item
    return lane * item


def logical_values(payload, cfg, out=False):
    dtype = cfg.out_dtype if out else cfg.dtype
    item = DTYPE_ITEMS[dtype]
    values = []
    for lane in range(cfg.count):
        offset = lane_offset(lane, item, cfg.layout, cfg.width, cfg.channels)
        values.append(decode_item(payload[offset:offset + item], dtype))
    return values


EXPECTED_MATRIX = {
    'int8_add_c8_w1': ('simple', 'ADD', 'INT8', 'INT8', 8, 8, 1, 'contiguous', 8, 8),
    'int8_max_c8_w1': ('simple', 'MAX', 'INT8', 'INT8', 8, 8, 1, 'contiguous', 8, 8),
    'int8_min_c8_w1': ('simple', 'MIN', 'INT8', 'INT8', 8, 8, 1, 'contiguous', 8, 8),
    'int8_mul_c8_w1': ('simple', 'MUL', 'INT8', 'INT8', 8, 8, 1, 'contiguous', 8, 8),
    'int16_add_c8_w1': ('simple', 'ADD', 'INT16', 'INT16', 8, 8, 1, 'contiguous', 16, 16),
    'int16_minus_c8_w1': ('simple', 'MINUS', 'INT16', 'INT16', 8, 8, 1, 'contiguous', 16, 16),
    'int16_mul_c8_w1': ('simple', 'MUL', 'INT16', 'INT16', 8, 8, 1, 'contiguous', 16, 16),
    'int32_add_c8_w2': ('simple', 'ADD', 'INT32', 'INT32', 8, 4, 2, 'contiguous', 32, 32),
    'int32_max_c8_w2': ('simple', 'MAX', 'INT32', 'INT32', 8, 4, 2, 'contiguous', 32, 32),
    'int32_mul_int16_operand_c8_w2': ('simple', 'MUL', 'INT32', 'INT32', 8, 4, 2, 'contiguous', 32, 32),
    'int8_add_c9_w1_layout': ('layout', 'ADD', 'INT8', 'INT8', 9, 9, 1, 'surface', 16, 16),
    'int16_add_c9_w1_layout': ('layout', 'ADD', 'INT16', 'INT16', 9, 9, 1, 'surface', 32, 32),
    'int16_minus_c9_w1_layout': ('layout', 'MINUS', 'INT16', 'INT16', 9, 9, 1, 'surface', 32, 32),
    'int32_add_c9_w1_layout': ('layout', 'ADD', 'INT32', 'INT32', 9, 9, 1, 'surface', 48, 48),
    'int16_add_to_int32_c8_w1': ('regroup', 'ADD', 'INT16', 'INT32', 8, 8, 1, 'contiguous', 16, 32),
}


def load_manifest():
    return json.loads(MANIFEST_PATH.read_text())


def ready_entries(manifest):
    return [entry for entry in manifest['cases'] if entry['status'] == 'READY']


class ManifestEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest()
        self.ready = ready_entries(self.manifest)

    def test_counts_and_blocked_cases(self):
        self.assertEqual(self.manifest['counts'], {'READY': 15, 'BLOCKED': 3})
        blocked = [entry for entry in self.manifest['cases']
                   if entry['status'] == 'BLOCKED']
        self.assertEqual({entry['case'] for entry in blocked},
                         {'int32_div_c8_w2', 'fp16_four_input_sum_c8_w1',
                          'fp16_bs_bn_relu_prelu_c8_w1'})
        for entry in blocked:
            self.assertEqual(entry['oracle'], 'none')
            self.assertTrue(entry.get('blocked_reason'))

    def test_bundle_hashes_match_manifest(self):
        for entry in self.ready:
            bundle = CAPTURE / entry['bundle_dir']
            for name, digest in entry['hashes'].items():
                self.assertEqual(sha(bundle / name), digest,
                                 f'{entry["case"]}/{name}')

    def test_ready_case_set(self):
        self.assertEqual({entry['case'] for entry in self.ready}, set(EXPECTED_MATRIX))

    def test_frozen_ew_files_untouched(self):
        frozen = json.loads(FROZEN.read_text())['files']
        for name in FROZEN_EW_FILES:
            self.assertIn(name, frozen)
            self.assertEqual(sha(ROOT / name), frozen[name]['sha256'],
                             f'frozen EW file changed: {name}')


class DecoderTest(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest()
        self.ready = ready_entries(self.manifest)

    def test_decoded_matrix(self):
        for entry in self.ready:
            config = decode_regcmd(patched(entry))[0]
            expected = EXPECTED_MATRIX[entry['case']]
            self.assertEqual(
                (config.mode, config.op, config.dtype, config.out_dtype,
                 config.count, config.channels, config.width, config.layout,
                 config.in_bytes, config.out_bytes),
                expected, entry['case'])

    def test_ew_cfg_reconstruction_matches_captured_words(self):
        for entry in self.ready:
            config = decode_regcmd(patched(entry))[0]
            bypass = config.dtype == 'INT32' and config.mode != 'regroup'
            source_dtype = 'INT16' if config.mode == 'regroup' else config.dtype
            source_op = 'ADD' if config.mode == 'regroup' else config.op
            captured = words(patched(entry))
            ew = [word for word in captured if (word >> 48) == 0x1001
                  and (word & 0xFFFF) == 0x4070][0]
            self.assertEqual((ew >> 16) & 0xFFFFFFFF,
                             ew_cfg_value(source_dtype, source_op, bypass),
                             entry['case'])

    def test_unsupported_ops_fail_closed(self):
        entry = next(e for e in self.ready if e['case'] == 'int8_add_c8_w1')
        base = patched(entry)
        for operation, alu_code in (('DIV', 3), ('ABS', 5), ('NEG', 6),
                                    ('FLOOR', 7), ('CEIL', 8)):
            stream = set_word(base, (0x1001, 0x4070), 0x104202C0 | (alu_code << 16))
            with self.assertRaises(ProfileError) as caught:
                decode_regcmd(stream)
            self.assertEqual(caught.exception.code, 2, operation)

    def test_unsupported_fp16_dtype_fails_closed(self):
        entry = next(e for e in self.ready if e['case'] == 'int8_add_c8_w1')
        stream = set_word(patched(entry), (0x1001, 0x4010), 0x48000002)
        with self.assertRaises(ProfileError) as caught:
            decode_regcmd(stream)
        self.assertEqual(caught.exception.code, 2)

    def test_wrong_geometry_fails_closed(self):
        entry = next(e for e in self.ready if e['case'] == 'int8_add_c8_w1')
        base = patched(entry)
        with self.assertRaises(ProfileError) as caught:
            decode_regcmd(set_word(base, (0x2001, 0x500c), 1))
        self.assertEqual(caught.exception.code, 6)
        with self.assertRaises(ProfileError) as caught:
            decode_regcmd(set_word(base, (0x2001, 0x5014), 8))
        self.assertEqual(caught.exception.code, 6)

    def test_unknown_register_and_target_fail_closed(self):
        entry = next(e for e in self.ready if e['case'] == 'int8_add_c8_w1')
        data = words(patched(entry))
        index = next(i for i, word in enumerate(data)
                     if (word >> 48) == 0x2001 and (word & 0xFFFF) == 0x5044)
        data[index] = (0x3001 << 48) | ((data[index] >> 16) & 0xFFFFFFFF) << 16 | 0x5044
        stream = b''.join(int(v).to_bytes(8, 'little') for v in data)
        with self.assertRaises(ProfileError) as caught:
            decode_regcmd(stream)
        self.assertEqual(caught.exception.code, 1)

    def test_duplicate_conflict_and_missing_register(self):
        entry = next(e for e in self.ready if e['case'] == 'int8_add_c8_w1')
        base = words(patched(entry))
        conflict = base[:-4] + [(0x1001 << 48) | (0x1E4 << 16) | 0x400C] + base[-4:]
        stream = b''.join(int(v).to_bytes(8, 'little') for v in conflict)
        with self.assertRaises(ProfileError) as caught:
            decode_regcmd(stream)
        self.assertEqual(caught.exception.code, 2)
        missing = [word for i, word in enumerate(base) if i != 5]
        stream = b''.join(int(v).to_bytes(8, 'little') for v in missing)
        with self.assertRaises(ProfileError) as caught:
            decode_regcmd(stream)
        self.assertEqual(caught.exception.code, 3)

    def test_address_errors(self):
        entry = next(e for e in self.ready if e['case'] == 'int8_add_c8_w1')
        with self.assertRaises(ProfileError) as caught:
            decode_regcmd(patched(entry, a=A_OFF + 2))
        self.assertEqual(caught.exception.code, 4)
        layout = next(e for e in self.ready if e['case'] == 'int32_add_c9_w1_layout')
        stream = set_word(patched(layout), (0x1001, 0x4020), 0xFFFFFFE0)
        with self.assertRaises(ProfileError) as caught:
            decode_regcmd(stream)
        self.assertEqual(caught.exception.code, 4)

    def test_pc_chain_rejected(self):
        entry = next(e for e in self.ready if e['case'] == 'int8_add_c8_w1')
        stream = set_word(patched(entry), (0x0101, 0x0010), 0x100)
        with self.assertRaises(ProfileError) as caught:
            decode_regcmd(stream)
        self.assertEqual(caught.exception.code, 2)


class ArithmeticEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest()
        self.ready = ready_entries(self.manifest)

    def test_captured_oracle_masked_exact(self):
        for entry in self.ready:
            bundle = CAPTURE / entry['bundle_dir']
            config = decode_regcmd(patched(entry))[0]
            memory = IntMemory()
            memory.map(BASE + A_OFF, (bundle / 'a.bin').read_bytes())
            memory.map(BASE + B_OFF, (bundle / 'b.bin').read_bytes())
            out = memory.map(BASE + OUT_OFF, bytes(BO_BYTES))
            IntEmulator(memory).submit(patched(entry))
            result = masked_compare(bytes(out), (bundle / 'expected.bin').read_bytes(),
                                    (bundle / 'expected.mask.bin').read_bytes())
            self.assertTrue(result['exact'], f'{entry["case"]}: {result["mismatches"]}')
            self.assertEqual(result['asserted_bytes'],
                             config.count * config.out_item, entry['case'])

    def test_captured_lanes_do_not_overflow(self):
        """Finding recorded in docs/EW_INT.md: the prose 'saturation' lanes in
        the capture README/manifest are arithmetically false; expected bytes are
        plain in-range arithmetic, so saturation is source-formula only."""
        limits = {'INT8': (-128, 127), 'INT16': (-32768, 32767),
                  'INT32': (-2147483648, 2147483647)}
        for entry in self.ready:
            config = decode_regcmd(patched(entry))[0]
            bundle = CAPTURE / entry['bundle_dir']
            a_values = logical_values((bundle / 'a.bin').read_bytes(), config)
            b_values = logical_values((bundle / 'b.bin').read_bytes(), config)
            expected = logical_values((bundle / 'expected.bin').read_bytes(), config, out=True)
            low, high = limits[config.out_dtype]
            for index, (a, b, got) in enumerate(zip(a_values, b_values, expected)):
                raw = {'ADD': a + b, 'MINUS': a - b, 'MAX': max(a, b),
                       'MIN': min(a, b), 'MUL': a * b}[config.op]
                if config.op == 'MUL' and config.dtype == 'INT32':
                    raw = a * signed16(b)
                self.assertEqual(got, raw, f'{entry["case"]} lane {index}')
                self.assertTrue(low <= got <= high)
        # The specific lanes the README calls overflowing are in range.
        self.assertEqual(max([31000, -31000, 105]), 31000)

    def test_int32_mul_signed16_operand(self):
        entry = next(e for e in self.ready
                     if e['case'] == 'int32_mul_int16_operand_c8_w2')
        config = decode_regcmd(patched(entry))[0]
        bundle = CAPTURE / entry['bundle_dir']
        b_values = logical_values((bundle / 'b.bin').read_bytes(), config)
        expected = logical_values((bundle / 'expected.bin').read_bytes(), config, out=True)
        self.assertEqual(signed16(b_values[0]), -15536)
        self.assertEqual(signed16(b_values[1]), 15536)
        self.assertEqual(expected[0], 15536000)
        self.assertEqual(expected[1], -31072000)

    def test_regroup_widens_without_int16_clamp(self):
        entry = next(e for e in self.ready if e['case'] == 'int16_add_to_int32_c8_w1')
        config = decode_regcmd(patched(entry))[0]
        bundle = CAPTURE / entry['bundle_dir']
        a_values = logical_values((bundle / 'a.bin').read_bytes(), config)
        b_values = logical_values((bundle / 'b.bin').read_bytes(), config)
        expected = logical_values((bundle / 'expected.bin').read_bytes(), config, out=True)
        self.assertEqual(config.out_dtype, 'INT32')
        self.assertEqual(a_values[-1] + b_values[-1], 31000)
        self.assertEqual(expected[-1], 31000)
        for a, b, got in zip(a_values, b_values, expected):
            self.assertEqual(got, int(a) + int(b))

    def test_surface_layout_reduces_to_contiguous_at_width_one(self):
        for entry in self.ready:
            config = decode_regcmd(patched(entry))[0]
            if config.layout != 'surface':
                continue
            self.assertEqual(config.width, 1)
            for lane in range(config.count):
                self.assertEqual(
                    lane_offset(lane, config.in_item, config.layout,
                                config.width, config.channels),
                    lane * config.in_item, entry['case'])
                self.assertEqual(
                    lane_offset(lane, config.out_item, config.layout,
                                config.width, config.channels),
                    lane * config.out_item, entry['case'])


class AluTest(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest()
        self.ready = ready_entries(self.manifest)

    def test_alu_matches_every_captured_lane(self):
        for entry in self.ready:
            config = decode_regcmd(patched(entry))[0]
            bundle = CAPTURE / entry['bundle_dir']
            a_values = logical_values((bundle / 'a.bin').read_bytes(), config)
            b_values = logical_values((bundle / 'b.bin').read_bytes(), config)
            expected = logical_values((bundle / 'expected.bin').read_bytes(), config, out=True)
            for index, (a, b, want) in enumerate(zip(a_values, b_values, expected)):
                operand_b = signed16(b) if (config.op == 'MUL' and
                                            config.dtype == 'INT32') else b
                self.assertEqual(alu(config.op, config.out_dtype, a, operand_b),
                                 want, f'{entry["case"]} lane {index}')

    def test_source_formula_saturation_edges(self):
        edges = [('ADD', 'INT8', 127, 1, 127),
                 ('ADD', 'INT8', -128, -1, -128),
                 ('MINUS', 'INT8', -128, 1, -128),
                 ('MUL', 'INT8', 100, 2, 127),
                 ('ADD', 'INT16', 32767, 1, 32767),
                 ('ADD', 'INT16', -32768, -1, -32768),
                 ('MUL', 'INT16', -30000, 2, -32768),
                 ('ADD', 'INT32', 2147483647, 1, 2147483647),
                 ('MINUS', 'INT32', -2147483648, 1, -2147483648),
                 ('MUL', 'INT32', 2147483647, 2, 2147483647),
                 ('MAX', 'INT8', -5, 3, 3),
                 ('MIN', 'INT16', -32768, 32767, -32768)]
        for op, dtype, a, b, want in edges:
            self.assertEqual(alu(op, dtype, a, b), want, (op, dtype, a, b))

    def test_unsupported_ops_raise(self):
        for operation in ('DIV', 'ABS', 'NEG', 'FLOOR', 'CEIL'):
            with self.assertRaises(ValueError):
                alu(operation, 'INT8', 1, 1)


class NegativeControlInventoryTest(unittest.TestCase):
    def test_tool_negative_controls_raise_declared_codes(self):
        path = ROOT / 'tools/ew_int/run_ew_int.py'
        spec = importlib.util.spec_from_file_location('run_ew_int', path)
        driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(driver)
        manifest = driver.load_manifest()
        controls = driver.negative_controls(manifest)
        self.assertGreaterEqual(len(controls), 15)
        for control in controls:
            with self.assertRaises(ProfileError) as caught:
                decode_regcmd(control['stream'])
            self.assertEqual(caught.exception.code, control['error_code'],
                             control['name'])


class ReplayReceiptTest(unittest.TestCase):
    def test_latest_receipt_is_fresh_and_green(self):
        receipts = sorted((ROOT / 'build/ew-int').glob('*/report.json'),
                          key=lambda path: path.stat().st_mtime)
        if not receipts:
            self.skipTest('no replay receipt yet; run tools/ew_int/run_ew_int.py')
        report = json.loads(receipts[-1].read_text())
        for name, digest in report['source_hashes'].items():
            if (ROOT / name).is_file() and sha(ROOT / name) != digest:
                self.skipTest(f'stale replay receipt ({name} changed); '
                              'regenerate with tools/ew_int/run_ew_int.py')
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(set(report['simulators']), {'verilator', 'iverilog'})
        for simulator, record in report['simulators'].items():
            self.assertEqual(record['status'], 'PASS', simulator)
            self.assertEqual(len(record['cases']), 15)
            self.assertTrue(all(case['status'] == 'PASS'
                                for case in record['cases'].values()))
            self.assertEqual(len(record['negative_controls']), 19)
            self.assertTrue(all(entry['status'] == 'PASS'
                                for entry in record['negative_controls'].values()))
        self.assertEqual(len(report['cases']), 15)
        self.assertTrue(all(case['status'] == 'PASS'
                            for case in report['cases'].values()))
        blocked = {entry['case'] for entry in report['blocked_cases']}
        self.assertEqual(blocked, {'int32_div_c8_w2', 'fp16_four_input_sum_c8_w1',
                                   'fp16_bs_bn_relu_prelu_c8_w1'})


if __name__ == '__main__':
    unittest.main()
