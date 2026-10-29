from pathlib import Path
import dataclasses,hashlib,json,sys,tempfile
from unittest.mock import patch
ROOT=Path('/home/fedora/rknpu-fpga');sys.path.insert(0,str(ROOT))
from tools.tinystories import run_projection as w
V=ROOT/'build/tinystories-joined-vectors/v2'
checks=[]
@dataclasses.dataclass
class Completion:
 tag:int
 completed_tasks:int
 error_code:int=0
class Link:
 def __init__(self,*a):self.host='mock';self.port=3741;self.closed=False
 def shutdown_bridge(self):self.closed=True
 def close(self):self.closed=True
class Transport:
 last=None
 def __init__(self,*a,**kw):self.memory={};self.profile='ew';self.count=0;self.acks=0;Transport.last=self
 def select_profile(self,p):self.profile=p
 def reg_read(self,o):return {0:0x524b4557 if self.profile=='ew' else 0x524b434d,4:65536,8:16}[o]
 def mem_write(self,a,d):
  for i,x in enumerate(d):self.memory[a+i]=x
 def mem_read(self,a,n):return bytes(self.memory[a+i] for i in range(n))
 def submit(self,a,amount,tag):
  assert amount==(45 if self.profile=='cmac' else 22)
  self.tag=tag
  words=w.lines(V/('ew_expected.txt' if self.profile=='ew' else ('cmac_expected.txt' if self.count==0 else 'repeat_expected.txt')))
  for addr,data in words.items():self.mem_write(addr,data)
  if scenario=='guard':self.memory[0x10010000+512]^=1
  self.count+=1
 def poll_result(self,timeout):return Completion(self.tag+int(scenario=='tag'),(1 if self.profile=='cmac' else 2)+int(scenario=='tasks'),int(scenario=='error'))
 def ack_success(self):self.acks+=1
 def close(self):pass
for scenario in ('good','guard','tag','tasks','error'):
 with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='projection-mock-') as d:
  out=Path(d)/'run';failed=False
  argv=['run_projection','--vectors',str(V),'--vectors-sha256',w.sha(V/'report.json'),'--out',str(out),'--quit-bridge']
  with patch.object(sys,'argv',argv),patch.object(w,'RecordedNativeLink',Link),patch.object(w,'DualRawTransport',Transport):
   try:w.main()
   except ValueError:failed=True
  report=json.loads((out/'report.json').read_text())
  assert failed==(scenario!='good')
  assert Transport.last.acks==(4 if scenario=='good' else 0)
  assert report['status']==('PASS_PHYSICAL_TRAINED_TILE_COMPACTION_AND_REARM_REQUIRES_AUDIT' if scenario=='good' else 'FAIL')
  checks.append(dict(scenario=scenario,status='PASS',acks=Transport.last.acks))
Path(__file__).with_name('harness-controls.json').write_text(json.dumps(dict(status='PASS_OFFLINE_TRAINED_PROJECTION_HARNESS_CONTROLS_ONLY',hardware_accessed=False,checks=checks,worker_sha256=w.sha(w.__file__)),indent=2)+'\n')
print('PASS_OFFLINE_HARNESS_CONTROLS',len(checks))
