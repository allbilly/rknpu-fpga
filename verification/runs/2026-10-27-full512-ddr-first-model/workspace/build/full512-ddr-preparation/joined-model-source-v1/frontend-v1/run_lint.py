#!/usr/bin/env python3
"""Hash-bound strict Verilator lint/elaboration for the frozen joined model."""
import hashlib,json,re
from pathlib import Path
import subprocess,time
ROOT=Path(__file__).resolve().parents[4]
PREP=ROOT/'build/full512-ddr-preparation/joined-model-source-v1/preparation.json'
OUT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    prep=json.loads(PREP.read_text());expected=prep['files'];inputs=prep['inputs'];sources=prep['hdl_sources'];headers=prep['headers']
    if prep['status']!='PREPARED_REAL_FULL512_DUAL_AXI_UI_MC_TEST_WITH_MODELED_PHY_ONLY':raise SystemExit('unexpected joined-model status')
    if prep['top']!='tb_jtag_dual_ddr_async' or len(sources)!=111:raise SystemExit('joined-model top/source count mismatch')
    if set(headers)!={'RK_MIG_LOGIC_AXI_PARAMS_HEADER','RK_MIG_LOGIC_UI_PARAMS_HEADER','RK_MIG_LOGIC_MC_PARAMS_HEADER','RK_MIG_LOGIC_CTRL_PARAMS_HEADER','RK_DDR_LINE_IMAGE_HEADER'}:raise SystemExit('header macro set mismatch')
    if prep['verilog_defines']!=['DESIGNWARE_NOEXIST','ASSERT_ON']:raise SystemExit('define set mismatch')
    selected=[Path(x['path']) for x in sources]+[Path(prep['bench'])]
    if any(str(p) not in expected for p in selected):raise SystemExit('selected HDL/bench absent from bound file manifest')
    before_files={p:sha(Path(p)) for p in expected}
    before_inputs={p:sha(Path(p)) for p in inputs}
    if any(before_files[p]!=expected[p] for p in expected):raise SystemExit('copied source artifact hash mismatch')
    if any(before_inputs[p]!=inputs[p] for p in inputs):raise SystemExit('source/preparation input hash mismatch')
    if any(before_files[str(Path(x['path']))]!=x['sha256'] for x in sources):raise SystemExit('selected HDL hash mismatch')
    prep_sha=sha(PREP)
    if OUT.exists():raise SystemExit('frontend output already exists')
    OUT.mkdir(parents=True)
    argv=['verilator','--lint-only','--timing','--assert','-Wall','--top-module',prep['top']]
    argv.extend('-D'+name+'="'+str(path)+'"' for name,path in headers.items())
    argv.extend('-D'+name for name in prep['verilog_defines'])
    argv.extend(str(p) for p in selected)
    start=time.time()
    try:
        result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=300)
        timeout=False
    except subprocess.TimeoutExpired as exc:
        result=exc;timeout=True
    stdout=result.stdout or '';stderr=result.stderr or ''
    (OUT/'verilator_lint.stdout.log').write_text(stdout);(OUT/'verilator_lint.stderr.log').write_text(stderr)
    version=subprocess.run(['verilator','--version'],cwd=ROOT,capture_output=True,text=True,timeout=15)
    toolpath=Path(subprocess.run(['which','verilator'],capture_output=True,text=True,timeout=5).stdout.strip()).resolve()
    after_files={p:sha(Path(p)) for p in expected}
    after_inputs={p:sha(Path(p)) for p in inputs}
    report={'status':'RUNNING','scope':'strict lint/elaboration of the frozen joined full512 endpoint plus logical MIG model; no simulator execution, numerical pass, physical PHY/training, DDR or hardware qualification',
      'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(start)),'finished_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
      'resource_scope':{'MemoryMax':'4G','MemorySwapMax':'0','CPUQuota':'200%','TasksMax':128,'timeout_seconds':300},
      'preparation_path':str(PREP),'preparation_sha256':prep_sha,'preparation_status':prep['status'],'top':prep['top'],
      'hdl_source_count':len(sources),'bench_path':prep['bench'],'verilog_defines':prep['verilog_defines'],'header_macros':headers,
      'argv':[str(x) for x in argv],'returncode':None if timeout else result.returncode,'timeout':timeout,
      'elapsed_seconds':round(time.time()-start,3),'tool':{'version_stdout':version.stdout,'version_stderr':version.stderr,'version_rc':version.returncode,'path':str(toolpath),'sha256':sha(toolpath)},
      'selected_hdl_hashes_before':{x['path']:before_files[str(Path(x['path']))] for x in sources},
      'input_hashes_before':before_inputs,'copied_file_hashes_before':before_files,
      'source_hashes_unchanged':before_files==after_files and before_inputs==after_inputs,
      'preparation_hash_unchanged':sha(PREP)==prep_sha,'stdout':stdout,'stderr':stderr,
      'warning_headers':re.findall(r'(?m)^%Warning-[A-Z0-9_]+:',stderr),
      'error_headers':re.findall(r'(?m)^%Error-[A-Z0-9_]+:',stderr),
      'binary_executed':False,'hardware_accessed':False}
    ok=(not timeout and result.returncode==0 and not report['error_headers'] and report['source_hashes_unchanged'] and report['preparation_hash_unchanged'])
    report['status']='PASS_STRICT_JOINED_MODEL_FRONTEND_ONLY' if ok else 'FAIL_STRICT_JOINED_MODEL_FRONTEND'
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'rc':report['returncode'],'elapsed':report['elapsed_seconds'],'warnings':len(report['warning_headers']),'errors':report['error_headers'],'hashes_unchanged':report['source_hashes_unchanged']},indent=2))
    return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
