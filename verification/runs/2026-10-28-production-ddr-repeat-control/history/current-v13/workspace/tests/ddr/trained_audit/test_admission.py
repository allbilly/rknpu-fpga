"""Reject unbound vectors and producer claims lacking actual wire artifacts."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from tools.ddr.audit_trained_tile import audit


class TrainedAuditAdmissionTests(unittest.TestCase):
    def fixture(self, base):
        worker, vectors = base / 'worker', base / 'vectors'
        worker.mkdir()
        vectors.mkdir()
        names = ('initial.txt', 'cmac_expected.txt', 'ew_expected.txt',
                 'repeat_expected.txt', 'ew_delta.txt', 'repeat_delta.txt')
        for name in names:
            (vectors / name).write_bytes(b'')
        source = dict(status='STATIC_TRAINED_TILE_JOINED_TEST_VECTORS',
                      lines=1408, cmac_amount=45, ew_amount=22,
                      files={name: hashlib.sha256(b'').hexdigest() for name in names})
        report = vectors / 'report.json'
        report.write_text(json.dumps(source))
        digest = hashlib.sha256(report.read_bytes()).hexdigest()
        child = dict(status='PASS_PHYSICAL_TRAINED_TILE_COMPACTION_AND_REARM_REQUIRES_AUDIT',
                     memory_profile='ddr', hardware_accessed=True, flash_written=False,
                     cpu_dense_fallback=False, vectors_report_sha256=digest, artifacts={})
        (worker / 'report.json').write_text(json.dumps(child))
        return worker, vectors, digest, child

    def test_external_vector_digest_is_required_before_worker_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            worker, vectors, digest, child = self.fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, 'externally reviewed digest'):
                audit(worker, vectors, '0' * 64)

    def test_producer_pass_without_scan_and_capture_hashes_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            worker, vectors, digest, child = self.fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, 'Missing actual scan/capture artifact hashes'):
                audit(worker, vectors, digest)

    def test_bram_or_cpu_result_cannot_be_counted_as_ddr(self):
        with tempfile.TemporaryDirectory() as directory:
            worker, vectors, digest, child = self.fixture(Path(directory))
            for field, value in (('memory_profile', 'bram'), ('hardware_accessed', False),
                                 ('cpu_dense_fallback', True)):
                changed = dict(child, **{field: value})
                (worker / 'report.json').write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'explicit DDR worker'):
                    audit(worker, vectors, digest)
