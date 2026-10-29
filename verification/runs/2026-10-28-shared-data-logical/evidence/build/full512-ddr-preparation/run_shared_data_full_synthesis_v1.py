"""Fresh unqualified shared-data full512/CH1 resource synthesis; unchanged clocks."""
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
SOURCE=ROOT/'build/full512-ddr-preparation/combined-shared-data-source-v1'
OUT=ROOT/'build/full512-ddr-preparation/combined-shared-data-full-synth-v1'
VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise RuntimeError(message)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()


require(not OUT.exists(),'Fresh shared-data experiment required')
prep=json.loads((SOURCE/'preparation.json').read_text())
inputs=dict(prep['inputs'])|dict(prep['files'])
for path in (SOURCE/'preparation.json',VIVADO,Path(__file__)):
    inputs[str(path)]=sha(path)
for path,digest in inputs.items():require(sha(path)==digest,'Changed exact RTL/XDC input: '+path)
require(prep['hdl_count']==152 and prep['full512_expected_products']==512 and prep['controllers_retained']==2,
        'Wrong full design scope')
text=(SOURCE/'synth.tcl').read_text()
require('-flatten_hierarchy none' in text,'Experimental source must retain the original hierarchy policy')
cg=Path('/sys/fs/cgroup')/next(line.split('::',1)[1].strip().lstrip('/')
    for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
limits={name:(cg/name).read_text().strip() for name in ('memory.max','memory.swap.max','cpu.max','pids.max')}
require(limits=={'memory.max':'12884901888','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'},
        'Shared-data synthesis requires 12GiB/2CPU/no-swap/256task scope')
mem=int(re.search(r'MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text())[1])
require(mem>=16*1024*1024,'Insufficient available memory for bounded synthesis')
OUT.mkdir()
script=OUT/'synth.tcl';script.write_text(text);inputs[str(script)]=sha(script)
argv=[str(VIVADO),'-mode','batch','-source',str(script),'-log',str(OUT/'vivado.log'),'-journal',str(OUT/'vivado.jou')]
record=dict(status='RUNNING_SHARED_DATA_FULL512_SOURCE_SYNTHESIS_ONLY',started_utc=now(),argv=argv,
    source_inputs=inputs,source_preparation_sha256=sha(SOURCE/'preparation.json'),kernel_limits=limits,
    selected_change='Two internal shared-data cell/array RTL replacements and one shared combinational preparation module',RTL_implementation_changed=True,numerical_equivalence_qualified=False,
    clock_pin_voltage_or_drc_checks_changed=False,product_target=512,controllers=2,
    timeout_seconds=3600,route_or_bitstream_permitted=False,hardware_accessed=False)
report=OUT/'report.json'
def save():report.write_text(json.dumps(record,indent=2)+'\n')
def interrupted(signum,frame):raise InterruptedError('Shared-data synthesis interrupted: '+str(signum))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
save();child=None;start=time.monotonic()
try:
    with (OUT/'stdout.log').open('x') as stdout,(OUT/'stderr.log').open('x') as stderr:
        child=subprocess.Popen(argv,cwd=OUT,stdout=stdout,stderr=stderr,start_new_session=True)
        record['pid']=child.pid;save()
        record['returncode']=child.wait(timeout=3600)
    require(record['returncode']==0,'Fresh shared-data synthesis failed')
    stdout=(OUT/'stdout.log').read_text(errors='replace')
    require('PASS_FULL512_DDR_EARLY_RESOURCE_SYNTHESIS_ONLY' in stdout.splitlines(),
            'Missing standalone native full-census completion')
    facts=dict(line.split('\t',1) for line in (OUT/'fit-facts.tsv').read_text().splitlines())
    require(facts['PRODUCT_DSPS']=='512' and facts['TOTAL_DSPS']=='516' and
            facts['PART']=='xc7k480tffg1156-2' and facts['TOP']=='ypcb_ddr_dual_top',
            'Actual shared-data synthesis did not retain the complete design')
    record.update(status='PASS_SHARED_DATA_FULL512_SYNTHESIS_ONLY_REQUIRES_RESOURCE_REVIEW',fit_facts=facts,
        native_tool_version_lines=[line for line in stdout.splitlines()
            if line.startswith(('****** Vivado v','  **** SW Build','DUAL_DDR_FIT_NATIVE_TOOL '))])
except BaseException as error:
    record.update(status='FAIL_SHARED_DATA_FULL512_SOURCE_SYNTHESIS',error=repr(error))
finally:
    if child is not None and child.poll() is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);child.wait()
    record['owned_child_exit']=child.returncode if child is not None else None
    record['all_source_inputs_unchanged']=all(sha(path)==digest for path,digest in inputs.items())
    if not record['all_source_inputs_unchanged']:
        record.update(status='FAIL_SHARED_DATA_FULL512_SOURCE_SYNTHESIS',error='Source/constraint drift')
    record.update(seconds=time.monotonic()-start,finished_utc=now(),
        outputs={str(path.relative_to(OUT)):sha(path) for path in OUT.rglob('*')
                 if path.is_file() and path!=report},memory_peak=(cg/'memory.peak').read_text().strip(),
        memory_events=(cg/'memory.events').read_text().strip())
    save()
print(json.dumps(dict(status=record['status'],report=str(report),seconds=record['seconds'])),flush=True)
raise SystemExit(0 if record['status'].startswith('PASS_') else 1)
