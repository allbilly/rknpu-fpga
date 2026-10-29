"""Build-source provenance controls; no compiler or hardware invocation."""
from copy import deepcopy
import json
import unittest

from tools.ddr.framework_profile import MANIFEST,ROOT,ProfileError,source_paths


class FrameworkSourceProfileTests(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads((ROOT/MANIFEST).read_text())

    def test_complete_public_profile_and_reset_selection(self):
        paths=source_paths()
        self.assertEqual(len(paths),68)
        self.assertEqual(len(set(paths)),68)
        self.assertEqual(paths[65].name,'rk_quiescent_compute_reset.sv')
        self.assertEqual(paths[66].name,'rk_compute_reset_regs.sv')
        self.assertEqual(paths[67].name,'rk_axil_compute_reset_router.sv')
        self.assertEqual(sum('framework' in p.parts for p in paths),18)

    def test_changed_hdl_digest_fails(self):
        self.manifest['sources'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ProfileError,'Changed HDL input'):
            source_paths(manifest=self.manifest)

    def test_duplicate_or_missing_inputs_fail(self):
        altered=deepcopy(self.manifest)
        altered['sources'][-1]=altered['sources'][0]
        with self.assertRaisesRegex(ProfileError,'Duplicate'):
            source_paths(manifest=altered)
        altered=deepcopy(self.manifest)
        altered['sources'][0]['path']='rtl/missing-framework-source.sv'
        with self.assertRaisesRegex(ProfileError,'Missing'):
            source_paths(manifest=altered)

    def test_escaped_or_absolute_source_paths_fail(self):
        for name in ('','.', '../outside.sv','/tmp/outside.sv','rtl/../outside.sv','./rtl/source.sv','rtl\\source.sv'):
            with self.subTest(path=name):
                altered=deepcopy(self.manifest);altered['sources'][0]['path']=name
                with self.assertRaises(ProfileError):source_paths(manifest=altered)

    def test_unknown_schema_and_precision_fail(self):
        for key,value in (('schema',True),('top','other'),('precision','INT8'),('atomic_c',16),
                          ('atomic_k',32),('defines',['SYNTHESIS']),('extra',1)):
            with self.subTest(key=key,value=value):
                altered=deepcopy(self.manifest);altered[key]=value
                with self.assertRaises(ProfileError):source_paths(manifest=altered)


if __name__=='__main__':unittest.main()
