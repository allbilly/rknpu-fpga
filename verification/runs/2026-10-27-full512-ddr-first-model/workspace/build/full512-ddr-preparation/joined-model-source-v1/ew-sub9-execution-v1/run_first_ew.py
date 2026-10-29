#!/usr/bin/env python3
"""Execute the original SUB9 raw BO pair through the joined model's EW CSR bank."""
from pathlib import Path
import datetime,hashlib,json,os,re,signal,subprocess,time
BASE=Path(__file__).resolve().parent.parent
OUT=Path(__file__).resolve().parent
ROOT=Path('/home/fedora/rknpu-fpga')
PREP=BASE/'preparation.json'
CASE=OUT/'preparation.json'
PREFLIGHT=OUT/'offline-preflight-v2.json'
COMPILE=BASE/'native-compile-v2/report.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,msg):
    if not ok:raise RuntimeError(msg)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def main():
    record=None;child=None;start=time.monotonic()
    prep=json.loads(PREP.read_text());case=json.loads(CASE.read_text());preflight=json.loads(PREFLIGHT.read_text());compiled=json.loads(COMPILE.read_text())
    require(prep['status']=='PREPARED_REAL_FULL512_DUAL_AXI_UI_MC_TEST_WITH_MODELED_PHY_ONLY','Joined source prep status changed')
    require(case['status']=='PREPARED_SAME_ELF_EW_SUB9_ORIGINAL_BO_PAIR_ONLY','EW SUB9 prep status changed')
    require(preflight['status']=='PASS_OFFLINE_EW_SUB9_SAME_ELF_PREFLIGHT_ONLY','Offline EW preflight not passed')
    require(compiled['status']=='PASS_JOINED_MODEL_NATIVE_COMPILE_ONLY','Joined model compile status not PASS')
    binary=Path(compiled['binary_path']);binary_sha='ca017f2afc191f4a07c681e2dc4648063997ee6ac35264695554c33eb4e9bf2e'
    require(sha(binary)==compiled['binary_sha256']==binary_sha,'Changed joined model ELF')
    vectors=Path(case['ew_vector_dir']);upload=vectors/'upload.txt';expected=vectors/'expected.txt'
    require(sha(upload)==case['vectors'][str(Path(case['parent_vector_dir'])/'upload.txt')]['source_sha256'],'EW upload differs from original SUB9')
    require(sha(expected)==case['vectors'][str(Path(case['parent_vector_dir'])/'expected.txt')]['source_sha256'],'EW expected BO differs from original SUB9')
    require(case['prospective_counts']=={'read64_packets':1602,'read64_axi_reads':1602,
        'phy_user_returns_formula':'65 + 1602 + 77*64 + 4*(35+22) + 3*16*2 + 1','phy_user_returns':6920},
        'Changed original EW prospective traffic contract')
    inputs=dict(prep['inputs'])|dict(prep['files'])|dict(compiled['source_hashes_before'])
    inputs.update(preflight['source_hashes_before'])
    for path,digest in case['vectors'].items():
        inputs[path]=digest['source_sha256']
        inputs[digest['copy']]=digest['copy_sha256']
    for path in (PREP,CASE,PREFLIGHT,COMPILE,Path(__file__),binary):inputs[str(path)]=sha(path)
    for path,digest in inputs.items():require(sha(path)==digest,'Changed joined-model EW run input: '+path)
    cg=Path('/sys/fs/cgroup')/next(line.split('::',1)[1].strip().lstrip('/') for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
    limits={name:(cg/name).read_text().strip() for name in ('memory.max','memory.swap.max','cpu.max','pids.max')}
    require(limits=={'memory.max':'4294967296','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'128'},
        'EW run requires 4GiB/no-swap/2CPU/128-task cgroup')
    output=OUT/'actual-bo.txt'
    require(not output.exists(),'Fresh EW output required')
    argv=[str(binary),'+CASE='+str(vectors),'+OUTPUT='+str(output),'+START=100e0000',
          '+AMOUNT=35','+NTASKS=2','+NLINES=1600','+JOBS=1','+NEGATIVE=0','+RESET_RECOVERY=0','+CSR_BASE=0']
    marker=('PASS jtag_dual_ddr_read_snapshot csr_base=00000000 jobs=1 negative=0 recovered=0 '
        'lines=1600 uploaded_nonzero=77 rawtasks=2 phy_user_returns=6920 read64_packets=1602 '
        'read64_axi_reads=1602 scope=actual_AXI_UI_MC_modeled_PHY')
    record={'status':'RUNNING_FIRST_JOINED_FULL512_EW_SUB9_MODEL_EXECUTION','started_utc':now(),
      'argv':argv,'source_inputs':inputs,'binary_sha256':sha(binary),'kernel_limits':limits,
      'timeout_seconds':1800,'expected_marker':marker,'expected_phy_user_returns':6920,
      'expected_read64_packets':1602,'expected_read64_axi_reads':1602,'expected_complete_bo_bytes':102400,
      'case_parameters':{'csr_base':0,'start':'0x100e0000','amount':35,'ntasks':2,'nlines':1600,'jobs':1,'negative':0,'reset_recovery':0},
      'tools':compiled['tool_versions'],'actual_toolchain':compiled['actual_toolchain'],
      'binary_executed':True,'hardware_accessed':False,'physical_phy_qualified':False,
      'physical_ddr_qualified':False,'ew_numerical_alternation_qualified':False,
      'cpu_arithmetic_or_layout_repair':False,'fixture_source':'Original capture_sub_9 bytes copied verbatim; no vector generation'}
    report=OUT/'report.json'
    def save():report.write_text(json.dumps(record,indent=2)+'\n')
    def interrupted(sig,frame):raise InterruptedError('Joined EW execution interrupted '+str(sig))
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
    save()
    try:
        with (OUT/'stdout.log').open('x') as stdout,(OUT/'stderr.log').open('x') as stderr:
            child=subprocess.Popen(argv,cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True)
            record['pid']=child.pid;save();record['returncode']=child.wait(timeout=1800)
        require(record['returncode']==0,'First joined EW SUB9 simulation failed')
        require(not (OUT/'stderr.log').read_bytes(),'Unexpected EW model stderr')
        text=(OUT/'stdout.log').read_text()
        require(not re.search(r'(?mi)^(?:FATAL:|ERROR:|FAIL|%Error)|Assertion failed|\bwarning:',text),
                'Unadmitted runtime warning or failure')
        require([x for x in text.splitlines() if x.startswith('PASS ')]==[marker],
                'EW marker/PHY/readback inventory differs from prospective fixed contract')
        require(output.is_file() and output.read_bytes()==expected.read_bytes(),
                'Complete 1600-row SUB9 readback differs from unchanged expected BO')
        require(len(output.read_text().splitlines())==1600 and output.stat().st_size==102400,
                'Incomplete EW complete-BO capture')
        require(all(sha(p)==d for p,d in inputs.items()),'EW execution input drifted during run')
        record.update(status='PASS_FIRST_JOINED_FULL512_EW_SUB9_MODEL_EXECUTION_ONLY',
            actual_marker=marker,checked_complete_bo_bytes=102400,observed_sha256=sha(output),
            readback_before_ack_asserted_by_bound_sv=True)
    except BaseException as error:
        record.update(status='FAIL_FIRST_JOINED_FULL512_EW_SUB9_MODEL_EXECUTION',error=repr(error))
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        record['owned_child_exit']=child.returncode if child is not None else None
        record['all_inputs_unchanged']=all(sha(p)==d for p,d in inputs.items())
        if not record['all_inputs_unchanged']:
            record.update(status='FAIL_FIRST_JOINED_FULL512_EW_SUB9_MODEL_EXECUTION',error='Execution input drift')
        record.update(seconds=time.monotonic()-start,finished_utc=now(),
            stdout_sha256=sha(OUT/'stdout.log') if (OUT/'stdout.log').exists() else None,
            stderr_sha256=sha(OUT/'stderr.log') if (OUT/'stderr.log').exists() else None,
            memory_peak=(cg/'memory.peak').read_text().strip(),memory_events=(cg/'memory.events').read_text().strip())
        save()
    print(json.dumps({'status':record['status'],'report':str(report),'seconds':record['seconds']},indent=2),flush=True)
    return 0 if record['status'].startswith('PASS_') else 1
if __name__=='__main__':raise SystemExit(main())
