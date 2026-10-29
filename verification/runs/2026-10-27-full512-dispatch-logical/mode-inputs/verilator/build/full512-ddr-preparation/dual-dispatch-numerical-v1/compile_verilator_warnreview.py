#!/usr/bin/env python3
"""Hash-check and compile-only the frozen shared-dispatch numerical bench."""
import hashlib,json,os,re
from pathlib import Path
import subprocess,time

ROOT=Path(__file__).resolve().parents[3]
OUT=Path(os.environ['NUMERICAL_COMPILE_OUT'])
PREP=ROOT/'build/full512-ddr-preparation/combined-source-v6/preparation.json'
BENCH_PREP=ROOT/'build/full512-ddr-preparation/dual-dispatch-numerical-v1/preparation.json'
OLD_REPORT=ROOT/'build/full512-ddr-preparation/cmac-async-verilator-modes-v1/report.json'
BENCH=ROOT/'build/full512-ddr-preparation/dual-dispatch-numerical-v1/tb_cmac_async_engine.sv'
ASSERT_ROOT=ROOT/'build/tinystories-fpga-preparation/dual-v1/source/rtl/vendor/nvdla/compat'
ASSERTIONS=[ASSERT_ROOT/'nv_assert_never.v',ASSERT_ROOT/'nv_assert_no_x.v']
INCLUDE=ASSERT_ROOT.parent
WORKER=ROOT/'build/full512-ddr-preparation/run_cmac_async_cases.py'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def record_cmd(argv,name,timeout):
    start=time.time()
    try:
        q=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=timeout)
        row={'argv':[str(x) for x in argv],'returncode':q.returncode,'elapsed_seconds':round(time.time()-start,3),'stdout':q.stdout,'stderr':q.stderr}
    except subprocess.TimeoutExpired as e:
        row={'argv':[str(x) for x in argv],'returncode':None,'timeout_seconds':timeout,'elapsed_seconds':round(time.time()-start,3),'stdout':e.stdout or '','stderr':e.stderr or '','timeout':True}
    (OUT/(name+'.stdout.log')).write_text(row['stdout']);(OUT/(name+'.stderr.log')).write_text(row['stderr'])
    return row
def main():
    sim=os.environ['NUMERICAL_SIMULATOR']
    if sim not in ('iverilog','verilator'):raise SystemExit('bad simulator')
    if OUT.exists():raise SystemExit(f'output already exists: {OUT}')
    OUT.mkdir(parents=True)
    prep=json.loads(PREP.read_text());bench_prep=json.loads(BENCH_PREP.read_text());old=json.loads(OLD_REPORT.read_text())
    sources=prep['frontend_sources'];expected=prep['files']
    if prep['status']!='PREPARED_FROZEN_COMBINED_FULL512_CH1_SOURCE_FOR_FRONTEND_AND_RESOURCE_REVIEW_ONLY':raise SystemExit('unexpected source prep status')
    if prep['verilog_defines']!=['DESIGNWARE_NOEXIST']:raise SystemExit('manifest define mismatch')
    if len(sources)!=48 or any(x not in expected for x in sources):raise SystemExit('frontend source closure mismatch')
    if bench_prep['status']!='PREPARED_ACTUAL_FULL512_CMAC_THROUGH_SHARED_DISPATCH_NUMERICAL_BENCH' or bench_prep['bench_sha256']!=sha(BENCH):raise SystemExit('numerical bench preparation/hash mismatch')
    fixture_expected={p:h for p,h in old['inputs'].items() if '/tests/cmac/array_data/' in p}
    source_paths=[Path(x) for x in sources]+ASSERTIONS+[BENCH,WORKER]+[Path(x) for x in fixture_expected]
    source_paths += [PREP,BENCH_PREP,OLD_REPORT,Path(__file__).resolve()]
    unique=list(dict.fromkeys(source_paths))
    before={str(p):sha(p) for p in unique}
    if any(before[p]!=expected[p] for p in sources):raise SystemExit('selected v6 frontend hash mismatch')
    if any(before[str(Path(p))]!=h for p,h in fixture_expected.items()):raise SystemExit('unchanged numerical fixture mismatch')
    if not all(p.is_file() for p in ASSERTIONS+[WORKER]):raise SystemExit('required assertion/worker source missing')
    report={'status':'RUNNING','scope':'compile-only actual full512 shared-dispatch numerical bench; no simulator execution/DDR/physical qualification',
      'simulator':sim,'top':'tb_cmac_async_engine','source_manifest':str(PREP),'source_manifest_sha256':sha(PREP),
      'bench_preparation':str(BENCH_PREP),'bench_preparation_sha256':sha(BENCH_PREP),
      'designware_define':'DESIGNWARE_NOEXIST','assertions_enabled':True,'include_dir':str(INCLUDE),
      'selected_frontend_count':len(sources),'selected_frontend_hashes_before':{p:before[p] for p in sources},
      'selected_assertion_sources':[str(p) for p in ASSERTIONS],
      'selected_fixture_hashes_before':fixture_expected,'worker':str(WORKER),
      'all_input_hashes_before':before,'resource_scope':{'iverilog':{'MemoryMax':'2G','MemorySwapMax':'0','CPUQuota':'100%','TasksMax':128,'timeout_seconds':120},
       'verilator':{'MemoryMax':'4G','MemorySwapMax':'0','CPUQuota':'200%','TasksMax':128,'timeout_seconds':900}},'tools':{},'commands':[]}
    version_argv=[['iverilog','-V'],['vvp','-V']] if sim=='iverilog' else [['verilator','--version'],['c++','--version']]
    for i,argv in enumerate(version_argv):report['tools'][f'{sim}_{i}']=record_cmd(argv,f'version_{i}',15)
    binary=OUT/('tb_cmac_async_engine.vvp' if sim=='iverilog' else 'obj/Vtb_cmac_async_engine')
    common=['-DDESIGNWARE_NOEXIST','-DASSERT_ON',f'-I{INCLUDE}']
    files=[*sources,*map(str,ASSERTIONS),str(BENCH)]
    if sim=='iverilog':
        argv=['iverilog','-g2012','-Wall',*common,'-s','tb_cmac_async_engine','-o',str(binary),*files]
        row=record_cmd(argv,'compile',120)
    else:
        obj=OUT/'obj'
        argv=['verilator','--binary','--timing','--assert','-Wall','-Wno-fatal','-j','1','--output-groups','0',
              '--output-split','5000','--output-split-cfuncs','1000','--top-module','tb_cmac_async_engine',
              '--Mdir',str(obj),*common,*files]
        row=record_cmd(argv,'compile',900)
        binpath=obj/'Vtb_cmac_async_engine'
        if binpath.exists():report['binary_sha256']=sha(binpath)
    report['commands'].append(row)
    strict_log=ROOT/'build/full512-ddr-preparation/dual-dispatch-numerical-v1/verilator-compile-v1/compile.stderr.log'
    review_path=ROOT/'build/full512-ddr-preparation/dual-dispatch-numerical-v1/verilator-diagnostics-root-review-v1.json'
    review=json.loads(review_path.read_text())
    strict_text=strict_log.read_text()
    actual_text=row['stderr']
    strict_tail='%Error: Exiting due to 56 warning(s)\n'
    expected_text=strict_text[:-len(strict_tail)] if strict_text.endswith(strict_tail) else None
    report['warning_review']={'review_path':str(review_path),'review_sha256':sha(review_path),
       'strict_log_sha256':sha(strict_log),'reviewed_strict_log_sha256':review['stderr_sha256'],
       'strict_warning_count':review['warning_count'],'strict_rc':review['native_strict_rc'],
       'only_nonfatal_summary_removed':expected_text is not None and actual_text==expected_text,
       'actual_verilator_warning_headers':len(re.findall(r'(?m)^%Warning-[A-Z0-9_]+:',actual_text)),
       'actual_verilator_error_headers':len(re.findall(r'(?m)^%Error-[A-Z0-9_]+:',actual_text))}
    after={str(p):sha(p) for p in unique}
    report['all_input_hashes_after']=after;report['all_inputs_unchanged']=before==after
    report['selected_frontend_hashes_after']={p:after[p] for p in sources}
    report['compile_binary_sha256']=sha(binary) if sim=='iverilog' and binary.exists() else report.get('binary_sha256')
    report['binary_executed']=False;report['hardware_accessed']=False
    reviewed=(sim!='verilator' or (report['warning_review']['strict_log_sha256']==review['stderr_sha256'] and
        report['warning_review']['only_nonfatal_summary_removed'] and report['warning_review']['actual_verilator_warning_headers']==56 and
        report['warning_review']['actual_verilator_error_headers']==0))
    report['status']='PASS_COMPILE_ONLY_REVIEWED_WARNINGS' if row['returncode']==0 and report['all_inputs_unchanged'] and reviewed else 'FAIL_STRICT_COMPILE_ONLY'
    report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'simulator':sim,'rc':row['returncode'],'elapsed_seconds':row['elapsed_seconds'],
      'all_inputs_unchanged':report['all_inputs_unchanged'],'binary_sha256':report.get('compile_binary_sha256')},indent=2))
    return 0 if report['status'].startswith('PASS') else 1
if __name__=='__main__':raise SystemExit(main())
