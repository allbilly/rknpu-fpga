"""Fail-closed continuation admission controls; no FPGA/numerical proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/cmac')]
from continue_prefix_shared_export import validate_preparation


def fixture():
    return dict(status='FAIL_PREFIX_SHARED_CANDIDATE', finished_utc='fixture-only',
        stage='candidate_export', error="AssertionError('Unsupported string primitive parameter')",
        channels=32, kernels=16, parallel_products=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588,
        circuit_lift_verified=True, actual_shared_INIT_bit_corruption_rejected=True,
        actual_private_DSP_removal_rejected=True, numerical_netlist_acceptance=False,
        native_packing_executed=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        cells_before={'DSP48E1': 515, 'RAMB36E1': 6}, cells_after={'DSP48E1': 515, 'RAMB36E1': 6},
        removed_cells={'LUT3': 14610, 'MUXF7': 105},
        commands=[dict(label=label, status='PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY', returncode=0)
                  for label in ('software_controls', 'generated_check', 'version')])


class PrefixSharedExportControl(unittest.TestCase):
    def test_exact_recorded_failure_is_admitted_without_mutation(self):
        parent = fixture()
        before = deepcopy(parent)
        validate_preparation(parent)
        self.assertEqual(parent, before)

    def reject(self, mutate):
        parent = fixture()
        mutate(parent)
        with self.assertRaises(AssertionError):
            validate_preparation(parent)

    def test_running_or_unfinished_rejected(self):
        self.reject(lambda r: r.update(status='RUNNING'))
        self.reject(lambda r: r.update(finished_utc=None))

    def test_unrelated_failure_rejected(self):
        self.reject(lambda r: r.update(error="AssertionError('Wrong numerical output')"))
        self.reject(lambda r: r.update(stage='numerical_replay'))

    def test_missing_actual_lift_or_negative_rejected(self):
        for field in ('circuit_lift_verified', 'actual_shared_INIT_bit_corruption_rejected',
                      'actual_private_DSP_removal_rejected'):
            self.reject(lambda r, k=field: r.update({k: False}))

    def test_smaller_target_or_changed_clock_part_seed_rejected(self):
        for field, value in (('parallel_products', 256), ('channels', 16), ('kernels', 8),
                            ('intended_part', 'xc7a100t'), ('intended_clock_period_ns', 40), ('seed', 0)):
            self.reject(lambda r, k=field, v=value: r.update({k: v}))

    def test_missing_failed_or_unbound_tool_command_rejected(self):
        self.reject(lambda r: r['commands'].pop())
        self.reject(lambda r: r['commands'][0].update(returncode=1))
        self.reject(lambda r: r['commands'][0].update(status='RUNNING'))

    def test_dsp_or_bram_loss_rejected(self):
        self.reject(lambda r: r['cells_after'].update(DSP48E1=514))
        self.reject(lambda r: r['cells_after'].update(RAMB36E1=5))

    def test_state_removal_or_changed_lut_gain_rejected(self):
        self.reject(lambda r: r['removed_cells'].update(FDCE=1))
        self.reject(lambda r: r['removed_cells'].update(LUT3=1))

    def test_inferred_numerical_physical_or_emission_acceptance_rejected(self):
        for field in ('numerical_netlist_acceptance', 'native_packing_executed', 'physical_fit_verified',
                      'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
            self.reject(lambda r, k=field: r.update({k: True}))


if __name__ == '__main__':
    unittest.main()
