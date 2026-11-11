"""Offline controls for tools/host/run_jtag_ew_hardware.py.

No board, cable, lease, socket, hw_server or Vivado is touched: every hardware
path is either refused before any resource is opened or driven through a
pure-Python fake transport. These are software controls, not hardware evidence.
"""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from tools.host import run_jtag_ew_hardware as ew
from tools.host import transport
from tools.host import run_jtag_dual_hardware as dual

NO_NETWORK = 'offline test opened a network connection'
NO_PROCESS = 'offline test launched a real subprocess'


class FakeJobResult:
    def __init__(self, tag, completed_tasks, error_code, status=0x10):
        self.tag = tag
        self.completed_tasks = completed_tasks
        self.error_code = error_code
        self.status = status


class FakeLink:
    def __init__(self):
        self.scans = 0
        self.requests = []


class FakeTransport:
    """Pure-Python stand-in for transport.JtagTransport used by the replay loop."""

    def __init__(self, plan, *, tamper_case=None, tamper_byte=0, silent_negative=False):
        self.memory = {}
        self.acked = []
        self.pending = None
        self.link = FakeLink()
        self.plan = plan
        self.tamper_case = tamper_case
        self.tamper_byte = tamper_byte
        self.silent_negative = silent_negative
        self.poisoned = False
        self.scans_at_negative = None

    def mem_write(self, address, data):
        self.memory[address] = bytearray(data)

    def mem_read(self, address, size):
        if self.poisoned:
            raise transport.ProtocolError('poisoned owner')
        return bytes(self.memory[address][:size])

    def submit(self, address, amount, tag):
        self.pending = {'address': address, 'amount': amount, 'tag': tag}

    def poll_result(self, timeout):
        if self.poisoned:
            raise transport.ProtocolError('poisoned owner')
        tag = self.pending['tag']
        if tag == ew.NEGATIVE_TAG:
            if self.silent_negative:
                return FakeJobResult(tag, 0, 0, 0x10)
            self.poisoned = True
            self.scans_at_negative = self.link.scans
            raise transport.JobError(FakeJobResult(tag, 0, 1, 0x21))
        case = next(case for case in self.plan['cases'] if case['tag'] == tag)
        for region in case['regions']:
            self.memory[region['address']] = bytearray(region['expected'])
        if case['name'] == self.tamper_case and case['regions']:
            self.memory[case['regions'][-1]['address']][self.tamper_byte] ^= 0xFF
        return FakeJobResult(tag, case['tasks'], 0, 0x10)

    def ack_success(self):
        if self.poisoned:
            raise transport.ProtocolError('poisoned owner')
        self.acked.append(self.pending['tag'])
        self.pending = None


class PlanTests(unittest.TestCase):
    def test_production_plan_is_complete_and_exact(self):
        plan = ew.build_plan()
        self.assertEqual(plan['case_count'], 9)
        self.assertEqual(plan['bytes'], 872448)
        names = [case['name'] for case in plan['cases']]
        self.assertEqual(names, ['capture_add_8', 'capture_add_9', 'capture_add_33',
                                 'capture_sub_8', 'capture_sub_9', 'capture_sub_33',
                                 'capture_mul_8', 'capture_mul_9', 'capture_mul_33'])
        tags = [case['tag'] for case in plan['cases']]
        self.assertEqual(len(set(tags)), 9)
        for case in plan['cases']:
            self.assertEqual(case['address'], 0x100E0000)
            self.assertEqual(case['amount'], 35)
            self.assertIn(case['tasks'], (1, 2))
            self.assertGreater(case['bytes'], 4096)
            for region in case['regions']:
                self.assertEqual(region['bytes'], len(region['input']))
                self.assertEqual(region['bytes'], len(region['expected']))
                self.assertEqual(region['input_sha256'],
                                 ew.sha_bytes(region['input']))
                self.assertEqual(region['expected_sha256'],
                                 ew.sha_bytes(region['expected']))

    def test_plan_summary_is_json_safe_and_has_no_raw_bo_bytes(self):
        plan = ew.build_plan()
        summary = ew.plan_summary(plan)
        encoded = json.dumps(summary)
        self.assertIn('capture_sub_9', encoded)
        self.assertNotIn('"input":', encoded)
        self.assertNotIn('"expected":', encoded)
        self.assertEqual(summary['case_count'], 9)
        self.assertEqual(summary['bytes'], 872448)

    def test_negative_plan_patches_only_the_first_qword(self):
        negative = ew.build_negative_plan()
        self.assertEqual(negative['name'], 'synthetic_unknown_register')
        self.assertEqual(negative['case'], 'capture_sub_9')
        self.assertEqual(negative['expected_error_code'], 1)
        self.assertEqual(negative['expected_completed_tasks'], 0)
        self.assertEqual(negative['tag'], ew.NEGATIVE_TAG)
        original = ew.build_plan()
        case = next(case for case in original['cases']
                    if case['name'] == negative['case'])
        for region in case['regions']:
            patched = negative['regions'][region['address']]
            if region['address'] == negative['address']:
                self.assertNotEqual(patched, region['input'])
                self.assertEqual(patched[8:], region['input'][8:])
                self.assertEqual(patched[:8],
                                 bytes.fromhex(negative['changed_bytes']['replacement_hex']))
            else:
                self.assertEqual(patched, region['input'])


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='ew-replay-')
        self.root = Path(self._tmp.name)
        self.plan = ew.build_plan()
        self.negative = ew.build_negative_plan()

    def tearDown(self):
        self._tmp.cleanup()

    def test_positive_replay_reads_complete_bos_before_ack(self):
        fake = FakeTransport(self.plan)
        result = ew.replay_positive(fake, self.plan, self.root / 'cases')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['bytes_checked'], 872448)
        self.assertEqual(fake.acked, [case['tag'] for case in self.plan['cases']])
        self.assertEqual(len(result['cases']), 9)
        for item in result['cases']:
            receipt = json.loads((self.root / 'cases' / item['receipt']).read_text())
            self.assertEqual(receipt['status'], 'PASS')
            self.assertTrue(receipt['ack_after_complete_readback'])
            self.assertTrue(all(region['matches'] for region in receipt['regions']))
            self.assertEqual(receipt['bytes_checked'], item['bytes_checked'])

    def test_positive_replay_refuses_to_ack_on_any_byte_mismatch(self):
        fake = FakeTransport(self.plan, tamper_case='capture_sub_8', tamper_byte=17)
        with self.assertRaises(ew.ModeFailure):
            ew.replay_positive(fake, self.plan, self.root / 'cases')
        # ACKs only the cases that completed before the mismatch; the tampered one is not ACKed.
        self.assertEqual(fake.acked,
                         [case['tag'] for case in self.plan['cases'][:3]])
        receipt = json.loads((self.root / 'cases' / 'capture_sub_8.json').read_text())
        self.assertEqual(receipt['status'], 'FAIL')
        self.assertIn('complete BO mismatch', receipt['failure'])
        self.assertNotIn('ack_after_complete_readback', receipt)

    def test_negative_control_expects_e1_and_poisoned_owner(self):
        fake = FakeTransport(self.plan)
        result = ew.replay_negative(fake, self.negative, self.root / 'negative')
        self.assertEqual(result['status'], 'PASS_EXPECTED_E1_AND_POISONED_OWNER')
        self.assertEqual(result['completion']['error_code'], 1)
        self.assertEqual(result['completion']['completed_tasks'], 0)
        self.assertNotIn(ew.NEGATIVE_TAG, fake.acked)
        receipt = json.loads((self.root / 'negative' / 'synthetic_unknown_register.json').read_text())
        self.assertEqual(receipt['status'], 'PASS_EXPECTED_E1_AND_POISONED_OWNER')
        self.assertFalse(receipt['ack_sent'])

    def test_negative_control_fails_if_unknown_register_is_silently_accepted(self):
        fake = FakeTransport(self.plan, silent_negative=True)
        with self.assertRaises(ew.ModeFailure):
            ew.replay_negative(fake, self.negative, self.root / 'negative')
        receipt = json.loads((self.root / 'negative' / 'synthetic_unknown_register.json').read_text())
        self.assertEqual(receipt['status'], 'FAIL')
        self.assertIn('silently accepted', receipt['failure'])


class OfflineCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bitstream = ROOT / 'build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit'
        cls.package = ROOT / 'build/host-jtag-preparation/20261109T210015Z'
        if not cls.bitstream.is_file() or not cls.package.is_dir():
            raise unittest.SkipTest('EW emitted artifact/package is not present in this workspace')
        cls.target = ew.DEFAULT_TARGET
        cls.lease = '/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='ew-cli-')
        self.root = Path(self._tmp.name)
        self.lease_tmp = self.root / 'ypcb-jtag.lock'

    def tearDown(self):
        self._tmp.cleanup()

    def base_args(self, out, *extra):
        return ['--image', ew.EW_IMAGE_SHA, '--source-tag', ew.EW_USR_ACCESS,
                '--target', self.target, '--lease', str(self.lease_tmp),
                '--out', str(out), '--ew-package', str(self.package), *extra]

    def test_check_is_offline_and_reports_pending_admission(self):
        out = self.root / 'check'
        with mock.patch('socket.create_connection', side_effect=AssertionError(NO_NETWORK)), \
                mock.patch('subprocess.run', side_effect=AssertionError(NO_PROCESS)), \
                mock.patch('subprocess.Popen', side_effect=AssertionError(NO_PROCESS)):
            code = ew.main(self.base_args(out, '--check'))
        self.assertEqual(code, 0)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'PASS_CHECK_PENDING_ADMISSION')
        self.assertFalse(receipt['hardware_accessed'])
        self.assertFalse(receipt['network_accessed'])
        self.assertFalse(receipt['lease_acquired'])
        self.assertTrue(receipt['check_only'])
        self.assertFalse(receipt['admission']['ready'])
        self.assertIn('Missing board reviewer', ' '.join(receipt['admission']['blockers']))
        self.assertEqual(receipt['plan']['case_count'], 9)
        self.assertEqual(receipt['plan']['bytes'], 872448)
        self.assertEqual(receipt['negative_plan']['case'], 'capture_sub_9')
        self.assertEqual(receipt['image']['sha256'], ew.EW_IMAGE_SHA)
        self.assertEqual(receipt['source_hashes_before'], receipt['source_hashes_after'])
        self.assertFalse(self.lease_tmp.exists())

    def test_check_rejects_wrong_image_sha(self):
        out = self.root / 'wrong-image'
        args = self.base_args(out, '--check')
        args[args.index(ew.EW_IMAGE_SHA)] = '11' * 32
        code = ew.main(args)
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'CHECK_FAILED')
        self.assertIn('exact EW image SHA-256', receipt['failure'])

    def test_check_rejects_wrong_source_tag(self):
        out = self.root / 'wrong-tag'
        args = self.base_args(out, '--check')
        args[args.index(ew.EW_USR_ACCESS)] = 'deadbeef'
        code = ew.main(args)
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'CHECK_FAILED')
        self.assertIn('--source-tag must be', receipt['failure'])

    def test_hardware_refuses_without_authorized(self):
        out = self.root / 'refused-auth'
        with mock.patch('socket.create_connection', side_effect=AssertionError(NO_NETWORK)), \
                mock.patch('subprocess.run', side_effect=AssertionError(NO_PROCESS)), \
                mock.patch('subprocess.Popen', side_effect=AssertionError(NO_PROCESS)):
            code = ew.main(self.base_args(out))
        self.assertEqual(code, 2)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'REFUSED')
        self.assertIn('--authorized', receipt['failure'])
        self.assertFalse(receipt['hardware_accessed'])
        self.assertFalse(self.lease_tmp.exists())

    def test_hardware_refuses_when_admission_is_pending(self):
        out = self.root / 'refused-admission'
        pending = {'package': str(self.package), 'status': 'SOURCE_INTACT_REVIEW_PENDING',
                   'blockers': ['Missing board reviewer'], 'ready': False,
                   'profile': 'host-jtag-ew-bram', 'vivado_executed': False,
                   'package_exists': True}
        with mock.patch.object(ew, 'admission_record', return_value=pending), \
                mock.patch.object(dual, 'acquire_lease',
                                  side_effect=AssertionError('lease opened before admission')), \
                mock.patch('socket.create_connection', side_effect=AssertionError(NO_NETWORK)), \
                mock.patch('subprocess.run', side_effect=AssertionError(NO_PROCESS)), \
                mock.patch('subprocess.Popen', side_effect=AssertionError(NO_PROCESS)):
            code = ew.main(self.base_args(out, '--authorized'))
        self.assertEqual(code, 2)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'REFUSED')
        self.assertIn('admission is not ready', receipt['failure'])
        self.assertIn('Missing board reviewer', receipt['failure'])
        self.assertFalse(receipt['hardware_accessed'])
        self.assertFalse(self.lease_tmp.exists())

    def test_hardware_refuses_when_cable_is_absent(self):
        out = self.root / 'refused-cable'
        ready = {'package': str(self.package),
                 'status': 'READY_FOR_SEPARATELY_AUTHORIZED_BUILD',
                 'blockers': [], 'ready': True, 'profile': 'host-jtag-ew-bram',
                 'vivado_executed': False, 'package_exists': True}
        with mock.patch.object(ew, 'admission_record', return_value=ready), \
                mock.patch.object(dual, 'acquire_lease', return_value=99), \
                mock.patch.object(dual, 'release_lease', return_value=None), \
                mock.patch.object(dual, 'check_controllers', return_value={}), \
                mock.patch.object(dual, 'check_ports', return_value={'listening': []}), \
                mock.patch.object(dual, 'check_cable',
                                  side_effect=dual.Refusal('Expected exactly one initialized '
                                                           'DLC10 (03fd:0008) on USB; found 0.')), \
                mock.patch('socket.create_connection', side_effect=AssertionError(NO_NETWORK)), \
                mock.patch('subprocess.run', side_effect=AssertionError(NO_PROCESS)), \
                mock.patch('subprocess.Popen', side_effect=AssertionError(NO_PROCESS)):
            code = ew.main(self.base_args(out, '--authorized'))
        self.assertEqual(code, 2)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'REFUSED')
        self.assertIn('03fd:0008', receipt['failure'])
        self.assertFalse(receipt['hardware_accessed'])
        self.assertTrue(receipt['lease_acquired'])


if __name__ == '__main__':
    unittest.main()
