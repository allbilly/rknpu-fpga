"""Admission/report controls only; no native execution is mocked as a pass."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
import qualify_dsp_constant_candidate as qualifier


class DSPConstantQualificationControl(unittest.TestCase):
    def build(self):
        built = dict(status=qualifier.BUILT, stage='complete', finished_utc='test-only',
            part='xc7k480tffg1156-2', full_parallel_products=512, upstream_DSP_revision=qualifier.UPSTREAM,
            changed_source_files=list(qualifier.UPSTREAM_DIGESTS), changed_link_objects=2,
            parent_relink_byte_identical=True, non_DSP_source_byte_identical=True,
            production_source_before='test-only', production_source_after='test-only')
        for key in ('assertion_removal', 'native_requalification_executed', 'native_placement_executed', 'native_routing_executed',
                    'old_full_placement_reuse_admitted', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
                    'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
            built[key] = False
        built['commands'] = [dict(label=label, returncode=0, status='PASS_TOOL_EXECUTION_ONLY') for label in (
            'software_controls', 'generated_check', 'compiler_version', 'relink_parent_identity',
            'compile_fasm.cc', 'compile_pack_dsp_xc7.cc', 'link_DSP_constant_candidate', 'native_version')]
        return built

    def native_log(self):
        return '\n'.join(('Running Static placer...', 'Running simulated annealing placer for refinement.',
                          'Running post-placement legalisation...', 'Routing complete.', 'Program finished normally.'))

    def test_build_only_metadata(self):
        qualifier.verify_build_metadata(self.build())

    def test_reduced_array_or_extra_objects_rejected(self):
        for key, value in [('full_parallel_products', 32), ('changed_link_objects', 3)]:
            built = self.build()
            built[key] = value
            with self.assertRaises(AssertionError): qualifier.verify_build_metadata(built)

    def test_old_placement_reuse_or_signoff_claim_rejected(self):
        for key in ('old_full_placement_reuse_admitted', 'timing_signoff', 'hardware_programmed'):
            built = self.build()
            built[key] = True
            with self.assertRaises(AssertionError): qualifier.verify_build_metadata(built)

    def test_partial_native_log_rejected(self):
        qualifier.check_native_log(self.native_log())
        for marker in ('Running simulated annealing placer for refinement.', 'Routing complete.'):
            with self.assertRaises(AssertionError):
                qualifier.check_native_log(self.native_log().replace(marker, ''))

    def test_native_warning_and_bounded_refinement_rejected(self):
        for suffix in ('\nWARNING: unmodeled pin\n', '\nStatic refinement iteration limit: 0\n'):
            with self.assertRaises(AssertionError): qualifier.check_native_log(self.native_log() + suffix)


if __name__ == '__main__':
    unittest.main()
