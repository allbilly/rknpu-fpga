"""Prefix mapped harness controls; not numerical, full-array or FPGA results."""
from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_mapped_prefix_dsp as runner


def parent():
    return dict(status='PASS_ISOLATED_DSP_PREFIX_CARRY_BINARY_AND_AREA_ONLY', stage='complete',
        source_bound_binary_lane_equivalence=True, native_binary_fixture_acceptance=True,
        lemma_free_binary_inputs=67, source_bound_lane_binary_inputs=37, compared_lane_outputs=40,
        expected_native_comparisons=135680, seed='0x3588d501', native_result=runner.MARKER,
        commands=[dict(log=n + '.log', status='PASS', returncode=1 if n in
            ('negative_sat', 'negative_native') else 0) for n in runner.PARENT_LABELS],
        mapped_cells={'reference': {'LUT6': 2, 'DSP48E1': 1}, 'actual': {'LUT6': 1, 'DSP48E1': 1}},
        mapped_lut_primitives={'reference': 2, 'actual': 1},
        **{n: False for n in ('four_state_leaf_acceptance', 'mapped_numerical_acceptance',
            'full_array_numerical_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


class PrefixMappedControls(unittest.TestCase):
    def test_only_completed_binary_proof_native_and_area_parent_is_admitted(self):
        good = parent(); before = deepcopy(good); runner.validate_parent_metadata(good)
        self.assertEqual(good, before)
        for field, value in (('status', 'RUNNING'), ('status', 'PASS_ISOLATED_LANE_DSP_XC7_AREA_ONLY'),
            ('stage', 'native_binary'), ('source_bound_binary_lane_equivalence', False),
            ('native_binary_fixture_acceptance', False), ('lemma_free_binary_inputs', 66),
            ('source_bound_lane_binary_inputs', 36), ('compared_lane_outputs', 39),
            ('expected_native_comparisons', 135679), ('seed', '0x1'), ('native_result', 'PASS other')):
            bad = deepcopy(good); bad[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_parent_metadata(bad)
        for field in ('four_state_leaf_acceptance', 'mapped_numerical_acceptance',
            'full_array_numerical_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
            bad = deepcopy(good); bad[field] = True
            with self.subTest(field=field), self.assertRaises(AssertionError): runner.validate_parent_metadata(bad)

    def test_every_actual_command_and_real_negative_exit_is_required(self):
        good = parent()
        for index in range(len(good['commands'])):
            for mutation in ('missing', 'status', 'returncode', 'label'):
                bad = deepcopy(good); c = bad['commands'][index]
                if mutation == 'missing': bad['commands'].pop(index)
                elif mutation == 'status': c['status'] = 'RUNNING'
                elif mutation == 'returncode': c['returncode'] = 0 if c['returncode'] else 1
                else: c['log'] = 'unrelated.log'
                with self.subTest(index=index, mutation=mutation), self.assertRaises(AssertionError):
                    runner.validate_parent_metadata(bad)

    def test_both_area_graphs_keep_one_dsp_nonzero_luts_and_no_state(self):
        for side in ('reference', 'actual'):
            for mutation in ('dsp', 'state', 'luts', 'counts', 'label'):
                bad = parent(); counts = bad['mapped_cells'][side]
                if mutation == 'dsp': counts['DSP48E1'] = 0
                elif mutation == 'state': counts['FDCE'] = 1
                elif mutation == 'luts': counts['LUT6'] = 0; bad['mapped_lut_primitives'][side] = 0
                elif mutation == 'counts': bad['mapped_lut_primitives'][side] += 1
                else: bad['mapped_lut_primitives']['extra'] = 1
                with self.subTest(side=side, mutation=mutation), self.assertRaises(AssertionError):
                    runner.validate_parent_metadata(bad)

    def test_mapped_adapter_has_one_literal_rebind_and_keeps_original_reference(self):
        original = runner.prefix.MITER.read_text(); mapped = runner.mapped_miter(original)
        self.assertEqual(mapped.replace(runner.MAPPED_TOP + ' actual (',
            'rk_cmac_fp16_lane_dsp_prefix actual ('), original)
        self.assertIn('rk_cmac_fp16_lane_dsp reference (', mapped)
        self.assertNotIn('rk_cmac_fp16_lane_dsp_prefix actual (', mapped)
        self.assertEqual(runner.SOURCES[:4], runner.prefix.lane.SOURCES[:4])
        self.assertEqual(runner.SOURCES[4:], [runner.prefix.HELPER, runner.prefix.CANDIDATE, runner.prefix.MITER])
        for bad in (original + original, mapped, original.replace(' actual (', ' hidden (')):
            with self.subTest(bad=bad[:40]), self.assertRaises(AssertionError): runner.mapped_miter(bad)

    def test_only_full_positive_marker_and_real_mismatch_negative_are_admitted(self):
        runner.validate_result(runner.MARKER, 0, False)
        runner.validate_result('FATAL: LANE_DSP_MISMATCH a=0000', 1, True)
        cases = [(runner.MARKER, 1, False), (runner.MARKER + '\n' + runner.MARKER, 0, False),
            (runner.MARKER.replace('135680', '1'), 0, False),
            (runner.MARKER.replace('4096', '1'), 0, False),
            (runner.MARKER.replace('3588d501', '1'), 0, False), ('compiler crash', 1, True),
            ('LANE_DSP_MISMATCH', 2, True), ('LANE_DSP_MISMATCH\nPASS other', 1, True)]
        cases += [(runner.MARKER + '\n' + s, 0, False) for s in
            ('warning: primitive', 'ERROR: failed', 'sorry: unimplemented', 'FATAL: failed')]
        for text, code, negative in cases:
            with self.subTest(text=text), self.assertRaises(AssertionError): runner.validate_result(text, code, negative)

    def test_native_state_unknown_cells_and_missing_dsp_are_not_export_acceptance(self):
        good = dict(modules={runner.MAPPED_TOP: dict(cells={'dsp': {'type': 'DSP48E1'},
            'lut': {'type': 'LUT6'}})})
        self.assertEqual(runner.verify_export_domain(good), {'DSP48E1': 1, 'LUT6': 1})
        for kind in ('rk_cmac_fp16_lane_dsp_prefix', 'rk_cmac_fp16_discarded_carry', '$mul', 'FDCE', 'unknown'):
            bad = deepcopy(good); bad['modules'][runner.MAPPED_TOP]['cells']['hidden'] = {'type': kind}
            with self.subTest(kind=kind), self.assertRaises(AssertionError): runner.verify_export_domain(bad)
        for mutation in ('missing_dsp', 'missing_lut', 'extra_dsp', 'hierarchy'):
            bad = deepcopy(good); cells = bad['modules'][runner.MAPPED_TOP]['cells']
            if mutation == 'missing_dsp': cells.pop('dsp')
            elif mutation == 'missing_lut': cells.pop('lut')
            elif mutation == 'extra_dsp': cells['second'] = {'type': 'DSP48E1'}
            else: bad['modules']['hidden'] = dict(cells={})
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError): runner.verify_export_domain(bad)

    def test_recursive_bindings_reject_stale_empty_escape_and_changed_manifest_digest(self):
        with TemporaryDirectory(prefix='prefix-binding-control-', dir=ROOT / 'build') as name:
            path = Path(name) / 'input.txt'; path.write_text('synthetic control only\n')
            binding = runner.fingerprint([path]); runner.verify_bindings(dict(source=binding, nested=[binding]))
            bad = deepcopy(binding); bad['sha256'] = '0' * 64
            with self.assertRaises(AssertionError): runner.verify_bindings(dict(nested=[bad]))
            with self.assertRaises(AssertionError): runner.verify_bindings(dict(source={'files': {}, 'sha256': '0'*64}))
            with self.assertRaises(AssertionError): runner.verify_bindings(dict(source={'files': {'/tmp/escape': '0'*64}, 'sha256': '0'*64}))
            path.write_text('different synthetic control\n')
            with self.assertRaises(AssertionError): runner.verify_bindings(dict(nested=[binding]))


if __name__ == '__main__': unittest.main()
