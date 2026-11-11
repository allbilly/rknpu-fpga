"""Offline tests for the Image-B S3/S4 replay plan (tools/merged/run_image_b_replay.py)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPLAY = ROOT / 'tools/merged/run_image_b_replay.py'


class ImageBReplayPlanTests(unittest.TestCase):
    def setUp(self):
        self.outs = []

    def tearDown(self):
        for out in self.outs:
            if out.exists():
                shutil.rmtree(out)

    def new_out(self, name: str) -> Path:
        out = ROOT / 'build/merged-image' / f'_replay-b-{name}-{id(self)}'
        if out.exists():
            shutil.rmtree(out)
        self.outs.append(out)
        return out

    def test_fixture_plan_covers_all_families_with_honest_oracles(self):
        out = self.new_out('plan')
        result = subprocess.run([sys.executable, str(REPLAY), '--mode', 'fixtures',
                                 '--out', str(out.relative_to(ROOT))],
                                cwd=ROOT, capture_output=True, text=True, timeout=300)
        # HEAVY_WINDOW_REQUIRED is a *refusal to start heavy work*, so the
        # tool returns non-zero on purpose; that is the correct outcome here.
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = json.loads((out / 'plan.json').read_text())
        self.assertEqual(plan['status'], 'PLAN_READY')
        self.assertFalse(plan['vivado_executed'])
        self.assertFalse(plan['hardware_accessed'])
        payload = plan['payload']
        counts = {family['family']: family['ready'] for family in payload['families']}
        self.assertEqual(counts, {'pooling-corpus': 19, 'ew-fp16': 54,
                                  'fdiv-systematic': 8, 'ew-int': 15})
        # Staging: pooling band pages 0x1_0000 + i*0x1000, ew-int four banks.
        pooling = payload['families'][0]
        addresses = [case['page_address'] for case in pooling['cases']]
        self.assertEqual(addresses[0], 0x0001_0000)
        self.assertEqual(addresses[-1], 0x0001_0000 + 18 * 0x1000)
        self.assertEqual(pooling['complete_bo_oracle'], 'device_out.bin (4096 B) per case')
        ew_int = payload['families'][3]
        self.assertEqual(ew_int['command_qwords'], [18, 31, 44])
        self.assertIn('masked complete', ew_int['complete_bo_oracle'])
        for case in ew_int['cases']:
            self.assertTrue(case['masked_complete_bo'])
            self.assertEqual(case['staging']['command'], 0x1100_4000)
        # Lead oracle decisions are recorded for the device-free bundles.
        ew_fp16 = payload['families'][1]
        self.assertIsNone(ew_fp16['complete_bo_oracle'])
        self.assertIn('logical oracle', ew_fp16['comparison_scope'])
        ew_oracle = ew_fp16['oracle_decision']
        self.assertIn('logical expected.bin comparison only', ew_oracle['adopted'])
        self.assertIn('9 production captures', ew_oracle['complete_bo_leg'])
        self.assertIn('no invented device expectations', ew_oracle['rule'])
        fdiv = payload['families'][2]
        self.assertIsNone(fdiv['complete_bo_oracle'])
        self.assertIn('three-guard-bit RTL model', fdiv['comparison_scope'])
        fd_oracle = fdiv['oracle_decision']
        self.assertIn('three-guard-bit RTL model from docs/FDIV.md',
                      fd_oracle['adopted'])
        self.assertIn('1,452/1,452', fd_oracle['evidence'])
        self.assertIn('20 documented A/7 one-ULP-low', fd_oracle['exception_set'])
        self.assertIn('-1 bit', fd_oracle['exception_set'])
        self.assertIn('value outside that set fails', fd_oracle['comparison'])
        self.assertIn('model/contract oracle', fd_oracle['nature'])
        self.assertIn('NOT a capture-derived expected BO', fd_oracle['nature'])
        self.assertIn('candidate', fd_oracle['special_values'])
        # Negatives + heavy-run policy are on record.
        controls = ' '.join(payload['negatives'])
        for needle in ('E2', 'E5', 'E1', 'E6', 'SLVERR', 'sticky error'):
            self.assertIn(needle, controls)
        self.assertIn('~10 min Icarus', payload['heavy_run'])

    def test_full_mode_now_reaches_the_heavy_window_gate(self):
        # S3 attached the real pooling band and S4 the real EW page + six-bank
        # aperture, so ALL Image-B pages are real and `full` is no longer refused
        # for missing pages. The remaining gate is the Lead-scheduled heavy window
        # (the ewint page replay is ~2 min Verilator / ~10 min Icarus single-core).
        out = self.new_out('full')
        result = subprocess.run([sys.executable, str(REPLAY), '--mode', 'full',
                                 '--out', str(out.relative_to(ROOT))],
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
        # HEAVY_WINDOW_REQUIRED is a refusal to start heavy work, so the tool
        # returns non-zero on purpose.
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('HEAVY_WINDOW_REQUIRED', result.stdout)
        self.assertNotIn('REFUSED_UNTIL_REAL_PAGES', result.stdout)
        self.assertIn('safe_run.sh', result.stdout)


if __name__ == '__main__':
    unittest.main()
