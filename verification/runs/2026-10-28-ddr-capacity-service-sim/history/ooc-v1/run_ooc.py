#!/usr/bin/env python3
"""Bounded OOC Vivado synthesis for the frozen ten-source DDR capacity service."""
from pathlib import Path
import datetime,hashlib,json,os,re,signal,subprocess,time

ROOT=Path('/home/fedora/rknpu-fpga');BASE=Path(__file__).resolve().parent
PREP=BASE/'preparation.json';REPORT=BASE/'report.json';OUTPUT=BASE/'output'
ROOT_REVIEW=BASE/'root-review.json';TOOL_MANIFEST=BASE/'native-tool-manifest.json'
VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado');CHILD=None;TIMEOUT=600

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,msg):
    if not ok:raise ValueError(msg)
def cgroup_dir():
    rel=next(x[3:] for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::')).lstrip('/')
    return Path('/sys/fs/cgroup')/rel
def group_pids(pgid):
    result=[]
    for e in Path('/proc').iterdir():
        if not e.name.isdigit():continue
        try:
            f=(e/'stat').read_text().rsplit(')',1)[1].split()
            if int(f[2])==pgid and f[0] not in {'Z','X'}:result.append(int(e.name))
        except (FileNotFoundError,ProcessLookupError,PermissionError,ValueError,IndexError):pass
    return sorted(result)
def stop_owned(child):
    if child is None:return []
    try:os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:child.wait(timeout=8)
    except subprocess.TimeoutExpired:pass
    live=group_pids(child.pid)
    if live:
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:pass
    return group_pids(child.pid)

def main():
    global CHILD
    started=time.monotonic();record={'status':'PREFLIGHT','scope':'ten-source rk_ddr_capacity_service OOC synthesis/resource report only; no implementation, timing, bitstream, or hardware claim',
        'hardware_accessed':False,'bitstream_emitted':False,'implementation_executed':False,'vivado_executed':False}
    need(not REPORT.exists(),'Fresh Vivado OOC output report required')
    try:
        prep=json.loads(PREP.read_text());need(prep['status']=='READY_FOR_ROOT_REVIEW_NO_NATIVE_LAUNCH','Preparation state changed')
        need(prep['native_launch_approved'] is True and prep['root_review_sha256'] is not None,'Root has not approved native Vivado launch')
        need(ROOT_REVIEW.is_file() and sha(ROOT_REVIEW)==prep['root_review_sha256'],'Root OOC review hash mismatch')
        review=json.loads(ROOT_REVIEW.read_text())
        for key,value in {'status':'ROOT_REVIEWED_DDR_CAPACITY_SERVICE_OOC_SYNTH','native_launch_approved':True,
            'source_manifest_sha256':prep['source_manifest_sha256'],'synth_tcl_sha256':prep['synth_tcl_sha256'],
            'clock_evidence_sha256':prep['clock_evidence_sha256'],'native_tool_sha256':prep['native_tool_sha256'],
            'top':'rk_ddr_capacity_service','part':'xc7k480tffg1156-2','mode':'out_of_context'}.items():
            need(review.get(key)==value,'Root OOC approval binding mismatch: '+key)
        manifest=json.loads((BASE/'source-manifest.json').read_text());need(len(manifest['sources'])==10,'Expected ten frozen Verilog sources')
        tool_manifest=json.loads(TOOL_MANIFEST.read_text())
        expected_tool=[{'name':'vivado','path':str(VIVADO),'sha256':sha(VIVADO),'bytes':VIVADO.stat().st_size,
            'version_argv':[str(VIVADO),'-version'],'version_status':'NOT_RUN'}]
        need(tool_manifest.get('tools')==expected_tool and sha(TOOL_MANIFEST)==prep['native_tool_manifest_sha256'],
             'Native tool hash manifest changed')
        lint=Path(prep['source_lint_report_path']);need(lint.is_file() and sha(lint)==prep['source_lint_report_sha256'],'Source lint report changed')
        clock=json.loads((BASE/'clock-evidence.json').read_text())
        need(clock['status']=='PASS_SOURCE_DERIVED_C1_UI_CLOCK_PERIOD' and clock['derived_ui_period_ns']==7.5,'C1 UI clock derivation mismatch')
        need(sha(clock['source_path'])==clock['source_sha256'],'Frozen C1 MIG clock source changed')
        before={}
        for row in manifest['sources']:
            for p,h in ((row['original_path'],row['original_sha256']),(row['copied_path'],row['copied_sha256'])):
                need(Path(p).is_file() and sha(p)==h,'Frozen OOC source changed: '+p);before[p]=sha(p)
        for p in (PREP,ROOT_REVIEW,TOOL_MANIFEST,BASE/'source-manifest.json',BASE/'clock-evidence.json',BASE/'synth.tcl',
                  BASE/'prepare_ooc.py',Path(__file__).resolve(),lint,VIVADO,Path(clock['source_path'])):
            before[str(p)]=sha(p)
        cg=cgroup_dir();limits={k:(cg/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        expected={'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'}
        need(limits==expected,'Vivado OOC cgroup limits were not enforced')
        available=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
        mempsi=Path('/proc/pressure/memory').read_text();cpupsi=Path('/proc/pressure/cpu').read_text()
        need(available>=12582912 and float(re.search(r'^full avg10=([0-9.]+)',mempsi,re.M)[1])<1 and
             float(re.search(r'^some avg10=([0-9.]+)',cpupsi,re.M)[1])<5,'Host resource admission failed')
        need(not OUTPUT.exists(),'Fresh OOC output directory required')
        version=subprocess.run([str(VIVADO),'-version'],capture_output=True,text=True,timeout=30,check=True)
        argv=[str(VIVADO),'-mode','batch','-source',str(BASE/'synth.tcl'),'-tclargs',str(OUTPUT)]
        record.update(status='RUNNING',argv=argv,vivado_path=str(VIVADO),vivado_sha256=sha(VIVADO),vivado_version=version.stdout,
          root_review_path=str(ROOT_REVIEW),root_review_sha256=sha(ROOT_REVIEW),
          tool_manifest_path=str(TOOL_MANIFEST),tool_manifest_sha256=sha(TOOL_MANIFEST),
          source_manifest_path=str(BASE/'source-manifest.json'),source_manifest_sha256=sha(BASE/'source-manifest.json'),
          synth_tcl_path=str(BASE/'synth.tcl'),synth_tcl_sha256=sha(BASE/'synth.tcl'),
          input_hashes_before=before,kernel_limits=limits,host_memavailable_kib=available,memory_psi=mempsi,cpu_psi=cpupsi,
          timeout_seconds=TIMEOUT,top='rk_ddr_capacity_service',part='xc7k480tffg1156-2',mode='out_of_context',
          clock_evidence_path=str(BASE/'clock-evidence.json'),clock_evidence_sha256=sha(BASE/'clock-evidence.json'),
          constraints_applied=False,implementation_executed=False)
        REPORT.write_text(json.dumps(record,indent=2)+'\n');OUTPUT.mkdir()
        with (BASE/'stdout.log').open('x') as out,(BASE/'stderr.log').open('x') as err:
            CHILD=subprocess.Popen(argv,cwd=BASE,stdout=out,stderr=err,start_new_session=True)
            record.update(pid=CHILD.pid,pgid=CHILD.pid);REPORT.write_text(json.dumps(record,indent=2)+'\n')
            try:record['returncode']=CHILD.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                record['status']='TIMEOUT';record['cleanup_live_pids']=stop_owned(CHILD);raise TimeoutError('Vivado OOC synthesis exceeded 600 seconds')
        text=(BASE/'stdout.log').read_text(errors='replace');marker='PASS_DDR_CAPACITY_SERVICE_OOC_SYNTH_ONLY'
        need(record['returncode']==0 and text.splitlines().count(marker)==1,'OOC synthesis lacks rc0 and exact marker')
        reports=[OUTPUT/'utilization.rpt',OUTPUT/'utilization-hierarchical.rpt']
        for p in reports:need(p.is_file(),'Missing OOC utilization report '+p.name)
        record.update(status='PASS_DDR_CAPACITY_SERVICE_OOC_SYNTH_RESOURCE_REPORT_ONLY',stdout_sha256=sha(BASE/'stdout.log'),
          stderr_sha256=sha(BASE/'stderr.log'),stdout_marker_count=1,
          outputs={str(p):{'sha256':sha(p),'bytes':p.stat().st_size} for p in reports},
          nominal_resource_scope_only=True,full_design_or_physical_qualification=False)
    except BaseException as error:
        record.update(status='TIMEOUT' if record.get('status')=='TIMEOUT' else 'FAIL_DDR_CAPACITY_SERVICE_OOC_SYNTH',error=repr(error))
        if CHILD is not None and CHILD.poll() is None:record['cleanup_live_pids']=stop_owned(CHILD)
    finally:
        if CHILD is not None:
            if CHILD.poll() is None:record['cleanup_live_pids']=stop_owned(CHILD)
            record['owned_process_group_live_pids_after']=group_pids(CHILD.pid)
            record['owned_process_group_stopped']=not bool(record['owned_process_group_live_pids_after'])
        try:
            prep=json.loads(PREP.read_text());manifest=json.loads((BASE/'source-manifest.json').read_text())
            after={}
            for row in manifest['sources']:
                after[row['original_path']]=sha(row['original_path']);after[row['copied_path']]=sha(row['copied_path'])
            for p in (PREP,ROOT_REVIEW,TOOL_MANIFEST,BASE/'source-manifest.json',BASE/'clock-evidence.json',BASE/'synth.tcl',
                      BASE/'prepare_ooc.py',Path(__file__).resolve(),
                      Path(prep['source_lint_report_path']),VIVADO,Path(json.loads((BASE/'clock-evidence.json').read_text())['source_path'])):
                after[str(p)]=sha(p)
            record['input_hashes_after']=after;record['all_inputs_unchanged']=after==record.get('input_hashes_before')
            if not record['all_inputs_unchanged'] and record.get('status','').startswith('PASS_'):record['status']='FAIL_INPUT_MUTATION_AFTER_OOC'
        except BaseException as error:record['rehash_error']=repr(error);record['all_inputs_unchanged']=False
        try:
            cg=cgroup_dir();record['memory_peak_bytes']=(cg/'memory.peak').read_text().strip();record['memory_events']=(cg/'memory.events').read_text().strip()
        except BaseException as error:record['cgroup_error']=repr(error)
        record['elapsed_seconds']=time.monotonic()-started;record['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        record.update(hardware_accessed=False,bitstream_emitted=False,implementation_executed=False)
        REPORT.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    return 0 if record.get('status')=='PASS_DDR_CAPACITY_SERVICE_OOC_SYNTH_RESOURCE_REPORT_ONLY' and record.get('all_inputs_unchanged') and record.get('owned_process_group_stopped') else 1

if __name__=='__main__':raise SystemExit(main())
