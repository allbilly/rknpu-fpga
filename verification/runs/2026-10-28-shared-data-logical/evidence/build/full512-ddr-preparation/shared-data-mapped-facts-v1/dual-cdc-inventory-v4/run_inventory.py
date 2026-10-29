#!/usr/bin/env python3
"""Read-only hash-bound Vivado query of the exact shared-data post-synth DCP."""
import hashlib,json,os,signal,subprocess,time
from pathlib import Path
ROOT=Path('/home/fedora/rknpu-fpga')
BASE=ROOT/'build/full512-ddr-preparation/combined-shared-data-full-synth-v1'
DCP=BASE/'post_synth.dcp';PRODUCER=BASE/'report.json';REVIEW=BASE/'root-resource-review-v1.json'
SOURCE_PREP=ROOT/'build/full512-ddr-preparation/combined-shared-data-source-v1/preparation.json'
CONSTRAINED_PREP=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v3/preparation.json'
PKG=Path(__file__).resolve().parent
OUT=PKG/'output';TCL=PKG/'inventory.tcl'
CONSTRAINED_SOURCE=CONSTRAINED_PREP.parent/'source'
HELPERS=[ROOT/'build/full512-ddr-preparation/dual-cdc-source-v3/job_cdc.tcl',ROOT/'build/full512-ddr-preparation/dual-cdc-source-v3/status_cdc.tcl',ROOT/'build/full512-ddr-preparation/dual-cdc-source-v3/permit_cdc.tcl',CONSTRAINED_SOURCE/'constraint-helpers/board_reset.tcl',CONSTRAINED_SOURCE/'constraint-helpers/memory_crossing.tcl']
HELPER_PREP=ROOT/'build/full512-ddr-preparation/dual-cdc-source-v3/preparation.json'
EXPECTED_DCP='1c9f4ba4eb12266ae9339416cfe90b4fa75afb0573493d077a2909e5ab46c076'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def exe(name):return Path(subprocess.run(['which',name],capture_output=True,text=True,timeout=10,check=True).stdout.strip()).resolve()
def run(argv,timeout):
    start=time.time();p=subprocess.Popen(argv,cwd=OUT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    try:stdout,stderr=p.communicate(timeout=timeout);rc=p.returncode;timedout=False
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGTERM)
        try:stdout,stderr=p.communicate(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);stdout,stderr=p.communicate()
        rc=p.returncode;timedout=True
    return {'argv':[str(x) for x in argv],'returncode':rc,'timeout':timedout,'timeout_seconds':timeout,
            'elapsed_seconds':round(time.time()-start,3),'stdout':stdout,'stderr':stderr}
def main():
    report_path=OUT/'report.json'
    if OUT.exists():raise SystemExit('query output already exists')
    producer=json.loads(PRODUCER.read_text());review=json.loads(REVIEW.read_text())
    if producer['status']!='PASS_SHARED_DATA_FULL512_SYNTHESIS_ONLY_REQUIRES_RESOURCE_REVIEW':raise SystemExit('producer synthesis status changed')
    if review['status']!='NOMINAL_SHARED_DATA_SYNTHESIS_LUT_FIT_REQUIRES_FRESH_FUNCTIONAL_CDC_AND_ROUTE_QUALIFICATION':raise SystemExit('resource review status changed')
    if review['post_synth_dcp_sha256']!=EXPECTED_DCP or sha(DCP)!=EXPECTED_DCP:raise SystemExit('post-synth DCP does not match pinned target')
    if sha(SOURCE_PREP)!=producer['source_preparation_sha256']:raise SystemExit('source preparation binding changed')
    inputs=dict(producer['source_inputs'])
    for p,h in inputs.items():
        if sha(p)!=h:raise SystemExit('source input changed before query: '+p)
    vivado=exe('vivado')
    if '2026.1' not in str(vivado):raise SystemExit('unexpected Vivado installation path')
    cgrp=Path('/sys/fs/cgroup')/next(x.split('::',1)[1].strip().lstrip('/') for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
    limits={k:(cgrp/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
    expected_limits={'memory.max':'6442450944','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'}
    if limits!=expected_limits:raise SystemExit('read-only query cgroup limits mismatch: '+repr(limits))
    copied_source_hashes={}
    constrained_prep=json.loads(CONSTRAINED_PREP.read_text())
    for row in constrained_prep['files']:
        copy_path=CONSTRAINED_SOURCE/row['relative_path']
        copied_source_hashes[str(copy_path)]=row['copy_sha256']
        if sha(copy_path)!=row['copy_sha256']:raise SystemExit('constrained helper/source copy hash mismatch: '+str(copy_path))
    tracked={**inputs,**copied_source_hashes,str(PRODUCER):sha(PRODUCER),str(REVIEW):sha(REVIEW),str(SOURCE_PREP):sha(SOURCE_PREP),
             str(CONSTRAINED_PREP):sha(CONSTRAINED_PREP),
             str(DCP):sha(DCP),str(TCL):sha(TCL),str(Path(__file__).resolve()):sha(__file__),str(vivado):sha(vivado),str(HELPER_PREP):sha(HELPER_PREP),**{str(h):sha(h) for h in HELPERS}}
    before={p:sha(p) for p in tracked}
    if any(before[p]!=h for p,h in tracked.items()):raise SystemExit('bound query input hash mismatch')
    OUT.mkdir(parents=True)
    version=run([str(vivado),'-version'],30)
    argv=[str(vivado),'-mode','batch','-source',str(TCL),'-log',str(OUT/'vivado.log'),'-journal',str(OUT/'vivado.jou')]
    result=run(argv,240)
    stdout_path=OUT/'stdout.log';stderr_path=OUT/'stderr.log'
    stdout_path.write_text(result['stdout']);stderr_path.write_text(result['stderr'])
    facts=OUT/'inventory-facts.txt';facts_text=facts.read_text() if facts.exists() else ''
    after={p:sha(p) for p in tracked}
    report={'status':'RUNNING','scope':'read_checkpoint-only inventory through v3 job/status/permit and old board-reset/memory helpers; no constraints/exceptions, design mutation, timing closure, implementation or hardware qualification',
      'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'dcp_path':str(DCP),'dcp_sha256':sha(DCP),
      'expected_dcp_sha256':EXPECTED_DCP,'producer_report':str(PRODUCER),'producer_report_sha256':sha(PRODUCER),
      'resource_review':str(REVIEW),'resource_review_sha256':sha(REVIEW),'source_preparation':str(SOURCE_PREP),
      'source_preparation_sha256':sha(SOURCE_PREP),'constrained_preparation':str(CONSTRAINED_PREP),'constrained_preparation_sha256':sha(CONSTRAINED_PREP),
      'constrained_copied_source_count':len(copied_source_hashes),'helper_preparation':str(HELPER_PREP),'helper_preparation_sha256':sha(HELPER_PREP),
      'source_input_count':len(inputs),'source_inputs':inputs,'helper_sources':[str(h) for h in HELPERS],'helper_hashes_before':{str(h):before[str(h)] for h in HELPERS},
      'query_tcl':str(TCL),'query_tcl_sha256':sha(TCL),'query_runner':str(Path(__file__).resolve()),'query_runner_sha256':sha(__file__),'vivado_path':str(vivado),'vivado_sha256':sha(vivado),
      'vivado_version':version,'kernel_limits':limits,'command':result,'facts_path':str(facts),
      'facts_sha256':sha(facts) if facts.exists() else None,'facts_text':facts_text,
      'stdout_path':str(stdout_path),'stderr_path':str(stderr_path),'stdout_sha256':sha(stdout_path),'stderr_sha256':sha(stderr_path),
      'vivado_log_path':str(OUT/'vivado.log'),'vivado_log_sha256':sha(OUT/'vivado.log') if (OUT/'vivado.log').exists() else None,
      'vivado_journal_path':str(OUT/'vivado.jou'),'vivado_journal_sha256':sha(OUT/'vivado.jou') if (OUT/'vivado.jou').exists() else None,
      'input_hashes_before':before,'input_hashes_after':after,'all_inputs_unchanged':before==after,'helper_hashes_after':{str(h):after[str(h)] for h in HELPERS},
      'design_mutated':False,'hardware_accessed':False}
    report['status']='PASS_READ_ONLY_MAPPED_FACTS_CAPTURED' if result['returncode']==0 and not result['timeout'] and facts.exists() and before==after else 'FAIL_READ_ONLY_MAPPED_FACTS_QUERY'
    report['finished_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    report_path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'rc':result['returncode'],'elapsed_seconds':result['elapsed_seconds'],
      'facts_sha256':report['facts_sha256'],'all_inputs_unchanged':report['all_inputs_unchanged']},indent=2))
    return 0 if report['status'].startswith('PASS') else 1
if __name__=='__main__':raise SystemExit(main())
