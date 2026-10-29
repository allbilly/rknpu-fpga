"""Complete-parent and exact negative-golden controls, not full HDL evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
import test_observed_mapped_board as runner


class ObservedMappedBoardControls(unittest.TestCase):
    def test_unmodified_fault_codes_unknown_mode_assertions_and_reference_provenance(self):
        # Wire-only fixture; it is not presented as hardware mapping evidence.
        bit=2;module={'netnames':{},'ports':{},'cells':{}}
        for name,width in runner.WIDTHS.items():
            bits=list(range(bit,bit+width));bit+=width
            module['netnames'][name]={'bits':bits,'attributes':{}}
            module['ports'][name]={'direction':'output','bits':bits.copy()}
        original=runner.BENCH.read_text();bound,edits=runner.bind(module,original)
        runner.verify_bound_bench(module,original,bound,edits)
        for changed in (bound.replace('failure(5);','failure(0);'),bound.replace('16\'hxxxx','16\'hffff'),
            bound.replace('checks!=4096','checks!=1'),bound.replace('case (mode)','case (0)')):
            with self.subTest(text=changed[:20]),self.assertRaises(AssertionError):
                runner.verify_bound_bench(module,original,changed,edits)
        changed_edits=deepcopy(edits);changed_edits[0]['replacement']='dut.n_99999'
        with self.assertRaises(AssertionError):runner.verify_bound_bench(module,original,bound,changed_edits)

    def test_all_nine_modes_and_exact_first_output_data_bit_negative(self):
        self.assertEqual(runner.MODES,tuple(range(9)))
        original=runner.WRITES.read_text();changed=runner.negative_golden(original)
        before,after=original.splitlines(),changed.splitlines()
        self.assertEqual(len(before),64);self.assertEqual(len(after),64)
        self.assertEqual(before[1:],after[1:]);self.assertEqual(int(before[0],16)^int(after[0],16),1)
        self.assertEqual(int(before[0],16)>>16,int(after[0],16)>>16)
        for bad in (original.rstrip(),original+'000000000000\n',original.replace(before[0],'xxxx00000000',1)):
            with self.subTest(text=bad[:30]),self.assertRaises(AssertionError):runner.negative_golden(bad)

    def test_running_partial_geometry_or_promotion_claims_rejected(self):
        report=dict(status='PASS_OBSERVABLE_RAW_BOARD_PARTITIONED_XC7_MAPPING_ONLY',stage='complete',channels=32,kernels=16,
            parallel_products=512,mapped_kernel_instances=16,intended_part='xc7k480tffg1156-2',intended_clock_period_ns=20,
            bindings={name:{} for name in runner.WIDTHS},imported_kernel_circuit_identity='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE',
            commands=[dict(log=name+'.log',status='PASS',returncode=0) for name in ('version','datadir','mapping')],
            cells={'RAMB36E1':6},dsp_count=0,numerical_netlist_acceptance=False,physical_fit_verified=False,bitstream_emitted=False,hardware_programmed=False)
        runner.verify_mapping_report(report)
        for key,value in [('status','RUNNING'),('stage','mapping'),('channels',8),('kernels',8),('parallel_products',64),
            ('mapped_kernel_instances',8),('intended_part','xc7a100t'),('intended_clock_period_ns',100),('bindings',{}),
            ('imported_kernel_circuit_identity','COUNTS_ONLY'),('cells',{}),('dsp_count',1),('numerical_netlist_acceptance',True),
            ('physical_fit_verified',True),('bitstream_emitted',True),('hardware_programmed',True)]:
            changed=deepcopy(report);changed[key]=value
            with self.subTest(field=key),self.assertRaises(AssertionError):runner.verify_mapping_report(changed)
        changed=deepcopy(report);changed['commands'][2]['returncode']=1
        with self.assertRaises(AssertionError):runner.verify_mapping_report(changed)


if __name__=='__main__':unittest.main()
