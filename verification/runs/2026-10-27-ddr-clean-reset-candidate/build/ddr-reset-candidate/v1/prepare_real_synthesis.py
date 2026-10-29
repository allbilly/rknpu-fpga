"""Freeze the actual118-source MIG/reset candidate; no tool/device invocation."""
from pathlib import Path
import datetime,hashlib,json,shutil
ROOT=Path('/home/fedora/rknpu-fpga')
BASE=Path(__file__).resolve().parent
PLATFORM=BASE/'workspace/build/original-ddr-platform/reset-v1'
OUT=ROOT/'build/original-ddr-real-synthesis/reset-v3'
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
def tcl(p):return '[encoding convertfrom utf-8 [binary format H* {'+str(p).encode().hex()+'}]]'
require(not OUT.exists(),'Fresh synthesis preparation required')
platform=json.loads((PLATFORM/'report.json').read_text())
require(platform['status']=='PREPARED_ORIGINAL_MIG_ASYNC_EW_PLATFORM_WIRING_ONLY' and
        platform['stub_selected_for_real_design'] is False,'Actual wiring profile required')
for n,h in platform['source_inputs'].items():require(sha(ROOT/n if not Path(n).is_absolute() else n)==h,'Changed source closure '+n)
real=[Path(n) for n in platform['real_hdl_sources']]
require(len(real)==118 and len(set(real))==118 and all('interface_only' not in p.name for p in real),
        'Exactly118 actual sources, without stubs, required')
require(sum(p.name=='rk_mig_reset_coordinator.sv' for p in real)==1 and
        sum(p.name=='rk_jtag_ew_ddr_async.sv' for p in real)==1,'Missing corrected reset/endpoint')
OUT.mkdir(parents=True);sources=[];inputs={str((PLATFORM/'report.json').resolve()):sha(PLATFORM/'report.json'),str(Path(__file__).resolve()):sha(__file__)}
for i,p in enumerate(real):
    target=OUT/'source/hdl'/f'{i:03d}'/p.name;target.parent.mkdir(parents=True)
    shutil.copyfile(p,target);require(sha(p)==sha(target),'Copied HDL differs')
    sources.append(target);inputs[str(target)]=sha(target);inputs[str(p.resolve())]=sha(p)
for name in ('mig-original.xdc','platform-clock.xdc'):
    source=ROOT/'build/original-ddr-real-synthesis/v2/source'/name;target=OUT/'source'/name
    shutil.copyfile(source,target);inputs[str(target)]=sha(target)
require(sha(OUT/'source/mig-original.xdc')=='5ea42669bed59d09cfad5c25a08aec20e0824d48895071ecd2acfbff8261b6fc','Original MIG constraints changed')
old=(ROOT/'build/original-ddr-real-synthesis/v2/synth.tcl').read_text().splitlines()
script=['set_param general.maxThreads 2','puts "NATIVE_TOOL_VERSION [version -short]"',
        'create_project -in_memory -part xc7k480tffg1156-2',
        'read_verilog -sv [list '+' '.join(tcl(p) for p in sources)+']',
        'read_xdc '+tcl(OUT/'source/mig-original.xdc'),
        'read_xdc '+tcl(OUT/'source/platform-clock.xdc')]
start=next(i for i,l in enumerate(old) if l.startswith('synth_design '))
script+=old[start:]
(OUT/'synth.tcl').write_text('\n'.join(script)+'\n');inputs[str(OUT/'synth.tcl')]=sha(OUT/'synth.tcl')
shutil.copyfile(ROOT/'build/original-ddr-real-synthesis/v2/run.py',OUT/'run.py')
record=dict(status='PREPARED_REAL_ORIGINAL_MIG_SYNTHESIS_ONLY',top=platform['top'],rtl_files=118,
    platform_report_sha256=sha(PLATFORM/'report.json'),source_fix='Private clean SYS status synchronizers with epoch validity and registered SYS-to-UI admission; same actual MIG and original XDC',
    inputs=inputs,source_map={str(dst):str(src) for src,dst in zip(real,sources)},
    stub_sources_selected=False,cached_checkpoint_selected=False,hardware_accessed=False,
    bitstream_emitted=False,implementation_requested=False,
    scope='Fresh full actual MIG/controller/reset-candidate source synthesis; no reused checkpoints, implementation or physical qualification',
    utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
(OUT/'preparation.json').write_text(json.dumps(record,indent=2)+'\n')
print(record['status'],len(sources),len(inputs))
