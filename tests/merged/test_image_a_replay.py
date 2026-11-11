"""Offline tests for the Image-A replay scaffolding (task-21 follow-up).

Covers tools/merged/run_image_a_replay.py: frozen-fixture discovery, complete-BO
replay plan, wrapper gate for full mode, and the ABI bench leg. No Vivado, no
hardware; the ABI leg is a short Icarus simulation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REPLAY = ROOT / 'tools/merged/run_image_a_replay.py'


def run_replay(mode: str, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPLAY), '--mode', mode,
                           '--out', str(out.relative_to(ROOT))],
                          cwd=ROOT, capture_output=True, text=True, timeout=600)


class ImageAReplayTests(unittest.TestCase):
    def setUp(self):
        self.outs = []

    def tearDown(self):
        for out in self.outs:
            if out.exists():
                shutil.rmtree(out)

    def new_out(self, name: str) -> Path:
        out = ROOT / 'build/merged-image' / f'_replay-{name}-{id(self)}'
        if out.exists():
            shutil.rmtree(out)
        self.outs.append(out)
        return out

    def test_fixture_plan_is_complete_and_complete_bo_compared(self):
        out = self.new_out('fixtures')
        result = run_replay('fixtures', out)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PLAN_READY', result.stdout)
        plan = json.loads((out / 'plan.json').read_text())
        self.assertEqual(plan['status'], 'PLAN_READY')
        self.assertFalse(plan['hardware_accessed'])
        self.assertFalse(plan['vivado_executed'])
        self.assertTrue(plan['source_match'])
        payload = plan['payload']
        self.assertEqual(len(payload['cases']), 15)
        self.assertEqual(payload['conv_simple_cases'], 7)
        self.assertEqual(payload['vendor_cases'], 8)
        self.assertEqual(payload['problems'], [])
        self.assertEqual(payload['comparison'],
                         'complete captured output BO, byte-exact')
        for case in payload['cases']:
            self.assertIn(case['command_qwords'], (52, 54))
            self.assertTrue(case['address_qwords'])
            self.assertTrue(case['complete_bo_compare'])
            total = 0
            for span in case['staging'].values():
                self.assertEqual(span['address'] % 16, 0)
                total = max(total, span['address'] + span['bytes'])
            self.assertLessEqual(total, 65536)
            for name, meta in case['files'].items():
                self.assertEqual(len(meta['sha256']), 64, name)
        # Engine-level negative controls are on record for the S1 replay.
        controls = ' '.join(payload['engine_negative_controls'])
        for needle in ('unsupported geometry', 'second stream without a reset',
                       'out-of-window', 'overlapping', 'unaligned START_ADDRESS',
                       'second submit while a result is pending'):
            self.assertIn(needle, controls)

    def test_full_mode_proceeds_now_that_the_wrapper_is_pinned(self):
        # S1 attached the real page wrapper, so the earlier REFUSED_UNTIL_WRAPPER
        # gate no longer applies. The family replay is the S1 remaining step and
        # still needs a Lead-scheduled window, so the honest assertion is that
        # the refusal is GONE (the mode no longer returns the refusal status).
        out = self.new_out('full')
        result = run_replay('full', out)
        self.assertNotEqual(result.returncode, 1,
                            'the wrapper is pinned, so full must not refuse')
        self.assertNotIn('REFUSED_UNTIL_WRAPPER', result.stdout)
        self.assertIn('WRAPPER_ATTACHED', result.stdout)

    def test_abi_bench_is_refused_once_the_real_page_is_attached(self):
        # S1 attached the real runtime page, so the scaffold ABI bench (which
        # only matched the retired `merged_job_stub` reference model) cannot
        # produce meaningful evidence any more. It must SAY SO explicitly rather
        # than reporting a pass/fail for the wrong model. The page's real
        # contract evidence is the page-contract bench (54/54 captured QWORDs)
        # plus the leg A/B equivalence receipts.
        out = self.new_out('abi')
        result = run_replay('abi', out)
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn('REFUSED_UNTIL_MEMORY_MODEL', result.stdout)
        plan = json.loads((out / 'plan.json').read_text())
        self.assertEqual(plan['status'], 'REFUSED')
        self.assertEqual(plan['payload']['reason'], 'REFUSED_UNTIL_MEMORY_MODEL')
        self.assertEqual(len(plan['payload']['superseded_by']), 2)


if __name__ == '__main__':
    unittest.main()
