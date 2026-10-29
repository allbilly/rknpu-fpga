from pathlib import Path
import hashlib,json,re,datetime,sys
ROOT=Path('/home/fedora/rknpu-fpga');sys.path.insert(0,str(ROOT))
from tools.hardware import sample_cmac512 as observer
W=ROOT/'build/full512-regmem-implementation/20261026T111740Z';Q=W/'image-command-qualified';L=Q/'emission-launch-20261026T160613Z';P=ROOT/'build/full512-regmem-preparation/1793013000';HW=Path(__file__).resolve().parent
def need(ok,msg):
 if not ok:raise ValueError(msg)
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
e=json.loads((L/'report.json').read_text());q=json.loads((Q/'report.json').read_text());M=ROOT/'build/regmem-closed-mapped-replay/20261026T122537Z-lutproof/report.json';m=json.loads(M.read_text())
need(e['exit_code']==0 and e['input_recheck']=='PASS' and e['input_recheck_after'] is True and e['completion_marker_found'] is True,'Native image emission incomplete')
need(m['status']=='PASS_ACTUAL_CLOSED_FULL512_MAPPED_STARTUP_WITH_PROVEN_LUT_MODEL_ONLY','Mapped qualification incomplete')
need(all(sha(p)==h for p,h in q['inputs'].items()),'Qualified image input changed')
need(sha(Q/'emit.tcl')==q['tcl_sha256']==e['emitter_tcl_sha256'],'Emitter source changed')
for f in e['outputs']:need(sha(ROOT/f['path'])==f['sha256'],'Emitted output changed')
for name in ['default_drc.rpt','bitstream_drc.rpt']:
 text=(Q/'bitstream'/name).read_text()
 for rule,count in [('DPIP-1',1030),('DPOP-1',515),('DPOP-2',515)]:need(re.search(r'^\| '+rule+r'\s*\| Warning\s*\|[^\n]+\|\s*'+str(count)+r'\s*\|',text,re.M),'Changed reviewed DRC table')
 need(not re.search(r'^\|\s*[^|]+\|\s*(?:Error|Critical Warning)\s*\|',text,re.M),'Blocking bitgen DRC')
bit=Q/'bitstream/cmac512-startup.bit';b=bit.read_bytes();pos=2+int.from_bytes(b[:2],'big')
need(b[2:pos]==bytes.fromhex('0ff00ff00ff00ff000') and b[pos:pos+2]==b'\x00\x01','Wrong bitstream framing');pos+=2;fields={}
for key in 'abcd':
 need(b[pos:pos+1]==key.encode(),'Wrong bitstream field order');pos+=1;n=int.from_bytes(b[pos:pos+2],'big');pos+=2;fields[key]=b[pos:pos+n].rstrip(b'\0').decode();pos+=n
need(b[pos:pos+1]==b'e','Missing payload field');pos+=1;n=int.from_bytes(b[pos:pos+4],'big');pos+=4;need(pos+n==len(b),'Payload length differs')
need(fields['b']=='7k480tffg1156' and fields['a'].startswith('ypcb_cmac_array_regmem_top;'),'Wrong design/family/package in bit header')
need(b[pos:].count(bytes.fromhex('3001a001ac6fee7e'))==1 and bytes.fromhex('aa995566') in b[pos:],'Missing source-tag packet bytes/configsync')
source=observer.source_contract(P/'report.json');files=dict(q['inputs'])
for f in [bit,Q/'report.json',Q/'emit.tcl',L/'report.json',W/'root-init-drc-review.json',W/'root-timing-review.json',P/'report.json',M,Path(__file__),ROOT/'tools/hardware/sample_cmac512.py',ROOT/'tools/hardware/sample_cmac512.tcl.in',ROOT/'tools/hardware/sample_ew.py',HW/'run_sram_tests.py',HW/'program-template.tcl.in',Path('/home/fedora/vivado/2026.1/Vivado/data/parts/xilinx/kintex7/public/bsdl/xc7k480t_ffg1156.bsd')]:files[str(f)]=sha(f)
r=dict(status='PASS_REVIEWED_CMAC512_IMAGE',reviewer='Root exact-image/source/native/numerical review',reviewed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),authorization='User: u can start fpga test if needed; u can build vivado',programming_scope='volatile-sram',flash_authorized=False,part='xc7k480tffg1156-2',profile=observer.PROFILE,source_sha256=observer.SOURCE_SHA,source_report=dict(path=str(P/'report.json'),sha256=sha(P/'report.json')),bitstream=dict(path=str(bit),sha256=sha(bit),bytes=bit.stat().st_size,header=fields,header_speed_grade_included=False,payload_bytes=n),usr_access='ac6fee7e',compiled_led_active_low=0,hardware_inputs=source['hardware_inputs'],electrical=dict(config_voltage='1.8',cfgbvs='GND',basis='Existing known-used YPCB SYS_CLK/LED LVCMOS18 configuration',rail_or_strap_new_measurement=False,optical_led_polarity_unknown=True),checks=dict(complete_mapped_startup_and_expected_rejection=True,configured_four_state_lut_equivalence=True,full512_retained=True,source_and_emit_inputs_unchanged=True,completed_native_emission_rc0=True,routed_timing_and_constraints_review=True,init_chain65_review=True,reviewed_factory_drc_warnings_only=True,bit_header_family_and_package=True,source_access_packet_bytes_present=True,fresh_target_audit_required_before_every_load=True,shared_cable_lease_required=True),bound_files=files,hardware_test_passed=False,optical_polarity_verified=False,direct_external_memory_readback=False,scope='Exact full512 atomicC32/K16 autonomous rawK65 built-in scoreboard image only. FPGA loading requires fresh cable/part/DNA/rawIDCODE audit under exclusive lease; no generalRK/host/DDR/PCIe or physical/electrical signoff claim.')
(HW/'image-review.json').write_text(json.dumps(r,indent=2)+'\n');print(HW/'image-review.json');print('Image',sha(bit),'bytes',len(b),'bound_files',len(files))
