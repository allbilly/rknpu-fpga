"""Bounded fresh DDR placement/routing; never emits an image or accesses hardware."""
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


def require(condition, message):
    if not condition:
        raise ValueError(message)


require(not (BASE / 'report.json').exists(), 'Fresh route attempt required')
group = Path('/sys/fs/cgroup') / next(line[3:] for line in
    Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')).lstrip('/')
limits = {n: (group / n).read_text().strip() for n in
          ('memory.max', 'memory.swap.max', 'cpu.max', 'pids.max')}
require(limits == {'memory.max': '8589934592', 'memory.swap.max': '0',
                  'cpu.max': '200000 100000', 'pids.max': '256'}, 'Wrong route resource caps')
available = int(re.search(r'^MemAvailable:\s+(\d+) kB',
                         Path('/proc/meminfo').read_text(), re.M)[1])
require(available >= 12582912, 'Route requires 12GiB host headroom')
memory_pressure = Path('/proc/pressure/memory').read_text()
cpu_pressure = Path('/proc/pressure/cpu').read_text()
require(float(re.search(r'^full avg10=([0-9.]+)', memory_pressure, re.M)[1]) < 1,
        'Route requires stable memory pressure')
require(float(re.search(r'^some avg10=([0-9.]+)', cpu_pressure, re.M)[1]) < 5,
        'Route requires CPU admission below5')
prepared = json.loads((BASE / 'preparation.json').read_text())
inputs = dict(prepared['inputs'])
inputs[str(BASE / 'preparation.json')] = sha(BASE / 'preparation.json')
require(all(sha(path) == value for path, value in inputs.items()), 'Prepared route input changed')
record = dict(status='RUNNING', scope=__doc__, inputs=inputs, kernel_limits=limits,
    initial_available_kib=available, initial_memory_pressure=memory_pressure,
    initial_cpu_pressure=cpu_pressure, started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    hardware_accessed=False, bitstream_emitted=False, flash_written=False,
    implementation_executed=True, source_revision=prepared['source_revision'],
    placement_and_route_seed='Vivado default; no seed override', timeout_seconds=3600)


def save():
    (BASE / 'report.json').write_text(json.dumps(record, indent=2) + '\n')


def interrupted(sig, frame):
    raise InterruptedError('Owned DDR route interrupted ' + str(sig))


for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, interrupted)
save()
child = None
started = time.monotonic()
try:
    argv = ['/home/fedora/vivado/2026.1/Vivado/bin/vivado', '-mode', 'batch',
            '-source', str(BASE / 'route.tcl'), '-log', str(BASE / 'vivado.log'),
            '-journal', str(BASE / 'vivado.jou')]
    record['argv'] = argv
    with (BASE / 'stdout.log').open('x') as log:
        watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
        try:
            child = subprocess.Popen(argv, cwd=BASE, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
                preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, mask))
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        record['pid'] = child.pid
        save()
        record['returncode'] = child.wait(timeout=3600)
    require(record['returncode'] == 0, 'DDR route or strict checkpoint acceptance failed')
    marker = 'PASS_CH1_ROUTED_CHECKPOINT_ONLY_REQUIRES_CDC_IO_IMAGE_AND_PHYSICAL_REVIEW'
    require((BASE / 'stdout.log').read_text().splitlines().count(marker) == 1,
            'Missing exact native route acceptance marker')
    require(all(sha(path) == value for path, value in inputs.items()), 'Route input changed')
    record['status'] = marker
except BaseException as error:
    record.update(status='FAIL', error=repr(error))
    if child is not None and child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
    raise
finally:
    record.update(seconds=time.monotonic() - started,
                  finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    record['all_inputs_unchanged'] = all(sha(path) == value for path, value in inputs.items())
    record['artifacts'] = {str(p.relative_to(BASE)): sha(p) for p in BASE.rglob('*')
                           if p.is_file() and p.name != 'report.json'}
    for name in ('memory.peak', 'memory.events'):
        record[name] = (group / name).read_text().strip()
    save()
print(record['status'])
