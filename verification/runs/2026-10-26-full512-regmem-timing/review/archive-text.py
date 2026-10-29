from pathlib import Path
import hashlib,json,shutil,datetime
ROOT=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent
P=ROOT/'build/full512-regmem-preparation/1793013000';A=W/'post-route-audit-20261026T115834Z'
OUT=ROOT/'verification/runs/2026-10-26-full512-regmem-timing'
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,message):
 if not ok:raise ValueError(message)
need(not OUT.exists(),'Fresh archive required');profile=json.loads((P/'report.json').read_text());OUT.mkdir(parents=True)
entries={}
def put(source,name,role):
 source=Path(source);raw=source.read_bytes();raw.decode('utf-8');need(not name.endswith(('.dcp','.bit','.so','.vvp')),'Binary archive forbidden')
 destination=OUT/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
 expected=sha(source);need(sha(destination)==expected,'Copy changed');entries[name]=dict(sha256=expected,bytes=len(raw),origin=str(source.relative_to(ROOT)),role=role)
for name,h in profile['source']['files'].items():
 need(sha(P/'source'/name)==h,'Frozen source changed');put(P/'source'/name,'snapshot/'+name,'exact frozen125-file source snapshot')
for name in ['report.json','build.tcl','root-build-review.json']:put(P/name,'profile/'+name,'source preparation and checkpoint-only admission')
run=json.loads((W/'run.json').read_text());need(run['status']=='PASS_REGISTERED_BRAM_FULL512_CHECKPOINT' and run['returncode']==0 and run['snapshot_intact'],'Incomplete native implementation')
for name,h in run['outputs'].items():
 need(sha(P/name)==h,'Implementation output changed')
 if name.endswith('.rpt'):put(P/name,'implementation/'+Path(name).name,'original routed/synthesis report')
for name in ['run.json','root-timing-review.json','root-init-drc-review.json','review-facts.py','post-route-audit.tcl','post-route-audit-context.json','archive-text.py']:
 put(W/name,'review/'+name,'actual implementation/root review; no image or programming admission')
for f in A.iterdir():
 if f.is_file():put(f,'native-audit/'+f.name,'exact native routed audit output')
put(W/'post-route-audit-launch-20261026T115834Z/report.json','review/original-native-audit-wrapper-FAIL.json','original failed wrapper retained; actual Tcl exited0, independent root review is separate')
for tool,path in [('iverilog',ROOT/'build/regmem-board/iverilog-reviewed-20261026T110614Z'),('verilator',ROOT/'build/regmem-board/verilator-20261026T105744Z/native')]:
 r=json.loads((path/'report.json').read_text());need(r['status']=='PASS_REGISTERED_BRAM_FULL512_STARTUP_NATIVE_ONLY','Native board report incomplete')
 put(path/'report.json','native-board/'+tool+'/report.json','full raw K65 native board report; binary remains external')
 for test in r['tests']:put(path/(test['spec']['name']+'.log'),'native-board/'+tool+'/'+test['spec']['name']+'.log','actual original result/fault/abort/restart log')
proof=ROOT/'build/regmem-fast-lut-proof/20261026T121838Z';r=json.loads((proof/'report.json').read_text());need(r['status']=='PASS_ALL_CONFIGURED_LUTS_EXHAUSTIVE_4STATE','LUT model proof incomplete')
for name in ['report.json','inventory.json','actual.log','wrong_output_control.log']:put(proof/name,'lut-model-proof/'+name,'exhaustive exact configured four-state model proof; AMD models/netlist/binary remain external')
for tool in ['tools/cmac/regmem/run_closed_mapped.py','tools/cmac/regmem/prove_fast_lut.py','tools/hardware/sample_cmac512.py','tools/hardware/sample_cmac512.tcl.in','tools/hardware/sample_ew.py','tests/hardware/test_sample_cmac512.py','tests/hardware/test_sample_ew.py']:
 put(ROOT/tool,'preparation-tools/'+tool,'current source/preparation control; not part of frozen hardware manifest')
for folder,label in [(ROOT/'build/cmac512-observer-controls-v2','observer-controls'),(ROOT/'build/cmac512-observer-copy-controls/20261026T120104Z','observer-copy-controls')]:
 put(folder/'audit.json',label+'/audit.json','SYNTHETIC observer controls only, no hardware')
prod=ROOT/'build/production-refresh-private/20261026T125525Z';r=json.loads((prod/'report.json').read_text());need(r['status']=='PASS_PRIVATE_COMPLETE_PRODUCTION_MAKE_TEST_ONLY','Fresh production suite incomplete')
put(prod/'report.json','production/report.json','fresh471.858s source-identical production suite only, not experimental FPGA proof')
index=dict(schema_version=1,status='PRESERVED_FULL512_REGISTERED_RAM_TIMING_TEXT_EVIDENCE',created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),scope='Complete125-file frozen source snapshot and selected native/timing/INIT/DRC/model/observer control text; DCP/netlist/binaries and full execution closures remain local. No image/programming admission or actual full512 FPGA result.',part=profile['part'],source_sha256=profile['source']['sha256'],frozen_source_files=profile['source']['files'],clock_period_ns=20,channels=32,kernels=16,cmac_products=512,source_git_revision=run['git_revision'],source_includes_uncommitted_work=True,routed_dcp_sha256=run['outputs']['implementation/routed.dcp'],timing=dict(setup_slack_ns=0.987,hold_slack_ns=0.057,pulse_slack_ns=9.6,failing_endpoints=0),files=entries,mapped_startup_qualification_included=False,bitstream_included=False,hardware_programmed=False,image_admission=False)
(OUT/'index.json').write_text(json.dumps(index,indent=2)+'\n');print(OUT/'index.json');print('files',len(entries),'bytes',sum(e['bytes'] for e in entries.values()))
