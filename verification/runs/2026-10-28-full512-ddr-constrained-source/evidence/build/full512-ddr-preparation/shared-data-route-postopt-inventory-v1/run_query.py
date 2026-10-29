#!/usr/bin/env python3
"""Read-only full512 post-opt hierarchy/reset inventory. No constraint/implementation commands."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import time

ROOT = Path('/home/fedora/rknpu-fpga')
PKG = Path(__file__).resolve().parent
OUT = PKG / 'output'
REPORT = PKG / 'report.json'
PREP_DIR = ROOT / 'build/full512-ddr-preparation/shared-data-constrained-prep-v4'
PREP = PREP_DIR / 'preparation.json'
SYNTH = PREP_DIR / 'synthesis'
DCP = SYNTH / 'post_opt.dcp'
SYNTH_REPORT = SYNTH / 'run.json'
FACTS = SYNTH / 'constrained_synthesis_facts.tsv'
DCP_SHA256 = 'e1a6441e396e11a1c78223ae78a3d8a9d482223449436d601cfe879a88b26e0b'
VIVADO = Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
TCL = PKG / 'inventory.tcl'
RUNNER = Path(__file__).resolve()
CHILD = None
RECEIVED_SIGNAL = None
RECORD = None

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def require(condition, message):
    if not condition:
        raise ValueError(message)

def save():
    REPORT.write_text(json.dumps(RECORD, indent=2) + '\n')

def group_dir():
    rel = next(line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines()
               if line.startswith('0::')).lstrip('/')
    return Path('/sys/fs/cgroup') / rel

def kill_owned(sig):
    global CHILD
    if CHILD is None:
        return
    try:
        os.killpg(CHILD.pid, sig)
    except ProcessLookupError:
        pass
    try:
        CHILD.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(CHILD.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        CHILD.wait()

def handle_signal(sig, frame):
    global RECEIVED_SIGNAL
    RECEIVED_SIGNAL = sig
    raise InterruptedError('owned post-opt inventory received signal ' + str(sig))

def source_hashes(prep):
    result = {}
    for row in prep['files']:
        p = PREP_DIR / 'source' / row['relative_path']
        result[str(p)] = row['copy_sha256']
    return result

def main():
    global CHILD, RECORD
    started = time.monotonic()
    RECORD = {'status':'PREFLIGHT','scope':'read_checkpoint-only post-opt source/cell/reset/CDC inventory; no constraints, timing exceptions, implementation or hardware',
              'hardware_accessed':False,'design_mutated':False,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    require(not REPORT.exists(), 'Fresh read-only inventory required')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, handle_signal)
    try:
        prep=json.loads(PREP.read_text()); synth=json.loads(SYNTH_REPORT.read_text())
        require(synth.get('status') == 'PASS_FRESH_SOURCE_CONSTRAINED_SYNTHESIS_ONLY' and synth.get('returncode') == 0,
                'Source-only synthesis report is not terminal pass')
        require(sha(DCP) == DCP_SHA256, 'Post-opt DCP hash changed')
        source_inputs=source_hashes(prep)
        require(len(source_inputs)==160 and all(sha(p)==h for p,h in source_inputs.items()), 'Frozen copied source changed')
        helper_paths=[PREP_DIR/'source/constraint-helpers'/n for n in
                      ['status_cdc.tcl','job_cdc.tcl','permit_cdc.tcl','memory_crossing.tcl','mailbox_ui.tcl','board_reset.tcl']]
        expected={**source_inputs}
        fixed={PREP:sha(PREP),SYNTH_REPORT:sha(SYNTH_REPORT),DCP:DCP_SHA256,FACTS:sha(FACTS),
               PREP_DIR/'synth.tcl':sha(PREP_DIR/'synth.tcl'),PREP_DIR/'run_synth.py':sha(PREP_DIR/'run_synth.py'),
               TCL:sha(TCL),RUNNER:sha(RUNNER),VIVADO:sha(VIVADO),
               ROOT/'build/full512-ddr-preparation/shared-data-mapped-facts-v1/dual-cdc-inventory-v4/output/inventory-facts.txt':
                 sha(ROOT/'build/full512-ddr-preparation/shared-data-mapped-facts-v1/dual-cdc-inventory-v4/output/inventory-facts.txt')}
        for p in helper_paths: fixed[p]=sha(p)
        expected.update({str(p):h for p,h in fixed.items()})
        before={p:sha(p) for p in expected}
        require(before==expected,'Read-only inventory input hash mismatch')
        cgroup=group_dir()
        limits={k:(cgroup/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        require(limits=={'memory.max':'6442450944','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'},
                'Wrong native query resource caps: '+repr(limits))
        avail=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
        mempsi=Path('/proc/pressure/memory').read_text();cpupsi=Path('/proc/pressure/cpu').read_text()
        require(avail>=8388608,'Read-only query requires8GiB host headroom')
        require(float(re.search(r'^full avg10=([0-9.]+)',mempsi,re.M)[1])<1 and
                float(re.search(r'^some avg10=([0-9.]+)',cpupsi,re.M)[1])<5,'Host pressure admission failed')
        require(OUT.is_dir() and not list(OUT.iterdir()),'Fresh empty output directory required')
        version=subprocess.run([str(VIVADO),'-version'],capture_output=True,text=True,timeout=30,check=True)
        argv=[str(VIVADO),'-mode','batch','-source',str(TCL),'-log',str(OUT/'vivado.log'),'-journal',str(OUT/'vivado.jou')]
        RECORD.update(status='RUNNING',argv=argv,pid=None,pgid=None,dcp_path=str(DCP),dcp_sha256=DCP_SHA256,
                      synthesis_facts_path=str(FACTS),synthesis_facts_sha256=sha(FACTS),source_input_count=len(source_inputs),
                      source_inputs=source_inputs,helper_paths=[str(x) for x in helper_paths],input_hashes_before=before,
                      vivado_path=str(VIVADO),vivado_sha256=sha(VIVADO),vivado_version=version.stdout,
                      kernel_limits=limits,initial_available_kib=avail,memory_psi=mempsi,cpu_psi=cpupsi,
                      timeout_seconds=240,started_native_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        save()
        with (OUT/'stdout.log').open('x') as stdout, (OUT/'stderr.log').open('x') as stderr:
            maskset={signal.SIGINT,signal.SIGTERM,signal.SIGHUP};oldmask=signal.pthread_sigmask(signal.SIG_BLOCK,maskset)
            try:
                CHILD=subprocess.Popen(argv,cwd=OUT,stdout=stdout,stderr=stderr,start_new_session=True,
                    preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,oldmask))
                RECORD.update(pid=CHILD.pid,pgid=CHILD.pid);save()
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK,oldmask)
            try: RECORD['returncode']=CHILD.wait(timeout=240)
            except subprocess.TimeoutExpired:
                RECORD['status']='TIMEOUT';kill_owned(signal.SIGTERM);raise TimeoutError('240s read-only inventory limit exceeded')
        facts_path=OUT/'inventory-facts.txt'
        require(CHILD.returncode==0 and facts_path.is_file(),'Native read-only inventory failed')
        after={p:sha(p) for p in expected}
        require(after==expected,'A frozen inventory input changed during query')
        facts=facts_path.read_text()
        require(facts.endswith('PASS_READ_ONLY_DUAL_CDC_AND_RESET_INVENTORY\n'),'Missing exact query terminal marker')
        RECORD.update(status='PASS_READ_ONLY_POST_OPT_CONTROLLER_RESET_AND_CDC_INVENTORY',input_hashes_after=after,
                      all_inputs_unchanged=True,facts_sha256=sha(facts_path),facts_text=facts,
                      native_stdout_sha256=sha(OUT/'stdout.log'),native_stderr_sha256=sha(OUT/'stderr.log'))
    except BaseException as error:
        if CHILD is not None and CHILD.poll() is None: kill_owned(signal.SIGTERM)
        if RECORD.get('status')!='TIMEOUT':RECORD['status']='FAIL_READ_ONLY_POST_OPT_INVENTORY'
        RECORD['error']=repr(error);RECORD['received_signal']=RECEIVED_SIGNAL
        RECORD['returncode']=CHILD.returncode if CHILD is not None else None
    finally:
        RECORD['elapsed_seconds']=time.monotonic()-started
        RECORD['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        if 'input_hashes_before' in RECORD:
            try:
                RECORD['input_hashes_after']={p:sha(p) for p in RECORD['input_hashes_before']}
                RECORD['all_inputs_unchanged']=RECORD['input_hashes_after']==RECORD['input_hashes_before']
            except BaseException as error:
                RECORD['input_rehash_error']=repr(error)
                RECORD['all_inputs_unchanged']=False
        if OUT.exists():RECORD['output_hashes']={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file()}
        try:
            cg=group_dir();RECORD['memory_peak_bytes']=(cg/'memory.peak').read_text().strip();RECORD['memory_events']=(cg/'memory.events').read_text().strip()
        except BaseException as error:RECORD['cgroup_error']=repr(error)
        RECORD['hardware_accessed']=False;RECORD['design_mutated']=False;save()
    return 0 if RECORD['status'].startswith('PASS_READ_ONLY') else 1

if __name__=='__main__': raise SystemExit(main())
