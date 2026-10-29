from pathlib import Path
import dataclasses,importlib.util,json,sys,tempfile,unittest
ROOT=Path('/home/fedora/rknpu-fpga');sys.path.insert(0,str(ROOT))
work=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('jobs_under_test',work/'run_jobs.py');jobs=importlib.util.module_from_spec(spec);spec.loader.exec_module(jobs)
from model.sim import Memory
from model.dma import DMAEmulator
from tools.host.transport import JobResult
class FakeTransport:
 def __init__(self,corrupt=False):self.memory=Memory();self.acked=False;self.corrupt=corrupt;self.read=0;self.tag=None
 def mem_write(self,address,data):self.memory.map(address,data)
 def submit(self,address,amount,tag):self.tag=tag;self.emulator=DMAEmulator(self.memory);self.emulator.submit_dma(address,amount)
 def poll_result(self,timeout):return JobResult(self.tag,self.emulator.completed,0,4)
 def mem_read(self,address,size):
  self.read+=size;data=bytes(self.memory.regions[address])
  return bytes([data[0]^1])+data[1:] if self.corrupt else data
 def ack_success(self):self.acked=True
class Controls(unittest.TestCase):
 def test_good_full_captured_bos_ack_after_all_bytes(self):
  case=next(c for c in jobs.production_cases() if c['name']=='capture_sub_9')
  with tempfile.TemporaryDirectory() as name:
   t=FakeTransport();r=jobs.positive(t,case,Path(name),123,'good')
   self.assertEqual(r['bytes_checked'],102400);self.assertEqual(t.read,102400);self.assertTrue(t.acked)
   saved=json.loads((Path(name)/'good.json').read_text());self.assertTrue(saved['ack_after_complete_readback']);self.assertTrue(all(x['matches'] for x in saved['regions']))
 def test_mismatch_preserves_failure_without_ack(self):
  case=jobs.production_cases()[0]
  with tempfile.TemporaryDirectory() as name:
   t=FakeTransport(True)
   with self.assertRaisesRegex(RuntimeError,'Complete BO mismatch'):jobs.positive(t,case,Path(name),124,'bad')
   self.assertFalse(t.acked);saved=json.loads((Path(name)/'bad.json').read_text());self.assertEqual(saved['status'],'FAIL');self.assertFalse(saved['regions'][0]['matches']);self.assertIn('observed',saved['regions'][0])
 def test_wrong_fault_code_cannot_pass(self):
  class WrongFault:
   def mem_write(self,*args):pass
   def submit(self,*args):pass
   def poll_result(self,timeout):raise jobs.JobError(JobResult(125,0,2,44))
  case=next(c for c in jobs.production_cases() if c['name']=='capture_sub_9')
  with tempfile.TemporaryDirectory() as name:
   with self.assertRaisesRegex(RuntimeError,'E1'):jobs.unknown_register(WrongFault(),case,Path(name),125)
   self.assertEqual(json.loads((Path(name)/'synthetic_unknown_register.json').read_text())['status'],'FAIL')
if __name__=='__main__':unittest.main()
