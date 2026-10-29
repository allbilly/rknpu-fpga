"""Offline admission controls for the private volatile capacity runner."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path('/home/fedora/rknpu-fpga')
RUNNER_PATH = ROOT / 'build/fpga-bringup/full512-capacity-retire-prep-v2/run_capacity_test.py'
PREP_PATH = ROOT / 'build/fpga-bringup/full512-capacity-retire-prep-v2/preparation.json'
SPEC = importlib.util.spec_from_file_location('private_capacity_runner', RUNNER_PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class PreparationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='retirement capacity controls ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.prep = copy.deepcopy(json.loads(PREP_PATH.read_text()))
        self.prep_path = self.base / 'preparation.json'
        self.image_path = self.base / 'image-review.json'
        self.approval_path = self.base / 'execution-approval.json'
        self.bit_path = self.base / 'capacity.bit'
        self.route_path = self.base / 'route-review.json'
        self.bit_audit_path = self.base / 'bitfile-audit.json'
        self.bit_path.write_bytes(b'synthetic bitstream fixture; never qualified')
        self.route_path.write_text(json.dumps({'status': 'PASS_ROOT_FULL512_RETIRE_ROUTE_TIMING'}))
        self.bit_audit_path.write_text(json.dumps({'status': 'PASS_INDEPENDENT_FULL512_RETIRE_BITFILE_AUDIT'}))
        self.review = self.expected_fields()
        self.review.update({
            'status': runner.REVIEW_STATUS,
            'bitstream_path': str(self.bit_path),
            'bitstream_sha256': digest(self.bit_path),
            'route_review_path': str(self.route_path),
            'bitfile_audit_path': str(self.bit_audit_path),
            'bound_files': {
                str(self.route_path): digest(self.route_path),
                str(self.bit_audit_path): digest(self.bit_audit_path),
            },
        })
        self.approval = self.expected_fields()
        self.approval.update({
            'status': runner.APPROVAL_STATUS,
            'approved': True,
            'image_review_sha256': None,
            'bitstream_sha256': digest(self.bit_path),
        })
        self.write_gates()

    def expected_fields(self):
        prep = self.prep
        manifest = prep['hardware_source_manifest']
        return dict(top='ypcb_ddr_dual_top', part='xc7k480tffg1156-2',
                    source_manifest_sha256=prep['source_manifest_sha256'],
                    source_tag=prep['source_tag'], target=runner.TARGET,
                    expected_dna_port=runner.DNA, expected_raw_idcode=runner.IDCODE,
                    product_dsps=512, total_dsps=516, bram_blocks=0,
                    memory_profile='ddr', selected_physical_channel=1,
                    capacity_base=0, capacity_bytes=1 << 31,
                    ecc_test_enabled=False, programming_scope='volatile-sram',
                    flash_authorized=False)

    def write_gates(self):
        self.image_path.write_text(json.dumps(self.review, sort_keys=True))
        self.approval['image_review_sha256'] = digest(self.image_path)
        self.approval_path.write_text(json.dumps(self.approval, sort_keys=True))
        self.prep['image_review_sha256'] = digest(self.image_path)
        self.prep['execution_approval_sha256'] = digest(self.approval_path)
        self.prep_path.write_text(json.dumps(self.prep, sort_keys=True))

    def with_runner_base(self):
        return patch.object(runner, 'BASE', self.base), patch.object(runner, 'PREP', self.prep_path)

    def test_default_preflight_succeeds_without_image_or_execution_approval(self):
        self.prep['image_review_sha256'] = None
        self.prep['execution_approval_sha256'] = None
        self.prep_path.write_text(json.dumps(self.prep))
        self.image_path.unlink(missing_ok=True)
        self.approval_path.unlink(missing_ok=True)
        self.assertFalse(self.image_path.exists())
        self.assertFalse(self.approval_path.exists())
        output = io.StringIO()
        with self.with_runner_base()[0], self.with_runner_base()[1], contextlib.redirect_stdout(output):
            self.assertEqual(runner.main([]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['status'], 'PREPARED_PENDING_RETIRE_CAPACITY_IMAGE')
        self.assertEqual(set(result['pending']), {'image_review_sha256', 'execution_approval_sha256'})
        self.assertFalse(result['hardware_accessed'])
        self.assertFalse(result['flash_written'])

    def test_execute_flag_rejects_before_utility_socket_subprocess_or_lease(self):
        self.prep['image_review_sha256'] = None
        self.prep['execution_approval_sha256'] = None
        self.prep_path.write_text(json.dumps(self.prep))
        with self.with_runner_base()[0], self.with_runner_base()[1], \
             patch.object(runner, 'utility_module', side_effect=AssertionError('utility loaded')), \
             patch('socket.socket', side_effect=AssertionError('socket created')), \
             patch('subprocess.Popen', side_effect=AssertionError('process started')), \
             patch('fcntl.flock', side_effect=AssertionError('lease acquired')):
            with self.assertRaisesRegex(RuntimeError, 'Pending exact capacity image/execution binding'):
                runner.main(['--execute-volatile-sram'])

    def test_complete_mock_review_and_approval_pass_admission_only(self):
        self.write_gates()
        with self.with_runner_base()[0], self.with_runner_base()[1]:
            image, approval, bit = runner.admission(self.prep)
        self.assertEqual(image['status'], runner.REVIEW_STATUS)
        self.assertEqual(approval['status'], runner.APPROVAL_STATUS)
        self.assertEqual(digest(bit), image['bitstream_sha256'])
        self.assertFalse(approval['flash_authorized'])
        self.assertFalse(image['ecc_test_enabled'])
        self.assertFalse(self.base.joinpath('physical-test').exists())

    def test_wrong_image_or_approval_profile_fields_fail_closed(self):
        keys = ('top', 'part', 'source_manifest_sha256', 'source_tag',
                'target', 'expected_dna_port', 'expected_raw_idcode',
                'product_dsps', 'total_dsps', 'bram_blocks', 'memory_profile',
                'selected_physical_channel', 'capacity_base', 'capacity_bytes',
                'ecc_test_enabled', 'programming_scope', 'flash_authorized')
        bad_values = {
            'top': 'wrong_top', 'part': 'xc7k480tffg1156-1',
            'source_manifest_sha256': '0' * 64, 'source_tag': '00000000',
            'target': 'localhost:3125/wrong_target', 'expected_dna_port': '000000000000000',
            'expected_raw_idcode': '00000000', 'product_dsps': 511,
            'total_dsps': 515, 'bram_blocks': 1, 'memory_profile': 'bram',
            'selected_physical_channel': 0, 'capacity_base': 64,
            'capacity_bytes': 1 << 30, 'ecc_test_enabled': True,
            'programming_scope': 'flash', 'flash_authorized': True,
        }
        for key in keys:
            with self.subTest(key=key):
                self.review[key] = bad_values[key]
                self.approval[key] = bad_values[key]
                self.write_gates()
                with self.with_runner_base()[0], self.with_runner_base()[1], self.assertRaisesRegex(
                        RuntimeError, 'Wrong capacity image/approval binding|Explicit false flash/ECC-test policy'):
                    runner.admission(self.prep)
                self.review[key] = self.expected_fields()[key]
                self.approval[key] = self.expected_fields()[key]

    def test_review_and_approval_hashes_and_statuses_are_exact(self):
        self.write_gates()
        cases = ('prep image review hash', 'prep approval hash', 'image status',
                 'approval status', 'approval boolean', 'approval image review hash',
                 'approval bitstream hash')
        for label in cases:
            with self.subTest(label=label):
                self.setUp()
                if label == 'prep image review hash':
                    self.prep['image_review_sha256'] = '0' * 64
                    self.prep_path.write_text(json.dumps(self.prep))
                    message = 'Pending exact capacity image/execution binding'
                elif label == 'prep approval hash':
                    self.prep['execution_approval_sha256'] = '0' * 64
                    self.prep_path.write_text(json.dumps(self.prep))
                    message = 'Pending exact capacity image/execution binding'
                elif label == 'image status':
                    self.review['status'] = 'PASS_OTHER_IMAGE'
                    self.write_gates()
                    message = 'Capacity review/approval incomplete'
                elif label == 'approval status':
                    self.approval['status'] = 'APPROVED_OTHER_IMAGE'
                    self.write_gates()
                    message = 'Capacity review/approval incomplete'
                elif label == 'approval boolean':
                    self.approval['approved'] = False
                    self.write_gates()
                    message = 'Capacity review/approval incomplete'
                elif label == 'approval image review hash':
                    self.approval['image_review_sha256'] = '0' * 64
                    self.approval_path.write_text(json.dumps(self.approval, sort_keys=True))
                    self.prep['execution_approval_sha256'] = digest(self.approval_path)
                    self.prep_path.write_text(json.dumps(self.prep, sort_keys=True))
                    message = 'Approval names another image'
                else:
                    self.approval['bitstream_sha256'] = '0' * 64
                    self.approval_path.write_text(json.dumps(self.approval, sort_keys=True))
                    self.prep['execution_approval_sha256'] = digest(self.approval_path)
                    self.prep_path.write_text(json.dumps(self.prep, sort_keys=True))
                    message = 'Approval names another image'
                with self.with_runner_base()[0], self.with_runner_base()[1], self.assertRaisesRegex(RuntimeError, message):
                    runner.admission(self.prep)

    def test_missing_or_nonpassing_route_and_bitfile_review_reject(self):
        self.write_gates()
        cases = ('missing route binding', 'missing audit binding', 'missing route file', 'missing audit file',
                 'route status', 'bitfile status')
        for label in cases:
            with self.subTest(label=label):
                self.setUp()
                if label == 'missing route binding':
                    self.review['bound_files'].pop(str(self.route_path))
                    self.write_gates()
                    expected = 'Missing route/bitfile review bindings'
                elif label == 'missing audit binding':
                    self.review['bound_files'].pop(str(self.bit_audit_path))
                    self.write_gates()
                    expected = 'Missing route/bitfile review bindings'
                elif label == 'missing route file':
                    self.write_gates()
                    self.route_path.unlink()
                    expected_exception = FileNotFoundError
                    expected = None
                elif label == 'missing audit file':
                    self.write_gates()
                    self.bit_audit_path.unlink()
                    expected_exception = FileNotFoundError
                    expected = None
                elif label == 'route status':
                    self.route_path.write_text(json.dumps({'status': 'FAIL'}))
                    self.review['bound_files'][str(self.route_path)] = digest(self.route_path)
                    self.write_gates()
                    expected = 'Capacity route/timing review has not passed'
                else:
                    self.bit_audit_path.write_text(json.dumps({'status': 'FAIL'}))
                    self.review['bound_files'][str(self.bit_audit_path)] = digest(self.bit_audit_path)
                    self.write_gates()
                    expected = 'Capacity bitfile audit has not passed'
                if label in ('missing route file', 'missing audit file'):
                    with self.with_runner_base()[0], self.with_runner_base()[1], self.assertRaises(expected_exception):
                        runner.admission(self.prep)
                else:
                    with self.with_runner_base()[0], self.with_runner_base()[1], self.assertRaisesRegex(RuntimeError, expected):
                        runner.admission(self.prep)

    def test_changed_bitstream_bytes_and_route_binding_hash_drift_reject(self):
        for label in ('bitstream bytes', 'route dependency bytes'):
            with self.subTest(label=label):
                self.setUp()
                self.write_gates()
                if label == 'bitstream bytes':
                    self.bit_path.write_bytes(b'mutated synthetic bitstream')
                    expected = 'Exact capacity bitstream changed'
                else:
                    self.route_path.write_text('changed route review bytes')
                    expected = 'Reviewed image dependency changed'
                with self.with_runner_base()[0], self.with_runner_base()[1], self.assertRaisesRegex(RuntimeError, expected):
                    runner.admission(self.prep)


if __name__ == '__main__':
    unittest.main(verbosity=2)
