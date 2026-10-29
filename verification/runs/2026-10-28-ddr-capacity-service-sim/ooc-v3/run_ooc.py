"""Hash-gated, bounded Vivado synthesis; no implementation or hardware actions."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import time

BASE=Path(__file__).resolve().parent
REPORT=BASE/'report.json'
children=[]
record={'status':'PREFLIGHT','commands':[],'vivado_executed':False,
        'hardware_accessed':False,'bitstream_emitted':False,'implementation_executed':False,
        'scope':'Exact ten-source OOC resource synthesis only; no timing/fit/physical qualification'}
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def need(ok,message):
    if not ok:raise RuntimeError(message)
def save():REPORT.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
def live_group(pgid):
    found=[]
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():continue
        try:
            fields=(path/'stat').read_text().rsplit(')',1)[1].split()
            if int(fields[2])==pgid and fields[0] not in ('Z','X'):found.append(int(path.name))
        except (OSError,ValueError,IndexError):pass
    return found
def stop(child):
    if child.poll() is None or live_group(child.pid):
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:pass
        if live_group(child.pid):
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait(timeout=5)
    return live_group(child.pid)
def interrupted(signum,frame):raise InterruptedError('OOC interrupted '+str(signum))
def run(name,argv,deadline):
    row={'name':name,'argv':argv,'timeout_seconds':deadline,'status':'RUNNING',
         'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    record['commands'].append(row)
    stdout=BASE/(name+'.stdout.log');stderr=BASE/(name+'.stderr.log')
    started=time.monotonic()
    with stdout.open('x') as out,stderr.open('x') as err:
        blocked={signal.SIGINT,signal.SIGTERM,signal.SIGHUP}
        previous=signal.pthread_sigmask(signal.SIG_BLOCK,blocked)
        try:
            child=subprocess.Popen(argv,cwd=BASE,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                start_new_session=True,preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,previous))
            children.append(child)
            row['pid']=child.pid;row['pgid']=child.pid
            record['vivado_executed']=True
            save()
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,previous)
        try:row['returncode']=child.wait(timeout=deadline)
        except BaseException:
            row['status']='FAIL_OR_INTERRUPTED';row['live_pids_after_cleanup']=stop(child)
            raise
        row['live_pids_after_cleanup']=stop(child)
    row.update(stdout_path=str(stdout),stdout_sha256=sha(stdout),stderr_path=str(stderr),
        stderr_sha256=sha(stderr),seconds=time.monotonic()-started,
        status='PASS' if row['returncode']==0 and not row['live_pids_after_cleanup'] else 'FAIL')
    save();need(row['status']=='PASS',name+' failed or left owned descendants')
    return row

def main():
    need(not REPORT.exists(),'Fresh output required')
    for signum in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(signum,interrupted)
    before={}
    try:
        approval_path=BASE/'root-review.json';approval=json.loads(approval_path.read_text())
        inputs_path=BASE/'input-manifest.json'
        need(approval['status']=='ROOT_APPROVED_TEN_SOURCE_OOC_RESOURCE_ONLY' and approval['approved'] is True,
             'Root approval absent')
        need(sha(inputs_path)==approval['input_manifest_sha256'],'Approved input manifest changed')
        manifest=json.loads(inputs_path.read_text())
        before={**manifest['files'],str(inputs_path):sha(inputs_path),str(approval_path):sha(approval_path)}
        for name,digest in before.items():need(sha(name)==digest,'Approved input changed: '+name)
        prep=json.loads((BASE/'preparation.json').read_text())
        need(prep['top']=='rk_ddr_capacity_service' and prep['part']=='xc7k480tffg1156-2','Target changed')
        rel=next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
        cg=Path('/sys/fs/cgroup')/rel.lstrip('/')
        limits={key:(cg/key).read_text().strip() for key in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        need(limits=={'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'},'Wrong enforced resource limits')
        mem=int(re.search(r'^MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text(),re.M)[1])
        mpsi=float(re.search(r'^full avg10=([0-9.]+)',Path('/proc/pressure/memory').read_text(),re.M)[1])
        cpsi=float(re.search(r'^some avg10=([0-9.]+)',Path('/proc/pressure/cpu').read_text(),re.M)[1])
        need(mem>=12582912 and mpsi<1 and cpsi<5,'Host resource admission failed')
        output=BASE/'output';need(not output.exists(),'Native output already exists')
        record.update(status='RUNNING',input_hashes_before=before,kernel_limits=limits,
                      host_memavailable_kib=mem,host_memory_psi=mpsi,host_cpu_psi=cpsi)
        save()
        executable=prep['vivado_launcher']
        version=run('version',[executable,'-version'],30)
        record['actual_tool_version']=Path(version['stdout_path']).read_text()
        output.mkdir()
        row=run('synthesis',[executable,'-mode','batch','-nojournal','-nolog','-source',str(BASE/'synth.tcl'),'-tclargs',str(output)],600)
        text=Path(row['stdout_path']).read_text()
        need(text.splitlines().count('PASS_DDR_CAPACITY_SERVICE_OOC_SYNTH_ONLY')==1,'Missing exact completion marker')
        outputs={str(path):sha(path) for path in (output/'utilization.rpt',output/'utilization-hierarchical.rpt')}
        record.update(status='PASS_TEN_SOURCE_OOC_SYNTH_RESOURCE_ONLY',outputs=outputs,
                      physical_capacity_qualified=False,full_design_fit_qualified=False)
    except BaseException as error:record.update(status='FAIL_OOC_RESOURCE_ATTEMPT',error=repr(error))
    finally:
        remaining={str(child.pid):stop(child) for child in children}
        record['owned_groups_after_cleanup']=remaining
        record['all_owned_groups_stopped']=not any(remaining.values())
        try:
            after={name:sha(name) for name in before}
            record.update(input_hashes_after=after,all_inputs_unchanged=bool(before) and before==after)
        except BaseException as error:record.update(all_inputs_unchanged=False,hash_error=repr(error))
        if record['status'].startswith('PASS_') and not (record['all_inputs_unchanged'] and record['all_owned_groups_stopped']):
            record['status']='FAIL_PROVENANCE_OR_CLEANUP'
        record['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
    return 0 if record['status']=='PASS_TEN_SOURCE_OOC_SYNTH_RESOURCE_ONLY' else 1

if __name__=='__main__':raise SystemExit(main())
