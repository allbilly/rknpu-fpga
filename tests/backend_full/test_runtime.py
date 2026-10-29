import struct, ctypes, json, os, pickle, socket, sys, unittest, zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tools.backend import runtime as base
ROOT=Path(__file__).resolve().parents[2]
BACKEND=Path(os.environ.get('TINYGRAD_ROOT', os.environ.get('RKNPU_TINYGRAD', str(Path.home()/'tinygrad'))))
from tools.backend import full_runtime as mod
class Transport:
 def __init__(self): self.memory={}; self.calls=[]; self.tag=0; self.fail=False; self.bad_tag=False; self.tasks=1
 def reg_read(self,n): return {0:0x524b4144,4:0x10000,8:0x10}[n]
 def select_profile(self,p): self.calls.append(('profile',p))
 def compute_reset(self,timeout): self.calls.append(('reset',)); return {'status':'ok'}
 def mem_write(self,a,d): self.calls.append(('write',a,len(d))); self.memory[a]=bytes(d)
 def mem_read(self,a,n): self.calls.append(('read',a,n)); return self.memory[a][:n]
 def submit(self,a,n,t): self.calls.append(('submit',a,n,t)); self.tag=t
 def poll_result(self,timeout):
  self.calls.append(('poll',)); return SimpleNamespace(tag=self.tag+int(self.bad_tag),completed_tasks=self.tasks,error_code=int(self.fail),status=0x714)
 def ack_success(self): self.calls.append(('ack',))
 def close(self): pass
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if not BACKEND.exists(): raise unittest.SkipTest('UNAVAILABLE: pinned tinygrad checkout is required')
  cls.rt,cls.rr,_,cls.receipt=base._load_backend(BACKEND)
 def setUp(self):
  self.patches=[patch.object(socket,'create_connection',side_effect=AssertionError('network')),patch.object(self.rt.FileIOInterface,'__init__',side_effect=AssertionError('DRM'))]
  for p in self.patches:p.start();self.addCleanup(p.stop)
  self.t=Transport(); self.d=mod.make_device_class(lambda:self.t,BACKEND)(); self.addCleanup(self.d.finalize)
 def program(self,img): return self.d.runtime(SimpleNamespace(name='mock_byte_contract',lib=zlib.compress(pickle.dumps(img,protocol=5))))
 def fixture_program(self,c):
  def decode(value):
   if type(value) is not dict: return value
   if value.get('type') == 'tuple' and set(value) == {'type','items'}:
    return tuple(decode(item) for item in value['items'])
   if value.get('class') == 'RKArg' and set(value) == {'class','fields','type'}:
    f=value['fields']; return self.rr.RKArg(self.rr.RKBufferKind[f['kind']['name']],f['index'],f['addend'])
   if value.get('class') == 'RKGather' and set(value) == {'class','fields','type'}:
    f=value['fields']; return self.rr.RKGather(**{k:decode(v) for k,v in f.items()})
   raise ValueError('Unsupported fixture encoding')
  gathers=tuple(decode(plan) for plan in c['rkgather_plans'])
  dims=c['encoded_dimensions']; scratch=tuple(c['scratch_bytes'])
  cmac=self.rr.RKCMAC(self.rr.RKArg(self.rr.RKBufferKind.SCRATCH,2),self.rr.RKArg(self.rr.RKBufferKind.SCRATCH,0),self.rr.RKArg(self.rr.RKBufferKind.SCRATCH,1),dims['m'],dims['n'],dims['k'])
  image=self.rr.RKImage(scratch,(gathers[0],gathers[1],cmac,gathers[2]))
  return self.program(image)
 def test_captures(self):
  self.assertIs(self.d.runtime_t._submit_bodies,self.rt.RockchipProgram._submit_bodies); self.assertIs(self.d.runtime_t._submit,self.rt.RockchipProgram._submit)
  self.assertEqual(sum(x[0]=='reset' for x in self.t.calls),1)
  fixtures=json.loads((ROOT/'tests/backend_layout/fixtures.json').read_text())
  for c in fixtures['cases']:
   with self.subTest(case=c['name']):
    p=self.fixture_program(c); bufs=[self.d._gpu_alloc(32768) for _ in range(3)]
    before=len(self.t.calls); lr=len(self.d.layout_records)
    with patch.object(self.rt,'_apply_gathers',side_effect=AssertionError('CPU gather')),patch.object(self.rt,'_regular_gather_payload',side_effect=AssertionError('CPU gather')): p(*bufs)
    calls=self.t.calls[before:]; profiles=[x[1] for x in calls if x[0]=='profile']; self.assertIn('cmac',profiles); self.assertIn('layout',profiles)
    submits=[i for i,x in enumerate(calls) if x[0]=='submit']; acks=[i for i,x in enumerate(calls) if x[0]=='ack']; self.assertEqual(len(submits),len(acks))
    records={r['tag']:r for r in self.d.records+self.d.layout_records if 'tag' in r}
    for s,a in zip(submits,acks):
     self.assertEqual({x[1] for x in calls[s:a] if x[0]=='read'},set(records[calls[s][3]]['after']))
    self.assertEqual([records[calls[i][3]]['profile'] for i in submits], ['layout','layout','cmac','layout'])
    self.assertEqual([x[0] for x in calls if x[0] in ('submit','reset')],['submit','submit','reset','submit','reset','submit'])
    layout=self.d.layout_records[lr:]
    for r,values in zip(layout,(c['expected_indices'][k] for k in ('input_a','weight','output'))):
     self.assertEqual(r['index_bytes'],struct.pack('<%dI'%len(values),*(0xffffffff if x == -1 else x for x in values)))
    cmac=next(op for op in p.image.program if type(op) is self.rr.RKCMAC)
    arena=self.d._buffers['scratch']
    def address(arg):
     b=bufs[arg.index] if arg.kind is self.rr.RKBufferKind.ARG else arena.offset(p._scratch_offsets[arg.index],p.image.scratch[arg.index])
     return b.meta.dma_addr+b.va_addr-b.base.va_addr+arg.addend
    body=self.rr.emit_cmac_stage(cmac,address)
    expected=body+(0x0001000000000000,0x0101000000000014,0x0041000000000000,0x00810000000d0008)
    rec=self.d.records[-1]; self.assertEqual(rec['command_bytes'][0],struct.pack('<49Q',*expected))
    self.assertEqual(rec['tasks'][0],dict(flags=0,op_idx=0,enable_mask=13,int_mask=0x300,int_clear=0x1ffff,int_status=0,regcfg_amount=45,regcfg_offset=0,regcmd_addr=rec['address']))
    for b in bufs:self.d._gpu_free(b)
 def test_preflight_allocation_rollback_on_partial_layout_pair(self):
  c=json.loads((ROOT/'tests/backend_layout/fixtures.json').read_text())['cases'][0]
  p=self.fixture_program(c); bufs=[self.d._gpu_alloc(32768) for _ in range(3)]
  self.d._ensure_buffer('scratch',p._scratch_offsets[-1],p._scratch_offsets[-1])
  remaining=base.CAPACITY-sum(item.physical_size for item in self.d._owned.values())-base.PAGE
  self.assertGreater(remaining,0)
  self.d._gpu_alloc(remaining)
  owned_before=set(self.d._owned)
  layouts_before=dict(p._layout_buffers)
  calls_before=list(self.t.calls)
  with self.assertRaises(MemoryError): p(*bufs)
  self.d._check_healthy()
  self.assertEqual(set(self.d._owned),owned_before)
  self.assertEqual(p._layout_buffers,layouts_before)
  self.assertEqual(self.t.calls,calls_before)
  self.d._check_healthy()
 def test_reset_no_copy(self):
  b=self.d._gpu_alloc(4096); ctypes.memmove(b.va_addr,b'hello',5); before=len(self.t.calls); self.d.reset_npu(); self.assertEqual(self.t.calls[before:],[('reset',)]); self.assertEqual(ctypes.string_at(b.va_addr,5),b'hello')
 def test_invalid_timeout_preflight_does_not_poison(self):
  c=json.loads((ROOT/'tests/backend_layout/fixtures.json').read_text())['cases'][0]; p=self.fixture_program(c); bufs=[self.d._gpu_alloc(32768) for _ in range(3)]
  original=os.environ.get('ROCKCHIP_SUBMIT_TIMEOUT_MS')
  before=list(self.t.calls)
  try:
   os.environ['ROCKCHIP_SUBMIT_TIMEOUT_MS']='bogus'
   with self.assertRaises(base.UnsupportedProfile): p(*bufs)
   self.assertEqual(self.t.calls,before)
   self.assertFalse(self.d._poisoned)
   self.d._check_healthy()
   os.environ['ROCKCHIP_SUBMIT_TIMEOUT_MS']='6000'
   p(*bufs)
   self.assertFalse(self.d._poisoned)
   self.assertTrue(any(x[0]=='submit' for x in self.t.calls[len(before):]))
  finally:
   if original is None: os.environ.pop('ROCKCHIP_SUBMIT_TIMEOUT_MS',None)
   else: os.environ['ROCKCHIP_SUBMIT_TIMEOUT_MS']=original
 def test_failure_poison(self):
  c=json.loads((ROOT/'tests/backend_layout/fixtures.json').read_text())['cases'][0]; p=self.fixture_program(c); self.t.fail=True
  with self.assertRaises(base.UnsupportedProfile): p(*[self.d._gpu_alloc(32768) for _ in range(3)])
  self.assertTrue(self.d._poisoned); self.assertFalse(any(x[0]=='ack' for x in self.t.calls))
  with self.assertRaises(RuntimeError): p()
 def test_options_and_bad_ops(self):
  c=json.loads((ROOT/'tests/backend_layout/fixtures.json').read_text())['cases'][0]; p=self.fixture_program(c); bufs=[self.d._gpu_alloc(32768) for _ in range(3)]
  for opts in ({'vals':(1,)},{'global_size':(2,1,1)},{'local_size':(True,1,1)},{'wait':1},{'timeout':1}):
   with self.subTest(opts=opts),self.assertRaises(base.UnsupportedProfile):p(*bufs,**opts)
  image=p.image; cmac=next(x for x in image.program if type(x) is self.rr.RKCMAC); gather=next(x for x in image.program if type(x) is self.rr.RKGather)
  bad=[cmac._replace(relu=True),gather._replace(index=gather.src),gather._replace(partial=True),gather._replace(itemsize=4)]
  for op in bad:
   with self.subTest(op=op),self.assertRaises(base.UnsupportedProfile):self.program(image._replace(program=(op,cmac)))
  self.assertFalse(any(x[0]=='submit' for x in self.t.calls))
 def test_bindings_and_mutation(self):
  c=json.loads((ROOT/'tests/backend_layout/fixtures.json').read_text())['cases'][0]; p=self.fixture_program(c); bufs=[self.d._gpu_alloc(32768) for _ in range(3)]
  for bad in (bufs[:2], [self.d._gpu_alloc(2),bufs[1],bufs[2]]):
   with self.subTest(bad=bad),self.assertRaises((base.UnsupportedProfile,ValueError)): p(*bad)
  b=self.d._gpu_alloc(32768); self.d._gpu_free(b)
  with self.assertRaises((base.UnsupportedProfile,RuntimeError)): p(b,bufs[1],bufs[2])
  p.image=p.image._replace(scratch=(8192,))
  with self.assertRaises(base.UnsupportedProfile):p(*bufs)
  self.assertFalse(any(x[0]=='submit' for x in self.t.calls))
 def test_cmac_alias_and_internal_buffer(self):
  a=lambda i:self.rr.RKArg(self.rr.RKBufferKind.ARG,i,0)
  op=self.rr.RKCMAC(a(0),a(1),a(2),1,16,32); p=self.program(self.rr.RKImage((),(op,)))
  b=[self.d._gpu_alloc(32768) for _ in range(3)]
  with self.assertRaises(base.UnsupportedProfile):p(b[0],b[0],b[2])
  internal=self.d._ensure_buffer('scratch',32768,32768)
  with self.assertRaises(base.UnsupportedProfile):p(internal,b[1],b[2])
  self.assertFalse(any(x[0]=='submit' for x in self.t.calls))
 def test_bad_task_count(self):
  c=json.loads((ROOT/'tests/backend_layout/fixtures.json').read_text())['cases'][0]; p=self.fixture_program(c); self.t.tasks=2
  with self.assertRaises(base.UnsupportedProfile):p(*[self.d._gpu_alloc(32768) for _ in range(3)])
  self.assertTrue(self.d._poisoned); self.assertFalse(any(x[0]=='ack' for x in self.t.calls))
 def test_bad_completion_tag(self):
  c=json.loads((ROOT/'tests/backend_layout/fixtures.json').read_text())['cases'][0]; p=self.fixture_program(c); self.t.bad_tag=True
  with self.assertRaises(base.UnsupportedProfile):p(*[self.d._gpu_alloc(32768) for _ in range(3)])
  self.assertTrue(self.d._poisoned); self.assertFalse(any(x[0]=='ack' for x in self.t.calls))
if __name__=='__main__': unittest.main(verbosity=2)
