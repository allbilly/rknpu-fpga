"""Full-target admission controls, not native packing or FPGA acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'tools/openxc7'),
                str(Path(__file__).resolve().parents[2] / 'tools/cmac')]
from prepare_prefix_shared_pack_input import validate_export, STATUS, TOP, PRIVATE, SHARED


def fixture():
    labels = ['sharing_controls', 'DSP_export_controls', 'continuation_controls',
              'generated_check', 'version', 'export', 'hierarchy_check']
    return dict(status=STATUS, stage='complete', finished_utc='fixture-only',
        circuit_lift_revalidated=True, old_failure_relabelled=False,
        channels=32, kernels=16, parallel_products=512, retained_kernel_instances=16,
        retained_cmac_dsps=512, retained_shell_dsps=3, intended_part='xc7k480tffg1156-2',
        intended_clock_period_ns=20, seed=3588, lut_count=431206, ff_count=17519,
        cells={'DSP48E1': 515, 'RAMB36E1': 6}, production_source_before={'fixture': 1},
        production_source_after={'fixture': 1}, sharing_controls=28, DSP_export_controls=6,
        continuation_controls=9, numerical_netlist_acceptance=False, native_packing_executed=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        export_circuit_identity={name: dict(cells=1, bijective_wires=1, endpoint_bits=1)
                                 for name in (TOP, PRIVATE, SHARED)},
        commands=[dict(label=n, status='PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY', returncode=0) for n in labels])


class PrefixSharedPackInputControl(unittest.TestCase):
    def reject(self, mutation):
        parent = fixture()
        mutation(parent)
        with self.assertRaises(AssertionError):
            validate_export(parent)

    def test_completed_full_export_admitted_without_mutation(self):
        parent = fixture()
        before = deepcopy(parent)
        validate_export(parent)
        self.assertEqual(parent, before)

    def test_running_unfinished_or_wrong_stage_rejected(self):
        self.reject(lambda r: r.update(status='RUNNING'))
        self.reject(lambda r: r.update(finished_utc=None))
        self.reject(lambda r: r.update(stage='literal_DSP_export'))

    def test_original_failed_candidate_not_admitted(self):
        self.reject(lambda r: r.update(status='FAIL_PREFIX_SHARED_CANDIDATE'))
        self.reject(lambda r: r.update(old_failure_relabelled=True))

    def test_smaller_target_or_wrong_part_clock_seed_rejected(self):
        for key, value in (('channels', 16), ('kernels', 8), ('parallel_products', 256),
                           ('retained_kernel_instances', 8), ('retained_cmac_dsps', 256),
                           ('retained_shell_dsps', 0), ('intended_part', 'xc7a100t'),
                           ('intended_clock_period_ns', 40), ('seed', 0)):
            self.reject(lambda r, k=key, v=value: r.update({k: v}))

    def test_changed_source_or_missing_lift_proof_rejected(self):
        self.reject(lambda r: r.update(production_source_after={'fixture': 2}))
        self.reject(lambda r: r.update(circuit_lift_revalidated=False))

    def test_changed_resources_rejected(self):
        self.reject(lambda r: r['cells'].update(DSP48E1=514))
        self.reject(lambda r: r['cells'].update(RAMB36E1=5))
        self.reject(lambda r: r.update(lut_count=1))
        self.reject(lambda r: r.update(ff_count=1))

    def test_unfinished_missing_or_unbound_command_rejected(self):
        self.reject(lambda r: r['commands'].pop())
        self.reject(lambda r: r['commands'][-1].update(status='RUNNING'))
        self.reject(lambda r: r['commands'][-1].update(returncode=1))
        self.reject(lambda r: r['commands'][-1].update(label='mock_hierarchy'))

    def test_incomplete_full_circuit_identity_rejected(self):
        self.reject(lambda r: r['export_circuit_identity'].pop(SHARED))
        self.reject(lambda r: r['export_circuit_identity'][PRIVATE].update(cells=0))
        self.reject(lambda r: r['export_circuit_identity'][TOP].update(bijective_wires=0))

    def test_inferred_numerical_or_physical_acceptance_rejected(self):
        for key in ('numerical_netlist_acceptance', 'native_packing_executed', 'physical_fit_verified',
                    'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
            self.reject(lambda r, k=key: r.update({k: True}))


if __name__ == '__main__':
    unittest.main()
