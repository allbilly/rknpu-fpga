#!/usr/bin/env python3
"""Freeze exact capacity-service OOC inputs and root-reviewable Vivado recipe."""
from pathlib import Path
import datetime,hashlib,json,re,sys,time

ROOT=Path('/home/fedora/rknpu-fpga');BASE=Path(__file__).resolve().parent
LINT=ROOT/'build/ddr-capacity-service-lint-v1/report.json'
V12=ROOT/'build/full512-ddr-preparation/full512-image-prep-v12/image-preparation.json'
MIG_REL='build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/099/top_mig_7series_0_0_mig.v'
VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
TOP='rk_ddr_capacity_service';PART='xc7k480tffg1156-2';UI_PERIOD_NS=7.5
UNIT='rknpu-ddr-capacity-service-ooc-v1'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,msg):
    if not ok:raise ValueError(msg)
def sample():
    mem=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
    mpsi=Path('/proc/pressure/memory').read_text();cpsi=Path('/proc/pressure/cpu').read_text()
    mfull=float(re.search(r'^full avg10=([0-9.]+)',mpsi,re.M)[1]);csome=float(re.search(r'^some avg10=([0-9.]+)',cpsi,re.M)[1])
    return {'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'memavailable_kib':mem,
        'memory_psi_full_avg10':mfull,'cpu_psi_some_avg10':csome,'pass':mem>=12582912 and mfull<1 and csome<5}
def main():
    # Re-running this generator may refresh preparation metadata in the same
    # private package; copied HDL is always regenerated from the pinned lint inputs.
    lint=json.loads(LINT.read_text());need(lint['status']=='PASS_STRICT_TEN_MODULE_SERVICE_LINT_ONLY','Expected exact v3 strict ten-module source lint')
    command=next(c for c in lint['commands'] if c.get('version')==3)
    need(command['returncode']==0,'latest v3 lint command did not pass')
    originals=command['argv'][command['argv'].index('--top-module')+2:]
    need(len(originals)==10 and command['argv'][command['argv'].index('--top-module')+1]==TOP,'latest lint source list/top changed')
    expected=command['source_hashes_before'];after=command['source_hashes_after']
    need(expected==after and len(expected)==10,'latest v3 lint source hashes changed')
    SRC=BASE/'source';SRC.mkdir(exist_ok=True);rows=[]
    for n,original in enumerate(originals):
        src=Path(original);digest=expected[str(src)];need(src.is_file() and sha(src)==digest,'original OOC source changed '+str(src))
        dest=SRC/f'{n:02d}-{src.name}';dest.write_bytes(src.read_bytes());copy_sha=sha(dest)
        need(copy_sha==digest,'frozen OOC source copy differs '+str(dest))
        rows.append({'original_path':str(src),'original_sha256':digest,'copied_path':str(dest),'copied_sha256':copy_sha,'bytes':dest.stat().st_size})
    v12=json.loads(V12.read_text());mig_path=ROOT/MIG_REL
    source_key=MIG_REL
    source_manifest=v12['hardware_source_manifest']['files']
    need(source_key in source_manifest and sha(mig_path)==source_manifest[source_key],'C1 clock reference is not pinned by current full512 manifest')
    mig_text=mig_path.read_text();tck_matches=list(re.finditer(r'^\s*parameter\s+C1_tCK\s*=\s*(\d+)\s*,?',mig_text,re.M))
    nck_matches=list(re.finditer(r'^\s*parameter\s+C1_nCK_PER_CLK\s*=\s*(\d+)\s*,?',mig_text,re.M))
    need(len(tck_matches)==len(nck_matches)==1,'Expected exactly one frozen C1_tCK and C1_nCK_PER_CLK parameter')
    tck_ps=int(tck_matches[0].group(1));nck=int(nck_matches[0].group(1));derived_ns=tck_ps*nck/1000.0
    need(derived_ns==UI_PERIOD_NS and (tck_ps,nck)==(1875,4),'C1 nCK/tCK does not produce expected 7.5ns UI clock')
    clock={'schema':'capacity-service-frozen-c1-ui-clock-derivation-v1','status':'PASS_SOURCE_DERIVED_C1_UI_CLOCK_PERIOD',
      'source_path':str(mig_path),'source_sha256':sha(mig_path),'source_manifest_path':str(V12),
      'source_manifest_sha256':sha(V12),'source_relative_path':source_key,'C1_tCK_ps':tck_ps,
      'C1_nCK_PER_CLK':nck,'derived_ui_period_ps':tck_ps*nck,'derived_ui_period_ns':derived_ns,
      'derivation':'C1_nCK_PER_CLK * C1_tCK = 4 * 1875 ps = 7500 ps = 7.5 ns',
      'parameter_lines':{'C1_tCK':mig_text[:tck_matches[0].start()].count('\n')+1,'C1_nCK_PER_CLK':mig_text[:nck_matches[0].start()].count('\n')+1},
      'timing_constraints_applied':False,'create_clock_applied':False}
    (BASE/'clock-evidence.json').write_text(json.dumps(clock,indent=2,sort_keys=True)+'\n')
    source_manifest={'schema':'ddr-capacity-service-ooc-source-manifest-v1','source_lint_report_path':str(LINT),
      'source_lint_report_sha256':sha(LINT),'source_lint_version':3,'source_lint_command':command['argv'],
      'top':TOP,'source_count':len(rows),'sources':rows,'C1_clock_reference_path':str(mig_path),'C1_clock_reference_sha256':sha(mig_path)}
    (BASE/'source-manifest.json').write_text(json.dumps(source_manifest,indent=2,sort_keys=True)+'\n')
    src_list='\n'.join('    '+str(Path(r['copied_path'])) for r in rows)
    tcl=f'''# Generated from the immutable 10-source manifest. Root review required before launch.\nset_param general.maxThreads 2\nset outdir [lindex $argv 0]\nif {{$outdir eq "" || ![file isdirectory $outdir]}} {{ error "Fresh OOC output directory required" }}\nset srcs [list \\\n{src_list}\n]\nread_verilog -sv $srcs\nsynth_design -top {TOP} -part {PART} -mode out_of_context\nreport_utilization -file [file join $outdir utilization.rpt]\nreport_utilization -hierarchical -file [file join $outdir utilization-hierarchical.rpt]\nputs "PASS_DDR_CAPACITY_SERVICE_OOC_SYNTH_ONLY"\n'''
    (BASE/'synth.tcl').write_text(tcl)
    banned=['place_design','phys_opt_design','route_design','write_bitstream','write_cfgmem','open_hw','program_hw','create_clock','create_generated_clock','set_false_path','set_clock_groups']
    tcl_lower=tcl.lower();need(not any(word in tcl_lower for word in banned),'OOC Tcl contains forbidden implementation/clock/bitstream command')
    samples=[]
    for i in range(3):
        row=sample();samples.append(row)
        if i<2:time.sleep(1)
    need(all(x['pass'] for x in samples),'Fresh host resource admission did not pass 3 samples')
    need(VIVADO.is_file(),'Installed main Vivado binary is unavailable')
    tool_manifest={'schema':'ddr-capacity-service-native-tool-manifest-v1','status':'HASH_BOUND_VERSION_NOT_QUERIED_PENDING_ROOT_REVIEW',
      'tools':[{'name':'vivado','path':str(VIVADO),'sha256':sha(VIVADO),'bytes':VIVADO.stat().st_size,
                'version_argv':[str(VIVADO),'-version'],'version_status':'NOT_RUN'}],
      'systemd_run_resource_limits':{'MemoryMax':'8G','MemorySwapMax':'0','CPUQuota':'200%','TasksMax':256,'timeout_seconds':600}}
    (BASE/'native-tool-manifest.json').write_text(json.dumps(tool_manifest,indent=2,sort_keys=True)+'\n')
    prep={'schema':'ddr-capacity-service-vivado-ooc-preparation-v1','status':'READY_FOR_ROOT_REVIEW_NO_NATIVE_LAUNCH',
      'scope':'Nominal Yosys-independent Vivado OOC synthesis/resource reports for exact ten-source capacity-service subsystem; no constraints, placement, routing, bitstream, hardware, or full-design fit/physical qualification.',
      'top':TOP,'part':PART,'mode':'out_of_context','source_manifest_path':str(BASE/'source-manifest.json'),
      'source_manifest_sha256':sha(BASE/'source-manifest.json'),'source_lint_report_path':str(LINT),'source_lint_report_sha256':sha(LINT),
      'source_lint_version':3,'source_count':10,'clock_evidence_path':str(BASE/'clock-evidence.json'),
      'clock_evidence_sha256':sha(BASE/'clock-evidence.json'),'source_ui_period_ns':UI_PERIOD_NS,
      'native_tool_path':str(VIVADO),'native_tool_sha256':sha(VIVADO),'native_tool_version':'NOT_QUERIED_PENDING_ROOT_REVIEW',
      'native_tool_manifest_path':str(BASE/'native-tool-manifest.json'),'native_tool_manifest_sha256':sha(BASE/'native-tool-manifest.json'),
      'synth_tcl_path':str(BASE/'synth.tcl'),'synth_tcl_sha256':sha(BASE/'synth.tcl'),
      'runner_path':str(BASE/'run_ooc.py'),'runner_sha256':sha(BASE/'run_ooc.py'),
      'preparation_generator_path':str(Path(__file__).resolve()),'preparation_generator_sha256':sha(Path(__file__).resolve()),
      'resource_limits':{'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256','timeout_seconds':600},
      'resource_admission_samples':samples,'planned_command':['systemd-run','--user','--scope','--unit='+UNIT,'-p','MemoryMax=8G',
        '-p','MemorySwapMax=0','-p','CPUQuota=200%','-p','TasksMax=256','python3',str(BASE/'run_ooc.py')],
      'root_review_sha256':None,'native_launch_approved':False,'hardware_accessed':False,'bitstream_emitted':False,
      'implementation_executed':False,'physical_capacity_qualified':False,'full_design_fit_claim':False}
    (BASE/'preparation.json').write_text(json.dumps(prep,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':prep['status'],'source_count':10,'manifest_sha256':prep['source_manifest_sha256'],
      'C1_clock':clock,'Vivado_path':str(VIVADO),'Vivado_sha256':prep['native_tool_sha256'],
      'resource_admission_samples':len(samples),'launch_approved':False},indent=2))

if __name__=='__main__':main()
