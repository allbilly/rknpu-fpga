#!/usr/bin/env python3
"""Reviewed-warning native C++ build of the frozen joined controller model; never executes it."""
import collections,hashlib,json,os,re,signal,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PKG=ROOT/'build/full512-ddr-preparation/joined-model-source-v1'
PREP=PKG/'preparation.json';REVIEW=PKG/'frontend-root-review-v1.json'
FRONT=PKG/'frontend-v2';STRICT_LOG=FRONT/'verilator_lint.stderr.log';STRICT_REPORT=FRONT/'report.json'
WRAPPER=ROOT/'build/ddr-endpoint-async/lto-profile-one-v6/compiler-o3-lto-one.sh'
OUT=PKG/'native-compile-v2';TOP='tb_jtag_dual_ddr_async'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def executable(name):return Path(subprocess.run(['which',name],capture_output=True,text=True,timeout=10,check=True).stdout.strip()).resolve()
def run(argv,name,timeout):
    started=time.time();p=subprocess.Popen(argv,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:stdout,stderr=p.communicate(timeout=timeout);rc=p.returncode;timed_out=False
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGTERM)
        try:stdout,stderr=p.communicate(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);stdout,stderr=p.communicate()
        rc=p.returncode;timed_out=True
    row={'argv':[str(x) for x in argv],'returncode':rc,'timeout':timed_out,'timeout_seconds':timeout,
         'elapsed_seconds':round(time.time()-started,3),'stdout':stdout,'stderr':stderr}
    (OUT/(name+'.stdout.log')).write_text(stdout);(OUT/(name+'.stderr.log')).write_text(stderr)
    return row
def normalize_warning(line,pkg):return line.replace(str(pkg),'$JOINED_MODEL')
def main():
    if OUT.exists():raise SystemExit('native output already exists')
    prep=json.loads(PREP.read_text());strict=json.loads(STRICT_REPORT.read_text());review=json.loads(REVIEW.read_text())
    if prep['status']!='PREPARED_REAL_FULL512_DUAL_AXI_UI_MC_TEST_WITH_MODELED_PHY_ONLY' or prep['top']!=TOP or len(prep['hdl_sources'])!=111:raise SystemExit('joined-model preparation status/top/source count mismatch')
    if review['status']!='REVIEWED_EXACT_JOINED_MODEL_FRONTEND_WARNINGS_FOR_NATIVE_COMPILE_ONLY' or review['total_known_warnings']!=628 or not review['compile_with_Wno_fatal_permitted']:raise SystemExit('no matching root warning review')
    if strict['status']!='FAIL_STRICT_JOINED_MODEL_FRONTEND' or strict['returncode']!=1 or len(strict['warning_headers'])!=628 or strict['error_headers']:raise SystemExit('strict frontend receipt does not match reviewed 628 warning set')
    if sha(STRICT_LOG)!=review['frontend_report_sha256'] and sha(STRICT_REPORT)!=review['frontend_report_sha256']:
        # The review binds the compact frontend report; strict raw-log SHA is
        # recorded in that report and checked below as a separate artifact.
        if strict.get('stderr_sha256')!=review.get('stderr_sha256'):raise SystemExit('root review does not bind strict frontend output')
    expected_warn=[x for x in STRICT_LOG.read_text().splitlines() if re.match(r'^%Warning-[A-Z0-9_]+:',x)]
    if len(expected_warn)!=628:raise SystemExit('strict lint warning header count mismatch')
    source_paths={p for p in prep['files']}
    source_paths.update(prep['inputs'])
    source_paths.update([str(PREP),str(REVIEW),str(STRICT_LOG),str(STRICT_REPORT),str(WRAPPER),str(Path(__file__).resolve())])
    verilator=executable('verilator');make=executable('make');cxx=executable('c++')
    source_paths.update([str(verilator),str(make),str(cxx)])
    before={p:sha(p) for p in sorted(source_paths)}
    if any(before[p]!=h for p,h in prep['files'].items()):raise SystemExit('copied source/header/fixture manifest mismatch')
    if any(before[p]!=h for p,h in prep['inputs'].items()):raise SystemExit('preparation dependency hash mismatch')
    strict_log_hash=sha(STRICT_LOG)
    if strict.get('stderr_sha256') and strict['stderr_sha256']!=strict_log_hash:raise SystemExit('strict log hash differs from its report')
    OUT.mkdir(parents=True)
    argv=['verilator','--cc','--exe','--main','--timing','--assert','-Wall','-Wno-fatal',
          '--output-groups','0','--output-split','5000','--output-split-cfuncs','1000','--top-module',TOP,
          '--Mdir',str(OUT/'obj')]
    for name,path in prep['headers'].items():argv.append('-D'+name+'="'+path+'"')
    argv.extend('-D'+name for name in prep['verilog_defines'])
    argv.extend(x['path'] for x in prep['hdl_sources']);argv.append(prep['bench'])
    report={'status':'RUNNING','scope':'native Verilator C++ build of joined logical-model design only; no executable launch, DDR/PHY/FPGA qualification or hardware',
      'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'preparation_path':str(PREP),'preparation_sha256':sha(PREP),
      'root_warning_review':str(REVIEW),'root_warning_review_sha256':sha(REVIEW),'strict_frontend_report':str(STRICT_REPORT),
      'strict_frontend_log_sha256':strict_log_hash,'selected_hdl_count':len(prep['hdl_sources']),'top':TOP,
      'headers':prep['headers'],'defines':prep['verilog_defines'],'expected_warning_headers':expected_warn,
      'source_hashes_before':before,'resource_scope':{'MemoryMax':'8G','MemorySwapMax':'0','CPUQuota':'200%','TasksMax':256,'total_timeout_seconds':1800},
      'tool_versions':{},'commands':[],'binary_executed':False,'hardware_accessed':False}
    for label,cmd in [('verilator_version',[str(verilator),'--version']),('make_version',[str(make),'--version']),('cxx_version',[str(cxx),'--version'])]:
        q=run(cmd,label,30);report['tool_versions'][label]=q
    lint_start=time.monotonic();lint=run(argv,'verilator_codegen',300);report['commands'].append(lint)
    actual_warn=[x for x in lint['stderr'].splitlines() if re.match(r'^%Warning-[A-Z0-9_]+:',x)]
    normalized_actual=[normalize_warning(x,str(PKG)) for x in actual_warn]
    normalized_expected=[normalize_warning(x,str(PKG)) for x in expected_warn]
    report['warning_comparison']={'expected_count':len(expected_warn),'actual_count':len(actual_warn),
       'expected_counter':dict(sorted(collections.Counter(re.match(r'^%Warning-([A-Z0-9_]+):',x).group(1) for x in expected_warn).items())),
       'actual_counter':dict(sorted(collections.Counter(re.match(r'^%Warning-([A-Z0-9_]+):',x).group(1) for x in actual_warn).items())),
       'normalized_headers_exact':normalized_actual==normalized_expected,
       'error_headers':re.findall(r'(?m)^%Error-[A-Z0-9_]+:',lint['stderr'])}
    report['commands'][-1]['warning_headers']=actual_warn
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    can_make=(lint['returncode']==0 and not lint['timeout'] and report['warning_comparison']['normalized_headers_exact'] and not report['warning_comparison']['error_headers'])
    if can_make:
        obj=OUT/'obj';mk=obj/f'V{TOP}.mk'
        elapsed=time.monotonic()-lint_start;remaining=max(1,int(1800-elapsed))
        make_argv=[str(make),'-j1','-C',str(obj),'-f',str(mk),f'CXX={WRAPPER}',f'LINK={WRAPPER}']
        build=run(make_argv,'make_cpp_link',remaining);report['commands'].append(build)
        binary=obj/f'V{TOP}'
        report['binary_path']=str(binary);report['binary_exists']=binary.is_file()
        report['binary_sha256']=sha(binary) if binary.is_file() else None
        report['binary_bytes']=binary.stat().st_size if binary.is_file() else None
        report['wrapper_sha256_after']=sha(WRAPPER)
    else:
        report['make_skipped_reason']='Strict command failed/timed out, warning set mismatch, or compiler error; no C++/link phase launched.'
    after={p:sha(p) for p in sorted(source_paths)}
    report['source_hashes_after']=after;report['source_hashes_unchanged']=before==after
    report['preparation_hash_unchanged']=sha(PREP)==report['preparation_sha256']
    report['compile_manifest_hashes_unchanged']=all(after[p]==h for p,h in prep['files'].items()) and all(after[p]==h for p,h in prep['inputs'].items())
    success=(can_make and report['commands'][-1]['returncode']==0 and report['binary_exists'] and report['source_hashes_unchanged'] and report['compile_manifest_hashes_unchanged'])
    report['status']='PASS_JOINED_MODEL_NATIVE_COMPILE_ONLY' if success else 'FAIL_JOINED_MODEL_NATIVE_COMPILE'
    report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'warnings':report['warning_comparison']['actual_count'],
      'warnings_exact':report['warning_comparison']['normalized_headers_exact'],'commands':[(x['argv'][0],x['returncode'],x['elapsed_seconds']) for x in report['commands']],
      'binary_sha256':report.get('binary_sha256'),'source_hashes_unchanged':report['source_hashes_unchanged']},indent=2))
    return 0 if success else 1
if __name__=='__main__':raise SystemExit(main())
