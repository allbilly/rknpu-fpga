"""Portable admission/result regressions; these do not qualify DDR hardware."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from tools.ddr import endpoint_contract as c, endpoint_vectors as v, run_endpoint as runner


class JoinedEndpointControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.specs = v.generate(cls.directory/'vectors')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def spec(self, name):
        return next(s for s in self.specs if s['name'] == name)

    def test_complete_selection_and_explicit_subset(self):
        self.assertEqual(len(c.selection(self.specs, None)), 20)
        self.assertEqual(len(c.selection(self.specs, ['rmw_ue', 'capture_add_8'])), 2)
        for names in (['missing'], ['capture_add_8']*2):
            with self.assertRaises(ValueError):
                c.selection(self.specs, names)
        with self.assertRaises(ValueError):
            c.selection(self.specs[:-1], None)

    def test_return_inventory_comes_from_actual_bo_and_scalar_contract(self):
        s = self.spec('capture_add_8')
        m = c.metrics(s, self.directory/'vectors')
        self.assertEqual((m['lines'], m['physical_bytes'], m['uploaded_nonzero'], m['phy_user_returns']),
                         (1472, 94208, 72, 52006))
        # Same raw ADD fixture through the real reset-recovery control path.
        r = dict(s, negative=2, reset_recovery=1)
        self.assertEqual(c.metrics(r, self.directory/'vectors')['phy_user_returns'], 51910)
        self.assertEqual(c.metrics(self.spec('repeat_sub_9'), self.directory/'vectors')['successful_jobs'], 2)

    def invoke(self, *, negative=0, recovered=0, corrupt='', readback=True, code=0):
        s = dict(self.spec('capture_add_8'), negative=negative, reset_recovery=recovered)
        m = c.metrics(s, self.directory/'vectors')
        jobs = 0 if negative == 9 else 1+bool(recovered)
        count = m['phy_user_returns'] if m['phy_user_returns'] is not None else 130
        marker = (f"PASS jtag_ew_ddr jobs={jobs} negative={negative} recovered={recovered} "
                  f"lines={m['lines']} uploaded_nonzero={m['uploaded_nonzero']} rawtasks=1 "
                  f"phy_user_returns={count} scope=actual_AXI_UI_MC_modeled_PHY")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'observed.txt'
            expected = self.directory/'vectors/capture_add_8/expected.txt'
            if readback:
                output.write_bytes(expected.read_bytes())
            if corrupt == 'byte':
                output.write_bytes(output.read_bytes().replace(b'0', b'1', 1))
            elif corrupt == 'short':
                output.write_bytes(output.read_bytes()[:-138])
            elif corrupt == 'duplicate':
                marker += '\n'+marker
            elif corrupt == 'old_marker_bug':
                marker = marker.replace('jobs=1', 'jobs=1=')
            elif corrupt == 'field':
                marker = marker.replace('rawtasks=1', 'rawtasks=0')
            elif corrupt == 'extra':
                marker += ' ignored=1'
            elif corrupt == 'returns':
                marker = marker.replace(f'phy_user_returns={count}', 'phy_user_returns=1')
            elif corrupt == 'fatal':
                marker += '\nFATAL: hidden failure\n'
            return c.check_result(marker, code, s, m, output, expected)

    def test_exact_success_preserves_physical_and_dump_byte_distinction(self):
        result = self.invoke()
        self.assertEqual(result['readback_physical_bytes'], 94208)
        self.assertEqual(result['observed_text_bytes'], 203136)

    def test_success_rejects_bad_coverage_or_incomplete_numerical_output(self):
        for bad in ('byte', 'short', 'duplicate', 'old_marker_bug', 'field', 'extra', 'returns', 'fatal'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.invoke(corrupt=bad)
        for kwargs in (dict(code=1), dict(readback=False)):
            with self.assertRaises(ValueError):
                self.invoke(**kwargs)

    def test_expected_fault_and_reset_recovery_are_different_results(self):
        self.assertEqual(self.invoke(negative=2, readback=False)['successful_jobs'], 0)
        self.assertEqual(self.invoke(negative=2, recovered=1)['successful_jobs'], 1)
        with self.assertRaises(ValueError):
            self.invoke(negative=2)
        with self.assertRaises(ValueError):
            self.invoke(negative=2, recovered=1, readback=False)

    def test_unchanged_fault_deadline_and_complete_original_command_boundary(self):
        s = self.spec('host_memory_timeout')
        self.assertEqual(runner.runtime_timeout(s, c.metrics(s, self.directory/'vectors')), 300)
        s = self.spec('joint_reset_recovery')
        self.assertEqual(runner.runtime_timeout(s, c.metrics(s, self.directory/'vectors')), 1800)
        args = runner.run_plan(Path('/package'), Path('/trial'), s)
        self.assertEqual(args[0], '/package/obj/sim')
        self.assertIn('+START=100e0000', args)
        self.assertIn('+AMOUNT=35', args)
        self.assertFalse(any('tensor' in a.lower() for a in args))

    def test_unknown_or_changed_descriptor_fields_fail_before_simulation(self):
        source = json.loads((v.ROOT/'tests/backend_ew_captures.json').read_text())
        for field, value in [('flags', 1), ('op_idx', 0), ('enable_mask', 1), ('int_mask', 0),
                             ('int_clear', 0), ('int_status', 1), ('regcfg_offset', 16), ('new_field', 0)]:
            changed = deepcopy(source)
            changed['cases'][0]['tasks'][0]['descriptor'][field] = value
            with self.subTest(field=field), patch.object(v, 'load_json', return_value=changed), self.assertRaises(ValueError):
                v.captured_cases()

    def test_diagnostic_count_source_and_version_are_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'vendor.v'
            source.write_text('fixed vendor fixture\n')
            policy = dict(schema=1, status='SOURCE_BOUND_LOGICAL_SIMULATION_BASELINE_ONLY',
                verilator_version='fixture', origin_sha256={'vendor.v': c.sha(source)},
                reset_context_sha256={}, verilator=[dict(code='WIDTH', file='vendor.v', line=1, column=2, message='fixture')])
            text = '%Warning-WIDTH: /fixture/vendor.v:1:2: fixture\n'
            self.assertEqual(len(c.check_warnings(text, policy, [source], 'fixture')), 1)
            for bad in ('', text+text, text.replace('fixture\n', 'different\n')):
                with self.assertRaises(ValueError):
                    c.check_warnings(bad, policy, [source], 'fixture')
            with self.assertRaises(ValueError):
                c.check_warnings(text, policy, [source], 'different version')
            source.write_text('changed')
            with self.assertRaises(ValueError):
                c.check_warnings(text, policy, [source], 'fixture')


if __name__ == '__main__':
    unittest.main()
