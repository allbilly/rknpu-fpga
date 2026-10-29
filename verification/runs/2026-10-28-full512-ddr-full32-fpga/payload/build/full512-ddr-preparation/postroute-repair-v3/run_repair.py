#!/usr/bin/env python3
"""Process-owned runner for a root-approved post-route repair attempt only.

The package stays unlaunchable until the Boot CE-driver query and separate root
repair admission are source/DCP-bound. No source or timing exceptions are edited.
"""
from pathlib import Path
import datetime, hashlib, json, os, re, signal, subprocess, sys, time

ROOT=Path('/home/fedora/rknpu-fpga')
BASE=Path(__file__).resolve().parent
V6=ROOT/'build/full512-ddr-preparation/shared-data-route-prep-v6'
SOURCE_PREP=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v4'
PREP=BASE/'preparation.json'; ADMISSION=BASE/'repair-admission.json'; SELECTION=BASE/'repair-selection.json'
ROUTE_TCL=BASE/'repair.tcl'; ANCHORS=BASE/'expected-anchor-names.txt'
OUTPUT=BASE/'output'; REPORT=BASE/'report.json'; VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
TIMEOUT=7200
child=None; received_signal=None; record=None
sys.path.insert(0,str(ROOT))
from tools.hardware.sample_ew import tcl_literal


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def need(ok,message):
    if not ok:raise ValueError(message)
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save():REPORT.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
def cgroup_dir():
    rel=next(x.split('::',1)[1].lstrip('/') for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
    return Path('/sys/fs/cgroup')/rel
def owned_group_members(pgid):
    members=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
            if int(fields[2])==pgid and fields[0] not in {'Z','X'}:members.append(int(entry.name))
        except (FileNotFoundError,ProcessLookupError,ValueError,IndexError):continue
    return sorted(members)
def kill_owned(sig):
    global child
    if child is None:return
    try:os.killpg(child.pid,sig)
    except ProcessLookupError:pass
    try:child.wait(timeout=10)
    except subprocess.TimeoutExpired:pass
    if owned_group_members(child.pid):
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        if child.poll() is None:child.wait()
def on_signal(sig,frame):
    global received_signal
    received_signal=sig
    raise InterruptedError('post-route repair runner interrupted '+str(sig))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,on_signal)
def hash_inputs(paths):return {str(Path(p)):sha(p) for p in paths}
def fresh_sample():
    avail=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
    mp=Path('/proc/pressure/memory').read_text();cp=Path('/proc/pressure/cpu').read_text()
    full=float(re.search(r'^full avg10=([0-9.]+)',mp,re.M)[1]);some=float(re.search(r'^some avg10=([0-9.]+)',cp,re.M)[1])
    return {'utc':stamp(),'memavailable_kib':avail,'memory_psi_full_avg10':full,'cpu_psi_some_avg10':some,
            'pass':avail>=12582912 and full<1 and some<5}
def validate_selection(sel,approval,prep):
    need(sel['status']=='ROOT_REVIEWED_ACTUAL_CE_DRIVER_NET_SELECTION','CE-driver net selection is pending Boot/root review')
    for key in ('parent_v6_route_report_sha256','parent_routed_dcp_sha256','source_post_opt_dcp_sha256'):
        prep_key={'parent_v6_route_report_sha256':'parent_v6_report_sha256'}.get(key,key)
        need(sel[key]==prep[prep_key],'CE-driver selection binds a different parent')
    query=Path(sel['ce_query_report_path'])
    need(query.is_absolute() and query.is_file() and sha(query)==sel['ce_query_report_sha256'],
         'Actual CE-driver query report is missing or changed')
    nets=sel['selected_nets']
    need(isinstance(nets,list) and nets and len(nets)==len(set(nets)),'Empty/duplicate CE-driver net list')
    for name in nets:
        need(isinstance(name,str) and name and all(c not in name for c in '\n\r\0'),
             'Malformed root-selected net name')
    need(approval['repair_selection_sha256']==sha(SELECTION) and
         approval['ce_query_report_sha256']==sel['ce_query_report_sha256'],
         'Root admission does not bind current CE-driver evidence')
    return nets,query

def main():
    global child,record
    need(not REPORT.exists() and not OUTPUT.exists(),'Fresh post-route repair attempt required')
    started=time.monotonic()
    record={'status':'PREFLIGHT','scope':'Post-route targeted physical repair of a source-bound failed routed checkpoint only; no image/hardware',
            'hardware_accessed':False,'bitstream_emitted':False,'flash_written':False,
            'place_design_executed':False,'route_design_started':False,'started_utc':stamp()}
    try:
        prep=json.loads(PREP.read_text());approval=json.loads(ADMISSION.read_text());selection=json.loads(SELECTION.read_text())
        need(prep['status']=='ROOT_REVIEWED_POSTROUTE_REPAIR_PACKAGE' and prep['launchable'] is True and
             prep['root_review_authorized_before_launch'] is True,'Package remains unlaunchable pending root review')
        need(approval['status']=='APPROVED_PHYSICAL_REPAIR_OF_SOURCE_BOUND_ROUTED_DCP' and
             approval['launch_approved'] is True and approval['root_repair_approval'] is True,
             'Separate source-bound root repair admission is not approved')
        need(approval['preparation_sha256']==sha(PREP) and approval['runner_sha256']==sha(Path(__file__)) and
             approval['repair_tcl_sha256']==sha(ROUTE_TCL),'Root admission is not bound to this package')
        need(prep['parent_v6_report_sha256']==sha(prep['parent_v6_report_path']) and
             prep['parent_v6_status']=='FAIL' and prep['parent_v6_returncode']==1,
             'Original V6 setup-failure provenance changed')
        need(approval['parent_route_report_sha256']==prep['parent_v6_report_sha256'] and
             approval['source_post_opt_review_sha256']==prep['source_post_opt_review_sha256'],
             'Root repair admission does not bind parent failure/source audit')
        need(prep['parent_routed_dcp_sha256']==approval['parent_routed_dcp_sha256']==
             sha(prep['parent_routed_dcp_path']),'Parent routed DCP hash changed')
        need(prep['source_post_opt_dcp_sha256']==approval['source_post_opt_dcp_sha256']==
             sha(prep['source_post_opt_dcp_path']),'Source post-opt DCP ancestry changed')
        source_review=json.loads(Path(prep['source_post_opt_review_path']).read_text())
        need(source_review['status']=='PASS_FULL512_POST_OPT_SOURCE_AUDIT' and
             source_review['post_opt_dcp_sha256']==prep['source_post_opt_dcp_sha256'],
             'Source post-opt review status/DCP binding changed')
        nets,query=validate_selection(selection,approval,prep)
        need(prep['repair_selection_sha256']==sha(SELECTION),'Preparation does not bind current CE-driver selection')
        need(approval['ce_query_report_path']==str(query),'Root repair approval query-report path changed')
        need(not OUTPUT.exists() and not REPORT.exists(),'Fresh post-route repair attempt required')
        cg=cgroup_dir();limits={k:(cg/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        required={'memory.max':'12884901888','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'}
        need(limits==required,'Wrong post-route repair cgroup: '+repr(limits))
        samples=[]
        for i in range(3):
            s=fresh_sample();samples.append(s);record['host_admission_samples']=samples[:]
            if not s['pass']:raise ValueError('Fresh host resource admission sample failed')
            if i<2:time.sleep(30)
        need(len(prep['parent_v6_input_hashes'])==186==prep['parent_v6_input_count'],
             'Parent V6 source/control input count changed')
        expected=dict(prep['parent_v6_input_hashes'])
        for path,h in prep['parent_v6_output_hashes'].items():
            key=str(Path(path));need(key not in expected or expected[key]==h,
                 'Parent input/output alias carries conflicting hash: '+key);expected[key]=h
        expected.update(prep['repair_control_hashes'])
        for label,path in prep['parent_extra_paths'].items():
            h=prep['parent_extra_hashes'][label]
            need(path not in expected or expected[path]==h,
                 'Parent source/control alias carries conflicting hash: '+path);expected[path]=h
        expected[str(PREP)]=approval['preparation_sha256']
        expected[str(SELECTION)]=sha(SELECTION);expected[str(ADMISSION)]=sha(ADMISSION)
        expected[str(query)]=selection['ce_query_report_sha256']
        before=hash_inputs(expected);need(before==expected,'Repair parent/source input drift')
        OUTPUT.mkdir()
        anchor_out=OUTPUT/'expected-anchor-names.txt';anchor_out.write_bytes(ANCHORS.read_bytes())
        nets_tcl=OUTPUT/'repair_selected_nets.tcl'
        nets_tcl.write_text('set repair_selected_nets [list '+' '.join(tcl_literal(n) for n in nets)+']\n')
        before[str(anchor_out)]=sha(anchor_out);before[str(nets_tcl)]=sha(nets_tcl)
        need(hash_inputs({str(anchor_out):before[str(anchor_out)],str(nets_tcl):before[str(nets_tcl)]})==
             {str(anchor_out):before[str(anchor_out)],str(nets_tcl):before[str(nets_tcl)]},'Generated repair control changed')
        record.update(status='READY_TO_LAUNCH',argv=[str(VIVADO),'-mode','batch','-source',str(ROUTE_TCL),
            '-log',str(OUTPUT/'vivado.log'),'-journal',str(OUTPUT/'vivado.jou')],cwd=str(OUTPUT),
            kernel_limits=limits,input_hashes_expected=before,input_hashes_before=before,
            parent_route_report_sha256=prep['parent_v6_report_sha256'],input_routed_dcp_sha256=prep['parent_routed_dcp_sha256'],
            source_post_opt_dcp_sha256=prep['source_post_opt_dcp_sha256'],repair_net_selection=selection,
            host_admission_samples=samples,vivado_path=str(VIVADO),vivado_sha256=sha(VIVADO),
            vivado_version_lines=prep['vivado_version_lines'],timeout_seconds=7200)
        save()
        env=dict(os.environ,RK_POSTROUTE_REPAIR_PARENT_DCP=prep['parent_routed_dcp_path'],
                 RK_SHARED_ROUTE_EXPECTED_ANCHOR_FILE=str(anchor_out),
                 RK_POSTROUTE_REPAIR_NETS_TCL=str(nets_tcl),
                 RK_POSTROUTE_REPAIR_APPROVAL='APPROVED_PHYSICAL_REPAIR_OF_SOURCE_BOUND_ROUTED_DCP')
        record.update(status='RUNNING',route_design_started=True);save()
        with (OUTPUT/'stdout.log').open('x') as so,(OUTPUT/'stderr.log').open('x') as se:
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
            try:
                child=subprocess.Popen(record['argv'],cwd=OUTPUT,env=env,stdout=so,stderr=se,start_new_session=True,
                    preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
                record.update(pid=child.pid,pgid=child.pid,launched_utc=stamp());save()
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
            try:record['returncode']=child.wait(timeout=7200)
            except subprocess.TimeoutExpired:
                record['status']='TIMEOUT';kill_owned(signal.SIGTERM);record['returncode']=child.returncode
                raise TimeoutError('Owned post-route physical repair exceeded 7200 seconds')
        stdout=(OUTPUT/'stdout.log').read_text(errors='replace')
        marker='PASS_FULL512_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_SOURCE_AUDIT_AND_PHYSICAL_REVIEW'
        need(record['returncode']==0 and stdout.splitlines().count(marker)==1,
             'Native repair did not meet the strict route gates/marker')
        after=hash_inputs(before);need(after==before,'Repair input changed during native implementation')
        repaired=OUTPUT/'post_route.dcp';need(repaired.is_file(),'Repaired post_route.dcp is missing')
        need((OUTPUT/'timing.rpt').is_file(),'Repaired routed timing report is missing')
        record.update(status=marker,input_hashes_after=after,all_inputs_unchanged=True,
            repaired_post_route_dcp_path=str(repaired),repaired_post_route_dcp_sha256=sha(repaired),
            repaired_timing_report_path=str(OUTPUT/'timing.rpt'),repaired_timing_report_sha256=sha(OUTPUT/'timing.rpt'))
    except BaseException as error:
        if child is not None and child.poll() is None:kill_owned(signal.SIGTERM)
        record.update(status=('TIMEOUT' if record.get('status')=='TIMEOUT' else ('CANCELLED' if received_signal else 'FAIL')),error=repr(error),received_signal=received_signal,
            returncode=(child.returncode if child is not None else None))
    finally:
        record['finished_utc']=stamp();record['elapsed_seconds']=time.monotonic()-started
        try:
            cg=cgroup_dir();record['memory_peak_bytes']=(cg/'memory.peak').read_text().strip();record['memory_events']=(cg/'memory.events').read_text().strip()
        except BaseException as error:record['cgroup_telemetry_error']=repr(error)
        if child is not None:
            group=owned_group_members(child.pid)
            if group:
                record['lingering_owned_group_pids_before_cleanup']=group;kill_owned(signal.SIGTERM)
                if owned_group_members(child.pid):
                    record['lingering_owned_group_pids_after_cleanup']=owned_group_members(child.pid)
                    if str(record.get('status','')).startswith('PASS_'):record['status']='FAIL_OWNED_GROUP_LINGERED'
                else:record['owned_process_group_stopped']=True
            else:record['owned_process_group_stopped']=True
        if 'input_hashes_before' in record:
            try:
                after=hash_inputs(record['input_hashes_before']);record['input_hashes_after']=after
                record['all_inputs_unchanged']=after==record['input_hashes_before']
                if not record['all_inputs_unchanged'] and str(record.get('status','')).startswith('PASS_'):
                    record['status']='FAIL_REPAIR_INPUT_MUTATION'
            except BaseException as error:
                record['input_rehash_error']=repr(error)
                if str(record.get('status','')).startswith('PASS_'):record['status']='FAIL_REPAIR_INPUT_REHASH'
        if OUTPUT.exists():record['output_hashes']={str(p.relative_to(OUTPUT)):sha(p) for p in OUTPUT.rglob('*') if p.is_file()}
        record.setdefault('hardware_accessed',False);record.setdefault('bitstream_emitted',False);record.setdefault('flash_written',False)
        save()
    return 0 if str(record.get('status','')).startswith('PASS_FULL512_DDR_ROUTED') else 1

if __name__=='__main__':raise SystemExit(main())
