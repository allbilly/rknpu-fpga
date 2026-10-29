"""Compiler orchestration controls; no HDL, arithmetic or hardware qualification."""
from copy import deepcopy
import unittest

from tools.ddr.staged_compile import Budget,plans,verify_record


class StagedCompileTests(unittest.TestCase):
    def fixture(self):
        plan=plans('/tool/verilator','/tool/make','/tool/cxx','tb_async','/build/fresh',['-DPROFILE=1'],['/source/rtl.sv'])
        phases=[dict(status='EXITED',returncode=0,argv=plan[0],timeout_seconds=900,seconds=100),
                dict(status='EXITED',returncode=0,argv=plan[1],timeout_seconds=798,seconds=700)]
        report=dict(status='EXITED',returncode=0,timeout_seconds=900,seconds=802,argv=list(plan),phases=deepcopy(phases))
        return report,plan,phases

    def test_translation_and_cpp_are_separate_and_preserve_required_flags(self):
        _,plan,_=self.fixture();translation,cpp=plan
        for flag in ('--cc','--exe','--main','--timing','--assert','-Wall','-Wno-fatal'):
            self.assertIn(flag,translation)
        self.assertNotIn('--build',translation);self.assertNotIn('--binary',translation)
        self.assertEqual(translation[translation.index('--output-groups')+1],'0')
        self.assertEqual(cpp,['/tool/make','-C','/build/fresh/obj','-f','Vtb_async.mk','-j','1',
                             'CXX=/tool/cxx','LINK=/tool/cxx'])
        self.assertEqual(translation[-2:],['-DPROFILE=1','/source/rtl.sv'])
        with self.assertRaises(ValueError):plans('v','make','cxx','bad/top','/out',[],[])

    def test_recorded_driver_reaches_linker_and_quoted_paths(self):
        _,cpp=plans('v','make','/tool with spaces/cxx','top','/out',[],[])
        self.assertEqual(cpp[-2:],["CXX='/tool with spaces/cxx'","LINK='/tool with spaces/cxx'"])
        report,plan,phases=self.fixture()
        phases[1]['argv']=[p for p in phases[1]['argv'] if not p.startswith('LINK=')]
        report['phases']=deepcopy(phases)
        with self.assertRaises(ValueError):verify_record(report,plan,phases)

    def test_valid_single_budget_and_failed_or_changed_phases(self):
        report,plan,phases=self.fixture();verify_record(report,plan,phases)
        for mutation in ('returned_error','changed_argv','second_full_budget','over_budget','missing_phase','nonfinite'):
            with self.subTest(mutation=mutation):
                r,p,x=deepcopy((report,plan,phases))
                if mutation=='returned_error':x[1]['returncode']=1;r['phases']=x
                elif mutation=='changed_argv':x[0]['argv']=[a for a in x[0]['argv'] if a!='--assert'];r['phases']=x
                elif mutation=='second_full_budget':x[1]['timeout_seconds']=900;r['phases']=x
                elif mutation=='over_budget':r['seconds']=901
                elif mutation=='missing_phase':x=x[:1];r['phases']=x
                else:x[1]['seconds']=float('nan');r['phases']=x
                with self.assertRaises(ValueError):verify_record(r,p,x)

    def test_budget_spans_work_and_policy_validation_without_reset(self):
        now=[10.0];budget=Budget(900,clock=lambda:now[0])
        now[0]=110;self.assertEqual(budget.remaining(),800)
        now[0]=150;self.assertEqual(budget.remaining(),760)
        now[0]=910;self.assertEqual(budget.finish(),900)
        with self.assertRaises(ValueError):budget.remaining()
        now[0]=911
        with self.assertRaises(ValueError):budget.finish()
        now[0]=9
        with self.assertRaises(ValueError):budget.remaining()
        for bad in (False,0,-1,float('inf'),float('nan')):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):Budget(bad)


if __name__=='__main__':unittest.main()
