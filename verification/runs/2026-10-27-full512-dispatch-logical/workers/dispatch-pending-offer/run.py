#!/usr/bin/env python3
"""Icarus controls for reviewed private dispatch fix and preserved old negative."""
import hashlib,json
from pathlib import Path
import subprocess,time

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
FIXED=ROOT/'build/full512-ddr-preparation/combined-source-v5/source/hdl/148/rk_dual_async_dispatch.sv'
OLD=ROOT/'rtl/ddr/rk_dual_async_dispatch.sv'
MODELS=ROOT/'tests/ddr/dispatch/control_models.sv'
OLD_BENCH=ROOT/'tests/ddr/dispatch/tb_dual_dispatch.sv'
NEW_BENCH=HERE/'tb_dual_dispatch.sv'
OUT=HERE/'results-v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(argv,name,timeout=30):
    start=time.time()
    try:
        q=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=timeout)
        row={'argv':[str(x) for x in argv],'returncode':q.returncode,'elapsed_seconds':round(time.time()-start,3),'stdout':q.stdout,'stderr':q.stderr}
    except subprocess.TimeoutExpired as e:
        row={'argv':[str(x) for x in argv],'returncode':None,'timeout_seconds':timeout,'elapsed_seconds':round(time.time()-start,3),'stdout':e.stdout or '','stderr':e.stderr or '','timeout':True}
    (OUT/(name+'.stdout.log')).write_text(row['stdout']);(OUT/(name+'.stderr.log')).write_text(row['stderr'])
    return row
def compile_run(label,dut,bench,expected_marker,expect_success):
    image=OUT/(label+'.vvp')
    comp=run(['iverilog','-g2012','-Wall','-s','tb_dual_dispatch','-o',str(image),str(dut),str(MODELS),str(bench)],label+'_compile',120)
    if comp['returncode']!=0:return {'compile':comp,'run':None,'expected_result':False}
    sim=run(['vvp',str(image)],label+'_run',30)
    marker=expected_marker in sim['stdout']
    result=(sim['returncode']==0 and marker) if expect_success else (sim['returncode']!=0 and marker)
    return {'compile':comp,'run':sim,'expected_marker_present':marker,'expected_result':result,'binary_sha256':sha(image)}
def main():
    OUT.mkdir(parents=True,exist_ok=False)
    sources=[FIXED,OLD,MODELS,OLD_BENCH,NEW_BENCH]
    before={str(x.relative_to(ROOT)):sha(x) for x in sources}
    report={'status':'RUNNING','scope':'Icarus control-only dispatch handshakes with handshake-only child models; no arithmetic/DDR/physical qualification',
        'resource_scope':{'MemoryMax':'512M','MemorySwapMax':'0','CPUQuota':'100%','TasksMax':128},
        'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'tools':{},
        'source_hashes_before':before,'commands':[]}
    q=run(['iverilog','-V'],'iverilog_version',10);report['tools']['iverilog']=q
    q=run(['vvp','-V'],'vvp_version',10);report['tools']['vvp']=q
    report['existing_bench_fixed_private']=compile_run('existing_fixed_private',FIXED,OLD_BENCH,
        'PASS dual_async_dispatch control_only=1 chain=EW-CMAC-EW req_result_backpressure=1 admission_readback_gate=1 failed_owner_late_drain=1 unowned_response=1 unknown_selection=1',True)
    report['pending_offer_fixed_private']=compile_run('pending_offer_fixed_private',FIXED,NEW_BENCH,
        'PASS dual_async_dispatch control_only=1 chain=EW-CMAC-EW req_result_backpressure=1 admission_readback_gate=1 failed_owner_late_drain=1 unowned_response=1 unknown_selection=1 duplicate_offer_without_ready=1',True)
    report['pending_offer_old_public_negative']=compile_run('pending_offer_old_public_negative',OLD,NEW_BENCH,
        'second offered request was ignored while downstream READY was low',False)
    after={str(x.relative_to(ROOT)):sha(x) for x in sources}
    report['source_hashes_after']=after;report['source_hashes_unchanged']=before==after
    runs=[report[x]['expected_result'] for x in ('existing_bench_fixed_private','pending_offer_fixed_private','pending_offer_old_public_negative')]
    ok=all(runs) and report['source_hashes_unchanged']
    report['status']='PASS_PRIVATE_DISPATCH_CONTROL_AND_OLD_NEGATIVE_ONLY' if ok else 'FAIL_PRIVATE_DISPATCH_CONTROL'
    report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'results':{k:report[k]['expected_result'] for k in ('existing_bench_fixed_private','pending_offer_fixed_private','pending_offer_old_public_negative')},'source_hashes_unchanged':report['source_hashes_unchanged']},indent=2))
    return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
