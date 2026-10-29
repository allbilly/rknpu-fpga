"""Async result/coverage gates only; fabricated markers are not model evidence."""
from pathlib import Path
import tempfile
import unittest

from tools.ddr import async_endpoint_contract as contract,endpoint_vectors
from tools.ddr.run_async_endpoint import expanded_specs,runtime_timeout


class AsyncContractTests(unittest.TestCase):
    def fixture(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);files,specs=endpoint_vectors.vector_contents()
        for name,text in files.items():
            if name.startswith('capture_sub_9/'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        spec=expanded_specs(specs)[-1];data=contract.metrics(spec,root)
        marker=(f"PASS jtag_ew_ddr_async jobs=1 negative=10 recovered=0 lines={data['lines']} "
                f"uploaded_nonzero={data['uploaded_nonzero']} rawtasks=2 phy_user_returns=129 "
                'scope=actual_AXI_UI_MC_modeled_PHY')
        return root,spec,data,marker

    def test_original_inventory_is_preserved_but_cannot_claim_new_full_coverage(self):
        _,original=endpoint_vectors.vector_contents();expanded=expanded_specs(original)
        self.assertEqual(expanded[:20],original)
        self.assertEqual(len(contract.selection(expanded,None)),21)
        self.assertEqual(contract.selection(expanded,['partial_task_fault'])[0]['negative'],10)
        with self.assertRaises(ValueError):contract.selection(original,None)
        with self.assertRaises(ValueError):contract.selection(expanded,['partial_task_fault']*2)
        with self.assertRaises(ValueError):contract.selection(expanded,['unsupported_case'])

    def test_partial_fault_requires_its_actual_count_and_first_cause_control(self):
        root,spec,data,marker=self.fixture()
        self.assertEqual(spec['tasks'],2);self.assertEqual(data['successful_jobs'],0)
        self.assertEqual(runtime_timeout(spec,data),300)
        proof='CHECKED partial_task_fault completed=1 ui_code=5'
        expected=root/'capture_sub_9/expected.txt';observed=root/'observed.txt'
        contract.check_result(proof+'\n'+marker+'\n',0,spec,data,observed,expected)
        for prefix in ('',proof.replace('completed=1','completed=0'),proof.replace('ui_code=5','ui_code=8'),proof+'\n'+proof):
            with self.subTest(prefix=prefix):
                with self.assertRaises(ValueError):
                    contract.check_result(prefix+'\n'+marker+'\n',0,spec,data,observed,expected)

    def test_fault_cannot_be_accepted_as_legacy_or_successful_readback(self):
        root,spec,data,marker=self.fixture();proof='CHECKED partial_task_fault completed=1 ui_code=5\n'
        expected=root/'capture_sub_9/expected.txt';observed=root/'observed.txt'
        for text,code in [(proof+marker.replace('jtag_ew_ddr_async','jtag_ew_ddr'),0),
                          (proof+marker,1),(proof+marker+'\n'+marker,0)]:
            with self.subTest(code=code,text=text):
                with self.assertRaises(ValueError):contract.check_result(text,code,spec,data,observed,expected)
        observed.write_bytes(expected.read_bytes())
        with self.assertRaisesRegex(ValueError,'Fault-only case'):
            contract.check_result(proof+marker,0,spec,data,observed,expected)


if __name__=='__main__':unittest.main()
