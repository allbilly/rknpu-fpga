#!/usr/bin/env python3
"""Run the pinned nine numerical modes on the separately compiled shared-dispatch Icarus image."""
import hashlib,json,os,re,signal,subprocess,time
from pathlib import Path

ROOT=Path('/home/fedora/rknpu-fpga')
BASE=ROOT/'build/full512-ddr-preparation/dual-dispatch-numerical-v1'
COMPILE=BASE/'iverilog-compile-v1'
COMPILE_REPORT=COMPILE/'report.json'
BINARY=COMPILE/'tb_cmac_async_engine.vvp'
BENCH=BASE/'tb_cmac_async_engine.sv'
FIXTURE=ROOT/'tests/cmac/array_data'
OUT=Path(os.environ['NUMERICAL_MODES_OUT']).resolve()
COUNTS={0:(2,2,98,13056,128,13576,2),1:(1,1,0,0,0,1,0),2:(1,1,0,0,0,0,0),
        3:(1,1,1,0,0,4,0),4:(1,1,0,0,0,1,0),5:(1,1,0,0,0,0,0),
        6:(1,1,49,6528,64,6788,0),7:(1,1,49,6528,64,6788,1),8:(1,1,49,6528,64,6788,1)}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def main():
    if OUT.exists() or not OUT.is_relative_to(ROOT/'build'):raise SystemExit('fresh build output required')
    OUT.mkdir(parents=True)
    compile_report=json.loads(COMPILE_REPORT.read_text())
    if compile_report['status']!='PASS_COMPILE_ONLY_UNQUALIFIED':raise SystemExit('Icarus compile receipt not a pass')
    binary_sha=compile_report['compile_binary_sha256']
    if sha(BINARY)!=binary_sha:raise SystemExit('new Icarus binary changed')
    inputs=dict(compile_report['all_input_hashes_before'])
    inputs[str(COMPILE_REPORT)]=sha(COMPILE_REPORT)
    inputs[str(BINARY)]=binary_sha
    inputs[str(Path(__file__).resolve())]=sha(__file__)
    inputs[str(Path(__import__('shutil').which('vvp')).resolve())]=sha(Path(__import__('shutil').which('vvp')).resolve())
    if any(sha(p)!=h for p,h in inputs.items()):raise SystemExit('runtime source/fixture/tool hash mismatch')
    record={'status':'RUNNING','scope':'nine unchanged CMAC numeric/control modes through actual shared dispatcher, with existing UI-halfword model; no DDR/MIG/physical qualification',
        'simulator':'Icarus 13.0','binary_sha256':binary_sha,'selected_modes':list(range(9)),
        'fixture_directory':str(FIXTURE),'source_and_fixture_hashes_before':inputs,'cases':[],
        'timeout_seconds_per_mode':1200,'hardware_accessed':False,'binary_executed':True,
        'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    (OUT/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    try:
        for mode in range(9):
            if any(sha(p)!=h for p,h in inputs.items()):raise ValueError('runtime source/fixture/tool changed before mode')
            argv=['vvp',str(BINARY),'+DIRECTORY='+str(FIXTURE),'+MODE='+str(mode)]
            item={'mode':mode,'status':'RUNNING','argv':argv,'timeout_seconds':1200}
            record['cases'].append(item);(OUT/'report.json').write_text(json.dumps(record,indent=2)+'\n')
            so=OUT/f'mode-{mode}.stdout.log';se=OUT/f'mode-{mode}.stderr.log';start=time.monotonic()
            with so.open('x') as stdout,se.open('x') as stderr:
                proc=subprocess.Popen(argv,cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True)
                item['pid']=proc.pid;(OUT/'report.json').write_text(json.dumps(record,indent=2)+'\n')
                try:item['returncode']=proc.wait(timeout=1200)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGTERM)
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                    item['returncode']=proc.returncode;item['timed_out']=True
                    raise TimeoutError(f'Icarus mode {mode} exceeded unchanged 1200s deadline')
            item['elapsed_seconds']=round(time.monotonic()-start,3)
            item['stdout_sha256']=sha(so);item['stderr_sha256']=sha(se)
            text=so.read_text();err=se.read_text();a,c,w,r,wr,rsp,rearm=COUNTS[mode]
            expected=(f'PASS async_cmac_boundary mode={mode} admitted={a} consumed={c} command_words={w} '
                f'operand_reads={r} writes={wr} responses={rsp} rearm={rearm} seed=3588ad16 raw_K65_two_clocks_only')
            item['expected_marker']=expected
            if item['returncode']!=0 or err or [x for x in text.splitlines() if x.startswith('PASS ')]!=[expected]:
                raise ValueError(f'Icarus mode {mode} failed exact marker/return/stderr contract')
            lines=text.splitlines()
            finish=re.fullmatch(re.escape(str(BENCH))+r':([0-9]+): \$finish called at ([0-9]+) \(1ps\)',lines[-1]) if len(lines)==2 else None
            if lines[0]!=expected or finish is None or BENCH.read_text().splitlines()[int(finish[1])-1].strip()!='$finish;':
                raise ValueError(f'Icarus mode {mode} changed exact completion marker/source line')
            if any(sha(p)!=h for p,h in inputs.items()):raise ValueError(f'runtime source/fixture/tool changed after mode {mode}')
            item.update(status='PASS',marker=expected);(OUT/'report.json').write_text(json.dumps(record,indent=2)+'\n')
            print(expected,flush=True)
        record['status']='PASS_ALL_NINE_SHARED_DISPATCH_CMAC_NUMERICAL_MODES_ONLY'
    except BaseException as error:
        record.update(status='FAIL_SHARED_DISPATCH_CMAC_NUMERICAL_MODES',error=repr(error))
        if record['cases'] and record['cases'][-1]['status']=='RUNNING':record['cases'][-1]['status']='FAIL'
        raise
    finally:
        record['all_inputs_unchanged']=all(sha(p)==h for p,h in inputs.items())
        record['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        (OUT/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    print(record['status'])
if __name__=='__main__':main()
