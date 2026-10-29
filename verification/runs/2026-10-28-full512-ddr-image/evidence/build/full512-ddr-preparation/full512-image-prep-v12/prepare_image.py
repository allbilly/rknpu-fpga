#!/usr/bin/env python3
"""Gate and render a source-bound full512 dual-MIG CH1 image Tcl script.

This utility is pure preparation. It never starts Vivado or accesses hardware.
"""
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path('/home/fedora/rknpu-fpga')
sys.path.insert(0,str(ROOT))
from tools.ddr.full512_image_template import HELPERS, render

ROOT=Path('/home/fedora/rknpu-fpga')
BASE=Path(__file__).resolve().parent
MANIFEST=BASE/'image-preparation.json'
RUN_BINDING=BASE/'root-bindings.json'
SOURCE_PREP=ROOT/'build/full512-ddr-preparation/shared-data-constrained-prep-v4/preparation.json'
IO_REPORT=BASE/'io-snapshot/full512-io-snapshot.json'
OUTPUT=BASE/'emission'
EMIT_TCL=BASE/'emit_full512_ch1.tcl'

class GateError(RuntimeError): pass

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def canonical_sha(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def load_json(path): return json.loads(Path(path).read_text())

def require(ok,message):
    if not ok:raise GateError(message)

def source_manifest_matches(m):
    sm=m['hardware_source_manifest']
    require(canonical_sha(sm)==m['hardware_source_sha256'],'hardware source manifest digest changed')
    require(m['source_tag']==m['hardware_source_sha256'][:8] and m['source_tag']!='00000000','source tag does not derive from manifest')
    require(len(sm['files'])==163 and m['source_copy_count']==160,'full512 source-manifest inventory changed')
    for relative,digest in sm['files'].items():
        path=ROOT/relative
        require(path.is_file() and sha(path)==digest,'source manifest input changed: '+str(path))
    for path,digest in m['source_inputs'].items():
        require(Path(path).is_file() and sha(path)==digest,'qualified full512 input missing or changed: '+path)

def collect_missing(m,b):
    missing=[]
    if m.get('status')!='READY_FOR_ROOT_REVIEWED_FULL512_DUAL_IMAGE_EMISSION':
        missing.append('preparation.status is not READY_FOR_ROOT_REVIEWED_FULL512_DUAL_IMAGE_EMISSION')
    if b.get('render_approved') is not True:
        missing.append('root preparation/render approval is absent')
    for name,gate in m['qualification_gates'].items():
        if not gate.get('path') or not gate.get('sha256') or not gate.get('required_status'):
            missing.append(name+': path/hash/status binding is pending')
            continue
        path=Path(gate['path'])
        if not path.is_file() or sha(path)!=gate['sha256']:
            missing.append(name+': bound artifact missing or changed')
            continue
        if gate.get('status_field'):
            data=load_json(path)
            if data.get(gate['status_field'])!=gate['required_status']:
                missing.append(name+': required status not met')
            if gate.get('expected_case_count') is not None:
                count_field=gate.get('count_field')
                if not count_field or data.get(count_field)!=gate['expected_case_count']:
                    missing.append(name+': expected controller case-union count is not bound/matched')
    route=m['route_gate']
    if not route.get('report_sha256') or not route.get('review_path') or not route.get('review_sha256') or not route.get('post_route_dcp_sha256'):
        missing.append('route terminal report/review/DCP binding is pending')
    elif route['route_report_path'] and Path(route['route_report_path']).is_file():
        if sha(route['route_report_path'])!=route['report_sha256']:
            missing.append('route repair report hash changed')
        report=load_json(route['route_report_path'])
        if report.get('status')!=route['required_report_status'] or report.get('returncode')!=0:
            missing.append('route repair report is not terminal PASS')
        if report.get('output_hashes',{}).get('post_route.dcp')!=route['post_route_dcp_sha256']:
            missing.append('route repair report does not bind post_route.dcp')
        if not Path(route['review_path']).is_file() or sha(route['review_path'])!=route['review_sha256']:
            missing.append('independent route/timing review missing or changed')
        else:
            review=load_json(route['review_path'])
            if review.get('status')!=route['independent_route_review_status'] or \
                    review.get('post_route_dcp_sha256')!=route['post_route_dcp_sha256']:
                missing.append('independent route/timing review does not bind and pass this post-route DCP')
    else:missing.append('route repair report path is unavailable')
    if IO_REPORT.is_file():
        io=load_json(IO_REPORT)
        if io.get('status')!='PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT':
            missing.append('full512 routed 242-port property snapshot is not PASS')
        if io.get('dcp',{}).get('sha256')!=route.get('post_route_dcp_sha256'):
            missing.append('I/O property snapshot is not bound to route DCP')
    else:missing.append('new full512 post-route I/O snapshot is pending')
    return missing

def render_to_fresh_paths(output_dir,emit_tcl,renderer):
    require(not Path(output_dir).exists(),'Fresh full512 emission output directory required')
    require(not Path(emit_tcl).exists(),'Fresh full512 emission Tcl path required')
    text=renderer()
    Path(emit_tcl).write_text(text)
    return text

def render_if_ready():
    m=load_json(MANIFEST);b=load_json(RUN_BINDING)
    source_manifest_matches(m)
    missing=collect_missing(m,b)
    if missing:raise GateError('UNLAUNCHABLE: '+'; '.join(missing))
    io=load_json(IO_REPORT)
    helpers={name:m['route_helpers'][name]['path'] for name in HELPERS}
    route=m['route_gate']
    inputs=dict(m['source_inputs'])
    inputs.update(dict(b.get('bound_image_inputs',{})))
    inputs[route['route_report_path']]=route['report_sha256']
    inputs[route['review_path']]=route['review_sha256']
    inputs[route['post_route_dcp_path']]=route['post_route_dcp_sha256']
    for gate in m['qualification_gates'].values():inputs[gate['path']]=gate['sha256']
    inputs[str(IO_REPORT)]=sha(IO_REPORT)
    for row in io['artifacts'].values():inputs[row['path']]=row['sha256']
    text=render_to_fresh_paths(OUTPUT,EMIT_TCL,lambda:render(route['post_route_dcp_path'],OUTPUT,inputs,helpers,io['ports'],m['source_tag']))
    m['status']='PREPARED_FOR_ROOT_REVIEWED_FULL512_IMAGE_EMISSION'
    m['launch_approved']=False
    m['emission_tcl_path']=str(EMIT_TCL);m['emission_tcl_sha256']=sha(EMIT_TCL)
    m['rendered_inputs']=inputs
    MANIFEST.write_text(json.dumps(m,indent=2)+'\n')
    print(json.dumps({'status':m['status'],'emit_tcl':str(EMIT_TCL),'emit_tcl_sha256':m['emission_tcl_sha256']}))

if __name__=='__main__':
    try:render_if_ready()
    except GateError as error:
        print(json.dumps({'status':'UNLAUNCHABLE','reason':str(error),'vivado_executed':False,'hardware_accessed':False}))
        raise SystemExit(2)
