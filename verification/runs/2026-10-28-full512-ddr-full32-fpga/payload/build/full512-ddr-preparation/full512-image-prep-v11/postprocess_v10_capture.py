#!/usr/bin/env python3
"""Offline postprocessing of the immutable v10 successful native query capture."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path

ROOT=Path('/home/fedora/rknpu-fpga')
V10=ROOT/'build/full512-ddr-preparation/full512-image-prep-v10'
V11=Path(__file__).resolve().parent
NATIVE=V10/'io-snapshot/native-output'
PARENT_REPORT=V10/'io-snapshot/query-report.json'
ROUTE=ROOT/'build/full512-ddr-preparation/strict-route-requalification-v1'
OLD=ROOT/'build/ypcb-ddr-shell/ch1-routed-io-review-v1'
SOURCE=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v4/source'
OUTPUT=V11/'io-snapshot/full512-io-snapshot.json'
RECEIPT=V11/'postprocessing-receipt.json'

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    import io_snapshot
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    query=NATIVE/'query-report.json';facts=NATIVE/'full512-io-facts.tsv';properties=NATIVE/'full512-properties.txt'
    ports=NATIVE/'full512-ports.tcl';report_io=NATIVE/'full512-route-report-io.rpt'
    route_review=ROUTE/'root-route-review.json';dcp=ROUTE/'output/post_route.dcp'
    old_facts=OLD/'facts.tsv';old_comparison=OLD/'comparison.json'
    files=[PARENT_REPORT,query,facts,properties,ports,report_io,NATIVE/'stdout.log',NATIVE/'stderr.log',
           NATIVE/'vivado.log',NATIVE/'vivado.jou',NATIVE/'full512-route-clocks.rpt',
           V10/'run_io_query.py',V10/'io_query.tcl',V10/'io_snapshot.py',V11/'io_snapshot.py',
           route_review,dcp,old_facts,old_comparison,SOURCE/'board.xdc',SOURCE/'mig-original.xdc']
    before={str(p):sha(p) for p in files}
    parent=json.loads(PARENT_REPORT.read_text());native=json.loads(query.read_text())
    if parent.get('status')!='FAIL_READ_ONLY_FULL512_IO_QUERY' or parent.get('pid') is None or parent.get('returncode')!=0:
        raise ValueError('v10 outer postchecker failure receipt is not the expected preserved native-success failure')
    if native.get('status')!='PASS_NATIVE_READ_ONLY_FULL512_ROUTE_IO_QUERY' or native.get('returncode')!=0 or native.get('stdout_marker_count')!=1:
        raise ValueError('v10 inner native query is not rc0 with exactly one PASS marker')
    args=argparse.Namespace(facts=facts,properties=properties,ports_tcl=ports,report_io=report_io,
        query_report=query,query_report_sha256=sha(query),route_review=route_review,expected_dcp=dcp,
        expected_dcp_sha256=sha(dcp),old_facts=old_facts,old_facts_sha256=sha(old_facts),
        old_comparison=old_comparison,old_comparison_sha256=sha(old_comparison),
        current_board_xdc=SOURCE/'board.xdc',current_mig_xdc=SOURCE/'mig-original.xdc')
    snapshot=io_snapshot.build_snapshot(args)
    OUTPUT.write_text(json.dumps(snapshot,indent=2)+'\n')
    after={str(p):sha(p) for p in files}
    artifacts={str(p):{'sha256':sha(p),'bytes':p.stat().st_size} for p in files if p.parent==NATIVE}
    receipt={
        'status':'PASS_OFFLINE_POSTPROCESSING_OF_V10_NATIVE_CAPTURE',
        'scope':'offline parsing/comparison only; no Vivado rerun, no hardware access',
        'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'started_utc':started,
        'preserved_v10_outer_status':parent['status'],
        'preserved_v10_outer_error':parent.get('error'),
        'v10_native_returncode':native['returncode'],'v10_native_status':native['status'],
        'v10_native_stdout_marker_count':native['stdout_marker_count'],
        'v10_outer_report_path':str(PARENT_REPORT),'v10_outer_report_sha256':before[str(PARENT_REPORT)],
        'native_artifact_paths_and_hashes':artifacts,
        'old_parser_path':str(V10/'io_snapshot.py'),'old_parser_sha256':before[str(V10/'io_snapshot.py')],
        'new_parser_path':str(V11/'io_snapshot.py'),'new_parser_sha256':before[str(V11/'io_snapshot.py')],
        'input_hashes_before':before,'input_hashes_after':after,'all_inputs_unchanged':before==after,
        'snapshot_path':str(OUTPUT),'snapshot_sha256':sha(OUTPUT),
        'ports':snapshot['port_count'],'properties':snapshot['property_count'],
        'mismatch_count':snapshot['old_pin_spec']['mismatch_count'],
        'native_execution_reused':True,'vivado_executed':False,'hardware_accessed':False,
    }
    if before!=after:receipt['status']='FAIL_OFFLINE_POSTPROCESSING_INPUT_MUTATION'
    RECEIPT.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':receipt['status'],'ports':receipt['ports'],'properties':receipt['properties'],
        'mismatches':receipt['mismatch_count'],'snapshot_sha256':receipt['snapshot_sha256'],'receipt':str(RECEIPT)}))
    return 0 if receipt['status'].startswith('PASS_') else 1

if __name__=='__main__':raise SystemExit(main())
