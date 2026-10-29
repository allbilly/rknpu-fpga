#!/usr/bin/env python3
"""Root test harness: raw captured BO jobs over an already audited native link.

Software arithmetic is exclusively a post-execution test expectation. It never
receives a hardware transport or supplies a result to the runtime/FPGA path.
"""
from pathlib import Path
import argparse, base64, dataclasses, datetime, hashlib, json, struct, sys, time, zlib
ROOT=Path('/home/fedora/rknpu-fpga');sys.path.insert(0,str(ROOT))
from tools.host.native_link import NativeLink
from tools.host.transport import JtagTransport,JobError,ProtocolError
from tools.dma_fixtures import production_cases,replay

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def need(c,m):
 if not c:raise RuntimeError(m)
def write(p,r):p.write_text(json.dumps(r,indent=2)+'\n')
def blob(raw):
 return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),zlib_base64=base64.b64encode(zlib.compress(raw)).decode())

class TraceLink(NativeLink):
 def __init__(self,trace):
  self.trace=trace;self.scans=0;self.requests=[]
  super().__init__(host='127.0.0.1',port=3741,timeout=30)
 def scan(self,value,bits=640,*,ir=False,deadline=None):
  if not ir and bits==640 and value:self.requests.append(((value>>548)&255,(value>>512)&0xffffffff))
  item=dict(index=self.scans,utc=now(),bits=bits,ir=ir,tdi=f'{value:x}')
  try:
   result=super().scan(value,bits,ir=ir,deadline=deadline)
   item['tdo']=f'{result:x}';return result
  except BaseException as error:item['error']=str(error);raise
  finally:
   self.scans+=1;self.trace.write(json.dumps(item,separators=(',',':'))+'\n');self.trace.flush()
 def reset(self,*,deadline=None):
  self.trace.write(json.dumps(dict(event='TAP_RESET_NOT_FABRIC_RESET',utc=now()))+'\n');self.trace.flush()
  return super().reset(deadline=deadline)

def positive(transport,case,out,tag,name):
 # Build test expectations before any card transfers; input BOs stay verbatim.
 expected,oracle=replay(case)
 record=dict(status='RUNNING',name=name,started_utc=now(),raw_descriptor=dict(address=case['address'],initial_amount=case['amount'],tag=tag),
             numerical_cpu_fallback=False,reference_scope='Test expectation only',regions=[])
 path=out/(name+'.json')
 for address,data in sorted(case['regions'].items()):
  record['regions'].append(dict(address=address,input=blob(data),expected=blob(bytes(expected.regions[address]))))
 write(path,record)
 try:
  for address,data in sorted(case['regions'].items()):transport.mem_write(address,data)
  transport.submit(case['address'],case['amount'],tag)
  result=transport.poll_result(timeout=30)
  record['completion']=dataclasses.asdict(result);write(path,record)
  need(result.tag==tag and result.completed_tasks==case['tasks'] and result.error_code==0,'Unexpected completion snapshot')
  checked=0
  for region in record['regions']:
   address=region['address'];golden=bytes(expected.regions[address])
   observed=transport.mem_read(address,len(golden));region['observed']=blob(observed);region['matches']=observed==golden
   write(path,record)
   need(observed==golden,'Complete BO mismatch at '+hex(address));checked+=len(observed)
  # ACK only after every owned byte (including command BO and padding) matches.
  transport.ack_success();record.update(status='PASS',bytes_checked=checked,ack_after_complete_readback=True,
      oracle_command_reads=oracle.command_reads,oracle_memory_transactions=oracle.memory_transactions,finished_utc=now())
 except BaseException as error:
  record.update(status='FAIL',error=str(error),finished_utc=now());raise
 finally:write(path,record)
 return dict(name=name,status=record['status'],bytes_checked=record['bytes_checked'],report_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def unknown_register(transport,case,out,tag):
 # Explicitly synthetic negative control: change only the first raw word's
 # target/offset to an unsupported DPU register. Do not change expected faults.
 regions=dict(case['regions']);base=case['address'];raw=bytearray(regions[base]);original=bytes(raw[:8])
 old=struct.unpack_from('<Q',raw)[0];bad=(0x1001<<48)|(old&0x0000ffffffff0000)|0x4074
 struct.pack_into('<Q',raw,0,bad);regions[base]=bytes(raw)
 record=dict(status='RUNNING',name='synthetic_unknown_register',started_utc=now(),tag=tag,expected_error_code=1,
  changed_bytes=dict(address=base,original=original.hex(),replacement=bytes(raw[:8]).hex()),regions=[dict(address=a,input=blob(d)) for a,d in sorted(regions.items())])
 path=out/'synthetic_unknown_register.json';write(path,record)
 try:
  for address,data in sorted(regions.items()):transport.mem_write(address,data)
  transport.submit(base,case['amount'],tag)
  try:transport.poll_result(timeout=30)
  except JobError as error:
   result=error.result;record['completion']=dataclasses.asdict(result)
   need(result.tag==tag and result.error_code==1 and result.completed_tasks==0,'Unknown register did not produce E1 before task execution')
  else:raise RuntimeError('Unknown register was silently accepted')
  before=transport.link.scans
  for action in (lambda:transport.mem_read(base,64),transport.ack_success):
   try:action()
   except ProtocolError:pass
   else:raise RuntimeError('Faulted owner remained usable')
  need(transport.link.scans==before,'Poisoned owner issued another scan')
  record.update(status='PASS_EXPECTED_E1_AND_POISONED_OWNER',finished_utc=now(),ack_sent=False)
 except BaseException as error:record.update(status='FAIL',error=str(error),finished_utc=now());raise
 finally:write(path,record)
 return dict(name=record['name'],status=record['status'],report_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--mode',choices=('suite','sticky-fault','recovery'),required=True);args=parser.parse_args()
 args.out.mkdir(parents=True,exist_ok=False)
 record=dict(status='RUNNING',mode=args.mode,started_utc=now(),scope='Actual USER2 physical raw captured EW BO execution; separate from full512, DDR, PCIe and RK equivalence',tests=[])
 link=transport=None;failure=None
 with (args.out/'scans.jsonl').open('w') as trace:
  try:
   link=TraceLink(trace);transport=JtagTransport(host=link.host,port=link.port,frequency_hz=6000000,link=link)
   record['identity']=dict(id=transport.reg_read(0),abi=transport.reg_read(4),status=transport.reg_read(8),actual_tck_frequency_hz=link.actual_frequency_hz,actual_tck_period_ns=dict(numerator=link.actual_period_ns.numerator,denominator=link.actual_period_ns.denominator))
   cases=production_cases();sub9=next(c for c in cases if c['name']=='capture_sub_9')
   if args.mode=='sticky-fault':
    status=transport.reg_read(8);code=transport.reg_read(0x24)
    need(status&8 and status&32 and code==1,'TAP reset/reconnect unexpectedly cleared fabric fault')
    before=len(link.requests)
    try:transport.mem_read(0x10000000,64)
    except ProtocolError:pass
    else:raise RuntimeError('Faulted fabric allowed memory access')
    need(link.requests[before:]==[(1,8)],'Expected only a status request before refusing memory')
    record['tests'].append(dict(name='sticky_fault_across_new_bridge_and_TAP_reset',status='PASS',rke_status=status,error_code=code,memory_read_opcode_sent=False))
   elif args.mode=='recovery':record['tests'].append(positive(transport,sub9,args.out,0x3588f001,'sub9_after_reconfiguration'))
   else:
    for index,case in enumerate(cases):
     result=positive(transport,case,args.out,0x35880001+index,case['name']);record['tests'].append(result);write(args.out/'report.json',record);print(json.dumps(result),flush=True)
    record['tests'].append(positive(transport,sub9,args.out,0x3588ff01,'sub9_repeat_without_rebuild'))
    record['tests'].append(unknown_register(transport,sub9,args.out,0x3588bad1))
   record.update(status='PASS',finished_utc=now(),scans=link.scans)
  except BaseException as error:failure=error;record.update(status='FAIL',error=str(error),finished_utc=now())
  finally:
   if link is not None:
    try:link.shutdown_bridge();record['bridge_clean_quit']=True
    except BaseException as error:record.update(status='FAIL',bridge_cleanup_error=str(error));failure=failure or error
   if transport is not None:transport.close()
   elif link is not None:link.close()
   write(args.out/'report.json',record)
 if failure is not None:raise failure
 print(json.dumps(dict(status=record['status'],mode=args.mode,report=str(args.out/'report.json'))),flush=True)

if __name__=='__main__':main()
