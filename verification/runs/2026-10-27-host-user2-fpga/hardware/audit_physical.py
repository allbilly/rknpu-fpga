"""Independent read-only decode of actual USER2 scans and complete BO receipts."""
from pathlib import Path
import base64,datetime,hashlib,json,sys,zlib
R=Path('/home/fedora/rknpu-fpga');sys.path.insert(0,str(R))
from tools.dma_fixtures import production_cases,replay
W=Path(__file__).resolve().parent;P=W/'physical-tests'
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(c,m):
 if not c:raise ValueError(m)
def load(p):return json.loads(Path(p).read_text())
def blob(d):
 raw=zlib.decompress(base64.b64decode(d['zlib_base64'],validate=True))
 need(len(raw)==d['size'] and hashlib.sha256(raw).hexdigest()==d['sha256'],'Invalid stored BO blob');return raw
def lines(regions):return {a+i:d[i:i+64] for a,d in regions.items() for i in range(0,len(d),64)}
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

record=dict(status='RUNNING',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),checks=[],scope='Independent raw numeric scan/complete BO/load/source hash replay; no new hardware access')
try:
 parent=load(P/'report.json');need(parent['status']=='PASS_USER2_PHYSICAL_RAW_JOBS_FAULT_AND_RECONFIGURATION','Physical producer incomplete')
 need(parent['flash_written'] is False and len(parent['loads'])==2,'Wrong load/flash scope')
 review=load(W/'image-review.json');need(parent['image_review_sha256']==sha(W/'image-review.json'),'Image review changed')
 for p,h in review['bound_files'].items():need(sha(p)==h,'Changed reviewed input '+p)
 for p,h in parent['artifacts'].items():need(sha(P/p)==h,'Changed physical artifact '+p)
 for item in parent['loads']:
  p=P/item['name']/'load.json';d=load(p);need(sha(p)==item['receipt_sha256'] and d['status']=='PASS' and d['flash_written'] is False,'Invalid load receipt')
  n=d['native'];need(all(n[k]==v for k,v in dict(DNA_PORT='004E544714C705C',IDCODE_BEFORE='23751093',IDCODE_AFTER='23751093',INIT_COMPLETE='1',DONE='1',USR_ACCESS='3a0ef75f',CLEANUP='1',PASS='1').items()),'Wrong load identity/configuration')
 case_map={c['name']:c for c in production_cases()};positives=0;total_bytes=0;wire_counts={}
 for phase in parent['tests']:
  directory=P/phase['name'];jobs=directory/'jobs';child=load(jobs/'report.json')
  need(sha(jobs/'report.json')==phase['report_sha256'] and child['status']=='PASS' and child['bridge_clean_quit'],'Bad child report')
  need(child['identity']['id']==0x524b4557 and child['identity']['abi']==0x10000 and child['identity']['actual_tck_frequency_hz']==3000000,'Wrong ABI/TCK')
  commands,counts=decode(jobs/'scans.jsonl');wire_counts[phase['name']]=counts
  need(commands[0]['op']==1 and commands[0]['address']==0 and commands[0]['response']==0x524b4557,'First ABI read missing')
  need(commands[1]['op']==1 and commands[1]['address']==4 and commands[1]['response']==0x10000,'Second ABI read missing')
  if child['mode']=='sticky-fault':
   need(all(x['op']==1 for x in commands),'Sticky-fault owner accessed memory/wrote registers')
   need(any(x['address']==0x24 and x['response']==1 for x in commands),'Sticky E1 not observed');continue
  by_tag={};staged={};uploads={};current=None;observed={};acks=[];raw_jobs=[]
  for x in commands:
   op,a,data,rsp=x['op'],x['address'],x['data'],x['response']
   if op in (2,4):need(rsp==0,'Nonzero write response')
   if op==4:need(current is None and a%64==0,'Upload overlaps active job');uploads[a]=data.to_bytes(64,'little')
   if op==2 and a in (0x10,0x14,0x18):staged[a]=data
   if op==2 and a==0x0c and data==1:
    need(current is None and set(staged)=={0x10,0x14,0x18},'Incomplete/overlapping descriptor')
    current=dict(tag=staged[0x18],address=staged[0x10],amount=staged[0x14],uploads=uploads,readback={},registers={})
    uploads={};staged={};raw_jobs.append(current)
   if op==3:need(current is not None and a%64==0,'Readback without owned job');current['readback'][a]=rsp.to_bytes(64,'little')
   if op==1 and current is not None:current['registers'][a]=rsp
   if op==2 and a==0x0c and data==2:
    need(current is not None,'ACK without active job');current['ack']=True;acks.append(current['tag']);current=None
  need(not uploads and not staged,'Unsubmitted upload/descriptor')
  for summary,actual in zip(child['tests'],raw_jobs):
   name=summary['name'];file=jobs/(name+'.json');d=load(file)
   need(sha(file)==summary['report_sha256'],'Changed job receipt')
   if name=='synthetic_unknown_register':
    need(d['status']=='PASS_EXPECTED_E1_AND_POISONED_OWNER' and d['expected_error_code']==1 and d['ack_sent'] is False,'Fault expectations changed')
    need(actual['tag']==d['tag'] and not actual.get('ack') and not actual['readback'] and actual['registers'][0x24]==1 and actual['registers'][0x20]==0,'Wire E1/task/ACK mismatch')
    need(actual['uploads']==lines({r['address']:blob(r['input']) for r in d['regions']}),'Negative upload differs');continue
   case=case_map[name] if name in case_map else case_map['capture_sub_9'];expected,_=replay(case)
   need(d['status']=='PASS' and d['ack_after_complete_readback'] and actual.get('ack'),'Success ACK missing')
   need((actual['address'],actual['amount'],actual['tag'])==(case['address'],case['amount'],d['raw_descriptor']['tag']),'Raw descriptor changed')
   need(actual['uploads']==lines(case['regions']),'Complete captured inputs changed')
   need(actual['readback']==lines({a:bytes(v) for a,v in expected.regions.items()}),'Actual wire output differs from raw DMA oracle')
   need(actual['registers'][0x1c]==actual['tag'] and actual['registers'][0x20]==case['tasks'] and actual['registers'][0x24]==0,'Wire completion mismatch')
   for region in d['regions']:
    a=region['address'];need(blob(region['input'])==case['regions'][a] and blob(region['observed'])==blob(region['expected'])==bytes(expected.regions[a]),'Stored full BO differs')
   size=sum(map(len,case['regions'].values()));need(size==d['bytes_checked'],'Wrong byte count');total_bytes+=size;positives+=1
  need(len(raw_jobs)==len(child['tests']),'Missing/extra raw jobs')
 need(positives==11 and total_bytes==1077248,'Wrong positive test/complete-byte inventory')
 record.update(status='PASS_INDEPENDENT_USER2_PHYSICAL_RAW_SCAN_AND_BO_REPLAY',positive_jobs=positives,complete_bytes_checked=total_bytes,raw_scan_inventory=wire_counts,source_inputs_rechecked=len(review['bound_files']),physical_artifacts_rechecked=len(parent['artifacts']),flash_written=False)
except BaseException as error:record.update(status='FAIL',error=str(error));raise
finally:
 record['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();record['auditor_sha256']=sha(__file__);(W/'independent-physical-audit.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
