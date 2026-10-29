import importlib.util
from pathlib import Path
import unittest

PACKAGE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full512_image_budget_runner',PACKAGE/'run_image.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class EmissionBudgetTests(unittest.TestCase):
    def test_prospective_image_workflow_budget_is_2400_seconds(self):
        self.assertEqual(runner.emission_timeout_seconds({'resource_limits':{'timeout_seconds':2400}}),2400)

    def test_invalid_or_missing_image_workflow_budget_is_rejected(self):
        for manifest in ({},{'resource_limits':{'timeout_seconds':0}},
                         {'resource_limits':{'timeout_seconds':1200.0}},
                         {'resource_limits':{'timeout_seconds':True}}):
            with self.subTest(manifest=manifest):
                with self.assertRaisesRegex(ValueError,'Invalid image-emission workflow timeout'):
                    runner.emission_timeout_seconds(manifest)

if __name__=='__main__':unittest.main()
