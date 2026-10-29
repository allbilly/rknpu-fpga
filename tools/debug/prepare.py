#!/usr/bin/env python3
"""Freeze an optional EW startup ILA checkpoint flow. Never invokes Vivado."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import prepare_ew_fpga as base
from tools.host import prepare as host

PROFILE = 'ew-startup-ila'
PLAN = 'fpga/debug/ew_ila.json'
TCL = 'fpga/debug/ew_ila.tcl'
PROFILES = {
    'ew-startup-ila': {'kind':'ew','plan':PLAN,'top':'ypcb_ew_startup_top','parent_profile':'startup'},
    'host-jtag-ew-ila': {'kind':'host','plan':'fpga/debug/host_ila.json','top':'ypcb_jtag_ew_top','parent_profile':host.PROFILE},
}
STATE_BOOKS = {
    'ew-startup-ila': {
        'demo_state': ('rtl/rk_ew_dma_demo.sv','state_t','demo/state',4,(0,1,2)),
        'dma_state': ('rtl/rk_ew_dma.sv','state_t','demo/core/state',3,(0,1,2)),
        'engine_state': ('rtl/rk_ew_engine.sv','state_t','demo/core/engine/state',4,(0,1,2,3)),
    },
    'host-jtag-ew-ila': {
        'backend_state': ('rtl/host/rk_jtag_backend.sv','state_t','endpoint/backend/state',3,(0,1,2)),
        'dma_state': ('rtl/rk_ew_dma.sv','state_t','endpoint/engine/state',3,(0,1,2)),
        'engine_state': ('rtl/rk_ew_engine.sv','state_t','endpoint/engine/engine/state',4,(0,1,2,3)),
    },
}
IMPORT_DEPENDENCIES = ('tools/host/prepare.py',)
BUILD_FILES = [PLAN, 'fpga/debug/host_ila.json', TCL, 'tools/debug/__init__.py', 'tools/debug/prepare.py',
               'tests/debug/test_prepare.py', 'tests/debug/test_ila_tcl.py', *IMPORT_DEPENDENCIES]
require, digest = base.require, base.digest
read_json, write_json, quote = base.read_json, base.write_json, base.tcl_path


def checked(root, name):
    root = Path(root).resolve()
    relative = Path(name)
    require(not relative.is_absolute() and relative.parts and '..' not in relative.parts, 'Unsafe snapshot path')
    path = root / relative
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root), 'Missing or escaping snapshot: '+name)
    return path


def manifest(files):
    text = ''.join(f'{sha}  {name}\n' for name,sha in sorted(files.items()))
    return {'sha256':hashlib.sha256(text.encode()).hexdigest(),'files':dict(sorted(files.items()))}


def plan(root, profile=PROFILE):
    require(profile in PROFILES,'Unknown debug profile')
    value = read_json(checked(root, PROFILES[profile]['plan']))
    require(value.get('schema') == 1 and type(value['schema']) is int and value.get('profile') == profile and
            value.get('top') == PROFILES[profile]['top'] and value.get('part') == base.PART,
            'Unsupported EW debug profile')
    require(value['clock']['name'] == 'sys_clk' and value['clock']['port'] == 'SYS_CLK' and
            value['clock']['period_ns'] == 20.0 and value['clock']['frequency_hz'] == 50000000,
            'Debug must retain the 50 MHz source clock')
    anchor = 'demo/core/state_reg[0]/C' if PROFILES[profile]['kind']=='ew' else 'endpoint/engine/state_reg[0]/C'
    require(value['clock'].get('anchor_pin') == anchor, 'Debug clock anchor differs from the selected profile')
    require(value['core'] == {'name':'u_rk_ew_ila','depth':1024,'input_pipe_stages':0,'jtag_user_chain':1},
            'Unexpected debug core configuration')
    require(value['synthesis_options'] == ['-flatten_hierarchy','none','-fsm_extraction','off'],
            'Debug synthesis must preserve hierarchy and source FSM encoding')
    probes = value['probes']
    require(type(probes) is list and 1 <= len(probes) <= 16, 'Unexpected probe count')
    names = []
    for probe in probes:
        names.append(probe['name'])
        require(re.fullmatch('[a-z][a-z0-9_]*',probe['name']) is not None and type(probe['width']) is int and
                1 <= probe['width'] <= 64 and type(probe['nets']) is list and len(probe['nets']) == probe['width'],
                'Invalid probe name/width')
        require(all(type(n) is str and re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_/]*(?:\[[0-9]+\])?',n) for n in probe['nets']),
                'Probe must name exact source nets')
        require(len(set(probe['nets'])) == len(probe['nets']), 'Duplicate bit within probe')
    require(len(set(names)) == len(names) and sum(p['width'] for p in probes) <= 256, 'Duplicate or excessive probes')
    by_name = {p['name']:p for p in probes}
    books = value['state_codebooks']
    required_books = STATE_BOOKS[profile]
    require(type(books) is list and len(books) == 3 and
            all(type(book) is dict and type(book.get('name')) is str for book in books) and
            {book['name'] for book in books} == set(required_books), 'Missing or duplicate state codebooks')
    for book in value['state_codebooks']:
        expected = required_books[book['name']]
        require((book.get('source'),book.get('type'),book.get('signal'),book.get('declared_width')) == expected[:4] and
                type(book.get('declared_width')) is int and type(book.get('selected_bits')) is list and
                all(type(bit) is int for bit in book['selected_bits']) and tuple(book['selected_bits']) == expected[4],
                'State codebook source/signal binding changed: '+book['name'])
        source = checked(root,book['source']).read_text()
        declaration = re.findall(r'typedef\s+enum\s+logic\s*\[(\d+)\s*:\s*0\]\s*\{([^}]+)\}\s*'+re.escape(book['type'])+r'\s*;',source,re.S)
        require(len(declaration) == 1, 'State enumeration is ambiguous or missing')
        high, labels = declaration[0]
        labels = [item.strip() for item in labels.split(',')]
        require(all(re.fullmatch('[A-Z][A-Z0-9_]*',item) for item in labels), 'Unsupported explicit FSM source encoding')
        require(book['declared_width'] == int(high)+1 and book['values'] == {name:i for i,name in enumerate(labels)},
                'State codebook does not match frozen RTL')
        bits = book['selected_bits']
        require(type(bits) is list and all(type(bit) is int for bit in bits) and
                1 <= len(bits) <= book['declared_width'] and bits == list(range(len(bits))) and
                len(labels)-1 < 1 << len(bits),
                'State probe omits a varying source bit')
        require(by_name[book['name']]['nets'] == [f'{book["signal"]}[{bit}]' for bit in bits], 'State probe/codebook mismatch')
    return value


def literal(value):
    if isinstance(value, dict):
        return '{'+' '.join(literal(item) for pair in value.items() for item in pair)+'}'
    if isinstance(value, list):
        return '{'+' '.join(literal(item) for item in value)+'}'
    require(type(value) in (str,int,float) and not any(c in str(value) for c in '{}\\\n\r'), 'Unsupported Tcl plan literal')
    return '{'+str(value)+'}'


def render_plan(root, profile=PROFILE):
    return '# Frozen probe plan; generated without Vivado. LSB-first net lists.\nset rk_ew_debug_plan '+literal(plan(root,profile))+'\n'


def render_cdc(root):
    """Select only the existing mailbox primitive; preserve every original bound."""
    text = checked(root,'fpga/host/mailbox_cdc.tcl').read_text()
    original = '[get_cells -quiet -hier -filter {REF_NAME == BSCANE2}]'
    require(text.count(original) == 2,'Changed mailbox CDC primitive selection')
    return ('# Debug-only derivative: USER2 mailbox remains u_bscan; USER1 hub is audited separately.\n'+
            text.replace(original,'[get_cells -quiet -hier -filter {REF_NAME == BSCANE2 && NAME == u_bscan}]'))


def render(directory, source_sha, profile=PROFILE):
    kind = PROFILES[profile]['kind']
    text = base.render(directory,'startup',source_sha) if kind=='ew' else host.render(directory,source_sha)
    synthesis = 'synth_design -top '+PROFILES[profile]['top']+' -part '+base.PART+' -generic LED_ACTIVE_LOW=$::env(RK_LED_ACTIVE_LOW)'
    require(text.count(synthesis) == text.count('route_design\n') == text.count('write_checkpoint -force [file join $out post_synth.dcp]') == 1,
            'Changed shared checkpoint control flow')
    text = text.replace(synthesis,synthesis+' -flatten_hierarchy none -fsm_extraction off')
    hook = ('source '+quote(directory/'source'/TCL)+'\nsource '+quote(directory/'debug-plan.tcl')+
            '\nrk_ew_debug_insert $out $rk_ew_debug_plan\n')
    text = text.replace('write_checkpoint -force [file join $out post_synth.dcp]',hook+'write_checkpoint -force [file join $out post_synth.dcp]')
    text = text.replace('route_design\n','route_design\nrk_ew_debug_audit $out $rk_ew_debug_plan\n')
    if kind=='host':
        original = 'source '+quote(directory/'source/fpga/host/mailbox_cdc.tcl')
        require(text.count(original) == 1,'Changed host CDC setup hook')
        text = text.replace(original,'source '+quote(directory/'debug-mailbox-cdc.tcl'))
    text = text.replace('RK_EW_PREPARED_SHA' if kind=='ew' else 'RK_HOST_PREPARED_SHA','RK_EW_DEBUG_PREPARED_SHA')
    text = text.replace('Rendered by prepare_ew_fpga.py.','Rendered by tools/debug/prepare.py.')
    text = text.replace('Rendered by tools/host/prepare.py.','Rendered by tools/debug/prepare.py.')
    require(not re.search(r'^\s*(write_bitstream|open_hw\w*|program_hw\w*|set_clock_groups|create_waiver)\b',text,re.M),
            'Debug checkpoint flow cannot emit/program an image or weaken constraints')
    return text


def parent_source(parent,kind):
    return parent['snapshot_files'] if kind=='ew' else parent['source']['files']


def parent_revision(parent,kind):
    return parent['production_revision'] if kind=='ew' else parent['protocol_source']


def evidence_manifest(directory, parent, kind):
    """Only the two bound reports and their qualified artifacts are evidence."""
    files = {}
    require(set(parent['simulation_reports']) == {'verilator','iverilog'}, 'Both functional simulator parents are required')
    for simulator,sha in parent['simulation_reports'].items():
        report_name = 'evidence/'+simulator+'.json'
        report_path = checked(directory,report_name)
        require(digest(report_path) == sha,'Changed functional report')
        files[report_name] = sha
        report = read_json(report_path)
        artifacts = report.get('artifacts',{}).get('files',{})
        require(type(artifacts) is dict and artifacts,'Missing functional artifact inventory')
        prefix = 'evidence/'+simulator+'/artifacts' if kind=='ew' else 'artifacts'
        for name,artifact_sha in artifacts.items():
            relative = Path(name)
            require(not relative.is_absolute() and relative.parts and '..' not in relative.parts,
                    'Unsafe functional artifact path')
            destination = str(Path(prefix)/relative)
            require(destination not in files or files[destination] == artifact_sha,'Conflicting functional artifacts')
            files[destination] = artifact_sha
    return manifest(files)


def evidence_inventory(directory, expected):
    actual = set()
    for name in ('evidence','artifacts'):
        container = directory/name
        require(not container.is_symlink(),'Symlinked functional evidence directory')
        if not container.exists():
            continue
        require(container.is_dir(),'Functional evidence container is not a directory')
        for path in container.rglob('*'):
            require(not path.is_symlink(),'Symlinked functional evidence entry')
            if path.is_file():
                actual.add(str(path.relative_to(directory)))
    require(actual == set(expected),'Unmanifested or missing functional evidence')


def validate_functional_evidence(directory, record):
    profile=record['profile'];spec=PROFILES[profile];kind=spec['kind']
    parent = read_json(checked(directory,'parent-report.json'))
    require(digest(directory/'parent-report.json') == record['parent_report_sha256'] and parent.get('profile') == spec['parent_profile'] and
            parent.get('status') == ('PREPARED_EW_CHECKPOINT_ONLY' if kind=='ew' else 'PREPARED_HOST_JTAG_EW_ONLY') and
            parent.get('simulation_bound' if kind=='ew' else 'native_qualification_bound') is True,
            'A completed functional source package is required')
    revision = parent_revision(parent,kind)
    require(record['functional_source_revision'] == revision and manifest(revision['files']) ==
            {'sha256':revision['sha256'],'files':revision['files']}, 'Functional source identity changed')
    require(set(parent['simulation_reports']) == {'verilator','iverilog'}, 'Both functional simulator parents are required')
    expected = evidence_manifest(directory,parent,kind)
    require(record.get('evidence_manifest') == expected,'Changed functional evidence manifest')
    evidence_inventory(directory,expected['files'])
    for simulator,sha in parent['simulation_reports'].items():
        path = checked(directory/'evidence',simulator+'.json')
        require(digest(path) == sha, 'Changed functional report')
        if kind=='ew':
            base.simulation_evidence(read_json(path),simulator,revision,'startup',directory/'evidence'/simulator/'artifacts')
        else:
            result=host.qualification().verify_report(path,source_root=directory/'source',artifact_root=directory/'artifacts')
            require(result['simulator']==simulator and result['source_revision']==revision,'Wrong copied host functional report')
    require(all(record['source']['files'].get(name) == sha for name,sha in parent_source(parent,kind).items()),
            'Debug source changed from the simulated functional RTL')
    return parent


def copy_evidence(parent_directory,directory,parent,kind):
    expected = evidence_manifest(parent_directory,parent,kind)
    evidence_inventory(parent_directory,expected['files'])
    for name,sha in expected['files'].items():
        source = checked(parent_directory,name)
        require(digest(source) == sha,'Changed functional artifact during copy')
        target = directory/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
        require(digest(target) == sha,'Changed copied functional artifact')
    evidence_inventory(directory,expected['files'])
    return expected


def prepare(parent_directory, out=None, profile=PROFILE):
    require(profile in PROFILES,'Unknown debug profile');spec=PROFILES[profile];kind=spec['kind']
    parent_directory = Path(parent_directory).resolve()
    (base if kind=='ew' else host).verify(parent_directory)
    parent = read_json(checked(parent_directory,'report.json'))
    require(parent['profile'] == spec['parent_profile'] and parent.get('simulation_bound' if kind=='ew' else 'native_qualification_bound') is True,
            'Use a matching simulation-bound functional package')
    require(set(parent['simulation_reports']) == {'verilator','iverilog'}, 'Both functional simulator parents are required')
    names = dict(parent_source(parent,kind))
    for name in BUILD_FILES:
        current = digest(checked(ROOT,name))
        if name in names:
            require(name in IMPORT_DEPENDENCIES and names[name] == current,
                    'Debug input collided with or changed a parent import dependency: '+name)
        else:
            names[name] = current
    source = manifest(names)
    directory = (Path(out) if out is not None else ROOT/'build/ew-debug-preparation'/str(time.time_ns())).resolve()
    require(directory.is_relative_to(ROOT/'build') and directory != ROOT/'build' and not directory.exists(), 'Use a fresh directory below build/')
    quote(directory);directory.mkdir(parents=True)
    record = dict(schema=1,status='PREPARING',profile=profile,board=base.BOARD,part=base.PART,started_utc=base.timestamp(),
                  source=source,functional_source_revision=parent_revision(parent,kind),parent_report_sha256=digest(parent_directory/'report.json'),
                  vivado_executed=False,implementation_completed=False,bitstream_emitted=False,hardware_programmed=False)
    try:
        for name,sha in names.items():
            original = checked(ROOT,name) if name in BUILD_FILES else checked(parent_directory/'source',name)
            require(digest(original) == sha, 'Input changed during source preparation')
            target = directory/'source'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
        shutil.copyfile(parent_directory/'report.json',directory/'parent-report.json')
        record['evidence_manifest'] = copy_evidence(parent_directory,directory,parent,kind)
        (directory/'debug-plan.tcl').write_text(render_plan(directory/'source',profile))
        if kind=='host':
            (directory/'debug-mailbox-cdc.tcl').write_text(render_cdc(directory/'source'))
            record['mailbox_cdc_sha256']=digest(directory/'debug-mailbox-cdc.tcl')
        (directory/'build.tcl').write_text(render(directory,source['sha256'],profile))
        record.update(debug_plan_sha256=digest(directory/'debug-plan.tcl'),build_tcl_sha256=digest(directory/'build.tcl'))
        validate_functional_evidence(directory,record)
        require(all(digest(checked(directory/'source',name)) == sha for name,sha in names.items()), 'Copied debug source changed')
        require(all(digest(checked(ROOT,name)) == names[name] for name in BUILD_FILES), 'Debug inputs changed during preparation')
        write_json(directory/'board-review.json',dict(schema=1,profile=profile,source_sha256=source['sha256'],board=base.BOARD,part=base.PART,
            reviewer='',checks={key:False for key in base.BOARD_CHECKS},evidence={key:'' for key in base.BOARD_CHECKS},
            config_voltage=None,cfgbvs=None,led_active_low=None))
        record.update(status='PREPARED_EW_DEBUG_CHECKPOINT_ONLY',
                      scope='Source-identical EW functional simulation parents only. Optional ILA insertion/implementation, mapped probe connectivity, debug hub, timing and physical JTAG remain unexecuted and unproven.')
    except BaseException as error:
        record.update(status='FAIL',error=repr(error));raise
    finally:
        record['finished_utc']=base.timestamp();write_json(directory/'report.json',record)
    return directory


def verify(directory, require_ready=False):
    directory = Path(directory).resolve();record = read_json(checked(directory,'report.json'))
    require(type(record.get('schema')) is int and record['schema'] == 1 and record.get('status') == 'PREPARED_EW_DEBUG_CHECKPOINT_ONLY' and
            record.get('profile') in PROFILES and record.get('board') == base.BOARD and record.get('part') == base.PART,
            'Incomplete or unsupported EW debug package')
    require(all(record.get(key) is False for key in ('vivado_executed','implementation_completed','bitstream_emitted','hardware_programmed')),
            'Unexpected physical debug acceptance claim')
    source = record['source'];require(manifest(source['files']) == source, 'Invalid debug source manifest')
    profile=record['profile'];kind=PROFILES[profile]['kind']
    for name,sha in source['files'].items():require(digest(checked(directory/'source',name)) == sha,'Changed debug source: '+name)
    parent = validate_functional_evidence(directory,record)
    require(set(source['files']) == set(parent_source(parent,kind)) | set(BUILD_FILES), 'Incomplete debug source inventory')
    require(digest(checked(directory,'build.tcl')) == record['build_tcl_sha256'] and
            (directory/'build.tcl').read_text() == render(directory,source['sha256'],profile), 'Changed debug checkpoint Tcl or moved package')
    require(digest(checked(directory,'debug-plan.tcl')) == record['debug_plan_sha256'] and
            (directory/'debug-plan.tcl').read_text() == render_plan(directory/'source',profile), 'Changed debug probe plan')
    if kind=='host':
        require(digest(checked(directory,'debug-mailbox-cdc.tcl'))==record['mailbox_cdc_sha256'] and
                (directory/'debug-mailbox-cdc.tcl').read_text()==render_cdc(directory/'source'),'Changed debug mailbox CDC constraints')
    validators = BUILD_FILES+['tools/prepare_ew_fpga.py',base.TEMPLATE]
    if kind=='host':
        validators += host.BUILD_FILES+['tools/host/qualification.py']
    for name in set(validators):
        require(digest(checked(ROOT,name)) == source['files'][name], 'Debug validator/input changed; prepare again: '+name)
    blockers=[]
    hardware = base.PROFILES['startup']['sources']+[base.PROFILES['startup']['constraints']] if kind=='ew' else host.specification(directory/'source')['synthesis']+[host.specification(directory/'source')['constraints'],host.specification(directory/'source')['cdc']]
    for name in hardware:
        if not (ROOT/name).is_file() or digest(ROOT/name) != source['files'][name]:blockers.append('Selected functional hardware source changed: '+name)
    try:base.validate_board_review(read_json(directory/'board-review.json'),dict(profile=profile,board=base.BOARD,part=base.PART,production_revision=source))
    except (ValueError,KeyError,TypeError,OSError) as error:blockers.append(str(error))
    if require_ready:require(not blockers,'; '.join(blockers))
    return dict(status='SOURCE_INTACT_REVIEW_PENDING' if blockers else 'READY_FOR_SEPARATELY_AUTHORIZED_DEBUG_BUILD',
                profile=profile,blockers=blockers,vivado_executed=False,debug_implementation_verified=False)


def command(directory):
    result=verify(directory,True);directory=Path(directory).resolve()
    require(not (directory/'implementation').exists(),'Implementation output already exists; prepare a fresh package')
    record=read_json(directory/'report.json');review=read_json(directory/'board-review.json')
    result['argv']=['vivado','-mode','batch','-source',str(directory/'build.tcl'),'-log',str(directory/'vivado.log'),'-journal',str(directory/'vivado.jou')]
    result['environment']=dict(RK_EW_DEBUG_PREPARED_SHA=record['source']['sha256'],RK_CONFIRM_BOARD=base.BOARD,
        RK_CONFIG_VOLTAGE=review['config_voltage'],RK_CFGBVS=review['cfgbvs'],RK_LED_ACTIVE_LOW=str(review['led_active_low']),RK_EMIT_BITSTREAM='0')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    make=sub.add_parser('prepare');make.add_argument('--parent-package','--ew-package',dest='parent_package',type=Path,required=True);make.add_argument('--out',type=Path)
    make.add_argument('--profile',choices=tuple(PROFILES),default=PROFILE)
    for name in ('verify','command'):sub.add_parser(name).add_argument('directory',type=Path)
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            directory=prepare(args.parent_package,args.out,args.profile);print(directory/'report.json');print(base.json.dumps(verify(directory),indent=2))
        else:print(base.json.dumps((verify if args.action=='verify' else command)(args.directory),indent=2))
    except (ValueError,KeyError,TypeError,OSError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
