"""First actual full512/AXI/UI/MC K65 execution; PHY remains a model."""
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
OUT=BASE/'cmac-k65-execution-v1'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise RuntimeError(message)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()


require(not OUT.exists(),'Fresh execution directory required')
prep_path=BASE/'preparation.json';prep=json.loads(prep_path.read_text())
compile_path=BASE/'native-compile-v2/report.json';compiled=json.loads(compile_path.read_text())
require(compiled['status']=='PASS_JOINED_MODEL_NATIVE_COMPILE_ONLY','Native compile not qualified')
binary=Path(compiled['binary_path'])
require(sha(binary)==compiled['binary_sha256']=='ca017f2afc191f4a07c681e2dc4648063997ee6ac35264695554c33eb4e9bf2e',
        'Changed actual joined binary')
inputs=dict(prep['inputs'])|dict(prep['files'])|dict(compiled['source_hashes_before'])
for path in (prep_path,compile_path,Path(__file__),binary):inputs[str(path)]=sha(path)
for name,digest in inputs.items():require(sha(name)==digest,'Changed execution input: '+name)
case=prep['cmac_case'];fixture=Path(case['case_dir'])
require((case['address'],case['amount'],case['tasks'],case['lines'],case['csr_base'])==
        (0x100e0000,45,1,320,0x100),'Changed fixed CMAC descriptor')
rows=(fixture/'upload.txt').read_text().splitlines()
require(len(rows)==320,'Incomplete fixed upload')
nonzero=sum(int(line.split()[1],16)!=0 for line in rows)
require(nonzero==173,'Changed raw input/padding/sentinel inventory')
# Fixed traffic derived BEFORE execution: startup init fence +32 zero-write
# RMW/fence pairs; two initial READ64s; 173 uploaded lines each with32 RMWs
# and32 fences; 49*4 command reads;6528 operands;64 write RMWs; one job fence;
#320 whole BO READ64s. Host snapshots never cache engine reads or writes.
packets=2+320
phy_returns=65+packets+nonzero*64+49*4+6528+64+1
require(phy_returns==18248,'Invalid prospective PHY inventory')
cg=Path('/sys/fs/cgroup')/next(line.split('::',1)[1].strip().lstrip('/')
    for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
limits={name:(cg/name).read_text().strip() for name in ('memory.max','memory.swap.max','cpu.max','pids.max')}
require(limits=={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'128'},
        'First execution requires 4GiB/no-swap/2CPU/128task scope')
OUT.mkdir()
actual=OUT/'actual-bo.txt'
argv=[str(binary),'+CASE='+str(fixture),'+OUTPUT='+str(actual),'+START=100e0000',
      '+AMOUNT=45','+NTASKS=1','+NLINES=320','+JOBS=1','+NEGATIVE=0','+RESET_RECOVERY=0','+CSR_BASE=100']
expected=('PASS jtag_dual_ddr_read_snapshot csr_base=00000100 jobs=1 negative=0 recovered=0 '
          'lines=320 uploaded_nonzero=173 rawtasks=1 phy_user_returns=18248 '
          'read64_packets=322 read64_axi_reads=322 scope=actual_AXI_UI_MC_modeled_PHY')
record=dict(status='RUNNING_FIRST_JOINED_FULL512_CMAC_MODEL_EXECUTION',started_utc=now(),argv=argv,
    source_inputs=inputs,binary_sha256=sha(binary),kernel_limits=limits,timeout_seconds=1800,
    expected_marker=expected,prospective_phy_returns=phy_returns,prospective_read64_packets=packets,
    expected_complete_bo_bytes=20480,hardware_accessed=False,physical_phy_qualified=False,
    cpu_arithmetic_or_layout_repair=False,case_seed='Parent controller stimulus and unchanged raw K65 fixture',
    tools=compiled['tool_versions'],actual_toolchain=compiled['actual_toolchain'])
report=OUT/'report.json'
def save():report.write_text(json.dumps(record,indent=2)+'\n')
def interrupted(signum,frame):raise InterruptedError('Joined execution interrupted: '+str(signum))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
save();child=None;start=time.monotonic()
try:
    with (OUT/'stdout.log').open('x') as stdout,(OUT/'stderr.log').open('x') as stderr:
        child=subprocess.Popen(argv,cwd=BASE,stdout=stdout,stderr=stderr,start_new_session=True)
        record['pid']=child.pid;save()
        record['returncode']=child.wait(timeout=1800)
    require(record['returncode']==0,'First joined CMAC simulation failed')
    require(not (OUT/'stderr.log').read_bytes(),'Unexpected runtime stderr')
    text=(OUT/'stdout.log').read_text()
    require(not re.search(r'(?mi)^(?:FATAL:|ERROR:|FAIL|%Error)|Assertion failed|\bwarning:',text),
            'Unadmitted runtime failure')
    markers=[line for line in text.splitlines() if line.startswith('PASS ')]
    require(markers==[expected],'Actual workload/PHY/readback inventory differs from prospective contract')
    require(actual.is_file() and actual.read_bytes()==(fixture/'expected.txt').read_bytes(),
            'Complete raw output BO differs')
    require(len(actual.read_text().splitlines())==320,'Incomplete actual BO readback')
    record.update(status='PASS_FIRST_JOINED_FULL512_CMAC_AXI_UI_MC_EXECUTION_ONLY',
        checked_complete_bo_bytes=20480,observed_sha256=sha(actual),actual_marker=expected,
        readback_before_ack_asserted_by_bound_sv=True)
except BaseException as error:
    record.update(status='FAIL_FIRST_JOINED_FULL512_CMAC_MODEL_EXECUTION',error=repr(error))
finally:
    if child is not None and child.poll() is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);child.wait()
    record['owned_child_exit']=child.returncode if child is not None else None
    record['all_inputs_unchanged']=all(sha(name)==digest for name,digest in inputs.items())
    if not record['all_inputs_unchanged']:
        record.update(status='FAIL_FIRST_JOINED_FULL512_CMAC_MODEL_EXECUTION',error='Execution input drift')
    record.update(seconds=time.monotonic()-start,finished_utc=now(),
        stdout_sha256=sha(OUT/'stdout.log'),stderr_sha256=sha(OUT/'stderr.log'),
        memory_peak=(cg/'memory.peak').read_text().strip(),memory_events=(cg/'memory.events').read_text().strip())
    save()
print(json.dumps(dict(status=record['status'],report=str(report),seconds=record['seconds'])),flush=True)
raise SystemExit(0 if record['status'].startswith('PASS_') else 1)
