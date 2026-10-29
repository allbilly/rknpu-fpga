from __future__ import annotations

import json
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ddr.capacity_pattern import (  # noqa: E402
    CapacityPlan,
    CapacityVerifier,
    DEFAULT_SEED,
    LINE_BYTES,
    PHYSICAL_BYTES,
)


def event_for(plan, ordinal):
    trial, kind, address = plan.operation(ordinal)
    return dict(trial=trial, kind=kind, address=address,
                data=plan.pattern(address, trial), response_status=0)


class CapacityPatternTests(unittest.TestCase):
    def test_full_2gib_plan_metadata_and_boundary_order(self):
        plan = CapacityPlan()
        manifest = plan.manifest()
        lines = 33_554_432
        self.assertEqual(PHYSICAL_BYTES, 2 * 1024**3)
        self.assertEqual(plan.lines, lines)
        self.assertEqual(manifest['operations'], 134_217_728)
        self.assertEqual(manifest['verified_read_bytes'], 4 * 1024**3)
        self.assertTrue(manifest['all_write_responses_required_before_reads'])
        self.assertTrue(manifest['planned_full_window'])
        self.assertFalse(manifest['physical_capacity_qualified'])
        self.assertEqual(plan.operation(0), (0, 'WRITE64', 0))
        self.assertEqual(plan.operation(lines - 1), (0, 'WRITE64', PHYSICAL_BYTES - LINE_BYTES))
        self.assertEqual(plan.operation(lines), (0, 'READ64', 0))
        self.assertEqual(plan.operation(2 * lines - 1), (0, 'READ64', PHYSICAL_BYTES - LINE_BYTES))
        self.assertEqual(plan.operation(2 * lines), (1, 'WRITE64', PHYSICAL_BYTES - LINE_BYTES))
        self.assertEqual(plan.operation(3 * lines - 1), (1, 'WRITE64', 0))
        self.assertEqual(plan.operation(3 * lines), (1, 'READ64', 0))
        self.assertEqual(plan.operation(4 * lines - 1), (1, 'READ64', PHYSICAL_BYTES - LINE_BYTES))
        self.assertEqual(plan.operation(2 * lines - 1)[1], 'READ64')
        self.assertEqual(plan.operation(2 * lines)[1], 'WRITE64')

    def test_known_independent_word_and_byte_goldens_and_complement_trial(self):
        plan = CapacityPlan()
        expected_words = [0x3588C350, 0xABBFBAE9,
                          0x09E63022, 0x70C8E287]
        words = struct.unpack('<16I', plan.pattern(0, 0))
        self.assertEqual([words[i] for i in (0, 1, 2, 15)], expected_words)
        self.assertEqual(plan.pattern(0, 0)[:16].hex(), '50c38835e9babfab2230e6097bae2eef')
        trial_one = struct.unpack('<16I', plan.pattern(0, 1))
        self.assertEqual([trial_one[i] for i in (0, 1, 2, 15)],
                         [0xCA773CAF, 0x54404516, 0xF619CFDD, 0x8F371D78])
        self.assertEqual(trial_one, tuple(word ^ 0xffffffff for word in words))
        self.assertEqual(struct.unpack('<16I', plan.pattern(LINE_BYTES, 0))[0], 0x3588C351)

    def test_rejects_boolean_unaligned_out_of_window_seed_and_trial_inputs(self):
        for kwargs in ({'base': True}, {'size': True}, {'base': 1}, {'size': 65},
                       {'base': PHYSICAL_BYTES, 'size': LINE_BYTES},
                       {'base': PHYSICAL_BYTES - LINE_BYTES, 'size': 2 * LINE_BYTES},
                       {'seed': True}, {'seed': -1}, {'seed': 1 << 32}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                CapacityPlan(**kwargs)
        plan = CapacityPlan()
        for address, trial in ((True, 0), (1, 0), (PHYSICAL_BYTES, 0), (0, True),
                               (0, -1), (0, 2)):
            with self.subTest(address=address, trial=trial), self.assertRaises(ValueError):
                plan.pattern(address, trial)
        for ordinal in (True, -1, 4 * plan.lines):
            with self.subTest(ordinal=ordinal), self.assertRaises(ValueError):
                plan.operation(ordinal)

    def test_aliasing_memory_passes_all_writes_then_fails_on_first_read(self):
        plan = CapacityPlan(size=4 * LINE_BYTES, seed=0x12345678)
        verifier = CapacityVerifier(plan)
        fake_memory = {}
        first_read_ordinal = None
        for ordinal in range(4 * plan.lines):
            trial, kind, address = plan.operation(ordinal)
            data = plan.pattern(address, trial)
            if kind == 'WRITE64':
                # The fake consumer drops address bit 6, aliasing adjacent lines.
                fake_memory[address & ~LINE_BYTES] = data
                verifier.observe(trial=trial, kind=kind, address=address, data=data)
            else:
                first_read_ordinal = ordinal if first_read_ordinal is None else first_read_ordinal
                observed = fake_memory.get(address & ~LINE_BYTES, bytes(LINE_BYTES))
                with self.assertRaisesRegex(ValueError, 'differs from its address/lane pattern'):
                    verifier.observe(trial=trial, kind=kind, address=address, data=observed)
                break
        self.assertEqual(first_read_ordinal, plan.lines)
        self.assertEqual(verifier.completed, plan.lines)
        self.assertTrue(verifier.failed)
        with self.assertRaisesRegex(ValueError, 'cannot resume'):
            verifier.observe(trial=0, kind='READ64', address=0, data=plan.pattern(0, 0))
        with self.assertRaises(ValueError):
            verifier.finish()

    def test_corrupt_wrong_address_reordered_skipped_or_truncated_streams_never_pass(self):
        plan = CapacityPlan(size=3 * LINE_BYTES)
        events = [event_for(plan, i) for i in range(4 * plan.lines)]
        corrupt = [dict(x) for x in events]
        read_index = plan.lines
        corrupt[read_index]['data'] = bytes(LINE_BYTES)
        cases = {
            'corrupted_read': corrupt,
            'wrong_address': [dict(events[0], address=LINE_BYTES), *events[1:]],
            'out_of_order': [events[1], events[0], *events[2:]],
            'skipped': events[1:],
        }
        for name, stream in cases.items():
            with self.subTest(name=name):
                verifier = CapacityVerifier(plan)
                with self.assertRaises(ValueError):
                    for event in stream:
                        verifier.observe(**event)
                with self.assertRaises(ValueError):
                    verifier.finish()
        truncated = CapacityVerifier(plan)
        for event in events[:-1]:
            truncated.observe(**event)
        with self.assertRaisesRegex(ValueError, 'Incomplete or failed'):
            truncated.finish()
        with self.assertRaisesRegex(ValueError, 'cannot resume'):
            truncated.observe(**events[-1])

    def test_successful_partial_window_is_bytes_only_not_full_capacity(self):
        plan = CapacityPlan(base=LINE_BYTES, size=3 * LINE_BYTES)
        verifier = CapacityVerifier(plan)
        for ordinal in range(4 * plan.lines):
            verifier.observe(**event_for(plan, ordinal))
        receipt = verifier.finish()
        self.assertEqual(receipt['status'], 'PASS_ORDERED_DDR_SPAN_PATTERN_BYTES_ONLY')
        self.assertEqual(receipt['completed_operations'], 12)
        self.assertEqual(receipt['read_bytes'], 2 * plan.size)
        self.assertFalse(receipt['full_window_bytes_checked'])
        self.assertFalse(receipt['physical_capacity_qualified'])
        self.assertFalse(plan.manifest()['planned_full_window'])
        self.assertTrue(plan.manifest()['controller_retirement_and_ecc_witness_required_separately'])
        with self.assertRaisesRegex(ValueError, 'cannot accept extra operations'):
            verifier.observe(**event_for(plan, 0))

    def test_offline_plan_cli_writes_metadata_only_and_refuses_existing_output(self):
        script = ROOT / 'tools/ddr/prepare_capacity_test.py'
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / 'capacity-plan.json'
            cmd = [sys.executable, str(script), '--out', str(out)]
            result = subprocess.run(cmd, cwd=td, text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out.read_text())
            self.assertEqual(report['status'], 'PREPARED_OFFLINE_DDR_CAPACITY_PLAN_ONLY')
            self.assertEqual(report['plan']['lines'], 33_554_432)
            self.assertEqual(report['plan']['operations'], 134_217_728)
            self.assertTrue(report['plan']['planned_full_window'])
            self.assertFalse(report['hardware_executed'])
            self.assertFalse(report['physical_capacity_qualified'])
            self.assertEqual(set(p.name for p in pathlib.Path(td).iterdir()), {'capacity-plan.json'})
            refused = subprocess.run(cmd, cwd=td, text=True, capture_output=True, timeout=20)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('already exists', refused.stderr)
            self.assertEqual(json.loads(out.read_text()), report)


if __name__ == '__main__':
    unittest.main()
