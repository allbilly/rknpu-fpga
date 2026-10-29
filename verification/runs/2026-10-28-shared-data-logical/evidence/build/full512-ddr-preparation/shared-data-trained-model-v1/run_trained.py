"""Execute the unchanged trained tile against private shared-data arithmetic in one controller epoch."""
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
OUT=BASE/'execution-v1'
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()

def require(ok,message):
    if not ok:raise RuntimeError(message)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()


require(not OUT.exists(),'Fresh same-epoch execution required')
prep_path=BASE/'preparation.json';prep=json.loads(prep_path.read_text())
compile_path=BASE/'native-compile-v1/report.json';compiled=json.loads(compile_path.read_text())
require(compiled['status']=='PASS_TRAINED_ALTERNATION_NATIVE_COMPILE_ONLY' and
        all(command['returncode']==0 for command in compiled['commands']),
        'Unqualified native compilation')
binary=Path(compiled['binary_path'])
require(sha(binary)==compiled['binary_sha256']=='9bd3ce2690c9c28d81abbd9a3b440ad6addafed148d611b8257d5953558c9f9c',
        'Changed trained-model executable')
inputs=dict(prep['inputs'])|dict(prep['files'])|dict(compiled['source_hashes_before'])
for path in (prep_path,compile_path,Path(__file__),binary):inputs[str(path)]=sha(path)
for name,digest in inputs.items():require(sha(name)==digest,'Changed original trained test input: '+name)
vectors=Path(prep['vectors'])
initial=(vectors/'initial.txt').read_text().splitlines()
require(len(initial)==1408 and sum(int(row.split()[1],16)!=0 for row in initial)==265,
        'Changed initialized raw upload inventory')
require(len((vectors/'ew_delta.txt').read_text().splitlines())==9 and
        len((vectors/'repeat_delta.txt').read_text().splitlines())==11,'Changed complete raw byte deltas')
# Predicted before execution:265 initial +9 +11 complete host-line writes,
# each32 masked RMWs and32 retirement fences. Kernel reads are392 original
# CMAC command halfwords +4352 operands,176 EW command halfwords +64 operands;
#96 engine write RMWs and3 job fences. Bootstrap is65 returns +2 READ64s.
read64=2+3*1408
returns=65+(265+9+11)*64+(2*(49*4+2176+32+1))+(2*22*4+3*16*2+1)+read64
require((read64,returns)==(4226,27614),'Invalid prospective trained traffic inventory')
cg=Path('/sys/fs/cgroup')/next(line.split('::',1)[1].strip().lstrip('/')
    for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
limits={name:(cg/name).read_text().strip() for name in ('memory.max','memory.swap.max','cpu.max','pids.max')}
require(limits=={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'128'},
        'Trained controller execution requires4GiB/2CPU/no-swap/128task scope')
OUT.mkdir()
argv=[str(binary),'+DIRECTORY='+str(vectors),'+OUTPUT_DIRECTORY='+str(OUT)]
marker=('PASS trained_tile_dual_ddr cmac_jobs=2 ew_tasks=2 engine_writes=96 rearm=2 '
        'checked_bo_lines=4224 phy_user_returns=27614 read64_packets=4226 '
        'read64_axi_reads=4226 scope=actual_AXI_UI_MC_modeled_PHY')
record=dict(status='RUNNING_TRAINED_SAME_EPOCH_CMAC_EW_CMAC_CONTROLLER_MODEL',started_utc=now(),
    argv=argv,inputs=inputs,binary_sha256=sha(binary),kernel_limits=limits,timeout_seconds=3600,
    expected_marker=marker,prospective_phy_returns=returns,prospective_read64_packets=read64,
    raw_bo_bytes_each=90112,ascii_capture_bytes_each=194304,total_checked_bo_bytes=270336,
    source_commands_and_deltas_unchanged=True,cpu_arithmetic_or_layout_repair=False,
    random_seed=None,stimulus='Original fixed BOS_Wq0 first32-output tile and static EW/CMAC byte deltas',
    hardware_accessed=False,physical_phy_or_ddr_qualified=False)
report=OUT/'report.json'
def save():report.write_text(json.dumps(record,indent=2)+'\n')
def interrupted(signum,frame):raise InterruptedError('Trained execution interrupted: '+str(signum))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
save();child=None;start=time.monotonic()
try:
    with (OUT/'stdout.log').open('x') as stdout,(OUT/'stderr.log').open('x') as stderr:
        child=subprocess.Popen(argv,cwd=BASE,stdout=stdout,stderr=stderr,start_new_session=True)
        record['pid']=child.pid;save()
        record['returncode']=child.wait(timeout=3600)
    require(record['returncode']==0,'Trained controller simulation failed')
    require(not (OUT/'stderr.log').read_bytes(),'Unexpected runtime stderr')
    text=(OUT/'stdout.log').read_text()
    require(not re.search(r'(?mi)^(?:FATAL:|ERROR:|FAIL|%Error)|Assertion failed|\bwarning:',text),
            'Unadmitted trained runtime failure')
    require([line for line in text.splitlines() if line.startswith('PASS ')]==[marker],
            'Trained ownership/traffic/rearm inventory differs')
    captures=[]
    for name,expected in [('cmac','cmac_expected.txt'),('ew','ew_expected.txt'),('repeat','repeat_expected.txt')]:
        actual=OUT/(name+'-actual.txt')
        require(actual.is_file() and actual.read_bytes()==(vectors/expected).read_bytes(),
                'Complete trained BO differs: '+name)
        require(len(actual.read_text().splitlines())==1408 and actual.stat().st_size==194304,
                'Incomplete trained ASCII BO: '+name)
        captures.append(dict(phase=name,raw_bytes=90112,ascii_bytes=194304,sha256=sha(actual)))
    record.update(status='PASS_TRAINED_CMAC_EW_CMAC_SAME_EPOCH_CONTROLLER_MODEL_ONLY',
        actual_marker=marker,captures=captures,full_readback_before_each_ack_bound_to_sv=True)
except BaseException as error:
    record.update(status='FAIL_TRAINED_SAME_EPOCH_CONTROLLER_MODEL',error=repr(error))
finally:
    if child is not None and child.poll() is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);child.wait()
    record['owned_child_exit']=child.returncode if child is not None else None
    record['all_inputs_unchanged']=all(sha(name)==digest for name,digest in inputs.items())
    if not record['all_inputs_unchanged']:
        record.update(status='FAIL_TRAINED_SAME_EPOCH_CONTROLLER_MODEL',error='Source/fixture drift')
    record.update(seconds=time.monotonic()-start,finished_utc=now(),
        stdout_sha256=sha(OUT/'stdout.log'),stderr_sha256=sha(OUT/'stderr.log'),
        memory_peak=(cg/'memory.peak').read_text().strip(),memory_events=(cg/'memory.events').read_text().strip())
    save()
print(json.dumps(dict(status=record['status'],report=str(report),seconds=record['seconds'])),flush=True)
raise SystemExit(0 if record['status'].startswith('PASS_') else 1)
