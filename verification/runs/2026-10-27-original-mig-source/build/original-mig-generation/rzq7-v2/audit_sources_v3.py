"""Read-only regenerated-source binding audit. Not physical/controller proof."""
from pathlib import Path
import datetime,hashlib,json,re,sys,xml.etree.ElementTree as E
R=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent;P=R/'build/original-mig-preparation/rzq7-v2';G=P/'generation';IP=G/'ip/top_mig_7series_0_0';C=IP/'top_mig_7series_0_0';V=C/'user_design/rtl'
sys.path.insert(0,str(R))
from tools.ddr.prepare_original_mig import verify
from tools.ddr.interface import parse_template,template_module,expected_ports,require,load_json
from tools.ddr.qualify_fence_order import literal_parameter
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
record=dict(status='RUNNING',scope='Actual original-profile generated source, parameter, port and constraint inventory only; no mapped/routed/PHY/DDR/FPGA application qualification',hardware_accessed=False,physical_integration_ready=False)
def canonical_xml(n):return (n.tag,tuple(sorted(n.attrib.items())),(n.text or '').strip(),tuple(canonical_xml(c) for c in n))
def wrapper_ports(text):
 m=re.search(r'\bmodule\s+top_mig_7series_0_0\s*\((.*?)\);',text,re.S);require(m is not None,'Missing generated module header')
 header=re.sub(r'/\*.*?\*/|//[^\n]*','',m[1],flags=re.S);result={}
 active=True
 for line in header.splitlines():
  stripped=line.strip()
  if stripped=='`ifdef SKIP_CALIB':
   require(active,'Nested unsupported calibration preprocessor');active=False;continue
  if stripped=='`endif':
   require(not active,'Unmatched generated header directive');active=True;continue
  require(not stripped.startswith('`'),'Unknown generated header conditional')
  if not active or not line.strip():continue
  p=re.fullmatch(r'\s*(input|output|inout)\s+(?:wire\s+)?(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?(\w+)\s*,?\s*',line)
  require(p is not None,'Unmodeled generated port declaration '+line)
  direction,hi,lo,name=p.groups();require(name not in result,'Duplicate generated port')
  result[name]=dict(direction={'input':'in','output':'out','inout':'inout'}[direction],width=(int(hi)-int(lo)+1 if hi is not None else 1))
 require(active,'Unclosed calibration-only port conditional')
 return result
try:
 prep=verify(P);native=load_json(W/'report.json')
 require(native['status']=='PASS_GENERATED_ORIGINAL_MIG_SOURCES_ONLY' and native['returncode']==0,'Generation incomplete')
 require(native['vendor_ip_generated'] is True and all(native[k] is False for k in ('top_implementation_executed','bitstream_emitted','hardware_accessed','flash_written','physical_integration_ready')),'Wrong native scope')
 for path,h in native['inputs'].items():require(sha(path)==h,'Generation input changed '+path)
 for name,h in native['artifacts'].items():require(sha(G/name)==h,'Generated source changed '+name)
 original=E.fromstring((P/'source/original/project/mig.prj').read_bytes());generated=E.fromstring((C/'mig.prj').read_bytes())
 removed=[]
 for ch in (0,1):
  parent=original.find(f"Controller[@number='{ch}']");node=parent.find(f'C{ch}_MEM_SIZE');require(node is not None and node.text=='2147483648','Missing original derived capacity')
  parent.remove(node);removed.append(f'C{ch}_MEM_SIZE')
 require(canonical_xml(original)==canonical_xml(generated),'Generator changed fields beyond the two omitted derived capacity tags')
 ports=wrapper_ports((V/'top_mig_7series_0_0.v').read_text());veo=parse_template((IP/'top_mig_7series_0_0.veo').read_text());old_veo=parse_template((P/'source/original/template/top_mig_7series_0_0.veo').read_text())
 require(template_module((IP/'top_mig_7series_0_0.veo').read_text())=='top_mig_7series_0_0','Wrong generated template module')
 require(all(n in ports and ports[n]==v for n,v in veo.items()),'Generated VEO conflicts with actual wrapper')
 omitted={f'c{ch}_{kind}':dict(direction='out',width=width) for ch in (0,1) for kind,width in (('app_ecc_single_err',8),('device_temp',12))}
 require({n:ports[n] for n in ports.keys()-veo.keys()}==omitted,'Unexpected generated VEO omission')
 added={f'c{ch}_app_{kind}_req':dict(direction='in',width=1) for ch in (0,1) for kind in ('sr','ref','zq')}
 require({n:veo[n] for n in veo.keys()-old_veo.keys()}==added and not old_veo.keys()-veo.keys() and all(veo[n]==v for n,v in old_veo.items()),'Unexpected generated template ABI change')
 for ch in (0,1):
  for name,v in expected_ports().items():
   name=name.replace('c0_',f'c{ch}_');require(ports.get(name)==v,'Generated AXI/reset profile differs '+name)
  for name,v in dict(awaddr=32,awvalid=1,awready=1,wdata=32,wvalid=1,wready=1,bresp=2,bvalid=1,bready=1,araddr=32,arvalid=1,arready=1,rdata=32,rresp=2,rvalid=1,rready=1).items():
   direction='out' if name in ('awready','wready','bresp','bvalid','arready','rdata','rresp','rvalid') else 'in'
   require(ports.get(f'c{ch}_s_axi_ctrl_{name}')==dict(direction=direction,width=v),'Generated ECC control interface differs')
 core=(V/'top_mig_7series_0_0_mig.v').read_text();parameters={}
 require(not re.search(r'(?m)^\s*`define\s+SKIP_CALIB\b',core),'Calibration skip macro is defined')
 for ch in (0,1):
  fields=dict(ROW_WIDTH=15,COL_WIDTH=10,BANK_WIDTH=3,RANKS=1,DQ_WIDTH=72,DATA_WIDTH=64,ECC='ON',ECC_TEST='OFF',OUTPUT_DRV='HIGH',nCK_PER_CLK=4,SIM_BYPASS_INIT_CAL='OFF',C_S_AXI_ADDR_WIDTH=31,C_S_AXI_DATA_WIDTH=512,C_S_AXI_ID_WIDTH=4,C_S_AXI_SUPPORTS_NARROW_BURST=0)
  observed={k:literal_parameter(core,f'C{ch}_{k}') for k in fields};require(observed==fields,'Generated geometry/AXI/drive differs')
  capacity=(1<<(observed['ROW_WIDTH']+observed['COL_WIDTH']+observed['BANK_WIDTH']))*observed['RANKS']*(observed['DATA_WIDTH']//8)
  require(capacity==2147483648,'Generated capacity is not2GiB')
  parameters[f'c{ch}']=dict(values=observed,capacity_bytes=capacity)
 xdc=(C/'user_design/constraints/top_mig_7series_0_0.xdc').read_text();clockfacts={}
 for ch,pins in ((0,('AH27','AH28')),(1,('G25','G26'))):
  require(f'create_clock -period 5 [get_ports c{ch}_sys_clk_p]' in xdc,'Changed generated200MHz clock')
  for suffix,pin in zip(('p','n'),pins):
   port=f'c{ch}_sys_clk_{suffix}'
   require(f'set_property PACKAGE_PIN {pin} [get_ports {{{port}}}]' in xdc and f'set_property IOSTANDARD DIFF_SSTL15 [get_ports {{{port}}}]' in xdc,'Changed original differential clock assignment')
  clockfacts[f'c{ch}']=dict(period_ns=5,pins=list(pins),iostandard='DIFF_SSTL15',board_delivery_verified=False)
 catalog=load_json(R/'fpga/ddr/xdma_archive_reference.json');same=[];different=[]
 for member,entry in catalog['members'].items():
  name=member.removeprefix(catalog['member_prefix']);file=IP/name;require(file.is_file(),'Missing generated archive counterpart')
  (same if sha(file)==entry['sha256'] else different).append(name)
 oldbase=R/'build/ddr-endpoint-current/native-v1/logic/source/top_mig_7series_0_0/user_design/rtl';ui_equal=[]
 for name in ('ui_cmd','ui_top','ui_rd_data','ui_wr_data'):
  name=f'ui/mig_7series_v4_2_{name}.v';a=(oldbase/name).read_bytes();b=(V/name).read_bytes();mark=b'`timescale'
  require(mark in a and mark in b and a[a.index(mark):]==b[b.index(mark):],'Generated UI body differs beyond its license header')
  ui_equal.append(name)
 patch=load_json(R/'fpga/ddr/patches/round_robin_width_one.json');arbiter=V/'controller/mig_7series_v4_2_round_robin_arb.v'
 require(sha(arbiter)==patch['original_sha256'],'Unexpected WIDTH1 arbiter source identity')
 record.update(status='PASS_ORIGINAL_PROFILE_GENERATED_SOURCE_BINDING_ONLY',native_report_sha256=sha(W/'report.json'),generation_inputs_rechecked=len(native['inputs']),generated_artifacts_rechecked=len(native['artifacts']),input_project_sha256=sha(P/'source/original/project/mig.prj'),generated_project_sha256=sha(C/'mig.prj'),generator_removed_derived_tags=removed,parameters=parameters,actual_ports=ports,veo_port_count=len(veo),actual_wrapper_port_count=len(ports),veo_omitted_outputs=omitted,new_request_inputs=added,clock_constraints=clockfacts,archive_comparison=dict(byte_identical=len(same),different=len(different),different_paths=different),ui_bodies_byte_identical_from_timescale=ui_equal,width_one_arbiter_requires_separate_variant=True,normal_hardware_abi_requires_SKIP_CALIB_undefined=True,calibration_bypass_defaults='OFF',
  remaining=['Bind actual wrapper ports; generated VEO still omits both single-ECC and device-temperature outputs','Explicitly bind new self-refresh/refresh/ZQ request inputs; no runtime low-power API is supplied','Apply and separately qualify the WIDTH1 arbiter source variant without modifying raw generated source','Complete source-matched model/PHY/reset/retirement and full-window qualification','Audit actual board clock delivery, electrical conditions, synthesis, CDC, routing/timing and exact image before any physical DDR claim'])
except BaseException as error:record.update(status='FAIL',error=repr(error));raise
finally:
 record['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();record['auditor_sha256']=sha(__file__);(W/'root-source-review-v3.json').write_text(json.dumps(record,indent=2)+'\n')
print(record['status'],record.get('actual_wrapper_port_count'),record.get('generated_artifacts_rechecked'))
