"""Independent read-only trained-tile raw-scan/complete-BO/target audit."""
from pathlib import Path
import datetime,hashlib,json,sys
R=Path('/home/fedora/rknpu-fpga');sys.path.insert(0,str(R))
from tools.tinystories.run_projection import lines,regions
W=Path(__file__).resolve().parent;P=W/'physical-tests'
def need(c,m):
 if not c:raise ValueError(m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def decode(path):
 selected=None;pending=None;commands=[];scans=0;idcodes=0;resets=0
 with path.open() as stream:
  for text in stream:
   d=json.loads(text)
   if d.get('event')=='TAP_RESET_NOT_FABRIC_RESET':
    need(pending is None,'Reset with pending command');selected=None;resets+=1;continue
   need(d['index']==scans,'Nonsequential raw scan');scans+=1
   value=int(d['tdi'],16);response=int(d['tdo'],16);bits=d['bits']
   need(0<=value<1<<bits and 0<=response<1<<bits,'Raw scan overflow')
   if d['ir']:
    need(bits==6 and value in (3,9,63) and pending is None,'Unsafe/mid-request IR');selected=value;continue
   if bits==32:
    need(selected==9 and value==0 and response==0x23751093,'Wrong raw IDCODE');idcodes+=1;continue
   need(bits==640 and selected==3,'Unexpected DR/instruction')
   need(response>>568==0 and (response>>536)&0xffffffff==0x4f54504a,'Wrong response magic/upper bits')
   seq=(response>>520)&65535;status=(response>>512)&255;payload=response&((1<<512)-1)
   if pending is not None and pending['seq']==seq:
    need(status==0,'Unexpected mailbox error');pending['response']=payload;commands.append(pending);pending=None
   if value:
    need(pending is None and value>>604==0 and (value>>572)&0xffffffff==0x4f54504a,'Malformed/overlapping request')
    op=(value>>548)&255;seq=(value>>556)&65535;address=(value>>512)&0xffffffff;payload=value&((1<<512)-1)
    need(op in (1,2,3,4) and seq>0 and (value>>544)&15==15,'Malformed command fields')
    pending=dict(op=op,seq=seq,address=address,data=payload)
 need(pending is None and idcodes==1 and resets==1,'Incomplete TAP/request history')
 return commands,dict(scans=scans,commands=len(commands),idcodes=idcodes,tap_resets=resets)
record=dict(status='RUNNING',hardware_accessed=False,scope='Independent actual raw-scan/whole-BO/target replay, trained tile only')
try:
 parent=load(P/'report.json');review=load(W/'image-review.json')
 need(parent['status']=='PASS_TINYSTORIES_PHYSICAL_TILE_ONLY_REQUIRES_INDEPENDENT_AUDIT','Producer incomplete')
 need(parent['image_review_sha256']==sha(W/'image-review.json') and parent['flash_written'] is False and len(parent['loads'])==1,'Wrong review/load scope')
 for p,h in review['bound_files'].items():need(sha(p)==h,'Changed reviewed source '+p)
 for p,h in parent['artifacts'].items():need(sha(P/p)==h,'Changed physical artifact '+p)
 load_path=P/'load-1/load.json';load_receipt=load(load_path)
 need(sha(load_path)==parent['loads'][0]['receipt_sha256'] and load_receipt['status']=='PASS','Invalid load receipt')
 expected=dict(DNA_PORT='004E544714C705C',IDCODE_BEFORE='23751093',IDCODE_AFTER='23751093',INIT_COMPLETE='1',DONE='1',USR_ACCESS='1e01179c',CLEANUP='1',PASS='1',TCK_HZ='3000000')
 need(all(load_receipt['native'].get(k)==v for k,v in expected.items()),'Wrong image/target/configuration')
 phase=parent['tests'][0];jobs=P/phase['name']/'jobs';child=load(jobs/'report.json')
 need(sha(jobs/'report.json')==phase['report_sha256'] and child['bridge_quit_ack'],'Child changed')
 commands,counts=decode(jobs/'native-scans.jsonl')
 need(commands[0]['op']==1 and commands[0]['address']==0 and commands[0]['response']==0x524b4557,'First EW identity absent')
 need(any(x['op']==1 and x['address']==0x100 and x['response']==0x524b434d for x in commands),'CMAC identity absent')
 uploads={};pre_reads={};staged={};current=None;wire=[]
 for x in commands:
  op,a,data,rsp=x['op'],x['address'],x['data'],x['response']
  if op in (2,4):need(rsp==0,'Bad write response')
  if op==4:
   need(current is None and a%64==0 and a not in uploads,'Concurrent/duplicate upload')
   uploads[a]=data.to_bytes(64,'little')
  if op==3:
   need(a%64==0,'Unaligned read')
   target=current['readback'] if current is not None else pre_reads
   need(a not in target,'Duplicate owned readback');target[a]=rsp.to_bytes(64,'little')
  if op==2:
   base=0x100 if a&0x100 else 0;offset=a-base
   need(base in (0,256) and offset in (0xc,0x10,0x14,0x18),'Unmodeled CSR write')
   if offset in (0x10,0x14,0x18):
    need(current is None and offset not in staged,'Overlapping descriptor')
    staged[offset]=data
   elif data==1:
    need(current is None and set(staged)=={0x10,0x14,0x18},'Incomplete submit')
    current=dict(base=base,address=staged[0x10],amount=staged[0x14],tag=staged[0x18],uploads=uploads,pre_reads=pre_reads,readback={},registers={})
    wire.append(current);uploads={};pre_reads={};staged={}
   elif data==2:
    need(current is not None and current['base']==base,'Wrong ACK ownership')
    current['ack']=True;current=None
   else:raise ValueError('Unexpected doorbell')
  if op==1 and current is not None:current['registers'][a]=rsp
 need(current is None and not staged and not uploads and not pre_reads and len(wire)==4,'Incomplete/extra wire work')
 vector=R/'build/tinystories-joined-vectors/v2'
 plans=[('cmac',0x100,45,'initial.txt','cmac_expected.txt'),('ew',0,22,'ew_delta.txt','ew_expected.txt'),('cmac',0x100,45,'repeat_delta.txt','repeat_expected.txt'),('ew',0,22,'ew_delta.txt','ew_expected.txt')]
 total=0
 for i,(profile,base,amount,upload,golden) in enumerate(plans):
  actual=wire[i];receipt=child['jobs'][i];expected=lines(vector/golden)
  need((actual['base'],actual['address'],actual['amount'],actual['tag'])==(base,0x100e0000,amount,0x26000001+i),'Changed raw descriptor')
  need(actual['uploads']==actual['pre_reads']==lines(vector/upload),'Byte upload/readback differs from complete original BO delta')
  need(actual['readback']==expected and actual['ack'],'Whole physical BO mismatch/missing ACK')
  need(actual['registers'][base+0x1c]==actual['tag'] and actual['registers'][base+0x20]==(1 if profile=='cmac' else 2) and actual['registers'][base+0x24]==0,'Wire completion mismatch')
  raw=b''.join(d for _,d in regions(expected));need((jobs/('job'+str(i)+'-readback.bin')).read_bytes()==raw,'Stored actual bytes differ from wire')
  need(receipt['status']=='PASS' and receipt['ack_after_complete_readback'] and receipt['bytes_checked']==len(raw),'Receipt/ACK mismatch')
  total+=len(raw)
 need(total==360448,'Wrong complete BO inventory')
 record.update(status='PASS_INDEPENDENT_PHYSICAL_TRAINED_TILE_RAW_SCAN_AND_WHOLE_BO_REPLAY',positive_raw_jobs=4,cmac_jobs=2,ew_tasks=4,complete_bytes_checked=total,wire=counts,flash_written=False,source_sha256=review['source_sha256'],bitstream_sha256=review['bitstream']['sha256'],auditor_sha256=sha(__file__))
except BaseException as error:record.update(status='FAIL',error=repr(error));raise
finally:
 record['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();(W/'independent-physical-audit.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
