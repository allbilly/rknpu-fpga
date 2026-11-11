"""Build-source provenance controls; no compiler or hardware invocation."""
from copy import deepcopy
import json
import unittest

from tools.ddr.framework_profile import MANIFEST,ROOT,ProfileError,source_paths


class FrameworkSourceProfileTests(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads((ROOT/MANIFEST).read_text())

    def test_complete_public_profile_and_reset_selection(self):
        paths=source_paths(expected_count=83)
        self.assertEqual(len(paths),83)
        self.assertEqual(len(set(paths)),83)
        self.assertEqual(paths[65].name,'rk_quiescent_compute_reset.sv')
        self.assertEqual(paths[66].name,'rk_compute_reset_regs.sv')
        self.assertEqual(paths[67].name,'rk_axil_compute_reset_router.sv')
        self.assertEqual(paths[63].name,'rk_layout_compute_dispatch_ppu.sv')
        self.assertEqual([path.name for path in paths[68:]], [
            'rk_ppu_pool_c3_raw_profile.sv',
            'rk_ppu_pool_max2x2s2_c3_tail_h2w2.sv',
            'rk_ppu_pool_c8_raw_profile.sv',
            'rk_ppu_pool_max2x2s1_c8.sv',
            'rk_ppu_pool_pad1_raw_profile.sv',
            'rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2.sv',
            'rk_ppu_pool_min_raw_profile.sv',
            'rk_ppu_pool_min2x2s1_fp16_capture.sv',
            'rk_ppu_pool_avg_raw_profile.sv',
            'rk_ppu_pool_avg2x2s1_fp16_capture.sv',
            'rk_ppu_pool_index_raw_profile.sv',
            'rk_ppu_pool_max2x2s2_index_c8_h2w2.sv',
            'rk_ppu_pool_global_raw_profile.sv',
            'rk_ppu_pool_max16x16s16_c8.sv',
            'rk_ppu_pool_raw_dma.sv',
        ])
        self.assertEqual(sum('framework' in p.parts for p in paths),18)

    def test_changed_hdl_digest_fails(self):
        self.manifest['sources'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ProfileError,'Changed HDL input'):
            source_paths(manifest=self.manifest,expected_count=83)

    def test_duplicate_or_missing_inputs_fail(self):
        altered=deepcopy(self.manifest)
        altered['sources'][-1]=altered['sources'][0]
        with self.assertRaisesRegex(ProfileError,'Duplicate'):
            source_paths(manifest=altered,expected_count=83)
        altered=deepcopy(self.manifest)
        altered['sources'][0]['path']='rtl/missing-framework-source.sv'
        with self.assertRaisesRegex(ProfileError,'Missing'):
            source_paths(manifest=altered,expected_count=83)

    def test_escaped_or_absolute_source_paths_fail(self):
        for name in ('','.', '../outside.sv','/tmp/outside.sv','rtl/../outside.sv','./rtl/source.sv','rtl\\source.sv'):
            with self.subTest(path=name):
                altered=deepcopy(self.manifest);altered['sources'][0]['path']=name
                with self.assertRaises(ProfileError):source_paths(manifest=altered,expected_count=83)

    def test_unknown_schema_and_precision_fail(self):
        for key,value in (('schema',True),('top','other'),('precision','INT8'),('atomic_c',16),
                          ('atomic_k',32),('defines',['SYNTHESIS']),('extra',1)):
            with self.subTest(key=key,value=value):
                altered=deepcopy(self.manifest);altered[key]=value
                with self.assertRaises(ProfileError):source_paths(manifest=altered,expected_count=83)

    def test_shared_validator_keeps_non_ppu_dual_host_profiles(self):
        from tools.ddr.dual_host_profile import source_paths as dual_host_sources
        from tools.ddr.dual_host_profile import core_source_paths as dual_host_core
        from tools.ddr.dual_host_factored_profile import source_paths as factored_sources
        from tools.ddr.dual_host_factored_profile import core_source_paths as factored_core
        from tools.ddr.dual_host_shared_cacc_profile import core_source_paths as shared_cacc_core

        self.assertEqual(len(dual_host_sources()),67)
        self.assertEqual(len(factored_sources()),67)
        self.assertEqual(dual_host_sources()[-1].name,'rk_axil_compute_reset_router.sv')
        self.assertEqual(len(dual_host_core()),72)
        self.assertEqual(len(factored_core()),72)
        self.assertEqual(len(shared_cacc_core()),72)

    def test_expected_source_count_is_explicit(self):
        with self.assertRaisesRegex(ProfileError,'Unsupported framework source count'):
            source_paths(expected_count=70)


if __name__=='__main__':unittest.main()
