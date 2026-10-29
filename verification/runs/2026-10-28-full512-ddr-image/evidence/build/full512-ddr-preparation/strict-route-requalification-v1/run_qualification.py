#!/usr/bin/env python3
"""Root-reviewed, read-only strict gate rerun over an existing routed DCP."""
from pathlib import Path
import datetime, hashlib, json, os, re, signal, subprocess, time

ROOT=Path('/home/fedora/rknpu-fpga')
BASE=Path(__file__).resolve().parent
PREP=BASE/'preparation.json'; REVIEW=BASE/'root-review.json'
TCL=BASE/'qualification.tcl'; OUTPUT=BASE/'output'; REPORT=BASE/'report.json'
PARENT=ROOT/'build/full512-ddr-preparation/postroute-repair-v3'
PARENT_REPORT=PARENT/'report.json'; PARENT_DCP=PARENT/'output/post_route.dcp'
TEMPLATE=ROOT/'fpga/ddr/emit_full512_ch1.tcl.in'
VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
TIMEOUT=1800
child=None; received_signal=None; record=None

def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()
def need(ok,message):
    if not ok: raise ValueError(message)
def stamp(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save(): REPORT.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
def cgroup_dir():
    rel=next(x.split('::',1)[1].lstrip('/') for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
    return Path('/sys/fs/cgroup')/rel
def group_members(pgid):
    out=[]
    for ent in Path('/proc').iterdir():
        if not ent.name.isdigit(): continue
        try:
            f=(ent/'stat').read_text().rsplit(')',1)[1].split()
            if int(f[2])==pgid and f[0] not in {'Z','X'}: out.append(int(ent.name))
        except (FileNotFoundError,ProcessLookupError,ValueError,IndexError): pass
    return sorted(out)
def kill_owned(sig):
    if child is None:return
    try: os.killpg(child.pid,sig)
    except ProcessLookupError: pass
    try: child.wait(timeout=10)
    except subprocess.TimeoutExpired: pass
    if group_members(child.pid):
        try: os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        if child.poll() is None: child.wait()
def on_signal(sig,frame):
    global received_signal
    received_signal=sig
    raise InterruptedError('strict route requalification interrupted '+str(sig))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP): signal.signal(sig,on_signal)
def hash_map(mapping): return {str(Path(p)):sha(p) for p in mapping}
def fresh_sample():
    avail=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
    mp=Path('/proc/pressure/memory').read_text(); cp=Path('/proc/pressure/cpu').read_text()
    full=float(re.search(r'^full avg10=([0-9.]+)',mp,re.M)[1]); some=float(re.search(r'^some avg10=([0-9.]+)',cp,re.M)[1])
    return {'utc':stamp(),'memavailable_kib':avail,'memory_psi_full_avg10':full,'cpu_psi_some_avg10':some,
            'pass':avail>=12582912 and full<1 and some<5}
def main():
    global child,record
    need(not OUTPUT.exists() and not REPORT.exists(),'Fresh strict route requalification output required')
    started=time.monotonic()
    record={'status':'PREFLIGHT','scope':'Read-only strict requalification and serialization of an already-routed full512 DDR DCP; no implementation or hardware',
            'hardware_accessed':False,'bitstream_emitted':False,'flash_written':False,
            'synthesis_executed':False,'place_design_executed':False,'phys_opt_design_executed':False,
            'route_design_executed':False,'started_utc':stamp()}
    try:
        prep=json.loads(PREP.read_text()); review=json.loads(REVIEW.read_text())
        need(prep.get('status')=='ROOT_REVIEWED_STRICT_ROUTE_REQUALIFICATION' and prep.get('launchable') is True,
             'Package remains unlaunchable pending root review and terminal repair-v3 parent')
        need(review.get('status')=='ROOT_APPROVED_STRICT_ROUTE_REQUALIFICATION' and review.get('launch_approved') is True,
             'Root strict-route requalification approval is missing')
        need(review.get('preparation_sha256')==sha(PREP) and review.get('runner_sha256')==sha(Path(__file__)) and
             review.get('qualification_tcl_sha256')==sha(TCL),'Root approval does not bind current package')
        parent=json.loads(PARENT_REPORT.read_text())
        need(parent.get('finished_utc') and parent.get('returncode')==0,'Repair-v3 native process is not terminal with rc0')
        need(parent.get('status')=='FAIL' and 'Repair input changed during native implementation' in str(parent.get('error','')),
             'Parent wrapper provenance failure is not the preserved exact emitter-drift failure')
        native_stdout=PARENT/'output/stdout.log'; native_stderr=PARENT/'output/stderr.log'
        marker=prep['parent_expected_native_marker']
        need(native_stdout.is_file() and native_stdout.read_text(errors='replace').splitlines().count(marker)==1,
             'Repair-v3 native PASS marker missing or duplicated')
        need(native_stderr.is_file() and sha(native_stderr)==parent.get('output_hashes',{}).get('stderr.log'),
             'Repair-v3 native stderr hash differs from terminal report')
        need(parent.get('input_hashes_before')==prep.get('parent_input_hashes_at_launch'),
             'Repair-v3 source-closure snapshot differs from reviewed package')
        after=parent.get('input_hashes_after'); before=parent.get('input_hashes_before')
        need(isinstance(after,dict) and isinstance(before,dict) and set(after)==set(before),
             'Repair-v3 final source closure is missing or changed')
        changed=[p for p in before if before[p]!=after[p]]
        drift=prep['only_allowed_parent_input_drift']['path']
        need(changed==[drift] and before[drift]==prep['only_allowed_parent_input_drift']['prior_expected_sha256'] and
             after[drift]==sha(TEMPLATE)==prep['only_allowed_parent_input_drift']['current_sha256'],
             'Repair-v3 input provenance failure is not the sole reviewed unused-template drift')
        for p,h in after.items(): need(Path(p).is_file() and sha(p)==h,'Repair-v3 source/control input changed: '+p)
        pgid=parent.get('pgid'); need(isinstance(pgid,int) and not group_members(pgid),'Repair-v3 owned process group remains active')
        parent_dcp=PARENT_DCP
        need(parent_dcp==PARENT_DCP and sha(parent_dcp)==parent.get('output_hashes',{}).get('post_route.dcp')==
             prep['parent_routed_dcp_sha256'],'Repair-v3 routed DCP hash changed')
        need(parent.get('source_post_opt_dcp_sha256')==prep['source_post_opt_dcp_sha256'],
             'Original source post-opt ancestry changed')
        need(prep.get('parent_report_sha256')==sha(PARENT_REPORT) and prep.get('parent_stdout_sha256')==sha(native_stdout),
             'Reviewed terminal repair-v3 report/log hashes changed')
        need(prep.get('bound_input_hashes') and hash_map(prep['bound_input_hashes'])==prep['bound_input_hashes'],
             'Strict requalification input closure is missing or changed')
        need(prep['bound_input_hashes'].get(str(PARENT_DCP))==sha(PARENT_DCP) and
             prep['bound_input_hashes'].get(str(PARENT_REPORT))==sha(PARENT_REPORT),
             'Strict requalification closure does not bind the routed DCP and terminal parent report')
        cg=cgroup_dir(); limits={k:(cg/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        required={'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'}
        need(limits==required,'Wrong strict requalification cgroup: '+repr(limits))
        samples=[]
        for i in range(3):
            sample=fresh_sample(); samples.append(sample); record['host_admission_samples']=samples[:]
            if not sample['pass']: raise ValueError('Fresh host resource admission sample failed')
            if i<2: time.sleep(30)
        before_hashes=hash_map(prep['bound_input_hashes'])
        expected=dict(prep['bound_input_hashes'])
        expected[str(PREP)]=sha(PREP); expected[str(REVIEW)]=sha(REVIEW)
        before_hashes=hash_map(expected)
        need(before_hashes==expected,'Strict route requalification input drift before launch')
        record.update(input_hashes_expected=expected,input_hashes_before=before_hashes,
            parent_report_status=parent.get('status'),parent_native_exception=parent.get('error'),
            parent_native_returncode=parent.get('returncode'),parent_native_marker_count=1,
            parent_provenance_drift_paths=changed,parent_provenance_failure_preserved=True,
            parent_vivado_version_lines_from_preparation=prep.get('parent_vivado_version_lines',[]),
            source_post_opt_dcp_sha256=prep['source_post_opt_dcp_sha256'],checkpoint_exported=False)
        OUTPUT.mkdir()
        record.update(status='READY_TO_LAUNCH',argv=[str(VIVADO),'-mode','batch','-source',str(TCL),
            '-log',str(OUTPUT/'vivado.log'),'-journal',str(OUTPUT/'vivado.jou')],cwd=str(OUTPUT),
            kernel_limits=limits,input_hashes_before=before_hashes,parent_report_sha256=sha(PARENT_REPORT),
            parent_routed_dcp_sha256=sha(PARENT_DCP),source_post_opt_dcp_sha256=prep['source_post_opt_dcp_sha256'],
            vivado_path=str(VIVADO),vivado_sha256=sha(VIVADO),timeout_seconds=TIMEOUT,
            host_admission_samples=samples)
        save()
        env=dict(os.environ,RK_POSTROUTE_REPAIR_PARENT_DCP=str(PARENT_DCP),
                 RK_SHARED_ROUTE_EXPECTED_ANCHOR_FILE=str(BASE/'expected-anchor-names.txt'))
        record['status']='RUNNING'; save()
        with (OUTPUT/'stdout.log').open('x') as so,(OUTPUT/'stderr.log').open('x') as se:
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
            try:
                child=subprocess.Popen(record['argv'],cwd=OUTPUT,env=env,stdout=so,stderr=se,start_new_session=True,
                    preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
                record.update(pid=child.pid,pgid=child.pid,launched_utc=stamp()); save()
            finally: signal.pthread_sigmask(signal.SIG_SETMASK,mask)
            try: record['returncode']=child.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                record['status']='TIMEOUT'; kill_owned(signal.SIGTERM); record['returncode']=child.returncode
                raise TimeoutError('Strict route requalification exceeded 1800 seconds')
        native=(OUTPUT/'stdout.log').read_text(errors='replace')
        need(record['returncode']==0 and native.splitlines().count(prep['future_marker'])==1,
             'Strict route requalification gate failed or marker missing')
        after_hashes=hash_map(expected)
        need(after_hashes==before_hashes,'Strict route requalification input changed during query')
        dcp=OUTPUT/'post_route.dcp'; need(dcp.is_file(),'Requalified checkpoint export missing')
        native_version=re.findall(r'^SHARED_DATA_ROUTE_TOOL\s+(.+)$',native,re.M)
        need(len(native_version)==1,'Actual Vivado version header missing or duplicated')
        record.update(status=prep['future_marker'],marker=prep['future_marker'],input_hashes_after=after_hashes,
            all_inputs_unchanged=True,output_dcp=str(dcp),output_dcp_sha256=sha(dcp),checkpoint_exported=True,
            actual_vivado_version_line=native_version[0])
    except BaseException as error:
        if child is not None and child.poll() is None: kill_owned(signal.SIGTERM)
        record.update(status='CANCELLED' if received_signal else ('TIMEOUT' if record.get('status')=='TIMEOUT' else 'FAIL'),
                      error=repr(error),received_signal=received_signal,
                      returncode=(child.returncode if child is not None else None))
    finally:
        record['finished_utc']=stamp(); record['elapsed_seconds']=time.monotonic()-started
        try:
            cg=cgroup_dir(); record['memory_peak_bytes']=(cg/'memory.peak').read_text().strip(); record['memory_events']=(cg/'memory.events').read_text().strip()
        except BaseException as error: record['cgroup_telemetry_error']=repr(error)
        if child is not None:
            members=group_members(child.pid)
            if members:
                record['lingering_owned_group_pids_before_cleanup']=members; kill_owned(signal.SIGTERM)
                if group_members(child.pid):
                    record['lingering_owned_group_pids_after_cleanup']=group_members(child.pid)
                    if str(record.get('status','')).startswith('PASS_'): record['status']='FAIL_OWNED_GROUP_LINGERED'
                else: record['owned_process_group_stopped']=True
            else: record['owned_process_group_stopped']=True
        if 'input_hashes_expected' in record:
            try:
                final_inputs=dict(record['input_hashes_expected'])
                record['input_hashes_after']=hash_map(final_inputs)
                record['all_inputs_unchanged']=record['input_hashes_after']==record['input_hashes_expected']
                if not record['all_inputs_unchanged']:
                    record['status']='FAIL_REQUALIFICATION_INPUT_MUTATION'; record['checkpoint_exported']=False
            except BaseException as error:
                record['input_rehash_error']=repr(error); record['status']='FAIL_REQUALIFICATION_INPUT_REHASH'; record['checkpoint_exported']=False
        if OUTPUT.exists(): record['output_hashes']={str(p.relative_to(OUTPUT)):sha(p) for p in OUTPUT.rglob('*') if p.is_file()}
        record.setdefault('checkpoint_exported',False); record.setdefault('hardware_accessed',False); record.setdefault('bitstream_emitted',False); record.setdefault('flash_written',False)
        save()
    return 0 if record.get('status')=='PASS_REQUALIFIED_FULL512_DDR_ROUTED_CHECKPOINT_ONLY' else 1
if __name__=='__main__': raise SystemExit(main())
