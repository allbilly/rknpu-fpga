"""Bounded offline CH1 image emission. No hardware manager, programming or flash."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import time

BASE = Path(__file__).resolve().parent


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def need(ok, message):
    if not ok:
        raise ValueError(message)


need(not (BASE/'report.json').exists(), 'Fresh image attempt required')
p = json.loads((BASE/'preparation.json').read_text())
need(p['status'] == 'PREPARED_REVIEWED_CH1_IMAGE_EMISSION_ONLY', 'Image review DAG not admitted')
inputs = dict(p['inputs'])
inputs[str(BASE/'preparation.json')] = sha(BASE/'preparation.json')
need(all(sha(n)==h for n,h in inputs.items()), 'Qualified image input changed')
group = Path('/sys/fs/cgroup')/next(s[3:] for s in Path('/proc/self/cgroup').read_text().splitlines()
                                   if s.startswith('0::')).lstrip('/')
limits = {n:(group/n).read_text().strip() for n in
          ('memory.max','memory.swap.max','cpu.max','pids.max')}
need(limits == {'memory.max':'8589934592','memory.swap.max':'0',
                'cpu.max':'200000 100000','pids.max':'256'}, 'Wrong image resource caps')
available = int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
need(available>=12582912, 'Image emission needs12GiB host headroom')
need(float(re.search(r'^some avg10=([0-9.]+)',Path('/proc/pressure/cpu').read_text(),re.M)[1])<5,
     'CPU admission unavailable')
need(float(re.search(r'^full avg10=([0-9.]+)',Path('/proc/pressure/memory').read_text(),re.M)[1])<1,
     'Memory admission unavailable')
r = dict(status='RUNNING',scope=__doc__,inputs=inputs,kernel_limits=limits,
    source_sha256=p['hardware_source_sha256'],usr_access=p['source_tag'],
    started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    hardware_accessed=False,hardware_programmed=False,flash_written=False,bitstream_emitted=False)


def save():
    (BASE/'report.json').write_text(json.dumps(r,indent=2)+'\n')


def stop(sig, frame):
    raise InterruptedError('Owned image emission interrupted '+str(sig))


for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
    signal.signal(sig,stop)
child = None
started = time.monotonic()
save()
try:
    argv = ['/home/fedora/vivado/2026.1/Vivado/bin/vivado','-mode','batch',
        '-source',str(BASE/'emit.tcl'),'-log',str(BASE/'vivado.log'),'-journal',str(BASE/'vivado.jou')]
    r['argv'] = argv
    with (BASE/'stdout.log').open('x') as log:
        watched={signal.SIGINT,signal.SIGTERM,signal.SIGHUP}
        mask=signal.pthread_sigmask(signal.SIG_BLOCK,watched)
        try:
            child=subprocess.Popen(argv,cwd=BASE,stdout=log,stderr=subprocess.STDOUT,
                start_new_session=True,preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK,mask)
        r['pid']=child.pid
        save()
        r['returncode']=child.wait(timeout=1200)
    need(r['returncode']==0,'Native emission or exact image checks failed')
    need((BASE/'stdout.log').read_text().splitlines().count(
        'PASS_REVIEWED_CH1_EW_DDR_BITSTREAM_EMISSION_ONLY')==1,'Missing exact emission result')
    need(all(sha(n)==h for n,h in inputs.items()),'Image source drift')
    bit=BASE/'emission/ew-ddr-ch1-user2.bit'
    need(bit.is_file(),'No bitstream emitted')
    r.update(status='PASS_NATIVE_CH1_IMAGE_EMISSION_REQUIRES_INDEPENDENT_BITSTREAM_REVIEW',
             bitstream=dict(path=str(bit),sha256=sha(bit),bytes=bit.stat().st_size))
except BaseException as error:
    r.update(status='FAIL',error=repr(error))
    if child is not None and child.poll() is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL)
            child.wait()
    raise
finally:
    r['bitstream_emitted']=(BASE/'emission/ew-ddr-ch1-user2.bit').is_file()
    r['all_inputs_unchanged']=all(sha(n)==h for n,h in inputs.items())
    r['seconds']=time.monotonic()-started
    r['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    r['artifacts']={str(f.relative_to(BASE)):sha(f) for f in BASE.rglob('*')
                    if f.is_file() and f.name!='report.json'}
    for name in ('memory.peak','memory.events'):
        r[name]=(group/name).read_text().strip()
    save()
print(r['status'])
