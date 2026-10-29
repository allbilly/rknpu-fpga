"""Synthetic RKMT capacity wire-audit controls; no device or network access."""
from pathlib import Path
import json
import tempfile
import unittest

from tools.ddr import audit_capacity
from tools.tinystories.audit_scans import MAGIC


RKAD = 0x524B4144
RKCD = 0x524B4344
RKMT = 0x524B4D54
ABI = 0x00010000
FULL_BYTES = 1 << 31
LINE_BYTES = 64
EXPECTED_OPS = 1 << 26
DEFAULT_SEED = 0x3588C350
IDCODE = 0x23751093


def command(op, address, data=0, response=0):
    return {'op': op, 'address': address, 'data': data, 'response': response}


def capacity_commands(*, seed=DEFAULT_SEED, ready_polls=(0, 0x10), progress=(),
                      identity=RKAD, abi=ABI, rkcd_identity=RKCD, rkcd_abi=ABI, rkmt_identity=RKMT,
                      management_abi=ABI, size=FULL_BYTES, base=0,
                      line_contract=0x00020040, normal_status=(0x10, 0x10),
                      diagnostic_ready=1, start_seed_readback=None,
                      terminal_status=0x68, final_health=0x68,
                      completion_counts=(EXPECTED_OPS, EXPECTED_OPS),
                      fault_codes=0, fault_sources=0):
    """Return decoded USER2 command dictionaries for one synthetic session."""
    rows = [command(1, 0, response=identity), command(1, 4, response=abi),
            command(1, 0x100, response=rkcd_identity), command(1, 0x104, response=rkcd_abi)]
    rows.extend(command(1, 8, response=status) for status in ready_polls)
    rows.extend((command(1, 0x200, response=rkmt_identity), command(1, 0x204, response=management_abi),
                 command(1, 0x214, response=size), command(1, 0x218, response=base),
                 command(1, 0x21C, response=line_contract),
                 command(1, 8, response=normal_status[0]),
                 command(1, 0x108, response=normal_status[1]),
                 command(1, 0x208, response=diagnostic_ready),
                 command(2, 0x210, data=seed, response=0),
                 command(1, 0x210, response=seed if start_seed_readback is None else start_seed_readback),
                 command(2, 0x20C, data=1, response=0)))
    snapshots = list(progress) + [(0x68, *completion_counts)]
    for status, writes, reads in snapshots:
        rows.extend((command(1, 0x208, response=status), command(1, 0x220, response=writes),
                     command(1, 0x224, response=reads), command(1, 0x228, response=fault_codes),
                     command(1, 0x22C, response=fault_sources)))
    rows.append(command(1, 0x208, response=final_health))
    return rows


def request(sequence, op, address=0, data=0):
    return (MAGIC << 572) | (sequence << 556) | (op << 548) | (15 << 544) | (address << 512) | data


def response(sequence, payload=0, status=0):
    return (MAGIC << 536) | (sequence << 520) | (status << 512) | payload


def scan_trace(decoded):
    """Encode decoded commands as a complete successful USER2 scan JSONL trace."""
    rows = [{'event': 'TAP_RESET_NOT_FABRIC_RESET'}]

    def scan(bits, ir, tdi, tdo):
        rows.append({'index': len(rows) - 1, 'bits': bits, 'ir': ir,
                     'tdi': f'{tdi:0{bits // 4}x}', 'tdo': f'{tdo:0{bits // 4}x}'})

    scan(6, True, 9, 0)
    scan(32, False, 0, IDCODE)
    scan(6, True, 3, 0)
    retained_sequence = 65534
    retained = response(retained_sequence)
    scan(640, False, 0, retained)
    last_request = retained_sequence
    for row in decoded:
        sequence = last_request % 65535 + 1
        scan(640, False, request(sequence, row['op'], row['address'], row['data']), retained)
        scan(640, False, 0, retained)
        retained = response(sequence, row['response'], 0)
        scan(640, False, 0, retained)
        last_request = sequence
    return rows


class CapacityWireAuditTests(unittest.TestCase):
    def test_full_two_gib_accepts_zero_progress_then_terminal_snapshot(self):
        result = audit_capacity.replay(capacity_commands(progress=()))
        self.assertEqual(result['base'], 0)
        self.assertEqual(result['size'], FULL_BYTES)
        self.assertEqual(result['trials'], 2)
        self.assertEqual(result['lines_per_trial'], FULL_BYTES // LINE_BYTES)
        self.assertEqual(result['completed_writes'], EXPECTED_OPS)
        self.assertEqual(result['completed_reads'], EXPECTED_OPS)
        self.assertEqual(result['device_status'], 0x68)
        self.assertEqual(result['snapshots'], 1)
        self.assertFalse(result['memory_payloads_observed_on_jtag'])
        self.assertTrue(result['four_retirement_witnesses_require_source_bound_bist'])

    def test_multiple_progress_snapshots_and_alternate_uint32_seed(self):
        seed = 0xDEADBEEF
        progress = ((0x40, 0, 0), (0x40, EXPECTED_OPS // 3, EXPECTED_OPS // 4),
                    (0x40, EXPECTED_OPS // 2, EXPECTED_OPS // 2))
        result = audit_capacity.replay(capacity_commands(seed=seed, progress=progress), seed=seed)
        self.assertEqual(result['seed'], seed)
        self.assertEqual(result['snapshots'], 4)

    def test_identity_abi_span_base_and_line_contract_are_exact(self):
        cases = (
            ('bad RKAD identity', {'identity': 0}),
            ('bad ABI', {'abi': ABI + 1}),
            ('bad RKCD identity', {'rkcd_identity': 0}),
            ('bad RKCD ABI', {'rkcd_abi': ABI + 1}),
            ('bad RKMT identity', {'rkmt_identity': 0}),
            ('bad management ABI', {'management_abi': ABI + 1}),
            ('partial span', {'size': FULL_BYTES - LINE_BYTES}),
            ('nonzero base', {'base': LINE_BYTES}),
            ('wrong line/trial metadata', {'line_contract': 0x00010040}),
        )
        for label, changes in cases:
            with self.subTest(label=label), self.assertRaises(ValueError):
                audit_capacity.replay(capacity_commands(**changes))

    def test_fresh_dual_transport_and_readiness_admission_order(self):
        good = capacity_commands(ready_polls=(0, 0, 0x10))
        result = audit_capacity.replay(good)
        self.assertEqual(result['decoded_commands'], len(good))
        # The two namespaces must be read before the memory-ready wait; the
        # complete nine-field management profile precedes seed and START.
        self.assertEqual([(r['op'], r['address']) for r in good[:4]],
                         [(1, 0), (1, 4), (1, 0x100), (1, 0x104)])
        self.assertEqual([r['address'] for r in good[4:7]], [8, 8, 8])
        seed_write = next(i for i, row in enumerate(good) if row['op'] == 2 and row['address'] == 0x210)
        seed_read = next(i for i, row in enumerate(good) if row['op'] == 1 and row['address'] == 0x210)
        start = next(i for i, row in enumerate(good) if row['op'] == 2 and row['address'] == 0x20C)
        self.assertLess(seed_write, seed_read)
        self.assertLess(seed_read, start)
        for mutate in ('memory_ready_fault', 'diagnostic_not_ready', 'ew_bank_busy', 'cmac_bank_busy'):
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                if mutate == 'memory_ready_fault': stream = capacity_commands(ready_polls=(0x40,))
                elif mutate == 'diagnostic_not_ready': stream = capacity_commands(diagnostic_ready=0x40)
                elif mutate == 'ew_bank_busy': stream = capacity_commands(normal_status=(0, 0x10))
                else: stream = capacity_commands(normal_status=(0x10, 0))
                audit_capacity.replay(stream)

    def test_seed_must_be_written_read_back_then_started_once(self):
        bad_readback = capacity_commands(start_seed_readback=DEFAULT_SEED ^ 1)
        with self.assertRaisesRegex(ValueError, 'Wrong capacity response'):
            audit_capacity.replay(bad_readback)
        normal = capacity_commands()
        seed_write = next(i for i, row in enumerate(normal) if row['op'] == 2 and row['address'] == 0x210)
        seed_read = next(i for i, row in enumerate(normal) if row['op'] == 1 and row['address'] == 0x210)
        start = next(i for i, row in enumerate(normal) if row['op'] == 2 and row['address'] == 0x20C)
        for stream in (normal[:seed_write] + [normal[start]] + normal[seed_write:start] + normal[start + 1:],
                       normal[:seed_read] + normal[seed_read + 1:]):
            with self.assertRaises(ValueError):
                audit_capacity.replay(stream)

    def test_unknown_failed_status_or_ecc_fault_never_accepts(self):
        cases = (
            ('unknown snapshot bit', capacity_commands(progress=((0xC0, 0, 0),))),
            ('fault status', capacity_commands(progress=((0x50, 0, 0),))),
            ('fault code', capacity_commands(fault_codes=1)),
            ('fault source', capacity_commands(fault_sources=1)),
            ('failed dual ID response', [command(1, 0, response=0xBAD)]),
        )
        for label, stream in cases:
            with self.subTest(label=label), self.assertRaises(ValueError):
                audit_capacity.replay(stream)

    def test_counter_regression_overflow_and_short_terminal_counts_reject(self):
        cases = (
            ('regression', capacity_commands(progress=((0x40, 8, 8), (0x40, 7, 8)))),
            ('overflow', capacity_commands(progress=((0x40, EXPECTED_OPS + 1, 0),))),
            ('short done', capacity_commands(completion_counts=(EXPECTED_OPS - 1, EXPECTED_OPS))),
            ('read short', capacity_commands(completion_counts=(EXPECTED_OPS, EXPECTED_OPS - 1))),
        )
        for label, stream in cases:
            with self.subTest(label=label), self.assertRaises(ValueError):
                audit_capacity.replay(stream)

    def test_final_health_change_rejects_terminal_snapshot(self):
        with self.assertRaisesRegex(ValueError, 'Wrong capacity response'):
            audit_capacity.replay(capacity_commands(final_health=0x40))

    def test_extra_and_truncated_decoded_commands_reject(self):
        good = capacity_commands()
        with self.assertRaisesRegex(ValueError, 'Extra command'):
            audit_capacity.replay(good + [command(1, 0x200, response=RKMT)])
        with self.assertRaisesRegex(ValueError, 'Truncated capacity protocol'):
            audit_capacity.replay(good[:-1])

    def test_uint32_seed_type_and_range(self):
        for seed in (-1, 1 << 32, True, 1.5):
            with self.subTest(seed=seed), self.assertRaisesRegex(ValueError, 'Seed must be uint32'):
                audit_capacity.replay(capacity_commands(), seed=seed)

    def test_synthetic_native_scan_jsonl_obeys_audit_scans_grammar_and_has_no_physical_claim(self):
        decoded = capacity_commands(seed=0xA5A5A5A5)
        rows = scan_trace(decoded)
        with tempfile.TemporaryDirectory(prefix='synthetic capacity USER2 ') as directory:
            trace = Path(directory) / 'scans.jsonl'
            trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            result = audit_capacity.audit(trace, seed=0xA5A5A5A5)
            self.assertEqual(result['status'], 'PASS_INDEPENDENT_FULL_WINDOW_RKMT_WIRE_WITNESSES_ONLY')
            self.assertEqual(result['scan_statistics']['commands'], len(decoded))
            self.assertEqual(result['scan_statistics']['idcodes'], 1)
            self.assertEqual(result['scan_statistics']['tap_resets'], 1)
            self.assertFalse(result['physical_capacity_qualified'])
            self.assertFalse(result['hardware_accessed'])

    def test_raw_idcode_sequence_magic_and_failed_scan_corruption_reject(self):
        valid = scan_trace(capacity_commands())
        corruptions = []
        wrong_idcode = [dict(row) for row in valid]
        wrong_idcode[2]['tdo'] = f'{IDCODE ^ 1:08x}'
        corruptions.append(('IDCODE', wrong_idcode))
        wrong_sequence = [dict(row) for row in valid]
        first_request_event = next(i for i, row in enumerate(wrong_sequence)
                                   if row.get('index') == 4)
        wrong_sequence[first_request_event]['tdi'] = f'{request(1, 1, 0):0160x}'
        corruptions.append(('sequence', wrong_sequence))
        wrong_magic = [dict(row) for row in valid]
        wrong_magic[4]['tdo'] = f'{response(65534) ^ (1 << 536):0160x}'
        corruptions.append(('magic', wrong_magic))
        wrong_status = [dict(row) for row in valid]
        # The response to the first USER2 command has a nonzero wire status.
        first_command_response = next(i for i, row in enumerate(wrong_status)
                                      if row.get('index') == 6)
        word = int(wrong_status[first_command_response]['tdo'], 16)
        wrong_status[first_command_response]['tdo'] = f'{word | (0x80 << 512):0160x}'
        corruptions.append(('failed mailbox status', wrong_status))
        failed_scan = [dict(row) for row in valid]
        failed_scan[-1].pop('tdo')
        failed_scan[-1]['error'] = "TimeoutError('synthetic timeout')"
        corruptions.append(('failed scan', failed_scan))
        for label, rows in corruptions:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'scans.jsonl'
                path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
                with self.assertRaises(ValueError):
                    audit_capacity.audit(path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
