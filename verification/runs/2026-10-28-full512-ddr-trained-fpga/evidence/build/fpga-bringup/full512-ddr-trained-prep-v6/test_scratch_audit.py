"""Adversarial saved-wire lifecycle checks; no transport or hardware."""
from pathlib import Path
import copy
import importlib.util
import unittest

spec = importlib.util.spec_from_file_location('private_scratch_audit',
    Path(__file__).with_name('audit_scratch.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
from tools.ddr.raw_test import scratch


def command(op, address, response, data=0):
    return dict(op=op, address=address, data=data, response=response)


def valid_wire():
    wire = []
    for base, identity in audit.IDENTITIES.items():
        wire.extend((command(1, base, identity), command(1, base+4, 0x10000),
                     command(1, base+8, 0), command(1, base+8, 16)))
    # Obtain the producer's fixed sequence independently of the audit oracle.
    # This is an in-memory test double; it never opens a transport.
    class RecordedMemory:
        def __init__(self):
            self.memory = {}
            self.rows = []
        def mem_write(self, address, data):
            self.memory[address] = data
            self.rows.append(command(4, address, 0, int.from_bytes(data, 'little')))
        def mem_read(self, address, size):
            data = self.memory[address]
            assert len(data) == size == 64
            self.rows.append(command(3, address, int.from_bytes(data, 'little')))
            return data
    producer = RecordedMemory()
    assert scratch(producer)['checked_bytes'] == 768
    wire.extend(producer.rows)
    wire.extend((command(1, 8, 16), command(1, 0x108, 16)))
    return wire


class ScratchAuditTests(unittest.TestCase):
    def test_both_namespaces_and_full_two_order_scratch(self):
        result = audit.replay(iter(valid_wire()))
        self.assertEqual(result['checked_bytes'], 768)
        self.assertFalse(result['full_capacity_qualified'])

    def test_changed_line_byte_is_rejected(self):
        wire = valid_wire(); wire[14]['response'] ^= 1
        with self.assertRaises(ValueError): audit.replay(wire)

    def test_address_alias_is_rejected(self):
        wire = valid_wire(); wire[15]['address'] = wire[14]['address']
        with self.assertRaises(ValueError): audit.replay(wire)

    def test_read_before_all_writes_is_rejected(self):
        wire = valid_wire(); wire[13], wire[14] = wire[14], wire[13]
        with self.assertRaises(ValueError): audit.replay(wire)

    def test_missing_last_read_is_rejected(self):
        wire = valid_wire(); del wire[-3]
        with self.assertRaises(ValueError): audit.replay(wire)

    def test_both_post_read_status_witnesses_are_required(self):
        for index in (-1, -2):
            wire = valid_wire(); del wire[index]
            with self.subTest(index=index), self.assertRaises(ValueError):
                audit.replay(wire)

    def test_peer_identity_or_abi_is_required_before_memory(self):
        for index in (4, 5):
            wire = valid_wire(); del wire[index]
            with self.subTest(index=index), self.assertRaises(ValueError):
                audit.replay(wire)

    def test_ready_loss_or_fault_after_start_is_rejected(self):
        for status in (0, 2, 4, 8, 32, 64):
            wire = valid_wire(); wire.insert(9, command(1, 8, status))
            with self.subTest(status=status), self.assertRaises(ValueError):
                audit.replay(wire)

    def test_csr_write_or_unknown_read_is_rejected(self):
        for row in (command(2, 12, 0, 1), command(1, 28, 0)):
            wire = valid_wire(); wire.insert(8, row)
            with self.subTest(row=row), self.assertRaises(ValueError):
                audit.replay(wire)

    def test_extra_memory_operation_is_rejected(self):
        wire = valid_wire(); wire.append(copy.deepcopy(wire[-3]))
        with self.assertRaises(ValueError): audit.replay(wire)


if __name__ == '__main__':
    unittest.main()
