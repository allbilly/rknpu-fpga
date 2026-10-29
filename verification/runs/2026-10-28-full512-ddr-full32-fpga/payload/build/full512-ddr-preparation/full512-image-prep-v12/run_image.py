#!/usr/bin/env python3
"""Bounded full512 dual-MIG image emission only; hardware programming is excluded."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import time

ROOT=Path('/home/fedora/rknpu-fpga')
BASE=Path(__file__).resolve().parent
PREP_PATH=BASE/'image-preparation.json'
BINDING_PATH=BASE/'root-bindings.json'
REPORT_PATH=BASE/'emission-report.json'
OUTPUT=BASE/'emission'
VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
CHILD=None
SIGNAL_SEEN=None
RECORD=None

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def require(ok,msg):
    if not ok:raise ValueError(msg)

def emission_timeout_seconds(manifest):
    value=manifest.get('resource_limits',{}).get('timeout_seconds')
    require(type(value) is int and value>0,'Invalid image-emission workflow timeout')
    return value

def save():REPORT_PATH.write_text(json.dumps(RECORD,indent=2)+'\n')

def cgroup_dir():
    rel=next(x[3:] for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::')).lstrip('/')
    return Path('/sys/fs/cgroup')/rel

def group_pids(pgid):
    result=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
            if int(fields[2])==pgid and fields[0] not in {'Z','X'}:result.append(int(entry.name))
        except (FileNotFoundError,ProcessLookupError,ValueError,IndexError):pass
    return sorted(result)

def kill_owned(sig):
    global CHILD
    if CHILD is None:return
    try:os.killpg(CHILD.pid,sig)
    except ProcessLookupError:pass
    try:CHILD.wait(timeout=10)
    except subprocess.TimeoutExpired:pass
    if group_pids(CHILD.pid):
        try:os.killpg(CHILD.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        if CHILD.poll() is None:CHILD.wait()

def handle_signal(sig,frame):
    global SIGNAL_SEEN
    SIGNAL_SEEN=sig
    raise InterruptedError('full512 image emitter received signal '+str(sig))

def restore_child_signal_mask(mask):
    signal.pthread_sigmask(signal.SIG_SETMASK,mask)

def verify_input_hashes(expected):
    actual={str(Path(p)):sha(p) for p in expected}
    require(actual==expected,'One or more bound full512 image inputs changed')
    return actual

def require_root_emission_approval(manifest,binding):
    require(manifest.get('status')=='READY_FOR_ROOT_REVIEWED_FULL512_IMAGE_EMISSION','Full512 image DAG is not ready')
    require(manifest.get('image_emission_approved') is True and binding.get('launch_approved') is True and
            binding.get('status')=='ROOT_REVIEWED_FULL512_IMAGE_EMISSION','Root image-emission bind is missing')

def spawn_emitter(expected,output_dir,argv,env,stdout,stderr,parent_mask,cwd=BASE,popen=subprocess.Popen):
    verify_input_hashes(expected)
    require(not Path(output_dir).exists(),'Emitter output directory must be absent when Vivado is spawned')
    return popen(argv,cwd=cwd,env=env,stdout=stdout,stderr=stderr,start_new_session=True,
                 preexec_fn=lambda:restore_child_signal_mask(parent_mask))

def main():
    global CHILD,RECORD
    started=time.monotonic()
    RECORD={'status':'PREFLIGHT','scope':'offline full512 dual-MIG image emission only; no programming, hardware access or flash','hardware_accessed':False,'hardware_programmed':False,'flash_written':False,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    require(not REPORT_PATH.exists(),'Fresh full512 image emission run required')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,handle_signal)
    try:
        manifest=json.loads(PREP_PATH.read_text());binding=json.loads(BINDING_PATH.read_text())
        timeout_seconds=emission_timeout_seconds(manifest)
        require_root_emission_approval(manifest,binding)
        require(binding.get('image_preparation_sha256')==sha(PREP_PATH),'Root binding does not pin image preparation')
        require(binding.get('run_image_sha256')==sha(BASE/'run_image.py') and binding.get('prepare_image_sha256')==sha(BASE/'prepare_image.py'),
                'Image generator/runner changed from root binding')
        sm=manifest['hardware_source_manifest']
        hw_sha=hashlib.sha256(json.dumps(sm,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        require(hw_sha==manifest['hardware_source_sha256'] and manifest['source_tag']==hw_sha[:8] and hw_sha[:8]!='00000000',
                'Source tag/manifest binding mismatch')
        require(binding.get('hardware_source_sha256')==hw_sha and binding.get('source_tag')==manifest['source_tag'],
                'Root binding names another source identity')
        route=manifest['route_gate'];dcp=Path(route['post_route_dcp_path']);route_report=Path(route['route_report_path']);review=Path(route['review_path'])
        require(dcp.is_file() and sha(dcp)==route['post_route_dcp_sha256']==binding['post_route_dcp_sha256'],'Route DCP hash mismatch')
        require(sha(route_report)==route['report_sha256'],'route report hash mismatch')
        require(sha(review)==route['review_sha256'],'Independent route review hash mismatch')
        route_data=json.loads(route_report.read_text())
        require(route_data.get('status')==route['required_report_status'] and route_data.get('returncode')==0,
                'Route v6 report is not terminal successful')
        require(route_data.get('output_hashes',{}).get('post_route.dcp')==sha(dcp),'Route report does not bind routed DCP')
        route_review=json.loads(review.read_text())
        require(route_review.get('status')=='PASS_INDEPENDENT_FULL512_DDR_ROUTE_AND_TIMING_ONLY' and
                route_review.get('post_route_dcp_sha256')==sha(dcp),'Independent route/timing review does not pass/bind this DCP')
        io_path=Path(manifest['io_snapshot_gate']['future_snapshot_json_path']);io=json.loads(io_path.read_text())
        require(io.get('status')=='PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT' and
                io.get('dcp',{}).get('sha256')==sha(dcp) and io.get('port_count')==242,'I/O snapshot is incomplete or bound to another DCP')
        for name,gate in manifest['qualification_gates'].items():
            path=Path(gate['path']);require(path.is_file() and sha(path)==gate['sha256'],name+' report missing or changed')
            data=json.loads(path.read_text());require(data.get(gate['status_field'])==gate['required_status'],name+' review status not accepted')
            if gate.get('expected_case_count') is not None:
                require(gate.get('count_field') and data.get(gate['count_field'])==gate['expected_case_count'],name+' controller case union mismatch')
        expected=dict(manifest['rendered_inputs'])
        expected[str(PREP_PATH)]=binding['image_preparation_sha256']
        expected[str(BINDING_PATH)]=sha(BINDING_PATH)
        emit=Path(manifest['emission_tcl_path'])
        require(emit.is_file() and sha(emit)==manifest['emission_tcl_sha256'],'Rendered Tcl missing/changed')
        require(binding.get('emission_tcl_path')==str(emit) and binding.get('emission_tcl_sha256')==manifest['emission_tcl_sha256'],
                'Root binding does not pin the exact rendered emitter Tcl')
        expected[str(emit)]=binding['emission_tcl_sha256']
        before=verify_input_hashes(expected)
        group=cgroup_dir();limits={k:(group/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        require(limits=={'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'},'Wrong image-emission cgroup limits')
        available=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
        mempsi=Path('/proc/pressure/memory').read_text();cpupsi=Path('/proc/pressure/cpu').read_text()
        require(available>=12582912,'Image emission requires12GiB host memory headroom')
        require(float(re.search(r'^full avg10=([0-9.]+)',mempsi,re.M)[1])<1 and float(re.search(r'^some avg10=([0-9.]+)',cpupsi,re.M)[1])<5,'Host pressure admission failed')
        require(not OUTPUT.exists(),'Fresh emission output directory required')
        version=subprocess.run([str(VIVADO),'-version'],text=True,capture_output=True,timeout=30,check=True)
        require(str(VIVADO)==manifest['vivado_path'] and sha(VIVADO)==manifest['vivado_sha256'],'Vivado identity changed')
        require(not OUTPUT.exists(),'Fresh output directory required; emitter writes only the image directory')
        env=dict(os.environ)
        argv=[str(VIVADO),'-mode','batch','-source',str(emit),'-log',str(BASE/'vivado.log'),'-journal',str(BASE/'vivado.jou')]
        RECORD.update(status='READY_TO_LAUNCH',argv=argv,kernel_limits=limits,initial_available_kib=available,memory_psi=mempsi,cpu_psi=cpupsi,
             vivado_path=str(VIVADO),vivado_sha256=sha(VIVADO),vivado_version_stdout=version.stdout,vivado_version_stderr=version.stderr,
             input_hashes_expected=expected,input_hashes_before=before,route_dcp_path=str(dcp),route_dcp_sha256=sha(dcp),source_tag=manifest['source_tag'],timeout_seconds=timeout_seconds)
        require(not OUTPUT.exists(),'Emitter output directory must remain absent before Vivado starts')
        RECORD.update(status='RUNNING',pid=None,pgid=None,bitstream_emitted=False)
        save()
        with (BASE/'stdout.log').open('x') as stdout,(BASE/'stderr.log').open('x') as stderr:
            maskset={signal.SIGINT,signal.SIGTERM,signal.SIGHUP};oldmask=signal.pthread_sigmask(signal.SIG_BLOCK,maskset)
            try:
                CHILD=spawn_emitter(expected,OUTPUT,argv,env,stdout,stderr,oldmask,cwd=BASE)
                RECORD.update(pid=CHILD.pid,pgid=CHILD.pid);save()
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,oldmask)
            try:RECORD['returncode']=CHILD.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                RECORD['status']='TIMEOUT';kill_owned(signal.SIGTERM);raise TimeoutError(f'Full512 image emission exceeded{timeout_seconds}s')
        stdout_text=(BASE/'stdout.log').read_text(errors='replace')
        marker='PASS_REVIEWED_FULL512_CH1_DDR_BITSTREAM_EMISSION_ONLY'
        require(RECORD['returncode']==0 and stdout_text.splitlines().count(marker)==1,'Native full512 image emission failed its exact marker/return-code check')
        require((OUTPUT/'image.dcp').is_file() and (OUTPUT/'full512-ddr-ch1-user2.bit').is_file(),'Expected full512 image artifacts missing')
        after=verify_input_hashes(expected)
        RECORD.update(status='PASS_FULL512_IMAGE_EMISSION_REQUIRES_INDEPENDENT_BITSTREAM_REVIEW',input_hashes_after=after,all_inputs_unchanged=True,
                      image_dcp_sha256=sha(OUTPUT/'image.dcp'),bitstream_path=str(OUTPUT/'full512-ddr-ch1-user2.bit'),bitstream_sha256=sha(OUTPUT/'full512-ddr-ch1-user2.bit'),bitstream_bytes=(OUTPUT/'full512-ddr-ch1-user2.bit').stat().st_size,
                      bitstream_emitted=True)
    except BaseException as error:
        if CHILD is not None and CHILD.poll() is None:kill_owned(signal.SIGTERM)
        RECORD.update(status=('TIMEOUT' if RECORD.get('status')=='TIMEOUT' else ('CANCELLED' if SIGNAL_SEEN else 'FAIL')),
                      error=repr(error),received_signal=SIGNAL_SEEN,returncode=CHILD.returncode if CHILD is not None else None)
    finally:
        RECORD['elapsed_seconds']=time.monotonic()-started;RECORD['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        if CHILD is not None:
            live=group_pids(CHILD.pid)
            if live:
                RECORD['owned_pids_before_cleanup']=live;kill_owned(signal.SIGTERM);live=group_pids(CHILD.pid)
            RECORD['owned_process_group_stopped']=not bool(live)
            if live and RECORD.get('status','').startswith('PASS_'):RECORD['status']='FAIL_OWNED_PROCESS_GROUP_LINGERED'
        if 'input_hashes_before' in RECORD:
            try:
                after={p:sha(p) for p in RECORD['input_hashes_before']};RECORD['input_hashes_after']=after
                RECORD['all_inputs_unchanged']=after==RECORD['input_hashes_before']==RECORD['input_hashes_expected']
                if not RECORD['all_inputs_unchanged'] and RECORD.get('status','').startswith('PASS_'):RECORD['status']='FAIL_INPUT_MUTATION_AFTER_EMISSION'
            except BaseException as error:
                RECORD['input_rehash_error']=repr(error);RECORD['all_inputs_unchanged']=False
                if RECORD.get('status','').startswith('PASS_'):RECORD['status']='FAIL_INPUT_REHASH_AFTER_EMISSION'
        if OUTPUT.exists():RECORD['output_hashes']={str(p.relative_to(OUTPUT)):sha(p) for p in OUTPUT.rglob('*') if p.is_file()}
        RECORD['run_artifact_hashes']={str(p.name):sha(p) for p in [BASE/'stdout.log',BASE/'stderr.log',BASE/'vivado.log',BASE/'vivado.jou',BASE/'emit_full512_ch1.tcl'] if p.is_file()}
        RECORD['bitstream_emitted']=bool((OUTPUT/'full512-ddr-ch1-user2.bit').is_file())
        try:
            cgroup=cgroup_dir();RECORD['memory_peak_bytes']=(cgroup/'memory.peak').read_text().strip();RECORD['memory_events']=(cgroup/'memory.events').read_text().strip()
        except BaseException as error:
            RECORD['cgroup_telemetry_error']=repr(error)
        RECORD.update(hardware_accessed=False,hardware_programmed=False,flash_written=False);save()
    return 0 if RECORD['status'].startswith('PASS_FULL512_IMAGE_EMISSION') else 1

if __name__=='__main__':raise SystemExit(main())
