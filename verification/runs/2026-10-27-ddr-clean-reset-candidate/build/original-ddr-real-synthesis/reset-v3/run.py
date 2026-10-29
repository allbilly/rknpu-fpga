"""Bounded actual-source synthesis only; no implementation/image/hardware."""
from pathlib import Path
import datetime,hashlib,json,os,re,resource,signal,subprocess,time
OUT=Path(__file__).resolve().parent
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def require(ok,message):
    if not ok:raise ValueError(message)
require(not (OUT/'report.json').exists(),'Fresh synthesis attempt required')
line=next(s for s in Path('/proc/self/cgroup').read_text().splitlines() if s.startswith('0::'))
group=Path('/sys/fs/cgroup')/line[3:].lstrip('/')
limits={n:(group/n).read_text().strip() for n in ('memory.max','memory.swap.max','cpu.max','pids.max')}
require(limits['memory.max']=='8589934592' and limits['memory.swap.max']=='0' and
        limits['cpu.max'].split()==['200000','100000'] and limits['pids.max']=='256','Own synthesis cgroup caps required')
available=re.findall(r'^MemAvailable:\s+([0-9]+) kB',Path('/proc/meminfo').read_text(),re.M)
require(len(available)==1 and int(available[0])>=12582912,'At least12GiB host headroom required')
pressure=Path('/proc/pressure/memory').read_text()
require(any(s.startswith('full ') and float(dict(p.split('=') for p in s.split()[1:])['avg10'])<1
        for s in pressure.splitlines()),'Stable memory pressure required')
prepared=json.loads((OUT/'preparation.json').read_text());inputs=dict(prepared['inputs'])
inputs[str(OUT/'preparation.json')]=sha(OUT/'preparation.json');inputs[str(OUT/'run.py')]=sha(__file__)
require(prepared['rtl_files']==118 and prepared['stub_sources_selected'] is False and
        prepared['cached_checkpoint_selected'] is False,'Actual source selection required')
require(all(sha(p)==h for p,h in inputs.items()),'Frozen actual source changed')
record=dict(status='RUNNING',inputs=inputs,kernel_limits=limits,cgroup=str(group),
    initial_available_kib=int(available[0]),scope=__doc__,hardware_accessed=False,bitstream_emitted=False,
    implementation_executed=False,board_timing_or_electrical_qualified=False)
def save():(OUT/'report.json').write_text(json.dumps(record,indent=2)+'\n')
def interrupted(sig,frame):raise InterruptedError('Owned real-source synthesis interrupted '+str(sig))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
resource.setrlimit(resource.RLIMIT_CORE,(0,0));save();child=None;start=time.monotonic()
try:
    argv=['/home/fedora/vivado/2026.1/Vivado/bin/vivado','-mode','batch','-source',str(OUT/'synth.tcl'),'-log',str(OUT/'vivado.log'),'-journal',str(OUT/'vivado.jou')]
    record['argv']=argv
    with (OUT/'stdout.log').open('x') as stream:
        watched={signal.SIGINT,signal.SIGTERM,signal.SIGHUP};mask=signal.pthread_sigmask(signal.SIG_BLOCK,watched)
        try:child=subprocess.Popen(argv,cwd=OUT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
            preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
        record['pid']=child.pid;save();code=child.wait(timeout=1200)
    record['returncode']=code;require(code==0,'Actual source synthesis failed')
    require(all(sha(p)==h for p,h in inputs.items()),'Frozen synthesis inputs changed')
    text=(OUT/'stdout.log').read_text()
    require(text.splitlines().count('PASS_ACTUAL_ORIGINAL_MIG_AND_ASYNC_EW_SYNTHESIS_ONLY')==1,'Missing exact native synthesis result')
    record['status']='PASS_ACTUAL_ORIGINAL_MIG_ASYNC_EW_SYNTHESIS_ONLY_REQUIRES_REVIEW'
except BaseException as error:
    record.update(status='FAIL',error=repr(error))
    if child is not None and child.poll() is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
    raise
finally:
    record['seconds']=time.monotonic()-start;record['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    record['artifacts']={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and p.name!='report.json'}
    for n in ('memory.peak','memory.events'):
        if (group/n).exists():record[n]=(group/n).read_text().strip()
    save()
print(record['status'])
