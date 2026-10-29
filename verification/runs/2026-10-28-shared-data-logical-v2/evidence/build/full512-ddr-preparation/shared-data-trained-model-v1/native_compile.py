#!/usr/bin/env python3
"""Reviewed-warning native C++ build of the trained same-epoch alternation bench; no execution."""
import collections,hashlib,json,os,re,signal,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PKG=ROOT/'build/full512-ddr-preparation/shared-data-trained-model-v1'
PREP=PKG/'preparation.json';REVIEW=PKG/'frontend-root-review-v1.json'
FRONT=PKG/'frontend-v1';STRICT_LOG=FRONT/'verilator_lint.stderr.log';STRICT_REPORT=FRONT/'report.json'
WRAPPER=ROOT/'build/ddr-endpoint-async/lto-profile-one-v6/compiler-o3-lto-one.sh'
OUT=PKG/'native-compile-v1';TOP='tb_jtag_dual_ddr_async'
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
def normalize_warning(line):return line.replace(str(PKG),'$TRAINED_ALTERNATION')
def main():
    if OUT.exists():raise SystemExit('native output already exists')
    prep=json.loads(PREP.read_text());strict=json.loads(STRICT_REPORT.read_text());review=json.loads(REVIEW.read_text())
    if prep['status']!='PREPARED_UNQUALIFIED_SHARED_DATA_TRAINED_CONTROLLER_MODEL' or prep['top']!=TOP or len(prep['hdl_sources'])!=112:raise SystemExit('shared-data prep status/top/source count mismatch')
    if review['status']!='REVIEWED_EXACT_SHARED_DATA_TRAINED_FRONTEND_FOR_NATIVE_COMPILE_ONLY' or review['warning_headers_exact']!=628 or not review['compile_with_Wno_fatal_permitted']:raise SystemExit('no matching root warning review')
    if strict['status']!='FAIL_STRICT_SHARED_DATA_FRONTEND' or strict['returncode']!=1 or strict['warning_count']!=628 or strict['error_headers']:raise SystemExit('strict frontend receipt does not match reviewed 628 warning set')
    if sha(STRICT_LOG)!=review['candidate_stderr_sha256']:raise SystemExit('strict lint log hash not bound by root review')
    expected_warn=[x for x in STRICT_LOG.read_text().splitlines() if re.match(r'^%Warning-[A-Z0-9_]+:',x)]
    if len(expected_warn)!=628:raise SystemExit('strict lint warning header count mismatch')
    source_paths=set(prep['files'])|set(prep['inputs'])
    source_paths.update([str(PREP),str(REVIEW),str(STRICT_LOG),str(STRICT_REPORT),str(WRAPPER),str(Path(__file__).resolve())])
    verilator=executable('verilator');make=executable('make');cxx_launcher=executable('c++')
    actual_cxx=Path('/usr/bin/c++').resolve();linker=Path('/usr/bin/ld').resolve()
    source_paths.update([str(verilator),str(make),str(cxx_launcher),str(actual_cxx),str(linker)])
    before={p:sha(p) for p in sorted(source_paths)}
    if any(before[p]!=h for p,h in prep['files'].items()):raise SystemExit('copied source/fixture manifest mismatch')
    if any(before[p]!=h for p,h in prep['inputs'].items()):raise SystemExit('source/vector input hash mismatch')
    if any(before[x['path']]!=x['sha256'] for x in prep['hdl_sources']):raise SystemExit('selected HDL source hash mismatch')
    strict_hash=sha(STRICT_LOG)
    OUT.mkdir(parents=True)
    argv=['verilator','--cc','--exe','--main','--timing','--assert','-Wall','-Wno-fatal',
          '--output-groups','0','--output-split','5000','--output-split-cfuncs','1000','--top-module',TOP,
          '--Mdir',str(OUT/'obj')]
    for name,path in prep['headers'].items():argv.append('-D'+name+'="'+path+'"')
    argv.extend('-D'+name for name in prep['verilog_defines'])
    argv.extend(x['path'] for x in prep['hdl_sources']);argv.append(prep['bench'])
    report={'status':'RUNNING','scope':'native C++ build of the original trained-tile CMAC/EW/CMAC alternation source/model only; binary is not executed and no physical DDR/PHY qualification is claimed',
      'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'preparation_path':str(PREP),'preparation_sha256':sha(PREP),
      'root_warning_review':str(REVIEW),'root_warning_review_sha256':sha(REVIEW),'strict_frontend_report':str(STRICT_REPORT),
      'strict_frontend_log_sha256':strict_hash,'selected_hdl_count':len(prep['hdl_sources']),'top':TOP,
      'expected_alternation_counts':prep['expected'],'headers':prep['headers'],'defines':prep['verilog_defines'],
      'expected_warning_headers':expected_warn,'source_hashes_before':before,
      'resource_scope':{'MemoryMax':'8G','MemorySwapMax':'0','CPUQuota':'200%','TasksMax':256,'total_timeout_seconds':1800},
      'tool_versions':{},'commands':[],'binary_executed':False,'hardware_accessed':False}
    cg=Path('/sys/fs/cgroup')/next(line.split('::',1)[1].strip().lstrip('/') for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::'))
    kernel_limits={name:(cg/name).read_text().strip() for name in ('memory.max','memory.swap.max','cpu.max','pids.max')}
    required_limits={'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'}
    if kernel_limits!=required_limits:raise SystemExit(f'wrong native compile cgroup limits: {kernel_limits}')
    for label,cmd in [('verilator_version',[str(verilator),'--version']),('make_version',[str(make),'--version']),
                      ('cxx_launcher_version',[str(cxx_launcher),'--version']),('actual_cxx_version',[str(actual_cxx),'--version']),
                      ('linker_version',[str(linker),'--version'])]:
        report['tool_versions'][label]=run(cmd,label,30)
    report['kernel_cgroup']={'path':str(cg),'limits':kernel_limits}
    lint_start=time.monotonic();lint=run(argv,'verilator_codegen',300);report['commands'].append(lint)
    actual_warn=[x for x in lint['stderr'].splitlines() if re.match(r'^%Warning-[A-Z0-9_]+:',x)]
    normalized_actual=[normalize_warning(x) for x in actual_warn]
    normalized_expected=[normalize_warning(x) for x in expected_warn]
    report['warning_comparison']={'expected_count':len(expected_warn),'actual_count':len(actual_warn),
      'expected_counter':dict(sorted(collections.Counter(re.match(r'^%Warning-([A-Z0-9_]+):',x).group(1) for x in expected_warn).items())),
      'actual_counter':dict(sorted(collections.Counter(re.match(r'^%Warning-([A-Z0-9_]+):',x).group(1) for x in actual_warn).items())),
      'normalized_headers_exact':normalized_actual==normalized_expected,
      'error_headers':re.findall(r'(?m)^%Error-[A-Z0-9_]+:',lint['stderr'])}
    report['commands'][-1]['warning_headers']=actual_warn
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    can_make=(lint['returncode']==0 and not lint['timeout'] and report['warning_comparison']['normalized_headers_exact'] and not report['warning_comparison']['error_headers'])
    if can_make:
        obj=OUT/'obj';mk=obj/f'V{TOP}.mk';elapsed=time.monotonic()-lint_start;remaining=max(1,int(1800-elapsed))
        make_argv=[str(make),'-j1','-C',str(obj),'-f',str(mk),f'CXX={WRAPPER}',f'LINK={WRAPPER}']
        build=run(make_argv,'make_cpp_link',remaining);report['commands'].append(build)
        binary=obj/f'V{TOP}';report['binary_path']=str(binary);report['binary_exists']=binary.is_file()
        report['binary_sha256']=sha(binary) if binary.is_file() else None
        report['binary_bytes']=binary.stat().st_size if binary.is_file() else None
        report['wrapper_sha256_after']=sha(WRAPPER)
    else:report['make_skipped_reason']='strict warning header mismatch/error/timeout; C++ phase not launched'
    after={p:sha(p) for p in sorted(source_paths)};report['source_hashes_after']=after
    report['source_hashes_unchanged']=before==after
    report['preparation_hash_unchanged']=sha(PREP)==report['preparation_sha256']
    report['compile_manifest_hashes_unchanged']=all(after[p]==h for p,h in prep['files'].items()) and all(after[p]==h for p,h in prep['inputs'].items())
    success=(can_make and report['commands'][-1]['returncode']==0 and report['binary_exists'] and report['source_hashes_unchanged'] and report['compile_manifest_hashes_unchanged'])
    report['status']='PASS_TRAINED_ALTERNATION_NATIVE_COMPILE_ONLY' if success else 'FAIL_TRAINED_ALTERNATION_NATIVE_COMPILE'
    report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'warning_count':report['warning_comparison']['actual_count'],
       'warnings_exact':report['warning_comparison']['normalized_headers_exact'],'commands':[(x['argv'][0],x['returncode'],x['elapsed_seconds']) for x in report['commands']],
       'binary_sha256':report.get('binary_sha256'),'source_hashes_unchanged':report['source_hashes_unchanged']},indent=2))
    return 0 if success else 1
if __name__=='__main__':raise SystemExit(main())
