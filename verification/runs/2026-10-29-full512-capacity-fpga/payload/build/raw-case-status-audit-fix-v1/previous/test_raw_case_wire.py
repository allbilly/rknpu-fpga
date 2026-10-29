"""Synthetic single-job raw USER2 audit controls; no device or network access."""
from pathlib import Path
import tempfile
import unittest

from tools.ddr import audit_raw_case


RKAD = 0x524B4144
RKCD = 0x524B4344
ABI = 0x00010000
RK_CMD = 0x100E0000
AMOUNT = 35
TASKS = 2
TAG = 0x44445201
LINE_BYTES = 64
MASK512 = (1 << 512) - 1


def command(op, address, data=0, response=0):
    return {'op': op, 'address': address, 'data': data, 'response': response}


class RawCaseWireTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic raw capacity session ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upload = self.root / 'original-bo.txt'
        self.expected = self.root / 'expected-bo.txt'
        self.addresses = (0x10000000, 0x10000040, 0x10000080)
        self.before = [(address, ((index + 1) * 0x0102030405060708090A0B0C0D0E0F) & MASK512)
                       for index, address in enumerate(self.addresses)]
        self.after = [(address, value ^ (0xA5A5 << index))
                      for index, (address, value) in enumerate(self.before)]
        self.write_fixture(self.upload, self.before)
        self.write_fixture(self.expected, self.after)

    @staticmethod
    def write_fixture(path, rows):
        path.write_text(''.join(f'{address:08x} {value:0128x}\n' for address, value in rows))

    def valid_wire(self, profile='ew', polls=1):
        base = 0 if profile == 'ew' else 0x100
        peer = 0x100 if profile == 'ew' else 0
        wire = [command(1, 0, response=RKAD), command(1, 4, response=ABI),
                command(1, 0x100, response=RKCD), command(1, 0x104, response=ABI),
                command(1, 8, response=0x10), command(1, 0x108, response=0x10)]
        # A second ready poll matches valid transport implementations which
        # perform a read-before-write admission check.
        wire.extend(command(1, base + 8, response=0x10) for _ in range(polls))
        wire.extend(command(4, address, data=value) for address, value in self.before)
        wire.extend((command(2, base + 16, RK_CMD), command(2, base + 20, AMOUNT),
                     command(2, base + 24, TAG)))
        wire.extend(command(1, base + 8, response=0x11) for _ in range(polls))
        wire.append(command(2, base + 12, 1))
        wire.extend(command(1, base + 8, response=0x40) for _ in range(polls))
        wire.append(command(1, base + 8, response=0x04))
        wire.extend((command(1, base + 28, response=TAG),
                     command(1, base + 32, response=TASKS),
                     command(1, base + 36, response=0)))
        wire.extend(command(3, address, response=value) for address, value in self.after)
        wire.extend((command(2, base + 12, 2), command(1, base + 8, response=0x10),
                     command(1, peer + 8, response=0x10)))
        return wire

    def replay(self, wire=None, *, profile='ew', upload=None, expected=None):
        return audit_raw_case.replay(self.valid_wire(profile) if wire is None else wire,
                                     self.upload if upload is None else upload,
                                     self.expected if expected is None else expected,
                                     profile=profile, command_address=RK_CMD,
                                     amount=AMOUNT, tasks=TASKS, tag=TAG)

    def index(self, wire, predicate):
        return next(i for i, row in enumerate(wire) if predicate(row))

    def test_ew_and_cmac_profiles_accept_single_and_double_status_polls(self):
        for profile in ('ew', 'cmac'):
            for polls in (1, 2):
                with self.subTest(profile=profile, polls=polls):
                    result = self.replay(self.valid_wire(profile, polls), profile=profile)
                    self.assertEqual(result['status'], 'PASS_INDEPENDENT_SINGLE_RAW_JOB_WIRE_ONLY')
                    self.assertEqual(result['profile'], profile)
                    self.assertEqual(result['jobs'], 1)
                    self.assertEqual(result['tasks'], TASKS)
                    self.assertEqual(result['complete_bo_bytes'], len(self.before) * LINE_BYTES)
                    self.assertTrue(result['complete_readback_before_ack'])
                    self.assertFalse(result['physical_image_qualified'])

    def test_complete_original_fixture_and_changed_upload_reject(self):
        wire = self.valid_wire()
        upload_index = self.index(wire, lambda row: row['op'] == 4 and row['address'] == self.addresses[1])
        wire[upload_index] = dict(wire[upload_index], data=wire[upload_index]['data'] ^ 1)
        with self.assertRaisesRegex(ValueError, 'Raw upload changed'):
            self.replay(wire)

    def test_descriptor_order_address_amount_and_tag_are_exact(self):
        changes = ('order', 'address', 'amount', 'tag')
        for change in changes:
            with self.subTest(change=change):
                wire = self.valid_wire()
                positions = [self.index(wire, lambda row, a=address: row['op'] == 2 and row['address'] == a)
                             for address in (16, 20, 24)]
                if change == 'order':
                    wire[positions[0]], wire[positions[1]] = wire[positions[1]], wire[positions[0]]
                else:
                    at = positions[{'address': 0, 'amount': 1, 'tag': 2}[change]]
                    wire[at] = dict(wire[at], data=wire[at]['data'] ^ 0x10)
                with self.assertRaisesRegex(ValueError, 'descriptor/order'):
                    self.replay(wire)

    def test_peer_status_during_owned_job_is_rejected(self):
        wire = self.valid_wire('ew')
        start = self.index(wire, lambda row: row['op'] == 2 and row['address'] == 12 and row['data'] == 1)
        wire.insert(start + 1, command(1, 0x108, response=0x10))
        with self.assertRaisesRegex(ValueError, 'Peer status during owned job'):
            self.replay(wire)

    def test_completed_job_cannot_return_to_busy_before_ack(self):
        wire = self.valid_wire()
        first_read = self.index(wire, lambda row: row['op'] == 3)
        wire.insert(first_read, command(1, 8, response=0x40))
        with self.assertRaisesRegex(ValueError, 'completion regressed before ACK'):
            self.replay(wire)

    def test_premature_missing_and_corrupt_result_registers_reject(self):
        good = self.valid_wire()
        first_output = self.index(good, lambda row: row['op'] == 3)
        premature = list(good)
        premature.insert(first_output, premature.pop(self.index(premature,
                          lambda row: row['op'] == 1 and row['address'] == 28)))
        with self.assertRaisesRegex(ValueError, 'Premature|Unexpected result'):
            self.replay(premature)
        missing = list(good)
        missing.pop(self.index(missing, lambda row: row['op'] == 1 and row['address'] == 32))
        with self.assertRaisesRegex(ValueError, 'Premature, incomplete'):
            self.replay(missing)
        corrupt = list(good)
        index = self.index(corrupt, lambda row: row['op'] == 1 and row['address'] == 24 + 4)
        corrupt[index] = dict(corrupt[index], response=TAG ^ 1)
        with self.assertRaisesRegex(ValueError, 'Wrong or duplicate result register'):
            self.replay(corrupt)

    def test_corrupt_partial_and_out_of_order_bo_rows_reject(self):
        wire = self.valid_wire()
        out_index = self.index(wire, lambda row: row['op'] == 3 and row['address'] == self.addresses[1])
        wire[out_index] = dict(wire[out_index], response=wire[out_index]['response'] ^ 1)
        with self.assertRaisesRegex(ValueError, 'changed output readback'):
            self.replay(wire)
        omitted = self.valid_wire()
        omitted.pop(self.index(omitted, lambda row: row['op'] == 4 and row['address'] == self.addresses[-1]))
        with self.assertRaisesRegex(ValueError, 'Wrong raw descriptor/order'):
            self.replay(omitted)
        reordered = self.valid_wire()
        first = self.index(reordered, lambda row: row['op'] == 4)
        reordered[first], reordered[first + 1] = reordered[first + 1], reordered[first]
        with self.assertRaisesRegex(ValueError, 'Raw upload changed'):
            self.replay(reordered)
        short = self.root / 'short-expected.txt'
        self.write_fixture(short, self.after[:-1])
        with self.assertRaisesRegex(ValueError, 'Incomplete or inert BO pair'):
            self.replay(expected=short)
        unsorted = self.root / 'unsorted-upload.txt'
        self.write_fixture(unsorted, self.before[::-1])
        with self.assertRaisesRegex(ValueError, 'Unordered or unmapped BO'):
            self.replay(upload=unsorted)
        malformed = self.root / 'partial-line.txt'
        malformed.write_text('10000000 0000\n')
        with self.assertRaisesRegex(ValueError, 'Malformed raw fixture'):
            self.replay(upload=malformed)

    def test_early_missing_and_duplicate_ack_reject(self):
        good = self.valid_wire()
        ack_index = self.index(good, lambda row: row['op'] == 2 and row['address'] == 12 and row['data'] == 2)
        early = list(good)
        ack = early.pop(ack_index)
        first_readback = self.index(early, lambda row: row['op'] == 3)
        early.insert(first_readback, ack)
        with self.assertRaisesRegex(ValueError, 'ACK before complete'):
            self.replay(early)
        missing = list(good)
        missing.pop(self.index(missing, lambda row: row['op'] == 2 and row['address'] == 12 and row['data'] == 2))
        # Without ACK, the next idle status now violates the stronger sticky
        # completion check before the subsequent peer-status read is reached.
        with self.assertRaisesRegex(ValueError, 'completion regressed before ACK'):
            self.replay(missing)
        duplicate = list(good)
        duplicate.insert(ack_index + 1, ack)
        with self.assertRaisesRegex(ValueError, 'ACK before complete successful BO readback'):
            self.replay(duplicate)

    def test_missing_final_idle_health_rejects(self):
        wire = self.valid_wire()
        ack = self.index(wire, lambda row: row['op'] == 2 and row['address'] == 12 and row['data'] == 2)
        idle = next(i for i, row in enumerate(wire) if i > ack and row['op'] == 1 and
                    row['address'] == 8 and row['response'] == 0x10)
        wire[idle] = dict(wire[idle], response=0x11)
        with self.assertRaisesRegex(ValueError, 'Unexpected idle/staged status'):
            self.replay(wire)

    def test_unmodeled_csr_operation_fault_and_write_failure_reject(self):
        cases = []
        unknown_read = self.valid_wire()
        submit = self.index(unknown_read, lambda row: row['op'] == 2 and row['address'] == 12 and row['data'] == 1)
        unknown_read.insert(submit + 1, command(1, 0x200, response=0))
        cases.append(('unmodeled CSR', unknown_read, 'Unexpected result CSR|premature completion'))
        unknown_op = self.valid_wire()
        unknown_op[0] = dict(unknown_op[0], op=5)
        cases.append(('unmodeled op', unknown_op, 'Unknown operation'))
        failed_write = self.valid_wire()
        up = self.index(failed_write, lambda row: row['op'] == 4)
        failed_write[up] = dict(failed_write[up], response=1)
        cases.append(('failed write', failed_write, 'Unknown operation or failed write'))
        fault_status = self.valid_wire()
        busy = self.index(fault_status, lambda row: row['op'] == 1 and row['address'] == 8 and row['response'] == 0x40)
        fault_status[busy] = dict(fault_status[busy], response=0x80)
        cases.append(('unknown/fault status', fault_status, 'Status before identity or faulted/unknown status'))
        reset = self.valid_wire()
        reset.insert(len(reset) - 2, command(2, 12, 4))
        cases.append(('reset attempt', reset, 'Unexpected raw CSR write/reset attempt'))
        for label, wire, message in cases:
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, message):
                self.replay(wire)


if __name__ == '__main__':
    unittest.main(verbosity=2)
