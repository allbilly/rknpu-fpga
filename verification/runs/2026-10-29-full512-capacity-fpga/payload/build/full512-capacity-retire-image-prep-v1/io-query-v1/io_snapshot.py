#!/usr/bin/env python3
"""Strictly bind native full512 routed-port facts to the old physical pin spec."""
import argparse
import hashlib
import json
from pathlib import Path

PORT_PROPERTIES=('PACKAGE_PIN','IOSTANDARD','SLEW','DRIVE','PULLTYPE','DIFF_TERM','IN_TERM','DIRECTION')
QUERY_STATUS='PASS_NATIVE_READ_ONLY_FULL512_ROUTE_IO_QUERY'
ROUTE_STATUS='PASS_ROOT_FULL512_RETIRE_ROUTE_TIMING'
OLD_STATUS='PASS_READONLY_ROUTED_IO_FACTS_COLLECTED'

class SnapshotError(ValueError):pass

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def need(ok,message):
    if not ok:raise SnapshotError(message)

def unescape(value):
    result=[];i=0
    while i<len(value):
        if value[i]=='\\' and i+1<len(value):
            i+=1;result.append({'t':'\t','n':'\n','r':'\r','\\':'\\'}.get(value[i],'\\'+value[i]))
        else:result.append(value[i])
        i+=1
    return ''.join(result)

def parse_facts(path):
    headers={'DESIGN':[],'DCP':[],'PORT_COUNT':[],'SNAPSHOT_COMPLETE':[]};rows={};indices={};observed=0
    for line_number,line in enumerate(Path(path).read_text().splitlines(),1):
        fields=[unescape(x) for x in line.split('\t')]
        if not fields or fields[0] not in {*headers,'PORT'}:raise SnapshotError(f'unknown facts row at line {line_number}')
        if fields[0] in headers:
            headers[fields[0]].append(fields);continue
        if len(fields)!=5:raise SnapshotError(f'malformed PORT property row at line {line_number}')
        _,index_text,name,key,value=fields
        try:index=int(index_text)
        except ValueError as error:raise SnapshotError(f'invalid port index at line {line_number}') from error
        if key not in PORT_PROPERTIES:raise SnapshotError(f'unexpected port property {key}')
        if index in indices and indices[index]!=name:raise SnapshotError(f'duplicate port index {index}')
        if name in rows and rows[name]['index']!=index:raise SnapshotError(f'duplicate port name {name}')
        indices[index]=name;row=rows.setdefault(name,{'index':index,'properties':{}})
        if key in row['properties']:raise SnapshotError(f'duplicate property {name}.{key}')
        row['properties'][key]=value;observed+=1
    for key in headers:need(len(headers[key])==1,f'exactly one {key} header required')
    design=headers['DESIGN'][0];dcp=headers['DCP'][0]
    need(len(design)==6 and design[1] in {'ypcb_ddr_dual_top','checkpoint_post_route'} and
         design[2:]==['ypcb_ddr_dual_top','xc7k480tffg1156-2','1.8','GND'],
         'wrong routed design/top/part/config properties')
    need(len(dcp)==3,'malformed DCP header')
    need(len(headers['PORT_COUNT'][0])==2 and int(headers['PORT_COUNT'][0][1])==242,'wrong PORT_COUNT')
    need(len(headers['SNAPSHOT_COMPLETE'][0])==2 and int(headers['SNAPSHOT_COMPLETE'][0][1])==242,'wrong snapshot completion count')
    need(len(rows)==242 and observed==242*8 and sorted(indices)==list(range(242)),'port rows must be unique indices0..241 with1936 properties')
    for name,row in rows.items():
        need(set(row['properties'])==set(PORT_PROPERTIES),f'incomplete eight-property vector for {name}')
        need(row['properties']['DIRECTION'] in {'IN','OUT','INOUT'},f'bad direction for {name}')
        need(not any(v.startswith('<UNAVAILABLE:') for v in row['properties'].values()),f'unavailable property for {name}')
    return {'design':{'name':design[1],'top':design[2],'part':design[3],'config_voltage':design[4],'cfgbvs':design[5]},
            'dcp':{'path':dcp[1],'sha256':dcp[2]},'port_count':242,'property_count':observed,
            'ports':{name:rows[name]['properties'] for name in sorted(rows)}}

def parse_old_pin_contract(path):
    rows={}
    for line_number,line in enumerate(Path(path).read_text().splitlines(),1):
        fields=line.split('\t')
        if not fields or fields[0]!='PORT':continue
        need(len(fields)==12,f'bad old pin specification row {line_number}')
        _,idx,name,direction,pin,bank,iostandard,slew,drive,pulltype,diff_term,in_term=fields
        need(name not in rows,'duplicate name in old pin specification')
        rows[name]={'PACKAGE_PIN':pin,'IOSTANDARD':iostandard,'SLEW':slew,'DRIVE':drive,
                    'PULLTYPE':pulltype,'DIFF_TERM':diff_term,'IN_TERM':in_term,'DIRECTION':direction}
    need(len(rows)==242,'old pin specification must contain242 unique ports')
    return rows

def build_snapshot(args):
    facts=Path(args.facts).resolve();properties=Path(args.properties).resolve();ports_tcl=Path(args.ports_tcl).resolve();report_io=Path(args.report_io).resolve()
    query_path=Path(args.query_report).resolve();route_review_path=Path(args.route_review).resolve();dcp_path=Path(args.expected_dcp).resolve()
    old_facts=Path(args.old_facts).resolve();old_comp_path=Path(args.old_comparison).resolve()
    query=json.loads(query_path.read_text());review=json.loads(route_review_path.read_text());oldcomp=json.loads(old_comp_path.read_text())
    need(sha(query_path)==args.query_report_sha256,'native query report hash mismatch')
    need(query.get('status')==QUERY_STATUS and query.get('returncode')==0 and query.get('stdout_marker_count')==1,
         'native query requires rc0 and one standalone PASS marker')
    need(query.get('dcp_path')==str(dcp_path) and query.get('dcp_sha256')==args.expected_dcp_sha256,
         'native query report bound to wrong DCP')
    need(review.get('status')==ROUTE_STATUS and review.get('post_route_dcp_sha256')==args.expected_dcp_sha256,
         'independent route review does not pass/bind this DCP')
    need(query.get('route_review_sha256')==sha(route_review_path),'native query receipt does not bind route review JSON')
    need(review.get('sha256') in {None,query.get('route_review_sha256')},'route-review receipt hash disagreement')
    need(oldcomp.get('status')==OLD_STATUS and oldcomp.get('port_count')==242 and not oldcomp.get('mismatches') and
         not oldcomp.get('unknown_actual_properties'),'old routed EW pin specification review is not clean')
    for name,path,digest in [('facts',facts,query.get('facts_sha256')),('properties',properties,query.get('properties_sha256')),
                             ('ports_tcl',ports_tcl,query.get('ports_tcl_sha256')),('report_io',report_io,query.get('report_io_sha256'))]:
        need(path.is_file() and sha(path)==digest,f'native query output {name} missing or hash mismatch')
    need(dcp_path.is_file() and sha(dcp_path)==args.expected_dcp_sha256,'bound routed DCP missing/changed')
    need(old_facts.is_file() and sha(old_facts)==args.old_facts_sha256,'old physical pin facts hash mismatch')
    need(old_comp_path.is_file() and sha(old_comp_path)==args.old_comparison_sha256,'old physical pin comparison hash mismatch')
    old_sources=oldcomp.get('source_inputs',{})
    expected_board=old_sources.get('board_xdc',{}).get('sha256');expected_mig=old_sources.get('original_mig_xdc',{}).get('sha256')
    board=Path(args.current_board_xdc).resolve();mig=Path(args.current_mig_xdc).resolve()
    need(expected_board and sha(board)==expected_board,'current full512 board XDC differs from old physical pin spec source')
    need(expected_mig and sha(mig)==expected_mig,'current full512 MIG XDC differs from old physical pin spec source')
    snap=parse_facts(facts)
    need(snap['dcp']=={'path':str(dcp_path),'sha256':args.expected_dcp_sha256},'facts TSV names another routed checkpoint')
    expected=parse_old_pin_contract(old_facts);actual=snap['ports']
    need(set(actual)==set(expected),'full512 routed port-name set differs from old pin spec')
    mismatches=[]
    for name in sorted(actual):
        for prop in PORT_PROPERTIES:
            if actual[name][prop]!=expected[name][prop]:mismatches.append({'port':name,'property':prop,'actual':actual[name][prop],'physical_pin_spec':expected[name][prop]})
    need(not mismatches,'routed full512 port properties differ from old EW physical pin specification')
    return {'schema':'full512-routed-io-property-snapshot-v2','status':'PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT',
      'scope':'actual full512 post-route DCP properties matched against old EW physical pin specification; not proof of electrical/PHY training or RTL equivalence',
      **snap,'property_names':list(PORT_PROPERTIES),'old_pin_spec':{'facts_path':str(old_facts),'facts_sha256':args.old_facts_sha256,
       'comparison_path':str(old_comp_path),'comparison_sha256':args.old_comparison_sha256,'status':oldcomp['status'],'matched_ports':242,'compared_properties':1936,'mismatch_count':0,
       'board_xdc_sha256':expected_board,'mig_xdc_sha256':expected_mig},
      'native_query':{'report_path':str(query_path),'report_sha256':args.query_report_sha256,'status':query['status'],'returncode':0,'stdout_marker_count':1},
      'route_review':{'path':str(route_review_path),'path_sha256':sha(route_review_path),'status':review['status'],'post_route_dcp_sha256':review['post_route_dcp_sha256']},
      'artifacts':{k:{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for k,p in {'facts':facts,'properties':properties,'ports_tcl':ports_tcl,'report_io':report_io,'query_report':query_path,'route_review':route_review_path,'dcp':dcp_path}.items()}}

def main():
    parser=argparse.ArgumentParser()
    for option in ['facts','properties','ports-tcl','report-io','query-report','query-report-sha256','route-review','expected-dcp','expected-dcp-sha256','old-facts','old-facts-sha256','old-comparison','old-comparison-sha256','current-board-xdc','current-mig-xdc','out']:
        parser.add_argument('--'+option,required=True)
    args=parser.parse_args();result=build_snapshot(args);Path(args.out).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'ports':242,'properties':1936,'mismatches':0,'dcp_sha256':result['dcp']['sha256'],'out':str(Path(args.out).resolve())}))
if __name__=='__main__':raise SystemExit(main())
