"""Freeze actual CH1 controller + selected full512 arithmetic for early fit."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import shutil

ROOT=Path('/home/fedora/rknpu-fpga')
HERE=Path(__file__).resolve().parent
OUT=ROOT/'build/full512-ddr-preparation/combined-source-v6'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(ok,message):
    if not ok:raise RuntimeError(message)
def load(path):return json.loads(Path(path).read_text())
def literal(value):
    value=str(value)
    need(not any(c in value for c in '{}\\\r\n'),'Unsafe build path')
    return '{'+value+'}'


need(not OUT.exists(),'Fresh combined output required')
OUT.mkdir()
script_snapshot=OUT/'prepare-source.py'
shutil.copyfile(Path(__file__),script_snapshot)
parent=ROOT/'build/ypcb-ddr-shell/ch1-physical-synth-v2/source'
image_prep=ROOT/'build/ypcb-ddr-shell/ch1-image-v2/preparation.json'
inventory_path=ROOT/'build/full512-ddr-preparation/source-inventory-v1.json'
image=load(image_prep)
inventory=load(inventory_path)
inputs={str(image_prep):sha(image_prep),str(inventory_path):sha(inventory_path),str(script_snapshot):sha(script_snapshot)}
files={}
by_name={}
selected=[]
replacements=[]


def bind(path,expected=None):
    path=Path(path)
    digest=sha(path)
    need(expected is None or digest==expected,'Changed source '+str(path))
    need(str(path) not in inputs or inputs[str(path)]==digest,'Conflicting input')
    inputs[str(path)]=digest
    return digest


def add(path,expected=None,transform=None):
    path=Path(path)
    digest=bind(path,expected)
    if path.name in by_name:
        previous=by_name[path.name]
        need(previous['original_sha256']==digest and transform is None,'Nonidentical duplicate source '+path.name)
        previous['also_selected_from'].append(str(path))
        return
    target=OUT/'source'/'hdl'/f'{len(selected):03d}'/path.name
    target.parent.mkdir(parents=True)
    if transform is None:shutil.copyfile(path,target)
    else:target.write_text(transform(path.read_text()))
    row=dict(path=str(target),sha256=sha(target),original_path=str(path),original_sha256=digest,also_selected_from=[])
    selected.append(row);by_name[path.name]=row;files[str(target)]=row['sha256']
    if transform is not None:replacements.append(row)


def platform(text):
    old='rk_jtag_ew_ddr_async endpoint ('
    need(text.count(old)==1,'Unexpected physical platform instance')
    return text.replace(old,'rk_jtag_dual_ddr_async endpoint (')


def board(text):
    old='module ypcb_ddr_ew_top #'
    need(text.count(old)==1,'Unexpected original board top')
    return text.replace(old,'module ypcb_ddr_dual_top #')


for name,digest in image['hardware_source_manifest'].items():
    path=parent/name
    if path.suffix not in ('.sv','.v'):continue
    bind(path,digest)
    if path.name=='rk_jtag_ew_ddr_async.sv':continue
    add(path,digest,platform if path.name=='platform.sv' else board if path.name=='top.sv' else None)

unused={'fpga/tinystories/ypcb_tinystories_top.sv','rtl/tinystories/rk_jtag_dual_bram.sv',
        'rtl/tinystories/rk_shared_bram_regport.sv'}
for record in inventory['source_closure']['synthesis_sources']:
    name=record['path']
    if name in unused:continue
    source=Path(inventory['source_closure']['source_files'][name]['snapshot_path'])
    add(source,record['sha256'])

bridge_review=load(ROOT/'build/full512-ddr-preparation/cmac-async-both-simulators-root-review-v1.json')
baseline_build=ROOT/'build/tinystories-fpga-preparation/dual-v1/build.tcl'
bind(baseline_build)
need('set_property verilog_define {DESIGNWARE_NOEXIST} [current_fileset]' in baseline_build.read_text(),
    'Missing qualified donor compatibility define')
for path in [ROOT/'rtl/ddr/rk_cmac_async_engine.sv',HERE/'source/rk_dual_async_dispatch.sv',
             HERE/'source/rk_dual_job_control.sv',HERE/'source/rk_jtag_dual_ddr_async.sv']:
    expected=bridge_review['source_inputs'].get(str(path))
    add(path,expected)
controls=HERE/'native-controls-v8/report.json'
control_report=load(controls)
need(control_report['status']=='PASS_PRIVATE_DUAL_CSR_CONTROL_BENCH_ONLY','Control leaf qualification missing')
for name,digest in control_report['source_hashes_before'].items():bind(ROOT/name,digest)
bind(controls)

xdc=[]
for name in ('mig-original.xdc','board.xdc'):
    source=parent/name
    bind(source,image['hardware_source_manifest']['constraints/'+name])
    target=OUT/'source'/name
    shutil.copyfile(source,target)
    files[str(target)]=sha(target);xdc.append(str(target))
defs={}
for row in selected:
    for module_bytes in re.findall(rb'^\s*module\s+(\w+)',Path(row['path']).read_bytes(),re.M):
        module=module_bytes.decode('ascii')
        need(module not in defs,'Duplicate module declaration '+module)
        defs[module]=row['path']
need(all(module in defs for module in ('rk_jtag_dual_ddr_async','rk_dual_job_control','rk_dual_async_dispatch',
    'rk_cmac_cacc_fp16_array','rk_cmac_fp16_array_dsp_prefix_pipe','rk_cmac_fp16_cell_dsp_prefix_pipe')),
    'Missing selected physical compute/control source')
need(not any(module in defs for module in ('rk_jtag_dual_bram','rk_shared_bram_regport','rk_jtag_ew_ddr_async')),
    'Old standalone endpoint or BRAM selected')
sources='[list '+ ' '.join(literal(row['path']) for row in selected)+']'
script='''set_param general.maxThreads 2
proc fit_require {condition message} {if {!$condition} {error $message}}
puts "DUAL_DDR_FIT_NATIVE_TOOL [version -short]"
create_project -in_memory -part xc7k480tffg1156-2
set_property verilog_define {DESIGNWARE_NOEXIST} [current_fileset]
read_verilog -sv @SOURCES@
@READ_XDC@
synth_design -top ypcb_ddr_dual_top -part xc7k480tffg1156-2 -flatten_hierarchy none
puts DUAL_DDR_SYNTHESIS_COMPLETED
set_property CONFIG_VOLTAGE 1.8 [current_design]
set_property CFGBVS GND [current_design]
fit_require [expr {[get_property TOP [current_design]] eq "ypcb_ddr_dual_top" && [get_property PART [current_design]] eq "xc7k480tffg1156-2"}] "Wrong actual top/part"
fit_require [expr {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]]==0}] "Unresolved source black box"
set kernels [get_cells -hierarchical -filter {ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe || REF_NAME == rk_cmac_fp16_cell_dsp_prefix_pipe}]
fit_require [expr {[llength $kernels]==16}] "Expected all sixteen C32 compute kernels"
set dsps [get_cells -hierarchical -filter {REF_NAME == DSP48E1}]
set owned [dict create]
foreach kernel $kernels {
    set prefix "[get_property NAME $kernel]/"
    set count 0
    foreach dsp $dsps {
        set name [get_property NAME $dsp]
        if {[string first $prefix $name]==0} {
            fit_require [expr {![dict exists $owned $name]}] "Duplicate product DSP ownership"
            dict set owned $name 1
            incr count
        }
    }
    fit_require [expr {$count==32}] "Reduced C32 compute kernel"
}
fit_require [expr {[dict size $owned]==512}] "Reduced 512 parallel product target"
set f [open fit-facts.tsv {WRONLY CREAT EXCL}]
puts $f "TOP\\t[get_property TOP [current_design]]"
puts $f "PART\\t[get_property PART [current_design]]"
puts $f "PRODUCT_DSPS\\t[dict size $owned]"
puts $f "TOTAL_DSPS\\t[llength $dsps]"
puts $f "CONFIG_VOLTAGE\\t[get_property CONFIG_VOLTAGE [current_design]]"
puts $f "CFGBVS\\t[get_property CFGBVS [current_design]]"
puts $f "TIMING_OR_CDC_ACCEPTANCE\\tNOT_QUALIFIED_BY_RESOURCE_SYNTHESIS"
close $f
write_checkpoint post_synth.dcp
report_utilization -hierarchical -file utilization.rpt
report_io -file io.rpt
report_clocks -file clocks.rpt
report_drc -file synthesis_drc.rpt
puts PASS_FULL512_DDR_EARLY_RESOURCE_SYNTHESIS_ONLY
exit
'''
script=script.replace('@SOURCES@',sources).replace('@READ_XDC@','\n'.join('read_xdc '+literal(p) for p in xdc))
script_path=OUT/'synth.tcl';script_path.write_text(script);files[str(script_path)]=sha(script_path)
report=dict(status='PREPARED_FROZEN_COMBINED_FULL512_CH1_SOURCE_FOR_FRONTEND_AND_RESOURCE_REVIEW_ONLY',
    created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),inputs=inputs,files=files,
    hdl_sources=selected,hdl_count=len(selected),module_definitions=defs,replacements=replacements,
    frontend_sources=[row['path'] for row in selected if 'mig_7series' not in Path(row['path']).name and
        Path(row['path']).name not in ('platform.sv','top.sv')],
    xdc=xdc,top='ypcb_ddr_dual_top',endpoint_top='rk_jtag_dual_ddr_async',part='xc7k480tffg1156-2',
    verilog_defines=['DESIGNWARE_NOEXIST'],verilog_define_source=str(baseline_build),
    full512_expected_products=512,physical_channel=1,controllers_retained=2,
    physical_pads_or_clock_constraints_changed=False,raw_commands_or_tensor_layout_changed=False,
    numerical_or_fault_composition_qualified=False,combined_fit_qualified=False,
    timing_or_cdc_qualified=False,bitstream_authorized_by_this_preparation=False,hardware_accessed=False)
(OUT/'preparation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('inputs','files','hdl_sources','module_definitions','replacements','frontend_sources')}))
