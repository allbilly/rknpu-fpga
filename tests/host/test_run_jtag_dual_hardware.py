"""Offline controls for tools/host/run_jtag_dual_hardware.py.

No board, cable, hw_server, Vivado, network or lease is touched here: every
link is a Python stub and every hardware entry point is asserted not to run.
The central control proves the new USER2 frame writer is wire-identical to
tools/host/transport.JtagTransport._command, which is the frozen OpenTPU
mailbox protocol.
"""
import hashlib
import json
import struct
import sys
import tempfile
import threading
import time
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from tools.host import run_jtag_dual_hardware as hw
from tools.host import transport

MAGIC = transport.MAGIC
IDCODE = transport.IDCODE
_FAIL_NO_NETWORK = 'offline test opened a network connection'
_FAIL_NO_PROCESS = 'offline test launched a subprocess'


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def response(sequence, status=0, payload=0, magic=MAGIC, reserved=0):
    return ((reserved << 568) | (magic << 536) | (sequence << 520) |
            (status << 512) | payload)


class WireLink:
    """Stub raw link: records every scan and answers mailbox frames."""

    def __init__(self, *, payload=0, status=0, stale_first=0, magic=MAGIC,
                 reserved=0, statuses=None):
        self.scans = []
        self.requests = []
        self.sequence = None
        self.payload = payload
        self.status = status
        self.stale_first = stale_first
        self.magic = magic
        self.reserved = reserved
        self.statuses = list(statuses or [])
        self.actual_frequency_hz = 3_000_000
        period = Fraction(1_000_000_000, 3_000_000)
        self.actual_period_ns = period

    def reset(self, *, deadline=None):
        self.scans.append(('RESET', None, None))
        return 0

    def scan(self, value, bits=640, *, ir=False, deadline=None):
        self.scans.append((value, bits, ir))
        if ir:
            return 0x23751093 if value == 0x09 else 0
        if bits == 32:
            return IDCODE
        if bits != 640:
            raise AssertionError('unexpected scan width in offline test')
        if value:
            self.requests.append(((value >> 548) & 0xFF, (value >> 512) & 0xFFFFFFFF, value))
            self.sequence = (value >> 556) & 0xFFFF
            return 0
        sequence = self.sequence if self.sequence is not None else 0
        status = self.statuses.pop(0) if self.statuses else self.status
        if self.stale_first > 0:
            self.stale_first -= 1
            return response((sequence ^ 0xFFFF) & 0xFFFF, status, self.payload,
                            self.magic, self.reserved)
        return response(sequence, status, self.payload, self.magic, self.reserved)


def bare_transport(link):
    """A JtagTransport without its RKEW constructor, for wire-equality controls."""
    instance = object.__new__(transport.JtagTransport)
    instance.timeout = 5.0
    instance._clock = time.monotonic
    instance._sleep = lambda seconds: None
    instance._mutex = threading.RLock()
    instance._failed = False
    instance._verified = True
    instance._seq = 0
    instance._active_tag = None
    instance._result = None
    instance.link = link
    instance._lock = None
    return instance


class FrameCompatibilityTests(unittest.TestCase):
    """The audited wire format must be byte-identical to transport.py."""

    CASES = [
        (1, 0x00008000, 0),
        (1, 0x0000E000, 0),
        (2, 0x00000010, 0xC0DE4001),
        (2, 0x0000000C, 1),
        (3, 0x00000140, 0),
        (4, 0x00003000, 0x1122334455667788),
    ]

    def test_frames_and_payloads_match_transport(self):
        for opcode, address, data in self.CASES:
            with self.subTest(opcode=opcode, address=address):
                left = WireLink(payload=0x12345678 if opcode == 1 else 0)
                reference = bare_transport(left)
                expected = reference._command(opcode, address, data)
                right = WireLink(payload=0x12345678 if opcode == 1 else 0)
                session = hw.MailboxSession(right, timeout=5.0)
                session._verified = True
                observed = session.command(opcode, address, data)
                self.assertEqual(left.scans, right.scans,
                                 '640-bit frame stream differs from transport.py')
                self.assertEqual(left.requests, right.requests)
                self.assertEqual(expected, observed)
                self.assertEqual([item[0] for item in right.requests], [item[0] for item in left.requests])

    def test_sequence_wrap_and_polling_match_transport(self):
        for start in (1, 0xFFFF, 0xFFFE):
            with self.subTest(start=start):
                left = WireLink(stale_first=2)
                reference = bare_transport(left)
                reference._seq = start
                expected = reference._command(1, 0x00008000)
                right = WireLink(stale_first=2)
                session = hw.MailboxSession(right, timeout=5.0)
                session._seq = start
                observed = session.command(1, 0x00008000)
                self.assertEqual(left.scans, right.scans)
                self.assertEqual(expected, observed)
                self.assertEqual(session._seq, reference._seq)

    def test_frame_layout_constants(self):
        session = hw.MailboxSession(WireLink(), timeout=5.0)
        session._verified = True
        session.command(2, 0x00000018, 0xC0DE4001)
        frame = session.link.requests[-1][2]
        self.assertEqual((frame >> 572) & 0xFFFFFFFF, 0x4F54504A)
        self.assertEqual((frame >> 548) & 0xFF, 2)
        self.assertEqual((frame >> 544) & 0xF, 0xF)
        self.assertEqual((frame >> 512) & 0xFFFFFFFF, 0x18)
        self.assertEqual(frame & ((1 << 512) - 1), 0xC0DE4001)
        self.assertEqual((frame >> 556) & 0xFFFF, 1)
        self.assertEqual(frame >> 604, 0)


class SessionRulesTests(unittest.TestCase):
    def session(self, **link_kwargs):
        link = WireLink(**link_kwargs)
        session = hw.MailboxSession(link, timeout=5.0)
        session._verified = True
        return session, link

    def test_writes_require_page_identity_verification(self):
        session, link = self.session()
        session._verified = False
        with self.assertRaises(transport.ProtocolError):
            session.command(2, 0x00008010, 0)
        self.assertEqual(link.requests, [])
        session._verified = True
        session.command(2, 0x00008010, 0)

    def test_expected_alignment_error_does_not_poison(self):
        session, link = self.session(status=4)
        self.assertEqual(session.command(3, 0x122, expected_status=4), 0)
        self.assertFalse(session.failed)
        self.assertFalse(session.quarantined)
        session.link.status = 0
        session.command(1, 0x00008000)

    def test_expected_downstream_error_quarantines(self):
        session, link = self.session(status=7)
        self.assertEqual(session.command(1, 0xE000, expected_status=7), 0)
        self.assertTrue(session.quarantined)
        self.assertFalse(session.failed)
        scans = len(link.scans)
        with self.assertRaises(transport.ProtocolError):
            session.command(1, 0x00008000)
        self.assertEqual(len(link.scans), scans, 'quarantined owner issued another scan')

    def test_unexpected_downstream_error_poisons(self):
        session, link = self.session(status=7)
        with self.assertRaises(transport.MailboxError) as caught:
            session.command(1, 0x00008000)
        self.assertEqual(caught.exception.status, 7)
        self.assertTrue(session.failed)
        self.assertTrue(session.quarantined)
        with self.assertRaises(transport.ProtocolError):
            session.command(1, 0x00008000)

    def test_unexpected_alignment_error_poisons(self):
        session, _ = self.session(status=4)
        with self.assertRaises(transport.MailboxError):
            session.command(1, 0x00008000)
        self.assertTrue(session.failed)

    def test_bad_magic_is_rejected(self):
        session, _ = self.session(magic=0xDEADBEEF)
        with self.assertRaises(transport.ProtocolError):
            session.command(1, 0x00008000)

    def test_reserved_response_bits_are_rejected(self):
        session, _ = self.session(reserved=1)
        with self.assertRaises(transport.ProtocolError):
            session.command(1, 0x00008000)

    def test_register_read_payload_above_32_bits_is_rejected(self):
        session, _ = self.session(payload=1 << 32)
        with self.assertRaises(transport.ProtocolError):
            session.command(1, 0x00008000)

    def test_write_response_payload_is_rejected(self):
        session, _ = self.session(payload=1)
        with self.assertRaises(transport.ProtocolError):
            session.command(2, 0x00008010, 0)

    def test_read_opcodes_must_carry_zero_data(self):
        session, _ = self.session()
        with self.assertRaises(ValueError):
            session.command(1, 0x00008000, 1)
        with self.assertRaises(ValueError):
            session.command(3, 0x00008000, 1)

    def test_attach_verifies_idcode_and_mailbox_magic(self):
        session = hw.MailboxSession(WireLink(), timeout=5.0)
        identity = session.attach()
        self.assertEqual(identity['idcode'], '23751093')
        self.assertTrue(session.attached)
        bad = WireLink(magic=0xDEADBEEF)
        with self.assertRaises(transport.ProtocolError):
            hw.MailboxSession(bad, timeout=5.0).attach()

    def test_bo_helpers_require_alignment_and_whole_blocks(self):
        session, _ = self.session()
        with self.assertRaises(ValueError):
            session.write_bo(0x40 + 64 + 1, [0])
        with self.assertRaises(ValueError):
            session.read_bo(0x2000, 1023)


class CompareTests(unittest.TestCase):
    def words(self, values):
        return struct.pack(f'<{len(values)}I', *values)

    def test_byte_exact(self):
        observed = self.words([1, 2, 3, 4])
        result = hw.compare_output(observed, observed, 4, 0.0)
        self.assertTrue(result['passed'])
        self.assertEqual(result['differing_words'], 0)

    def test_byte_mismatch_fails_without_tolerance(self):
        expected = self.words([1, 2, 3, 4])
        observed = self.words([1, 2, 3, 5])
        result = hw.compare_output(observed, expected, 4, 0.0)
        self.assertFalse(result['passed'])
        self.assertEqual(result['first_mismatch']['word'], 3)

    def test_absolute_tolerance_accepts_small_difference(self):
        one = 0x3F800000  # 1.0
        near = 0x3F800001  # 1.0000001
        result = hw.compare_output(self.words([near]), self.words([one]), 1, 0.001)
        self.assertTrue(result['passed'])
        result = hw.compare_output(self.words([near]), self.words([one]), 1, 0.0)
        self.assertFalse(result['passed'])

    def test_absolute_tolerance_rejects_large_difference(self):
        one = 0x3F800000
        two = 0x40000000
        result = hw.compare_output(self.words([two]), self.words([one]), 1, 0.1)
        self.assertFalse(result['passed'])

    def test_f32_model_matches_bench_conventions(self):
        self.assertEqual(hw.f32_to_real(0x3F800000), 1.0)
        self.assertEqual(hw.f32_to_real(0x00000000), 0.0)
        self.assertEqual(hw.f32_to_real(0x80000000), 0.0)  # bench treats zero exponent as 0.0


def fake_image(page_names, *, stamp='20261109T000000Z'):
    pages = [{'name': name, 'base': hw.PAGE_MAP[name][0], 'identity': hw.PAGE_MAP[name][1]}
             for name in page_names]
    return {'stamp': stamp, 'top': 'ypcb_jtag_dual_top',
            'part': 'xc7k480tffg1156-2', 'pages': pages,
            'bitstream_sha256': 'ab' * 32, 'source_hashes': {}}


FOUR_PAGES = ['conv_page', 'pool_page', 'gemm_page', 'conv_fp32_page']
SIX_PAGES = FOUR_PAGES + ['conv_k5_page', 'conv_c16_page']


class PlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='jtag-dual-hw-plan-tests-')
        cls.root = Path(cls._tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def plan(self, mode):
        directory = self.root / f'plan-{mode}'
        staged = hw.stage_mode(mode, directory, 'gemm_m2_n2_k1')
        return hw.build_plan(mode, staged, fake_image(SIX_PAGES), 'gemm_m2_n2_k1')

    def test_mode1_conv_plan(self):
        plan = self.plan(1)
        self.assertEqual(plan['page'], 'conv_page')
        self.assertEqual(plan['page_base'], 0x8000)
        self.assertEqual(plan['amount'], 52)
        self.assertEqual(f"{plan['tag']:08x}", 'c0de4001')
        self.assertEqual(len(plan['loads']), 4)
        command = plan['loads'][0]
        self.assertEqual((command['base'], command['words'], command['blocks'],
                          command['zero_pad_words']), (0, 104, 7, 8))
        self.assertEqual(plan['output_base'], 0x3000)
        self.assertEqual(plan['output_words'], 1024)
        self.assertEqual(len(plan['expected_bytes']), 4096)
        self.assertEqual(plan['tolerance_abs'], 0.0)

    def test_mode2_pool_plan(self):
        plan = self.plan(2)
        self.assertEqual(plan['page'], 'pool_page')
        self.assertEqual(plan['amount'], 26)
        self.assertEqual(len(plan['loads']), 3)
        self.assertEqual((plan['loads'][0]['words'], plan['loads'][0]['blocks'],
                          plan['loads'][0]['zero_pad_words']), (52, 4, 12))
        self.assertEqual(plan['output_base'], 0x2000)
        self.assertEqual(len(plan['expected_bytes']), 4096)

    def test_mode3_gemm_plan_uses_frozen_tolerance(self):
        plan = self.plan(3)
        self.assertEqual(plan['page'], 'gemm_page')
        self.assertEqual(plan['amount'], 45)
        self.assertEqual(plan['tolerance_abs'], 0.0)
        staged = hw.stage_mode(3, self.root / 'gemm-tol', 'gemm_m2_n16_k32')
        other = hw.build_plan(3, staged, fake_image(SIX_PAGES), 'gemm_m2_n16_k32')
        self.assertEqual(other['tolerance_abs'], 0.1)

    def test_mode4_fp32_conv_plan(self):
        plan = self.plan(4)
        self.assertEqual(plan['page'], 'conv_fp32_page')
        self.assertEqual(plan['tolerance_abs'], 0.001)
        self.assertEqual(len(plan['expected_bytes']), 4096)

    def test_mode5_and_6_conv_pages(self):
        five = self.plan(5)
        self.assertEqual((five['page'], five['output_base']), ('conv_k5_page', 0x4000))
        self.assertEqual((five['loads'][2]['words'], five['loads'][2]['blocks']), (1600, 100))
        six = self.plan(6)
        self.assertEqual((six['page'], six['output_base']), ('conv_c16_page', 0x5000))
        self.assertEqual((six['loads'][2]['words'], six['loads'][2]['blocks']), (2304, 144))
        self.assertEqual(len(six['expected_bytes']), 4096)

    def test_modes_5_and_6_need_their_pages(self):
        for mode in (5, 6):
            staged = hw.stage_mode(mode, self.root / f'unsupported-{mode}', 'gemm_m2_n2_k1')
            with self.assertRaises(hw.PlanUnsupported):
                hw.build_plan(mode, staged, fake_image(FOUR_PAGES), 'gemm_m2_n2_k1')

    def test_bo_ranges_stay_inside_the_memory_window_and_do_not_overlap(self):
        for mode in range(1, 7):
            plan = self.plan(mode)
            spans = sorted((load['base'], load['base'] + load['blocks'] * 64)
                           for load in plan['loads'])
            self.assertGreaterEqual(spans[0][0], 0)
            self.assertLessEqual(spans[-1][1], 0x8000)
            for previous, following in zip(spans, spans[1:]):
                self.assertLessEqual(previous[1], following[0])

    def test_descriptor_amount_fits_the_command_bo(self):
        for mode in range(1, 7):
            plan = self.plan(mode)
            command = plan['loads'][0]
            self.assertLessEqual(plan['amount'] * 8, command['words'] * 4)


class ImageCatalogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='jtag-dual-image-catalog-')
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_image(self, stamp, pages, *, bit_bytes=b'\x00' * (2 * 1024 * 1024),
                    status='PASS', emitted=True, top='ypcb_jtag_dual_top',
                    part='xc7k480tffg1156-2'):
        directory = self.root / stamp
        (directory / 'implementation').mkdir(parents=True)
        bit = directory / 'implementation/rk_jtag_dual.bit'
        bit.write_bytes(bit_bytes)
        (directory / 'inputs.json').write_text(json.dumps({
            'profile': 'ypcb_jtag_dual', 'status': status, 'bitstream_emitted': emitted,
            'hardware_accessed': False, 'top': top, 'part': part,
            'bitstream': 'rk_jtag_dual.bit',
            'source_hashes': {'tools/host/transport.py': 'deadbeef'},
        }))
        (directory / 'build.tcl').write_text(
            'foreach page {' + ' '.join(pages) + '} {\n    set cells 1\n}\n')
        return directory, hashlib.sha256(bit_bytes).hexdigest()

    def test_emitted_and_rejected_receipts(self):
        directory, digest = self.write_image('20261109T010101Z', FOUR_PAGES)
        self.write_image('20261109T020202Z', FOUR_PAGES, emitted=False)
        self.write_image('20261109T030303Z', SIX_PAGES, status='FAIL')
        self.write_image('20261109T040404Z', ['conv_page'], top='wrong_top')
        emitted, rejected = hw.scan_image_catalog(self.root)
        self.assertEqual([entry['stamp'] for entry in emitted], ['20261109T010101Z'])
        self.assertEqual(emitted[0]['bitstream_sha256'], digest)
        self.assertEqual(emitted[0]['page_names'], FOUR_PAGES)
        self.assertEqual(len(rejected), 3)

    def test_find_emitted_image(self):
        _, digest = self.write_image('20261109T010101Z', FOUR_PAGES)
        image, emitted, _ = hw.find_emitted_image(digest, self.root)
        self.assertEqual(image['stamp'], '20261109T010101Z')
        self.assertEqual(len(emitted), 1)
        with self.assertRaises(hw.Refusal):
            hw.find_emitted_image('00' * 32, self.root)

    def test_page_gate_parser(self):
        path = self.root / 'gate.tcl'
        path.write_text('foreach page {conv_page pool_page} {\n}\n')
        self.assertEqual(hw.parse_page_gate(path), ['conv_page', 'pool_page'])
        path.write_text('foreach page {conv_page mystery_page} {\n}\n')
        with self.assertRaises(ValueError):
            hw.parse_page_gate(path)
        path.write_text('no gate here\n')
        with self.assertRaises(ValueError):
            hw.parse_page_gate(path)

    def test_source_freshness(self):
        image = fake_image(FOUR_PAGES)
        image['source_hashes'] = {
            'tools/host/transport.py': hw.sha_file(ROOT / 'tools/host/transport.py'),
            'tools/host/does-not-exist.py': '00',
            'README.md': '00',
        }
        freshness = hw.source_freshness(image)
        self.assertEqual(freshness['matched'], 1)
        self.assertEqual(freshness['changed_count'], 1)
        self.assertEqual(freshness['missing_count'], 1)
        self.assertFalse(freshness['current_tree_matches_image_sources'])


class CliOfflineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='jtag-dual-hw-cli-')
        self.root = Path(self._tmp.name)
        self.catalog = self.root / 'catalog'
        directory = self.catalog / '20261109T010101Z'
        (directory / 'implementation').mkdir(parents=True)
        self.bit_bytes = b'\x01' * (2 * 1024 * 1024)
        (directory / 'implementation/rk_jtag_dual.bit').write_bytes(self.bit_bytes)
        (directory / 'inputs.json').write_text(json.dumps({
            'profile': 'ypcb_jtag_dual', 'status': 'PASS', 'bitstream_emitted': True,
            'hardware_accessed': False, 'top': 'ypcb_jtag_dual_top',
            'part': 'xc7k480tffg1156-2', 'bitstream': 'rk_jtag_dual.bit',
            'source_hashes': {},
        }))
        (directory / 'build.tcl').write_text(
            'foreach page {conv_page pool_page gemm_page conv_fp32_page} {\n}\n')
        self.image_sha = hashlib.sha256(self.bit_bytes).hexdigest()
        self.lease = self.root / 'ypcb-jtag.lock'
        self.target = hw.DEFAULT_TARGET

    def tearDown(self):
        self._tmp.cleanup()

    def check_args(self, out, *extra):
        return ['--check', '--image', self.image_sha, '--target', self.target,
                '--lease', str(self.lease), '--out', str(out),
                '--catalog-root', str(self.catalog), *extra]

    def test_check_is_offline_and_passes(self):
        out = self.root / 'check-out'
        with mock.patch('socket.create_connection', side_effect=AssertionError(_FAIL_NO_NETWORK)), \
                mock.patch('subprocess.run', side_effect=AssertionError(_FAIL_NO_PROCESS)), \
                mock.patch('subprocess.Popen', side_effect=AssertionError(_FAIL_NO_PROCESS)):
            code = hw.main(self.check_args(out, '--mode', '1', '--mode', '2', '--mode', '3',
                                          '--mode', '4'))
        self.assertEqual(code, 0)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'PASS_CHECK')
        self.assertFalse(receipt['hardware_accessed'])
        self.assertFalse(receipt['network_accessed'])
        self.assertFalse(receipt['lease_acquired'])
        self.assertTrue(receipt['check_only'])
        self.assertEqual(receipt['modes'], [1, 2, 3, 4])
        self.assertEqual(receipt['image']['bitstream_sha256'], self.image_sha)
        self.assertEqual(receipt['image']['page_names'], FOUR_PAGES)
        self.assertFalse(receipt['blockers'])
        self.assertEqual(sorted(receipt['plans']), ['1', '2', '3', '4'])
        self.assertFalse(self.lease.exists(), '--check created/opened the lease file')
        self.assertEqual(receipt['source_hashes_before'], receipt['source_hashes_after'])

    def test_check_blocks_modes_without_pages(self):
        out = self.root / 'check-blocked'
        with (mock.patch('socket.create_connection', side_effect=AssertionError),
              mock.patch('subprocess.run', side_effect=AssertionError)):
            code = hw.main(self.check_args(out))
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'CHECK_BLOCKED')
        self.assertEqual(len(receipt['blockers']), 2)
        self.assertIn('conv_k5_page', receipt['blockers'][0])
        self.assertIn('conv_c16_page', receipt['blockers'][1])
        self.assertEqual(sorted(receipt['plans']), ['0', '1', '2', '3', '4'])

    def test_check_rejects_unknown_image_sha(self):
        out = self.root / 'check-unknown'
        args = self.check_args(out, '--mode', '1')
        args[args.index(self.image_sha)] = '11' * 32
        with mock.patch('socket.create_connection', side_effect=AssertionError):
            code = hw.main(args)
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'CHECK_FAILED')
        self.assertIn('does not name exactly one real emitted bitstream', receipt['failure'])

    def test_hardware_refuses_without_authorized(self):
        out = self.root / 'hardware-refused'
        args = ['--image', self.image_sha, '--target', self.target,
                '--lease', str(self.lease), '--source-tag', 'none',
                '--out', str(out), '--catalog-root', str(self.catalog), '--mode', '1']
        with mock.patch('socket.create_connection', side_effect=AssertionError(_FAIL_NO_NETWORK)), \
                mock.patch('subprocess.run', side_effect=AssertionError(_FAIL_NO_PROCESS)), \
                mock.patch('subprocess.Popen', side_effect=AssertionError(_FAIL_NO_PROCESS)):
            code = hw.main(args)
        self.assertEqual(code, 2)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'REFUSED')
        self.assertFalse(receipt['hardware_accessed'])
        self.assertFalse(receipt['lease_acquired'])
        self.assertIn('--authorized', receipt['failure'])
        self.assertFalse(self.lease.exists())

    def test_hardware_argument_validation_is_offline(self):
        cases = [
            (['--target', '10.0.0.1:3125/xilinx_tcf/Xilinx/80802026a77a01'], 'local'),
            (['--source-tag', 'zzz'], '--source-tag'),
            (['--lease', str(self.root / 'missing-dir/lock')], 'parent'),
        ]
        for index, (override, expected) in enumerate(cases):
            out = self.root / f'validation-{index}'
            args = ['--authorized', '--image', self.image_sha, '--target', self.target,
                    '--lease', str(self.lease), '--source-tag', 'none',
                    '--out', str(out), '--catalog-root', str(self.catalog), '--mode', '1']
            for token, value in zip(override[::2], override[1::2]):
                if token == '--lease':
                    args[args.index('--lease') + 1] = value
                elif token == '--target':
                    args[args.index('--target') + 1] = value
                else:
                    args[args.index('--source-tag') + 1] = value
            with mock.patch('socket.create_connection', side_effect=AssertionError(_FAIL_NO_NETWORK)), \
                    mock.patch('subprocess.run', side_effect=AssertionError(_FAIL_NO_PROCESS)), \
                    mock.patch('subprocess.Popen', side_effect=AssertionError(_FAIL_NO_PROCESS)):
                code = hw.main(args)
            self.assertEqual(code, 1, (override, expected))
            receipt = json.loads((out / 'receipt.json').read_text())
            self.assertEqual(receipt['status'], 'FAIL')
            self.assertFalse(receipt['hardware_accessed'])
            self.assertFalse(self.lease.exists())


class FakeNativeLink:
    """Minimal in-process USER2 + dual-endpoint image for orchestration tests.

    It implements the frozen frame codec (opcodes 1..4, 64-bit-block rules and
    the bridge's status/quarantine policy) over a 32 KiB memory window and the
    four page register files of the emitted four-page image. It is a transport
    flow model, not an RTL/numeric model: on submit it places preloaded expected
    output bytes so the harness's own compare/ACK logic is what is under test.
    """

    def __init__(self, pages, job_outputs=None):
        self.memory = bytearray(0x8000)
        self.pages = {}
        for name in pages:
            base = hw.PAGE_MAP[name][0]
            self.pages[base] = {'identity': hw.PAGE_MAP[name][1], 'fields': 0,
                                'command': 0, 'amount': 0, 'tag': 0, 'result_valid': False,
                                'result_error': False, 'result_tag': 0, 'result_tasks': 0,
                                'result_code': 0, 'active': False}
        self.job_outputs = dict(job_outputs or {})
        self.fault = False
        self.ir = None
        self.pending = (MAGIC << 536)
        self.requests = []
        self.actual_frequency_hz = 3_000_000
        self.actual_period_ns = Fraction(1000, 3)
        self.quit_ack = False
        self.closed = False

    # NativeLink-shaped surface -------------------------------------------
    def reset(self, *, deadline=None):
        self.ir = None

    def scan(self, value, bits=640, *, ir=False, deadline=None):
        if ir:
            self.ir = value
            return 0
        if bits == 32:
            return IDCODE
        if bits != 640:
            raise AssertionError('unexpected scan width in fake native link')
        if value == 0:
            return self.pending
        magic = (value >> 572) & 0xFFFFFFFF
        opcode = (value >> 548) & 0xFF
        address = (value >> 512) & 0xFFFFFFFF
        data = value & ((1 << 512) - 1)
        sequence = (value >> 556) & 0xFFFF
        self.requests.append((opcode, address, data, sequence))
        status, payload = self.execute(magic, opcode, address, data)
        self.pending = (magic << 536) | (sequence << 520) | (status << 512) | payload
        return 0

    def shutdown_bridge(self):
        self.quit_ack = True
        self.closed = True
        return 0

    def close(self):
        self.closed = True

    # Fake image -----------------------------------------------------------
    def page_status(self, page):
        fields = page['fields']
        writable = (not page['active'] and not page['result_valid'])
        status = 0
        status |= 1 << 4  # memory_ready
        status |= fields << 8
        if page['active']:
            status |= 1 << 1
        if page['result_valid']:
            status |= 1 << 2
        if page['result_error']:
            status |= 1 << 3
        if writable and fields == 0b111:
            status |= 1
        return status

    def read_page(self, page, offset):
        if offset == 0x00:
            return 0, page['identity']
        if offset == 0x04:
            return 0, hw.ABI_VERSION
        if offset == 0x08:
            return 0, self.page_status(page)
        if offset in (0x10, 0x14, 0x18):
            return 0, page[{0x10: 'command', 0x14: 'amount', 0x18: 'tag'}[offset]]
        if offset == 0x1C:
            return 0, page['result_tag']
        if offset == 0x20:
            return 0, page['result_tasks']
        if offset == 0x24:
            return 0, page['result_code']
        self.fault = True
        return hw.ST_DOWNSTREAM, 0

    def write_page(self, page, offset, value):
        writable = (not page['active'] and not page['result_valid'])
        if offset == 0x0C:
            if value == 1 and self.page_status(page) & 1:
                page['active'] = True
                output = self.job_outputs.get(page['identity'])
                if output is not None:
                    base, raw = output
                    self.memory[base:base + len(raw)] = raw
                page['result_valid'] = True
                page['result_tag'] = page['tag']
                page['result_tasks'] = 1
                page['result_code'] = 0
                page['active'] = False
                return 0, 0
            if value == 2 and page['result_valid'] and not page['result_error']:
                page['result_valid'] = False
                page['fields'] = 0
                return 0, 0
            self.fault = True
            return hw.ST_DOWNSTREAM, 0
        field = {0x10: ('command', 1), 0x14: ('amount', 2), 0x18: ('tag', 4)}
        if offset in field and writable:
            name, bit = field[offset]
            page[name] = value & 0xFFFFFFFF
            page['fields'] |= bit
            return 0, 0
        self.fault = True
        return hw.ST_DOWNSTREAM, 0

    def execute(self, magic, opcode, address, data):
        if magic != MAGIC:
            return hw.ST_FRAME, 0
        if opcode not in (1, 2, 3, 4):
            return hw.ST_FRAME, 0
        if opcode in (3, 4) and address % 64:
            return hw.ST_ALIGN, 0
        if opcode in (1, 2) and address % 4:
            return hw.ST_ALIGN, 0
        if self.fault:
            return hw.ST_DOWNSTREAM, 0
        if address < hw.MEMORY_END:
            if opcode == 1:
                return 0, struct.unpack_from('<I', self.memory, address)[0]
            if opcode == 2:
                struct.pack_into('<I', self.memory, address, data & 0xFFFFFFFF)
                return 0, 0
            if opcode == 3:
                return 0, int.from_bytes(self.memory[address:address + 64], 'little')
            if opcode == 4:
                self.memory[address:address + 64] = data.to_bytes(64, 'little')
                return 0, 0
        base = address & ~0xFFF
        if base in self.pages:
            offset = address & 0xFFF
            if opcode == 1:
                return self.read_page(self.pages[base], offset)
            if opcode == 2:
                return self.write_page(self.pages[base], offset, data & 0xFFFFFFFF)
            self.fault = True
            return hw.ST_DOWNSTREAM, 0
        self.fault = True
        return hw.ST_DOWNSTREAM, 0


class FakeProcess:
    def __init__(self, returncode=0):
        self.pid = 4242
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


class FakeBridgeContextTests(unittest.TestCase):
    """Full hardware orchestration against an in-process fake image (no board)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='jtag-dual-hw-fake-run-')
        self.root = Path(self._tmp.name)
        self.catalog = self.root / 'catalog'
        directory = self.catalog / '20261109T010101Z'
        (directory / 'implementation').mkdir(parents=True)
        bit_bytes = b'\x02' * (2 * 1024 * 1024)
        (directory / 'implementation/rk_jtag_dual.bit').write_bytes(bit_bytes)
        (directory / 'inputs.json').write_text(json.dumps({
            'profile': 'ypcb_jtag_dual', 'status': 'PASS', 'bitstream_emitted': True,
            'hardware_accessed': False, 'top': 'ypcb_jtag_dual_top',
            'part': 'xc7k480tffg1156-2', 'bitstream': 'rk_jtag_dual.bit',
            'source_hashes': {},
        }))
        (directory / 'build.tcl').write_text(
            'foreach page {conv_page pool_page gemm_page conv_fp32_page} {\n}\n')
        self.image_sha = hashlib.sha256(bit_bytes).hexdigest()
        self.lease = self.root / 'ypcb-jtag.lock'
        # The fake device emits the same expected bytes the mode-1 plan compares.
        staged = hw.stage_mode(1, self.root / 'expected', 'gemm_m2_n2_k1')
        plan = hw.build_plan(1, staged, fake_image(FOUR_PAGES), 'gemm_m2_n2_k1')
        self.expected_bytes = plan['expected_bytes']

    def tearDown(self):
        self._tmp.cleanup()

    def fake_bridge(self, args, target, image, source_tag, out):
        link = FakeNativeLink(FOUR_PAGES,
                              job_outputs={0x524B4353: (0x3000, self.expected_bytes)})
        bridge_dir = Path(out) / 'bridge'
        bridge_dir.mkdir(parents=True, exist_ok=True)
        (bridge_dir / 'bridge-stdout.log').write_text(
            'PASS_AUDITED_NATIVE_USER2_BRIDGE_READY\nPASS_NATIVE_USER2_BRIDGE_CLEAN_EXIT\n')
        (bridge_dir / 'hw-server.log').write_text('owned fake server\n')
        record = {'argv_hw_server': ['fake-hw-server'], 'argv_vivado': ['fake-vivado'],
                  'tcl_sha256': '00', 'ready_marker': 'PASS_AUDITED_NATIVE_USER2_BRIDGE_READY',
                  'hw_server_pid': 4242, 'bridge_pid': 4243, 'native_link': {},
                  'cleanup': {}}
        return {'record': record, 'tools': {'python': '3.14.5'}, 'link': link,
                'server_proc': FakeProcess(), 'bridge_proc': FakeProcess(),
                'bridge_dir': bridge_dir, 'ready_path': bridge_dir / 'ready.txt'}

    def run_hardware(self, *modes):
        out = self.root / 'run-out'
        argv = ['--authorized', '--image', self.image_sha, '--target', hw.DEFAULT_TARGET,
                '--lease', str(self.lease), '--source-tag', 'none',
                '--out', str(out), '--catalog-root', str(self.catalog),
                '--authorization-note', 'offline orchestration control',
                *[item for mode in modes for item in ('--mode', str(mode))]]
        with mock.patch.object(hw, 'check_controllers', return_value={}), \
                mock.patch.object(hw, 'check_ports', return_value={'listening': []}), \
                mock.patch.object(hw, 'check_cable', return_value={'lsusb': 'fake'}), \
                mock.patch.object(hw, 'run_bridge_hardware', side_effect=self.fake_bridge):
            code = hw.main(argv)
        return code, out

    def test_modes_run_to_pass_and_clean_up(self):
        code, out = self.run_hardware(1, 0)
        self.assertEqual(code, 0)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'PASS')
        self.assertTrue(receipt['hardware_accessed'])
        self.assertTrue(receipt['authorized'])
        self.assertFalse(receipt['fabric_programmed'])
        self.assertFalse(receipt['fabric_reset'])
        self.assertFalse(receipt['configuration_written'])
        self.assertFalse(receipt['flash_written'])
        self.assertFalse(receipt['image_loaded_by_this_tool'])
        self.assertTrue(receipt['lease_acquired'])
        self.assertTrue(receipt['lease_released'])
        self.assertEqual(receipt['modes'], [1, 0])
        self.assertTrue(receipt['cleanup']['bridge_quit_ack'])
        self.assertEqual(receipt['cleanup']['owned_hw_server_exit'], 0)
        mode1 = json.loads((out / 'mode-1.json').read_text())
        self.assertEqual(mode1['status'], 'PASS')
        self.assertTrue(mode1['compare']['passed'])
        self.assertEqual(mode1['compare']['words'], 1024)
        self.assertEqual(mode1['compare']['differing_words'], 0)
        self.assertEqual(mode1['result']['tag'], 'c0de4001')
        self.assertTrue(mode1['ack']['completion_cleared'])
        self.assertTrue(all(entry['readback_matches'] for entry in mode1['loads']))
        mode0 = json.loads((out / 'mode-0.json').read_text())
        self.assertTrue(mode0['quarantine_observed'])
        self.assertEqual(mode0['negative_checks']['misaligned_block']['status'], 4)
        self.assertEqual(mode0['negative_checks']['unmapped_read']['status'], 7)
        self.assertTrue(mode0['round_trips']['word']['passed'])
        self.assertTrue(mode0['round_trips']['block']['passed'])
        self.assertTrue((out / 'mode-1-ops.jsonl').is_file())
        ops = [json.loads(line) for line in (out / 'mode-1-ops.jsonl').read_text().splitlines()]
        self.assertTrue(ops)
        self.assertTrue(all(set(('opcode', 'address', 'status', 'polls')) <= set(op) for op in ops))
        self.assertIn('PASS YPCB_JTAG_DUAL_HARDWARE mode=1', mode1['pass_marker'])

    def test_failed_compare_preserves_evidence_and_skips_ack(self):
        out = self.root / 'run-bad'
        staged = hw.stage_mode(1, self.root / 'bad-expected', 'gemm_m2_n2_k1')
        wrong = bytearray(self.expected_bytes)
        wrong[0] ^= 0xFF
        link = FakeNativeLink(FOUR_PAGES,
                              job_outputs={0x524B4353: (0x3000, bytes(wrong))})

        def bad_bridge(args, target, image, source_tag, out_dir):
            context = self.fake_bridge(args, target, image, source_tag, out_dir)
            context['link'] = link
            return context

        argv = ['--authorized', '--image', self.image_sha, '--target', hw.DEFAULT_TARGET,
                '--lease', str(self.lease), '--source-tag', 'none',
                '--out', str(out), '--catalog-root', str(self.catalog), '--mode', '1']
        with mock.patch.object(hw, 'check_controllers', return_value={}), \
                mock.patch.object(hw, 'check_ports', return_value={'listening': []}), \
                mock.patch.object(hw, 'check_cable', return_value={'lsusb': 'fake'}), \
                mock.patch.object(hw, 'run_bridge_hardware', side_effect=bad_bridge):
            code = hw.main(argv)
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'FAIL')
        mode1 = json.loads((out / 'mode-1.json').read_text())
        self.assertEqual(mode1['status'], 'FAIL')
        self.assertFalse(mode1['compare']['passed'])
        self.assertEqual(mode1['compare']['differing_words'], 1)
        self.assertNotIn('ack', mode1)


SIX_PAGE_NAMES = FOUR_PAGES + ['conv_k5_page', 'conv_c16_page']


class SixPageCatalogControls(unittest.TestCase):
    """SYNTHETIC software controls, not hardware evidence.

    These prove that the page-gate-driven catalog admits any future six-page
    PASS receipt of the ypcb_jtag_dual profile for modes 0-6, and that the same
    refusals survive: FAIL receipt, no emitted bitstream, hash mismatch, missing
    conv_k5_page/conv_c16_page, wrong target/part. The bitstreams here are
    fabricated fixtures under tests/ only; they are never cited as board
    evidence. No socket or subprocess may be opened by these controls.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='jtag-dual-sixpage-')
        self.root = Path(self._tmp.name)
        self.catalog = self.root / 'catalog'
        self.lease = self.root / 'ypcb-jtag.lock'

    def tearDown(self):
        self._tmp.cleanup()

    def write_image(self, stamp='20261110T000000Z', pages=None, *,
                    bit_bytes=b'\x03' * (2 * 1024 * 1024), status='PASS',
                    emitted=True, top='ypcb_jtag_dual_top',
                    part='xc7k480tffg1156-2', bitstream='rk_jtag_dual.bit'):
        directory = self.catalog / stamp
        (directory / 'implementation').mkdir(parents=True, exist_ok=True)
        bit = directory / 'implementation/rk_jtag_dual.bit'
        bit.write_bytes(bit_bytes) if bit_bytes is not None else None
        (directory / 'inputs.json').write_text(json.dumps({
            'profile': 'ypcb_jtag_dual', 'status': status, 'bitstream_emitted': emitted,
            'hardware_accessed': False, 'top': top, 'part': part,
            'bitstream': bitstream, 'source_hashes': {},
        }))
        (directory / 'build.tcl').write_text(
            'foreach page {' + ' '.join(pages or SIX_PAGE_NAMES) + '} {\n}\n')
        return hashlib.sha256(bit_bytes).hexdigest()

    def check_args(self, out, image_sha=None, *extra):
        return ['--check', '--image', image_sha or self.six_page_sha,
                '--target', hw.DEFAULT_TARGET, '--lease', str(self.lease),
                '--out', str(out), '--catalog-root', str(self.catalog), *extra]

    def run_check(self, args):
        with mock.patch('socket.create_connection', side_effect=AssertionError(_FAIL_NO_NETWORK)), \
                mock.patch('subprocess.run', side_effect=AssertionError(_FAIL_NO_PROCESS)), \
                mock.patch('subprocess.Popen', side_effect=AssertionError(_FAIL_NO_PROCESS)):
            return hw.main(args)

    def test_six_page_pass_admits_modes_0_to_6(self):
        self.six_page_sha = self.write_image()
        out = self.root / 'six-page-pass'
        code = self.run_check(self.check_args(out))
        self.assertEqual(code, 0)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'PASS_CHECK')
        self.assertEqual(receipt['modes'], [0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(sorted(receipt['plans']), ['0', '1', '2', '3', '4', '5', '6'])
        self.assertEqual(receipt['image']['page_names'], SIX_PAGE_NAMES)
        self.assertEqual(receipt['plans']['5']['page'], 'conv_k5_page')
        self.assertEqual(receipt['plans']['6']['page'], 'conv_c16_page')
        self.assertEqual(receipt['plans']['5']['output_base'], 0x4000)
        self.assertEqual(receipt['plans']['6']['output_base'], 0x5000)
        self.assertEqual(len(receipt['plans']['6']['expected_bytes'])
                         if 'expected_bytes' in receipt['plans']['6'] else 4096, 4096)
        self.assertFalse(receipt['hardware_accessed'])
        self.assertFalse(self.lease.exists())

    def test_fail_receipt_is_refused(self):
        self.write_image(status='FAIL')
        self.six_page_sha = hashlib.sha256(b'\x03' * (2 * 1024 * 1024)).hexdigest()
        out = self.root / 'fail-receipt'
        code = self.run_check(self.check_args(out, self.six_page_sha, '--mode', '0'))
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'CHECK_FAILED')
        self.assertIn('does not name exactly one real emitted bitstream', receipt['failure'])
        self.assertIn('receipt status', receipt['failure'])

    def test_receipt_without_bitstream_is_refused(self):
        self.write_image(emitted=False)
        self.six_page_sha = hashlib.sha256(b'\x03' * (2 * 1024 * 1024)).hexdigest()
        out = self.root / 'no-bitstream'
        code = self.run_check(self.check_args(out, self.six_page_sha, '--mode', '0'))
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertIn('bitstream_emitted is not true', receipt['failure'])

    def test_hash_mismatch_is_refused(self):
        self.six_page_sha = self.write_image()
        out = self.root / 'hash-mismatch'
        code = self.run_check(self.check_args(out, '11' * 32, '--mode', '0'))
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'CHECK_FAILED')
        self.assertIn('does not name exactly one real emitted bitstream', receipt['failure'])

    def test_missing_conv_k5_page_blocks_mode5(self):
        self.six_page_sha = self.write_image(pages=[p for p in SIX_PAGE_NAMES
                                                    if p != 'conv_k5_page'])
        out = self.root / 'missing-k5'
        code = self.run_check(self.check_args(out))
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'CHECK_BLOCKED')
        self.assertEqual(len(receipt['blockers']), 1)
        self.assertIn('conv_k5_page', receipt['blockers'][0])
        self.assertEqual(sorted(receipt['plans']), ['0', '1', '2', '3', '4', '6'])

    def test_missing_conv_c16_page_blocks_mode6(self):
        self.six_page_sha = self.write_image(pages=[p for p in SIX_PAGE_NAMES
                                                    if p != 'conv_c16_page'])
        out = self.root / 'missing-c16'
        code = self.run_check(self.check_args(out))
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'CHECK_BLOCKED')
        self.assertIn('conv_c16_page', receipt['blockers'][0])
        self.assertEqual(sorted(receipt['plans']), ['0', '1', '2', '3', '4', '5'])

    def test_wrong_target_is_refused(self):
        self.six_page_sha = self.write_image()
        out = self.root / 'wrong-target'
        args = self.check_args(out, self.six_page_sha, '--mode', '0')
        args[args.index('--target') + 1] = '10.0.0.9:3125/xilinx_tcf/Xilinx/80802026a77a01'
        code = self.run_check(args)
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertEqual(receipt['status'], 'CHECK_FAILED')
        self.assertIn('locally owned hw_server', receipt['failure'])

    def test_wrong_part_receipt_is_refused(self):
        self.six_page_sha = self.write_image(part='xc7a100t')
        out = self.root / 'wrong-part'
        code = self.run_check(self.check_args(out, self.six_page_sha, '--mode', '0'))
        self.assertEqual(code, 1)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertIn('part', receipt['failure'])


if __name__ == '__main__':
    unittest.main()
