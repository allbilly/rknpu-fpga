from pathlib import Path
import datetime,hashlib,json,re,struct,sys
R=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent
sys.path.insert(0,str(R))
from tools.tinystories.prepare import require
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
E=R/'build/tinystories-image/20261026T220800Z';d=json.loads((E/'report.json').read_text())
require(d['status']=='PASS_EXACT_FULL512_DUAL_IMAGE_EMISSION_ONLY' and d['input_hashes_unchanged'],'Native emission incomplete')
require(d['source_sha256']=='1e01179cf730fdec0faa6644eae1f51dbeee4a5474f3734b327a0f8c7677b425' and d['usr_access']=='1e01179c','Wrong source')
require(d['part']=='xc7k480tffg1156-2' and d['top']=='ypcb_tinystories_top' and not d['hardware_accessed'] and not d['flash_written'],'Wrong emission scope')
prep=json.loads((R/'build/tinystories-fpga-preparation/dual-v1/report.json').read_text())
native_matches={}
for label,entry in prep['native'].items():
 native=json.loads(Path(entry['path']).read_text());count=0
 for name in prep['synthesis_sources']:
  if name in {'rtl/vendor/opentpu/otpu_jtag_mailbox.sv','fpga/tinystories/ypcb_tinystories_top.sv'}:continue
  require(any(n.endswith('/'+name) and v==prep['source']['files'][name] for n,v in native['inputs'].items()),'Native/frozen HDL disagreement '+name)
  count+=1
 require(count==35,'Native HDL coverage changed');native_matches[label]=count
bound=dict(d['inputs'])
for n,h in d['artifacts'].items():bound[str(E/n)]=h
bound[str(E/'report.json')]=sha(E/'report.json')
for name in ('run_sram_tests.py','program-template.tcl.in','audit_physical.py','harness_controls.py','harness-controls.json','review_image.py'):
 bound[str(W/name)]=sha(W/name)
for directory in ('tools/tinystories','tools/host'):
 for p in (R/directory).glob('*.py'):bound[str(p)]=sha(p)
for name in ('fpga/host/native_rpc.tcl.in','tools/hardware/sample_ew.py','build/tinystories-software-before-fpga.json',
 'build/tinystories-joined-vectors/v2/report.json','build/tinystories-first-projection/bos-wq-v3/report.json',
 'build/production-dual-endpoint/20261026T203139Z/report.json'):
 bound[str(R/name)]=sha(R/name)
v=R/'build/tinystories-joined-vectors/v2';vr=json.loads((v/'report.json').read_text())
for n,h in vr['files'].items():bound[str(v/n)]=h
controls=json.loads((W/'harness-controls.json').read_text())
require(controls['status']=='PASS_OFFLINE_TRAINED_PROJECTION_HARNESS_CONTROLS_ONLY' and len(controls['checks'])==5 and controls['worker_sha256']==sha(R/'tools/tinystories/run_projection.py'),'Wrong worker controls')
for p,h in bound.items():require(sha(p)==h,'Changed reviewed input '+p)
log=(E/'stdout.log').read_text();require(not re.search(r'^ERROR:',log,re.M),'Native tool error')
require('PASS_SOURCE_REVIEWED_TINYSTORIES_FULL512_DUAL_BITSTREAM_EMISSION' in log and 'DRC finished with 0 Errors' in log,'Native gates missing')
bit=Path(d['bitstream']['path']);require(sha(bit)==d['bitstream']['sha256'],'Bit changed')
b=bit.read_bytes();pos=0
length=struct.unpack_from('>H',b,pos)[0];pos+=2
require(length==9 and b[pos:pos+length]==bytes.fromhex('0ff00ff00ff00ff000'),'Wrong bit header magic');pos+=length
require(struct.unpack_from('>H',b,pos)[0]==1,'Wrong bit format');pos+=2
header={}
for key in 'abcd':
 require(b[pos:pos+1]==key.encode(),'Wrong bit header order');pos+=1
 length=struct.unpack_from('>H',b,pos)[0];pos+=2
 value=b[pos:pos+length];pos+=length
 require(value.endswith(b'\0'),'Nonterminated bit header');header[key]=value[:-1].decode('ascii')
require(b[pos:pos+1]==b'e','Missing payload');pos+=1
length=struct.unpack_from('>I',b,pos)[0];pos+=4
require(pos+length==len(b) and length==18735004,'Unexpected payload extent')
require(header['a'].startswith('ypcb_tinystories_top;') and header['b']=='7k480tffg1156','Wrong physical image header')
r=dict(status='PASS_REVIEWED_TINYSTORIES_FULL512_DUAL_IMAGE',reviewer='Root exact native/source/header/reset/timing/CDC/DRC review',
 reviewed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),part=d['part'],top=d['top'],source_sha256=d['source_sha256'],usr_access=d['usr_access'],
 bitstream=dict(d['bitstream'],header=header,payload_bytes=length),bound_files=bound,vectors_report_sha256=sha(v/'report.json'),
 compiled_led_active_low=0,optical_polarity='unknown; indicators are IRQ/fault/heartbeat, no PASS LED',
 flash_authorized=False,programming_scope='volatile-sram',authorization='User: u can start fpga test if needed',
 electrical_scope='Same reviewed AA28 clock and P30/M30/N30 LVCMOS18 ports,1.8V/GND configuration; no DDR/PCIe/R28 pins',
 native_scope='Both corrected full512 joined suites five modes each; current production make test passed; actual synthesized/routed registered reset cone and65startupINITs verified',
 mapped_replay='No new monolithic mapped numeric replay; this reviewed experimental volatile test establishes new control/image physical evidence. Earlier image logs are not reused as new image results.',
 native_hdl_correspondence=native_matches,physical_acceptance=False,scope='Exact new image admitted only for audited trained-tile experimental volatile SRAM test; not full model/RK/DDR/PCIe acceptance')
path=W/'image-review.json';require(not path.exists(),'Fresh review required');path.write_text(json.dumps(r,indent=2)+'\n')
print(r['status'],len(bound),r['bitstream']['sha256'],path)
