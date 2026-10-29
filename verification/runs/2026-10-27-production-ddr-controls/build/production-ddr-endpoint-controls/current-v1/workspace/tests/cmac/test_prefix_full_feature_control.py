"""Full inventory and saved actual-native reader controls, not a full route."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from check_full_native_features import (FEATURE_CONTROL, verify_feature_control_metadata, full_inventory,
    routed_primitives, placed_primitives, compare_selected, verify_full_features, SiteBELMap, DATABASE, CONSTIDS)
from probe_prefix_native_config import SELECTED, parse_native_features


class PrefixFullFeatureControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(FEATURE_CONTROL.read_text())
        cls.full = json.loads(SELECTED.read_text())
        cls.chosen = {n: cls.full[source] for n, source in cls.report['control_origins'].items()}
        cls.folder = FEATURE_CONTROL.parent
        cls.packed = routed_primitives(cls.folder / 'routed.json', cls.chosen)
        cls.placed = placed_primitives(cls.folder / 'placement.json', cls.chosen)
        cls.features, cls.repeated = parse_native_features((cls.folder / 'control.fasm').read_text())

    def test_completed_actual_control_requires_same_engine_clock_commands_and_scope(self):
        transition = self.report['native_tool_transition']
        verify_feature_control_metadata(self.report, transition)
        for change in ('status', 'clock', 'engine', 'missing_run', 'failed_run', 'claim', 'counts', 'frequency', 'warning_gate'):
            r = deepcopy(self.report)
            if change == 'status': r['status'] = 'RUNNING'
            elif change == 'clock': r['clock_admission']['target_period_ns'] = 10
            elif change == 'engine': r['native_tool_transition']['selected_executable']['sha256'] = '0' * 64
            elif change == 'missing_run': r['commands'].pop()
            elif change == 'failed_run': r['commands'][-1]['returncode'] = 1
            elif change == 'claim': r['full_board_native_FASM_executed'] = True
            elif change == 'counts': r['native_control_primitive_counts']['DSP48E1'] = 515
            elif change == 'frequency': r['commands'][-1]['argv'][r['commands'][-1]['argv'].index('--freq') + 1] = '25'
            else: r['commands'][-1]['argv'].remove('--Werror')
            with self.subTest(change=change), self.assertRaises(AssertionError): verify_feature_control_metadata(r, transition)

    def test_full_census_requires_every_actual_kernel_and_all_six_memories(self):
        packed = {n: dict(type='DSP48E1_DSP48E1' if c['type'] == 'DSP48E1' else 'RAMB36E1_RAMB36E1')
                  for n, c in self.full.items()}
        groups = full_inventory(self.full, packed)
        self.assertEqual(len(groups), 16); self.assertEqual(set(groups.values()), {32})
        for change in ('missing_dsp', 'missing_bram', 'extra_native', 'type', 'kernel'):
            s, p = deepcopy(self.full), deepcopy(packed)
            name = next(n for n, c in s.items() if c['type'] == ('RAMB36E1' if change == 'missing_bram' else 'DSP48E1') and ('.' in n if change == 'kernel' else True))
            if change.startswith('missing'): s.pop(name); p.pop(name)
            elif change == 'extra_native': p['extra'] = dict(type='DSP48E1_DSP48E1')
            elif change == 'type': p[name]['type'] = 'SLICE_LUTX'
            else: s['other.' + name] = s.pop(name); p['other.' + name] = p.pop(name)
            with self.subTest(change=change), self.assertRaises(AssertionError): full_inventory(s, p)

    def test_saved_actual_native_records_compare_but_cannot_be_full_evidence(self):
        with SiteBELMap(DATABASE, CONSTIDS) as db:
            result = compare_selected(self.features, self.placed, self.chosen, self.packed, db.global_label)
        self.assertEqual(len(result), 10)
        self.assertEqual(len(self.repeated), 5)
        self.assertTrue(all(not c['numerical_or_silicon_acceptance'] for c in result.values()))
        with self.assertRaises(AssertionError): full_inventory(self.chosen, self.packed)
        with self.assertRaises(AssertionError):
            verify_full_features(self.folder / 'control.fasm', self.folder / 'placement.json',
                                 self.folder / 'routed.json', self.chosen, {})

    def test_saved_native_feature_bel_membership_and_parameter_corruptions_fail(self):
        dsp = next(n for n, c in self.chosen.items() if c['type'] == 'DSP48E1')
        bram = next(n for n, c in self.chosen.items() if c['type'] == 'RAMB36E1')
        for change in ('dsp_feature', 'bram_init', 'bel', 'alias_bel', 'missing', 'parameter'):
            f, p, c = deepcopy(self.features), deepcopy(self.placed), deepcopy(self.packed)
            if change == 'dsp_feature':
                key = next(k for k in f if k.startswith(p[dsp]['tile'] + '.DSP48.') and k.endswith('AREG_0')); f.pop(key)
            elif change == 'bram_init':
                key = p[bram]['tile'] + '.RAMB18_Y0.INIT_00[255:0]'; f[key] = ('1' if f[key][0] == '0' else '0') + f[key][1:]
            elif change == 'bel': c[dsp]['attributes']['NEXTPNR_BEL'] = 'DSP48_X0Y0/DSP48E1'
            elif change == 'alias_bel': p[bram]['nextpnr_bel'] = p[dsp]['nextpnr_bel']
            elif change == 'missing': c.pop(dsp)
            else: c[dsp]['parameters']['AREG'] = '1'
            with SiteBELMap(DATABASE, CONSTIDS) as db, self.subTest(change=change), self.assertRaises(AssertionError):
                compare_selected(f, p, self.chosen, c, db.global_label)

    def test_native_readers_reject_missing_extra_duplicate_and_partial_records(self):
        dsp = next(n for n, c in self.chosen.items() if c['type'] == 'DSP48E1')
        with self.assertRaises(AssertionError): routed_primitives(self.folder / 'routed.json', set(self.chosen) - {dsp})
        with self.assertRaises(AssertionError): placed_primitives(self.folder / 'placement.json', set(self.chosen) | {'missing'})
        with TemporaryDirectory(prefix='rknpu-feature-reader-control-') as tmp:
            out = Path(tmp)
            duplicate = {'modules': {'one': {'cells': {dsp: self.packed[dsp]}}, 'two': {'cells': {dsp: self.packed[dsp]}}}}
            path = out / 'duplicate.json'; path.write_text(json.dumps(duplicate, indent=2) + '\n')
            with self.assertRaises(AssertionError): routed_primitives(path, {dsp})
            line = '  ' + json.dumps(dsp) + ': ' + json.dumps(self.placed[dsp])
            for text in ('{\n' + line + ',\n' + line + '\n}\n', '{\n' + line + '\n'):
                path = out / 'bad-placement.json'; path.write_text(text)
                with self.assertRaises(AssertionError): placed_primitives(path, {dsp})


if __name__ == '__main__': unittest.main()
