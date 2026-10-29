#!/usr/bin/env python3
"""Bounded read-only query of a root-reviewed full512 post-route DCP."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time

ROOT=Path('/home/fedora/rknpu-fpga');BASE=Path(__file__).resolve().parent
PREP_PATH=BASE/'image-preparation.json';RUNNER=Path(__file__).resolve();OUT=BASE/'io-snapshot'
REPORT=OUT/'query-report.json';QUERY_TCL=BASE/'io_query.tcl';PARSER=BASE/'io_snapshot.py'
VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
OLD=ROOT/'build/ypcb-ddr-shell/ch1-routed-io-review-v1'
SOURCE=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v4'
CHILD=None;SIGNAL_SEEN=None;RECORD=None

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def require(ok,msg):
    if not ok:raise ValueError(msg)
def save():REPORT.write_text(json.dumps(RECORD,indent=2)+'\n')
def cgroup_dir():
    rel=next(x[3:] for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::')).lstrip('/')
    return Path('/sys/fs/cgroup')/rel
def group_pids(pgid):
    pids=[]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            f=(entry/'stat').read_text().rsplit(')',1)[1].split()
            if int(f[2])==pgid and f[0] not in {'Z','X'}:pids.append(int(entry.name))
        except (FileNotFoundError,ProcessLookupError,ValueError,IndexError):pass
    return sorted(pids)
def kill_owned(sig):
    global CHILD
    if CHILD is None:return
    try:os.killpg(CHILD.pid,sig)
    except ProcessLookupError:pass
    try:CHILD.wait(timeout=8)
    except subprocess.TimeoutExpired:pass
    if group_pids(CHILD.pid):
        try:os.killpg(CHILD.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        if CHILD.poll() is None:CHILD.wait()

def enforce_stopped_group(record,pgid,members=group_pids,terminator=kill_owned):
    live=members(pgid)
    if live:
        record['owned_pids_before_cleanup']=live
        terminator(signal.SIGTERM)
        live=members(pgid)
    record['owned_process_group_stopped']=not bool(live)
    if live:
        record['owned_pids_after_cleanup']=live
        if str(record.get('status','')).startswith('PASS_'):
            record['status']='FAIL_OWNED_PROCESS_GROUP_LINGERED'
        return False
    return True

def finalize_input_hashes(record,hasher=None):
    hasher=hasher or sha
    if 'input_hashes_before' not in record:return True
    try:
        after={p:hasher(p) for p in record['input_hashes_before']}
        record['input_hashes_after']=after
        record['all_inputs_unchanged']=(after==record['input_hashes_before']==record['input_hashes_expected'])
        if not record['all_inputs_unchanged'] and str(record.get('status','')).startswith('PASS_'):
            record['status']='FAIL_INPUT_MUTATION_AFTER_QUERY'
        return record['all_inputs_unchanged']
    except BaseException as error:
        record['input_rehash_error']=repr(error);record['all_inputs_unchanged']=False
        if str(record.get('status','')).startswith('PASS_'):record['status']='FAIL_INPUT_REHASH_AFTER_QUERY'
        return False
def handle_signal(sig,frame):
    global SIGNAL_SEEN
    SIGNAL_SEEN=sig;raise InterruptedError('read-only route-I/O query interrupted '+str(sig))
def check_inputs(expected):
    actual={p:sha(p) for p in expected}
    require(actual==expected,'read-only I/O query input hash mismatch')
    return actual

def comparison_source_sha256(comparison,name):
    source=comparison.get('source_inputs',{}).get(name)
    require(isinstance(source,dict) and isinstance(source.get('path'),str) and source['path'] and
            isinstance(source.get('preserved_copy'),str) and source['preserved_copy'] and
            isinstance(source.get('sha256'),str) and re.fullmatch(r'[0-9a-f]{64}',source['sha256']) is not None,
            'Malformed nested source binding in old physical pin-spec comparison: '+name)
    return source['sha256']

def spawn_query(argv,env,stdout,stderr,oldmask,popen=subprocess.Popen):
    require(OUT.joinpath('native-output').is_dir(),'Native I/O query output directory must exist before spawn')
    require(not (OUT/'native-output/full512-io-facts.tsv').exists(),'Native I/O query outputs must be fresh')
    return popen(argv,cwd=OUT.joinpath('native-output'),env=env,stdout=stdout,stderr=stderr,start_new_session=True,
                 preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,oldmask))

def main():
    global CHILD,SIGNAL_SEEN,RECORD
    started=time.monotonic();RECORD={'status':'PREFLIGHT','scope':'read-only full512 post-route DCP 242-port query and old physical pin-spec comparison; no constraints/implementation/hardware','hardware_accessed':False,'design_mutated':False}
    require(not REPORT.exists(),'Fresh full512 I/O query required')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,handle_signal)
    try:
        manifest=json.loads(PREP_PATH.read_text());route=manifest['route_gate']
        require(route.get('report_sha256') and route.get('review_path') and route.get('review_sha256') and route.get('post_route_dcp_sha256'),
                'UNLAUNCHABLE: route report/review/DCP hash bindings are pending')
        dcp=Path(route['post_route_dcp_path']);route_report=Path(route['route_report_path']);review=Path(route['review_path'])
        require(dcp.is_file() and route_report.is_file() and review.is_file(),'Bound route inputs unavailable')
        require(sha(dcp)==route['post_route_dcp_sha256'],'Post-route DCP hash mismatch')
        require(sha(route_report)==route['report_sha256'],'Route report hash mismatch')
        require(sha(review)==route['review_sha256'],'Independent root review hash mismatch')
        route_data=json.loads(route_report.read_text());review_data=json.loads(review.read_text())
        require(route_data.get('status')==route['required_report_status'] and route_data.get('returncode')==0 and
                route_data.get('output_hashes',{}).get('post_route.dcp')==sha(dcp),'Repair route report is not terminal and DCP-bound')
        require(review_data.get('status')==route['independent_route_review_status'] and
                review_data.get('post_route_dcp_sha256')==sha(dcp),'Independent route review not passed or DCP-bound')
        oldfacts=OLD/'facts.tsv';oldcmp=OLD/'comparison.json';oldproperties=OLD/'properties.txt';oldio=OLD/'report_io.rpt'
        oldcomp=json.loads(oldcmp.read_text())
        require(oldcomp.get('status')=='PASS_READONLY_ROUTED_IO_FACTS_COLLECTED' and oldcomp.get('port_count')==242 and
                not oldcomp.get('mismatches') and not oldcomp.get('unknown_actual_properties'),'Old pin-spec reference is not clean')
        require(sha(SOURCE/'source/board.xdc')==comparison_source_sha256(oldcomp,'board_xdc') and
                sha(SOURCE/'source/mig-original.xdc')==comparison_source_sha256(oldcomp,'original_mig_xdc'),'Full512 XDC sources changed from reviewed physical pin spec')
        expected=dict(manifest['source_inputs'])
        expected.update({str(dcp):route['post_route_dcp_sha256'],str(route_report):route['report_sha256'],str(review):route['review_sha256'],
                         str(PREP_PATH):sha(PREP_PATH),str(QUERY_TCL):sha(QUERY_TCL),str(PARSER):sha(PARSER),str(RUNNER):manifest['source_inputs'][str(RUNNER)],str(VIVADO):manifest['vivado_sha256'],
                         str(oldfacts):sha(oldfacts),str(oldcmp):sha(oldcmp),str(oldproperties):sha(oldproperties),str(oldio):sha(oldio),
                         str(SOURCE/'source/board.xdc'):sha(SOURCE/'source/board.xdc'),str(SOURCE/'source/mig-original.xdc'):sha(SOURCE/'source/mig-original.xdc')})
        before=check_inputs(expected)
        group=cgroup_dir();limits={k:(group/k).read_text().strip() for k in ('memory.max','memory.swap.max','cpu.max','pids.max')}
        require(limits=={'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'100000 100000','pids.max':'128'},'Wrong I/O query cgroup limits')
        available=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M)[1])
        mempsi=Path('/proc/pressure/memory').read_text();cpupsi=Path('/proc/pressure/cpu').read_text()
        require(available>=12582912 and float(re.search(r'^full avg10=([0-9.]+)',mempsi,re.M)[1])<1 and
                float(re.search(r'^some avg10=([0-9.]+)',cpupsi,re.M)[1])<5,'I/O query host admission failed')
        native=OUT/'native-output';require(not native.exists(),'Fresh native query directory required');native.mkdir()
        version=subprocess.run([str(VIVADO),'-version'],capture_output=True,text=True,timeout=30,check=True)
        argv=[str(VIVADO),'-mode','batch','-source',str(QUERY_TCL),'-log',str(native/'vivado.log'),'-journal',str(native/'vivado.jou')]
        RECORD.update(status='RUNNING',argv=argv,pid=None,pgid=None,dcp_path=str(dcp),dcp_sha256=sha(dcp),route_review_path=str(review),
                      route_review_sha256=sha(review),route_report_path=str(route_report),route_report_sha256=sha(route_report),input_hashes_expected=expected,
                      input_hashes_before=before,kernel_limits=limits,initial_available_kib=available,memory_psi=mempsi,cpu_psi=cpupsi,
                      vivado_path=str(VIVADO),vivado_sha256=sha(VIVADO),vivado_version=version.stdout,timeout_seconds=600)
        save()
        with (native/'stdout.log').open('x') as stdout,(native/'stderr.log').open('x') as stderr:
            maskset={signal.SIGINT,signal.SIGTERM,signal.SIGHUP};oldmask=signal.pthread_sigmask(signal.SIG_BLOCK,maskset)
            try:
                CHILD=spawn_query(argv,dict(os.environ,RK_FULL512_ROUTE_DCP=str(dcp),RK_FULL512_ROUTE_DCP_SHA256=sha(dcp)),stdout,stderr,oldmask)
                RECORD.update(pid=CHILD.pid,pgid=CHILD.pid);save()
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,oldmask)
            try:RECORD['returncode']=CHILD.wait(timeout=600)
            except subprocess.TimeoutExpired:RECORD['status']='TIMEOUT';kill_owned(signal.SIGTERM);raise TimeoutError('600s read-only I/O query timeout')
        outtext=(native/'stdout.log').read_text(errors='replace');marker='PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT'
        marker_count=sum(line.strip()==marker for line in outtext.splitlines())
        require(CHILD.returncode==0 and marker_count==1,'Native I/O query lacks rc0 and one standalone marker')
        facts=native/'full512-io-facts.tsv';properties=native/'full512-properties.txt';ports_tcl=native/'full512-ports.tcl';report_io=native/'full512-route-report-io.rpt'
        for path in (facts,properties,ports_tcl,report_io):require(path.is_file(),'Missing read-only I/O query output '+path.name)
        query_receipt={'status':'PASS_NATIVE_READ_ONLY_FULL512_ROUTE_IO_QUERY','returncode':CHILD.returncode,'stdout_marker_count':marker_count,
                       'dcp_path':str(dcp),'dcp_sha256':sha(dcp),'route_review_sha256':sha(review),'facts_sha256':sha(facts),
                       'properties_sha256':sha(properties),'ports_tcl_sha256':sha(ports_tcl),'report_io_sha256':sha(report_io)}
        query_report=native/'query-report.json';query_report.write_text(json.dumps(query_receipt,indent=2)+'\n')
        outputjson=OUT/'full512-io-snapshot.json'
        from io_snapshot import build_snapshot
        args=argparse.Namespace(facts=facts,properties=properties,ports_tcl=ports_tcl,report_io=report_io,
            query_report=query_report,query_report_sha256=sha(query_report),route_review=review,expected_dcp=dcp,
            expected_dcp_sha256=sha(dcp),old_facts=oldfacts,old_facts_sha256=sha(oldfacts),old_comparison=oldcmp,
            old_comparison_sha256=sha(oldcmp),current_board_xdc=SOURCE/'source/board.xdc',current_mig_xdc=SOURCE/'source/mig-original.xdc')
        snapshot=build_snapshot(args);snapshot_json=outputjson;snapshot_json.write_text(json.dumps(snapshot,indent=2)+'\n')
        after=check_inputs(expected)
        require(after==before,'I/O query input changed during run')
        RECORD.update(status='PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT',stdout_marker_count=marker_count,
                      query_report_path=str(query_report),query_report_sha256=sha(query_report),snapshot_path=str(snapshot_json),
                      snapshot_sha256=sha(snapshot_json),port_count=snapshot['port_count'],property_count=snapshot['property_count'],
                      old_pin_spec_mismatch_count=0,input_hashes_after=after,all_inputs_unchanged=True)
    except BaseException as error:
        if CHILD is not None and CHILD.poll() is None:kill_owned(signal.SIGTERM)
        RECORD.update(status=('TIMEOUT' if RECORD.get('status')=='TIMEOUT' else ('CANCELLED' if SIGNAL_SEEN else 'FAIL_READ_ONLY_FULL512_IO_QUERY')),
                      error=repr(error),received_signal=SIGNAL_SEEN,returncode=CHILD.returncode if CHILD is not None else None)
    finally:
        RECORD['elapsed_seconds']=time.monotonic()-started;RECORD['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        if CHILD is not None:
            enforce_stopped_group(RECORD,CHILD.pid)
        finalize_input_hashes(RECORD)
        try:
            cg=cgroup_dir();RECORD['memory_peak_bytes']=(cg/'memory.peak').read_text().strip();RECORD['memory_events']=(cg/'memory.events').read_text().strip()
        except BaseException as error:RECORD['cgroup_error']=repr(error)
        if (OUT/'native-output').exists():RECORD['native_output_hashes']={str(p.relative_to(OUT/'native-output')):sha(p) for p in (OUT/'native-output').rglob('*') if p.is_file()}
        RECORD.update(hardware_accessed=False,design_mutated=False);save()
    return 0 if RECORD['status']=='PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT' else 1

if __name__=='__main__':raise SystemExit(main())
