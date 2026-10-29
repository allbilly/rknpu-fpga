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

def spawn_emitter(expected,output_dir,argv,env,stdout,stderr,parent_mask,cwd=BASE,popen=subprocess.Popen):
    verify_input_hashes(expected)
    require(not Path(output_dir).exists(),'Emitter output directory must be absent when Vivado is spawned')
    return popen(argv,cwd=cwd,env=env,stdout=stdout,stderr=stderr,start_new_session=True,
                 preexec_fn=lambda:restore_child_signal_mask(parent_mask))

def main():
    global CHILD,RECORD
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-emission',action='store_true')
    args=parser.parse_args()
    if not args.execute_emission:
        print(json.dumps(dict(status='PREPARED_PENDING_RENDER_AND_ROOT_EMISSION_APPROVAL',
              preparation_present=PREP_PATH.is_file(),approval_present=BINDING_PATH.is_file(),
              vivado_executed=False,hardware_accessed=False)))
        return 0
    require(not REPORT_PATH.exists(),'Fresh retirement emission receipt required')
    RECORD=dict(status='PREFLIGHT',started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
       vivado_executed=False,hardware_accessed=False,hardware_programmed=False,flash_written=False,
       bitstream_emitted=False,scope='New retirement routed-image emission only; no implementation, programming or flash')
    started=time.monotonic();expected={}
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,handle_signal)
    try:
        manifest=json.loads(PREP_PATH.read_text());binding=json.loads(BINDING_PATH.read_text())
        require(manifest['status']=='PREPARED_ROOT_BOUND_FULL512_RETIRE_EMISSION_ONLY','Retirement render not ready')
        require(binding['status']=='ROOT_APPROVED_RETIRE_IMAGE_EMISSION' and binding['launch_approved'] is True,
                'Root retirement-image-emission approval absent')
        for name,path in [('image_preparation_sha256',PREP_PATH),('run_image_sha256',Path(__file__)),
                          ('vivado_launcher_sha256',VIVADO)]:
            require(binding[name]==sha(path),'Root-bound emission input changed: '+name)
        source_hash=hashlib.sha256(json.dumps(manifest['hardware_source_manifest'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        require(source_hash==manifest['source_manifest_sha256']==binding['source_manifest_sha256'] and
                source_hash[:8]==manifest['source_tag']==binding['source_tag'] and source_hash[:8]!='00000000',
                'Retirement source/tag binding changed')
        hardware=manifest['hardware_source_manifest']
        require(len(hardware['files'])==171 and hardware['top']=='ypcb_ddr_dual_top' and
                hardware['part']=='xc7k480tffg1156-2' and
                hardware['profile']=='full512-ch1-ddr-capacity-retire-snapshot-ecc-test-off',
                'Wrong 171-file retirement hardware closure/profile')
        dcp=Path(manifest['route_dcp_path']);emit=Path(manifest['tcl_path'])
        require(sha(dcp)==manifest['route_dcp_sha256']==binding['route_dcp_sha256'],'Retirement route DCP changed')
        require(sha(emit)==manifest['tcl_sha256']==binding['tcl_sha256'],'Retirement emitter Tcl changed')
        expected={**manifest['input_hashes'],str(PREP_PATH):sha(PREP_PATH),str(BINDING_PATH):sha(BINDING_PATH),
                  str(Path(__file__).resolve()):sha(__file__),str(emit):sha(emit),str(VIVADO):sha(VIVADO)}
        before=verify_input_hashes(expected)
        limits={key:(cgroup_dir()/key).read_text().strip() for key in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        require(limits=={'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'},
                'Wrong enforced image-emission resource limits')
        available=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
        mempsi=Path('/proc/pressure/memory').read_text();cpupsi=Path('/proc/pressure/cpu').read_text()
        require(available>=12582912 and float(re.search(r'^full avg10=([0-9.]+)',mempsi,re.M)[1])<1 and
                float(re.search(r'^some avg10=([0-9.]+)',cpupsi,re.M)[1])<5,'Host pressure/headroom gate failed')
        require(not OUTPUT.exists(),'Fresh image output required')
        version=subprocess.run([str(VIVADO),'-version'],text=True,capture_output=True,timeout=30,check=True)
        argv=[str(VIVADO),'-mode','batch','-source',str(emit),'-log',str(BASE/'vivado.log'),'-journal',str(BASE/'vivado.jou')]
        RECORD.update(status='RUNNING',argv=argv,vivado_executed=True,kernel_limits=limits,
             actual_tool_version=version.stdout,version_stderr=version.stderr,
             input_hashes_expected=expected,input_hashes_before=before,
             source_manifest_sha256=source_hash,source_tag=source_hash[:8],route_dcp_path=str(dcp),
             route_dcp_sha256=sha(dcp),timeout_seconds=2400)
        save()
        with (BASE/'stdout.log').open('x') as stdout,(BASE/'stderr.log').open('x') as stderr:
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
            try:
                CHILD=spawn_emitter(expected,OUTPUT,argv,dict(os.environ),stdout,stderr,mask,cwd=BASE)
                RECORD.update(pid=CHILD.pid,pgid=CHILD.pid);save()
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
            RECORD['returncode']=CHILD.wait(timeout=2400)
        text=(BASE/'stdout.log').read_text()
        require(RECORD['returncode']==0 and text.splitlines().count('PASS_REVIEWED_FULL512_RETIRE_BITSTREAM_EMISSION_ONLY')==1,
                'Capacity emitter failed/has missing native terminal marker')
        require(not (BASE/'stderr.log').read_bytes(),'Unexpected capacity emitter stderr')
        bit=OUTPUT/'full512-ddr-ch1-user2.bit';image=OUTPUT/'image.dcp'
        require(bit.is_file() and image.is_file(),'Retirement bitfile/checkpoint missing')
        after=verify_input_hashes(expected)
        RECORD.update(status='PASS_FULL512_RETIRE_IMAGE_EMITTED_REQUIRES_BITFILE_REVIEW',
             input_hashes_after=after,all_inputs_unchanged=True,bitstream_emitted=True,
             bitstream_path=str(bit),bitstream_sha256=sha(bit),image_dcp_sha256=sha(image),
             outputs={str(p):sha(p) for p in OUTPUT.rglob('*') if p.is_file()})
    except BaseException as error:
        if CHILD is not None and (CHILD.poll() is None or group_pids(CHILD.pid)):kill_owned(signal.SIGTERM)
        RECORD.update(status='FAIL_OR_TIMEOUT_RETIRE_IMAGE_EMISSION',error=repr(error))
    finally:
        if CHILD is not None and (CHILD.poll() is None or group_pids(CHILD.pid)):kill_owned(signal.SIGTERM)
        remaining=[] if CHILD is None else group_pids(CHILD.pid)
        RECORD.update(owned_pids_after_cleanup=remaining,elapsed_seconds=time.monotonic()-started,
                      finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        if remaining:RECORD['status']='FAIL_OWNED_PROCESS_CLEANUP'
        if expected:
            try:RECORD['input_hashes_after']=verify_input_hashes(expected)
            except BaseException as error:RECORD.update(status='FAIL_INPUT_PROVENANCE',hash_error=repr(error))
        save()
    print(json.dumps(dict(status=RECORD['status'],report=str(REPORT_PATH))))
    return 0 if RECORD['status']=='PASS_FULL512_RETIRE_IMAGE_EMITTED_REQUIRES_BITFILE_REVIEW' else 1

if __name__=='__main__':raise SystemExit(main())
