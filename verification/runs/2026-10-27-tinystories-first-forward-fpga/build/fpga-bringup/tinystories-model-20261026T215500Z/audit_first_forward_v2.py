"""Read-only independent model receipt and actual raw scan audit; no execution."""
from pathlib import Path
import ast,base64,datetime,hashlib,json,sys,zlib
R=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent;P=W/'physical-tests'
sys.path.insert(0,str(R))
def need(c,m):
 if not c:raise ValueError(m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
# Reuse only the reviewed pure decoder function, never the old audit's main.
source=(R/'build/fpga-bringup/tinystories-dual-20261026T221500Z/audit_physical.py').read_text()
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='decode')
exec(compile(ast.Module(body=[node],type_ignores=[]),'<reviewed-pure-scan-decoder>','exec'))
def raw(e):
 data=zlib.decompress(base64.b64decode(e['output_zlib_base64'],validate=True))
 need(len(data)==e['whole_bo_bytes'] and hashlib.sha256(data).hexdigest()==e['output_sha256'],'Raw BO blob differs');return data
record=dict(status='RUNNING',hardware_accessed=False,scope='Independent first complete BOS forward only, all36 learned projections; the longer32-position run remains separate, no new hardware access')
try:
 parent=load(P/'report.json');review=load(W/'image-review.json')
 need(parent.get('first_forward_logits_match_donor_bit_exact') is True,'First full forward gating incomplete')
 need(parent['flash_written'] is False and len(parent['loads'])==1 and len(parent['tests'])>=1,'Wrong action scope')
 need(parent['image_review_sha256']==sha(W/'image-review.json'),'Image review changed')
 for p,h in review['bound_files'].items():need(sha(p)==h,'Changed source '+p)
 # The outer32-position run may still be active; the first worker is closed.

 l=load(P/'load-1/load.json');need(l['status']=='PASS' and l['flash_written'] is False,'Bad load')
 need(all(l['native'].get(k)==v for k,v in dict(DNA_PORT='004E544714C705C',IDCODE_BEFORE='23751093',IDCODE_AFTER='23751093',INIT_COMPLETE='1',DONE='1',USR_ACCESS='1e01179c',TCK_HZ='3000000',CLEANUP='1',PASS='1').items()),'Wrong image/target')
 reference=R/'build/tinystories-full-oracle/v1';oracle=load(reference/'donor-dense-calls.json')
 catalog=load(R/'build/tinystories-programs/all-v1/report.json');programs={}
 for p in catalog['programs']:
  for key in ('cmac','compaction'):
   job=p[key];cmd=zlib.decompress(base64.b64decode(job['command_bo']['zlib_base64']));programs.setdefault((job['profile'],job['amount']),set()).add(hashlib.sha256(cmd).hexdigest())
 package=load(R/'build/tinystories-preparation/260k-first-v2/report.json')
 buffers=package['candidate_buffers'];phases=[]
 projection_map={p['name']:p for p in package['projections']}
 tile_map={name:[t for t in package['tiles'] if t['projection']==name] for name in projection_map}
 program_map={(p['projection'],p['first_output']):p for p in catalog['programs']}
 def memory_bytes(memory,address,size):
  need(address%64==0 and size%64==0,'Nonphysical audit extent')
  return b''.join(memory[address+i] for i in range(0,size,64))
 def original_bo(item):
  data=zlib.decompress(base64.b64decode(item['zlib_base64'],validate=True))
  need(len(data)==item['size'] and hashlib.sha256(data).hexdigest()==item['sha256'],'Catalog BO changed')
  return data
 for summary,positions in zip(parent['tests'][:1],(1,)):
  J=P/summary['name']/'jobs';child=load(J/'report.json')
  need(sha(J/'report.json')==summary['report_sha256'] and child['status']=='PASS_PHYSICAL_HYBRID_MODEL_EXECUTION_REQUIRES_INDEPENDENT_AUDIT' and child['bridge_quit_ack'],'Bad worker')
  need(child['completed_projections']==positions*36 and child['raw_jobs']==positions*232 and child['raw_completed_tasks']==positions*348,'Missing projection/jobs/tasks')
  for n,h in child['artifacts'].items():need(sha(J/n)==h,'Changed first worker artifact '+n)
  calls=load(J/'dense-calls.json');need(len(calls)==positions*36,'Missing calls')
  need(all(all(a[k]==b[k] for k in ('name','input_fp16_sha256','output_fp16_sha256')) for a,b in zip(calls,oracle[:positions*36])),'Dense bytes differ from independent oracle')
  need((J/'logits.bin').read_bytes()==(reference/'donor-logits.bin').read_bytes()[:positions*512*4],'Full logits differ')
  if positions==1:
   gold=load(R/'build/tinystories-standalone-worker/bos-one-v1/report.json')['result']
   need(all(child['result'][k]==gold[k] for k in ('generated_tokens','input_tokens','prompt_tokens','text','forward_positions','dense_calls')),'BOS-only generated token/text differs')
  if positions==32:

   gold=load(reference/'donor-result.json')
   need(all(child['result'][k]==gold[k] for k in ('generated_tokens','input_tokens','prompt_tokens','text','forward_positions','dense_calls')),'Token/text sequence differs')
  events=load(J/'raw-jobs.json');commands,counts=decode(J/'native-scans.jsonl')
  schedule=[]
  for call_index,call in enumerate(calls):
   tiles=tile_map[call['name']]
   need(call['first_job']==len(schedule) and call['raw_jobs']==2*len(tiles),'Projection/raw job boundaries differ')
   for tile_index,tile in enumerate(tiles):
    program=program_map[call['name'],tile['first_output']]
    for kind in ('cmac','compaction'):
     schedule.append(dict(call=call_index,tile=tile_index,kind=kind,original=program[kind],first=(tile_index==0 and kind=='cmac'),last=(tile_index==len(tiles)-1 and kind=='compaction')))
  need(len(schedule)==len(events),'Incomplete static raw schedule')
  memory={};staged={};active=None;finished=[]
  for x in commands:
   op,a,value,rsp=x['op'],x['address'],x['data'],x['response']
   if op in (2,4):need(rsp==0,'Write response error')
   if op==4:
    need(active is None and a%64==0,'Upload while active')
    memory[a]=value.to_bytes(64,'little')
   if op==3:
    need(a%64==0,'Unaligned readback')
    data=rsp.to_bytes(64,'little')
    if active is None:need(memory.get(a)==data,'Uploaded bytes not verified on wire')
    else:active['reads'][a]=data
   if op==2:
    base=256 if a&256 else 0;offset=a-base
    if offset in (0x10,0x14,0x18):
     need(active is None and offset not in staged,'Descriptor overlap');staged[offset]=value
    elif offset==12 and value==1:
     need(active is None and set(staged)=={16,20,24},'Incomplete descriptor')
     profile='cmac' if base else 'ew';address=staged[16]
     cmd=b''.join(memory[address+i] for i in range(0,65536,64))
     plan=schedule[len(finished)];original=plan['original'];call=calls[plan['call']];proj=projection_map[call['name']]
     need(profile==original['profile'] and staged[20]==original['amount'] and cmd==original_bo(original['command_bo']),'Actual full command BO differs from exact original tile')
     tasks=memory_bytes(memory,buffers['tasks']['address'],buffers['tasks']['bytes'])
     raw_tasks=original_bo(original['task_bo'])
     need(tasks==raw_tasks+bytes(len(tasks)-len(raw_tasks)),'Actual complete task BO differs from original writer')
     if plan['first']:
      input_bo=memory_bytes(memory,buffers['input']['address'],buffers['input']['bytes'])
      logical=2*proj['inputs']
      need(hashlib.sha256(input_bo[:logical]).hexdigest()==oracle[plan['call']]['input_fp16_sha256'] and not any(input_bo[logical:]),'Actual contiguous input BO or zero padding differs from oracle contract')
     if len(finished)==0:
      for tile in package['tiles']:
       need(memory_bytes(memory,tile['address'],tile['bytes'])==(R/'build/tinystories-preparation/260k-first-v2'/tile['file']).read_bytes(),'Actual resident packed weight bytes differ')
     active=dict(base=base,profile=profile,tag=staged[24],amount=staged[20],reads={},regs={});staged={}
    elif offset==12 and value==2:
     need(active is not None and active['base']==base,'Wrong ACK namespace')
     event=events[len(finished)];need(event['profile']==active['profile'] and event['tag']==active['tag'] and event['ack_after_readback'],'Wrong wire job')
     need(active['regs'].get(base+28)==event['tag'] and active['regs'].get(base+32)==event['tasks'] and active['regs'].get(base+36)==0,'Wrong completion')
     data=raw(event);address=buffers[event['output']]['address']
     plan=schedule[len(finished)];call=calls[plan['call']]
     if plan['last']:
      logical=2*projection_map[call['name']]['outputs']
      need(hashlib.sha256(data[:logical]).hexdigest()==oracle[plan['call']]['output_fp16_sha256'],'Actual final contiguous dense output bytes differ from oracle')
     need(active['reads']=={address+i:data[i:i+64] for i in range(0,len(data),64)},'Actual complete output BO differs before ACK')
     # Retain device-owned output bytes for later CPU delta verification only.
     memory.update(active['reads']);finished.append(active);active=None
    else:raise ValueError('Unmodeled CSR write')
   if op==1 and active is not None:active['regs'][a]=rsp
  need(active is None and not staged and len(finished)==len(events)==positions*232,'Missing raw completion')
  phases.append(dict(name=summary['name'],positions=positions,projections=positions*36,raw_jobs=len(finished),tasks=positions*348,wire=counts,logits_sha256=sha(J/'logits.bin')))
 record.update(status='PASS_INDEPENDENT_PHYSICAL_TINYSTORIES_FIRST_FORWARD_EXACT_PROGRAM_INPUT_WEIGHT_OUTPUT_AUDIT',phases=phases,actual_projection_input_and_output_pairs_checked=36,actual_resident_weight_tiles_checked=116,actual_original_raw_program_bos_checked=232,source_sha256=review['source_sha256'],bitstream_sha256=review['bitstream']['sha256'],flash_written=False,learned_dense_cpu_fallback=False,fp32_reference_boundary='FPGA matches separate donor-policy reference bit-exact; FP32 drift remains separate')
except BaseException as e:record.update(status='FAIL',error=repr(e));raise
finally:
 record['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();record['auditor_sha256']=sha(__file__);(W/'independent-first-forward-audit-v2.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
