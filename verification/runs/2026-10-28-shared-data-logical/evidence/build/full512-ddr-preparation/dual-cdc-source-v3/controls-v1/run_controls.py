#!/usr/bin/env python3
"""Source-bound Tcl mocks for v3 status inventory and v2 job/permit CDC helpers."""
import hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path('/home/fedora/rknpu-fpga');HERE=Path(__file__).resolve().parent
HELPERS=[ROOT/'build/full512-ddr-preparation/dual-cdc-source-v3/job_cdc.tcl',
         ROOT/'build/full512-ddr-preparation/dual-cdc-source-v3/status_cdc.tcl',
         ROOT/'build/full512-ddr-preparation/dual-cdc-source-v3/permit_cdc.tcl']
TESTS=[HERE/'test_private_helpers.py',HERE/'test_job_cdc.py',
       ROOT/'tests/ddr/async_job/test_cdc_constraints.py',ROOT/'tests/ddr/async_job/test_engine_observer.py',
       ROOT/'tests/ddr/board_shell/test_reset_bridge_board.py',ROOT/'tools/hardware/sample_ew.py']
PINNED={'job_cdc.tcl':'b5a155ec9229ecc012e5ed077838873c762d4e620e90f3dfa36a70c1f5cdfdb3',
        'status_cdc.tcl':'1d368380ad134e4ebcd2277d2843455e5b0657ef76783a1ea7e720ea19e34ab9',
        'permit_cdc.tcl':'d8ae90ce8f2589783d3fba9f790c91761052058004f12ca8de47558f523adc25'}
OUT=HERE
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    paths=[*HELPERS,*TESTS,Path(__file__).resolve()]
    before={str(p):sha(p) for p in paths}
    for p in HELPERS:
        if before[str(p)]!=PINNED[p.name]:raise SystemExit('root-pinned helper hash mismatch '+str(p))
    py=subprocess.run([sys.executable,'--version'],capture_output=True,text=True,timeout=15)
    tclpath=Path(shutil.which('tclsh')).resolve()
    tcl=subprocess.run(['tclsh'],input='puts [info patchlevel]\n',capture_output=True,text=True,timeout=15)
    argv=[sys.executable,'-m','unittest','discover','-s',str(HERE),'-v']
    start=time.time();result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=180)
    (OUT/'unittest.stdout.log').write_text(result.stdout);(OUT/'unittest.stderr.log').write_text(result.stderr)
    after={str(p):sha(p) for p in paths};unchanged=before==after
    passed=(result.returncode==0 and unchanged and all(after[str(p)]==PINNED[p.name] for p in HELPERS))
    report={'status':'PASS_PRIVATE_V3_STATUS_AND_CMAC_TERMINAL_FULL8_MOCK_CONTROLS_ONLY' if passed else 'FAIL_PRIVATE_V3_STATUS_AND_CMAC_TERMINAL_FULL8_MOCK_CONTROLS',
      'scope':'portable Tcl command-object mocks only; no Vivado timing queries, constraints, design changes, simulation or hardware',
      'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(start)),
      'command':argv,'returncode':result.returncode,'elapsed_seconds':round(time.time()-start,3),
      'stdout':result.stdout,'stderr':result.stderr,'tool_versions':{'python':{'argv':[sys.executable,'--version'],'returncode':py.returncode,'stdout':py.stdout,'stderr':py.stderr},
       'tclsh':{'argv':['tclsh'],'returncode':tcl.returncode,'stdout':tcl.stdout,'stderr':tcl.stderr}},
      'helper_hashes_expected':PINNED,'source_hashes_before':before,'source_hashes_after':after,
      'source_hashes_unchanged':unchanged,'hardware_accessed':False}
    report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'returncode':result.returncode,'seconds':report['elapsed_seconds'],'source_hashes_unchanged':unchanged},indent=2))
    return 0 if passed else 1
if __name__=='__main__':raise SystemExit(main())
