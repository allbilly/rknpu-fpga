#!/usr/bin/env python3
"""Run unchanged nine CMAC modes against the reviewed-warning Verilator binary."""
import hashlib,json,os,re,signal,subprocess,time
from pathlib import Path
ROOT=Path('/home/fedora/rknpu-fpga');BASE=ROOT/'build/full512-ddr-preparation/shared-data-dispatch-numerical-v1'
COMPILE=BASE/'verilator-compile-v1';REPORT=COMPILE/'report.json';BINARY=COMPILE/'obj/Vtb_cmac_async_engine'
FIXTURE=ROOT/'tests/cmac/array_data';OUT=Path(os.environ['NUMERICAL_MODES_OUT']).resolve()
COUNTS={0:(2,2,98,13056,128,13576,2),1:(1,1,0,0,0,1,0),2:(1,1,0,0,0,0,0),
        3:(1,1,1,0,0,4,0),4:(1,1,0,0,0,1,0),5:(1,1,0,0,0,0,0),
        6:(1,1,49,6528,64,6788,0),7:(1,1,49,6528,64,6788,1),8:(1,1,49,6528,64,6788,1)}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    if OUT.exists() or not OUT.is_relative_to(ROOT/'build'):raise SystemExit('fresh build output required')
    OUT.mkdir(parents=True)
    cr=json.loads(REPORT.read_text())
    if cr['status']!='PASS_COMPILE_ONLY_REVIEWED_WARNINGS':raise SystemExit('reviewed Verilator compile is not qualified for execution')
    binary_sha=cr.get('compile_binary_sha256')
    if not binary_sha or sha(BINARY)!=binary_sha:raise SystemExit('compiled Verilator binary hash mismatch')
    inputs=dict(cr['all_input_hashes_before'])
    review=ROOT/'build/full512-ddr-preparation/shared-data-dispatch-numerical-v1/verilator-diagnostics-root-review-v1.json'
    strict_log=BASE/'verilator-strict-v1/compile.stderr.log'
    inputs.update({str(REPORT):sha(REPORT),str(BINARY):binary_sha,str(review):sha(review),str(strict_log):sha(strict_log),str(Path(__file__).resolve()):sha(__file__)})
    if any(sha(p)!=h for p,h in inputs.items()):raise SystemExit('mode input hash mismatch')
    record={'status':'RUNNING','scope':'nine unchanged CMAC numeric/control modes using the actual shared dispatcher and halfword UI model; no DDR/MIG/physical qualification',
        'simulator':'Verilator 5.048','binary_sha256':binary_sha,'compile_report_sha256':sha(REPORT),'warning_review_sha256':sha(review),
        'selected_modes':list(range(9)),'fixture_directory':str(FIXTURE),'source_and_fixture_hashes_before':inputs,
        'timeout_seconds_per_mode':1200,'binary_executed':True,'hardware_accessed':False,'cases':[],
        'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    (OUT/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    try:
        for mode in range(9):
            if any(sha(p)!=h for p,h in inputs.items()):raise ValueError('runtime input changed before mode')
            argv=[str(BINARY),'+DIRECTORY='+str(FIXTURE),'+MODE='+str(mode)]
            item={'mode':mode,'status':'RUNNING','argv':argv,'timeout_seconds':1200};record['cases'].append(item)
            (OUT/'report.json').write_text(json.dumps(record,indent=2)+'\n')
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
                    raise TimeoutError(f'Verilator mode {mode} exceeded unchanged 1200s deadline')
            item['elapsed_seconds']=round(time.monotonic()-start,3);item['stdout_sha256']=sha(so);item['stderr_sha256']=sha(se)
            text=so.read_text();err=se.read_text();a,c,w,reads,writes,responses,rearms=COUNTS[mode]
            expected=(f'PASS async_cmac_boundary mode={mode} admitted={a} consumed={c} command_words={w} '
                f'operand_reads={reads} writes={writes} responses={responses} rearm={rearms} seed=3588ad16 raw_K65_two_clocks_only')
            item['expected_marker']=expected
            if item['returncode']!=0 or err or [x for x in text.splitlines() if x.startswith('PASS ')]!=[expected]:
                raise ValueError(f'Verilator mode {mode} failed exact marker/return/stderr contract')
            if re.search(r'(?i)%Error|%Warning|\b(?:warning|error|fatal|sorry):|assertion failed',text):
                raise ValueError(f'Verilator mode {mode} produced a runtime diagnostic')
            if any(sha(p)!=h for p,h in inputs.items()):raise ValueError(f'runtime input changed after mode {mode}')
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
