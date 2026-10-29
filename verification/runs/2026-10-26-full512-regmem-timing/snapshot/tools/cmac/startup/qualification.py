"""Source and native execution admission for the full 512-product startup top."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
PROFILE = 'full512-startup'
STATUS = 'PASS_FULL512_STARTUP_NATIVE_ONLY'
PARENT_STATUS = 'PREPARED_OWN_PARENTS_VALIDATED_FULL_C32K16_PREFIX_CHECKPOINT_ONLY'
TOP = 'fpga/cmac/startup/ypcb_cmac_array_startup_top.sv'
CONSTRAINTS = 'fpga/cmac/startup/ypcb_cmac_array_startup.xdc'
BENCH = 'tests/cmac/startup/tb_array_startup.sv'
SPEC = 'fpga/cmac/array_sources.json'
RESET = 'rtl/rk_startup_reset.sv'
EXPECTED_HIERARCHY = {'rk_cmac_fp16_array_dsp_prefix':1,'rk_cmac_fp16_cell_dsp_prefix':16,
                      'rk_cmac_fp16_lane_dsp_prefix':512,'rk_cmac_fp16_discarded_carry':512}
NEW_FILES = [TOP,CONSTRAINTS,BENCH,RESET,'tools/cmac/startup/__init__.py',
             'tools/cmac/startup/qualification.py','tools/cmac/startup/run.py',
             'tests/cmac/startup/test_qualification.py']


def require(condition,message):
    if not condition:raise ValueError(message)


def safe(root,name):
    root=Path(root).resolve();relative=Path(name)
    require(not relative.is_absolute() and relative.parts and '..' not in relative.parts,'Unsafe source/evidence path')
    result=root/relative
    require(result.is_file() and not result.is_symlink() and result.resolve().is_relative_to(root),'Missing/escaping source/evidence: '+name)
    return result


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(names,root=ROOT):
    files={n:digest(safe(root,n)) for n in sorted(set(names))}
    text=''.join(f'{h}  {n}\n' for n,h in files.items())
    return {'sha256':hashlib.sha256(text.encode()).hexdigest(),'files':files}


def original_driver():
    for directory in (ROOT/'tools',ROOT/'tools/cmac'):
        if str(directory) not in sys.path:sys.path.insert(0,str(directory))
    return importlib.import_module('vivado_dsp_prefix_array')


def relative(path):
    result=Path(path).resolve();require(result.is_relative_to(ROOT),'Use an in-workspace parent preflight')
    return str(result.relative_to(ROOT))


def verify_parent(path):
    require(not sys.flags.optimize,'Parent qualification requires assertions enabled; do not use Python -O')
    name=relative(path);path=safe(ROOT,name);record=json.loads(path.read_text())
    require(record.get('status')==PARENT_STATUS and record.get('stage')=='complete' and record.get('finished_utc'),
            'Completed own-parent-validated full-prefix preflight required')
    require((record['channels'],record['kernels'],record['parallel_products'])==(32,16,512) and
            record['own_numerical_parents_validated'] is True,'Parent does not retain full C32/K16')
    require(all(record.get(n) is False for n in ('actual_vivado_executed','routed_checkpoint_produced',
            'physical_fit_verified','bitstream_emitted','hardware_programmed')),'Unexpected parent physical claim')
    for group in ('source','artifacts'):
        require(fingerprint(record[group]['files'])==record[group],'Changed parent '+group)
    driver=original_driver();spec,tracked=driver.inputs(path.parent)
    tracked=set(tracked)|{ROOT/'tools/cmac/prepare_dsp_prefix_checkpoint.py'}
    require(fingerprint([relative(p) for p in tracked])==record['source'],'Parent input/dependency inventory changed')
    parents=driver.validate_evidence(path.parent)
    require(record['validated_parent_source_sha256']=={n:r['source']['sha256'] for n,r in parents.items()},
            'Parent numerical source identities changed')
    require(safe(ROOT,record['build_script']).read_text()==driver.render(spec,path.parent,record['source']['sha256']),
            'Parent checkpoint Tcl changed')
    return record


def parent_name(path,root=ROOT):
    path=Path(path)
    if path.is_absolute():
        require(path.resolve().is_relative_to(Path(root).resolve()),'Parent source path escapes snapshot')
        return str(path.resolve().relative_to(Path(root).resolve()))
    return str(path)


def source_names(parent_path,root=ROOT):
    """The original literal prefix composition, with only the board top replaced."""
    parent=parent_name(parent_path,root);record=json.loads(safe(root,parent).read_text())
    require(record['status']==PARENT_STATUS and record['source_profile']=='dsp-prefix-c32k16','Wrong full-prefix parent')
    spec=json.loads(safe(root,SPEC).read_text())
    require((spec['top'],spec['part'],spec['clock_period_ns'],spec['constraints'])==
            ('ypcb_cmac_array_top','xc7k480tffg1156-2',20,'fpga/ypcb.xdc'),'Changed baseline geometry/clock profile')
    join=str(Path(parent).parent/'rk_cmac_cacc_fp16_array.sv')
    replacements={
        'rtl/cmac/rk_cmac_fp16_cell.sv':['rtl/cmac/experimental/rk_cmac_fp16_rows.sv',
            'rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv','rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv',
            'rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix.sv'],
        'rtl/cmac/rk_cmac_fp16_array.sv':['rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix.sv'],
        'rtl/cmac/rk_cmac_cacc_fp16_array.sv':[join],
        'fpga/cmac/ypcb_cmac_array_top.sv':[TOP],
    }
    original=spec['simulation_helpers']+spec['synthesis']
    require(len(original)==len(set(original)) and all(original.count(n)==1 for n in replacements),'Ambiguous source replacement')
    names=[]
    for name in original:names.extend(replacements.get(name,[name]))
    names.append(RESET)
    require(len(names)==len(set(names)) and not any(n in names for n in replacements),'Baseline/fixed array fallback or duplicate source')
    for name in names:safe(root,name)
    return names


def sources(parent_directory):
    parent=Path(parent_directory)
    if parent.is_dir():parent=parent/'report.json'
    return [safe(ROOT,n) for n in source_names(relative(parent))]


def source_revision(parent_path,root=ROOT):
    name=parent_name(parent_path,root);parent=json.loads(safe(root,name).read_text())
    return fingerprint(set(parent['source']['files'])|{name}|set(NEW_FILES)|set(source_names(name,root)),root)


def specs(simulator):
    require(simulator in ('iverilog','verilator'),'Unknown startup simulator')
    modes=[0,1,2,3]+([4] if simulator=='iverilog' else [])+[10,11,12]
    result=[]
    for polarity in (0,1):
        for mode in modes:
            result.append({'name':f'led{polarity}_mode{mode}','polarity':polarity,'mode':mode,'fresh_after':None})
            if mode>=10:result.append({'name':f'led{polarity}_fresh_after{mode}','polarity':polarity,'mode':0,'fresh_after':mode})
    return result


def binary_path(simulator,out,polarity):
    return str(Path(out)/f'led{polarity}'/('obj/sim' if simulator=='verilator' else 'sim.vvp'))


def build_argv(report,polarity,action='compile'):
    root=Path(report['execution_root']);out=report['output_directory'];sim=report['simulator'];compiler=report['compiler']['path']
    names=report['simulation_sources']+[BENCH]
    defines=['-DDESIGNWARE_NOEXIST','-DASSERT_ON','-I'+str(root/'rtl/vendor/nvdla')]
    if sim=='iverilog':
        require(action=='compile','Icarus has no selected Verilator action')
        return [compiler,'-g2012',*defines,'-s','tb_array_startup','-Ptb_array_startup.LED_ACTIVE_LOW='+str(polarity),
                '-o',str(root/binary_path(sim,out,polarity))]+[str(root/n) for n in names]
    flags=['--timing','--assert','-Wall','-Wno-fatal','--timescale-override','1ns/1ps',*defines,
           '--top-module','tb_array_startup','-GLED_ACTIVE_LOW='+str(polarity)]
    if action=='lint':return [compiler,'--lint-only',*flags]+[str(root/n) for n in names]
    if action=='hierarchy':
        return [compiler,'--json-only',*flags,'--Mdir',str(root/out/f'led{polarity}/obj'),
                '--json-only-output',str(root/out/f'led{polarity}/hierarchy.tree.json'),
                '--json-only-meta-output',str(root/out/f'led{polarity}/hierarchy.meta.json')]+[str(root/n) for n in names]
    require(action=='compile','Unknown Verilator action')
    return [compiler,'--binary',*flags,'-j','2','--Mdir',str(root/out/f'led{polarity}/obj'),'-o','sim']+[str(root/n) for n in names]


def run_argv(report,spec):
    image=str(Path(report['execution_root'])/binary_path(report['simulator'],report['output_directory'],spec['polarity']))
    return ([image] if report['simulator']=='verilator' else [report['runtime']['path'],image])+[f'+MODE={spec["mode"]}']


def hierarchy_vvp(text):
    result={name:len(re.findall(r'\.scope module, "[^"]*" "'+name+r'"',text)) for name in EXPECTED_HIERARCHY}
    require(result==EXPECTED_HIERARCHY,'Compiled full512 hierarchy mismatch')
    for name in ('rk_cmac_fp16_cell','rk_cmac_fp16_cell_fixed','rk_cmac_fp16_array','rk_cmac_fp16_array_fixed',
                 'rk_cmac_fp16_cell_dsp','rk_cmac_fp16_lane_dsp','rk_cmac_fp16_array_dsp'):
        require(not re.search(r'\.scope module, "[^"]*" "'+name+r'"',text),'Unexpected non-prefix array fallback')
    return result


def hierarchy_json(path):
    tree=json.loads(Path(path).read_text())
    require(tree.get('type')=='NETLIST' and type(tree.get('modulesp')) is list,'Missing actual elaborated JSON hierarchy')
    modules={m['addr']:m for m in tree['modulesp'] if m.get('type')=='MODULE'}
    require(len(modules)==len(tree['modulesp']),'Duplicate or unknown elaborated module node')
    roots=[m for m in modules.values() if m.get('origName')=='tb_array_startup']
    require(len(roots)==1,'Missing unique startup test root')
    counts={name:0 for name in EXPECTED_HIERARCHY}
    def children(node):
        if isinstance(node,dict):
            require(node.get('type') not in ('GENFOR','GENIF'),'Unelaborated generate cannot prove instance counts')
            if node.get('type')=='CELL':yield node;return
            for value in node.values():yield from children(value)
        elif isinstance(node,list):
            for value in node:yield from children(value)
    def instance(module,stack):
        require(module['addr'] not in stack,'Recursive elaborated hierarchy')
        name=module.get('origName',module['name'])
        if name in counts:counts[name]+=1
        if name in ('rk_cmac_fp16_cell','rk_cmac_fp16_cell_fixed','rk_cmac_fp16_array','rk_cmac_fp16_array_fixed',
                    'rk_cmac_fp16_cell_dsp','rk_cmac_fp16_lane_dsp','rk_cmac_fp16_array_dsp'):
            raise ValueError('Elaborated baseline/fixed fallback is not the prefix target')
        for cell in children(module.get('stmtsp',[])):
            require(cell.get('modp') in modules,'Unlinked/black-box elaborated cell')
            instance(modules[cell['modp']],stack|{module['addr']})
    instance(roots[0],set())
    require(counts==EXPECTED_HIERARCHY,'Elaborated full512 hierarchy mismatch')
    return counts


# Exactly 54 instances from build/full512-startup-dev/lint.log, including both
# sides of the OR at CACC line 656/column 96. The unchanged donor's width/X and
# unused-template conventions remain candidate behavior, not numerical proof;
# the existing native/mapped arithmetic parents and complete startup runs remain
# mandatory. The four prefix empty-output/high-nibble diagnostics are supported
# by the existing source-bound prefix proof. No directory or reset-net blanket
# exception exists, and no SYNCASYNCNET warning occurred in this reviewed set.
REVIEWED_WARNING_LOCATIONS = (
    ('DECLFILENAME','rtl/vendor/nvdla/NV_NVDLA_CMAC_CORE_MAC_mul.v',680,8),
    ('PINCONNECTEMPTY','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',327,76),
    ('PINCONNECTEMPTY','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',409,87),
    ('DECLFILENAME','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',11,8),
    ('PINCONNECTEMPTY','rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv',19,34),
    ('PINCONNECTEMPTY','rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv',19,44),
    ('WIDTHTRUNC','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',89,6),
    ('WIDTHTRUNC','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',105,32),
    ('WIDTHTRUNC','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',131,4),
    ('WIDTHEXPAND','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',1287,10),
    ('WIDTHXZEXPAND','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',367,24),
    ('WIDTHXZEXPAND','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',377,24),
    ('WIDTHTRUNC','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',387,17),
    ('WIDTHTRUNC','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',397,21),
    ('WIDTHEXPAND','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',414,63),
    ('WIDTHTRUNC','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',426,16),
    ('WIDTHXZEXPAND','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',436,23),
    ('WIDTHEXPAND','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',498,56),
    ('WIDTHTRUNC','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',519,25),
    ('WIDTHXZEXPAND','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',529,28),
    ('WIDTHEXPAND','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',656,69),
    ('WIDTHEXPAND','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',656,96),
    ('WIDTHEXPAND','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',656,96),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',79,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',82,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',98,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',103,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',104,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',105,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',106,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',107,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',108,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/NV_NVDLA_CACC_CALC_fp_48b.v',132,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',687,14),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',712,14),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',723,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',726,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',734,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',742,14),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',751,13),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',752,13),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',753,13),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',802,13),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',804,13),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',806,13),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',820,14),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',1465,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',1485,15),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',1475,15),
    ('UNUSEDSIGNAL','rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv',7,23),
    ('UNUSEDSIGNAL','rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv',7,34),
    ('UNUSEDSIGNAL','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',107,28),
    ('UNUSEDPARAM','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',13,21),
    ('UNUSEDPARAM','rtl/vendor/nvdla/HLS_fp32_to_fp16.v',55,21),
)


def reviewed_warnings(text,execution_root=ROOT):
    """Require the exact reviewed location multiset, not a donor-folder waiver."""
    root=Path(execution_root)
    require(not re.search(r'(?im)%Error|\b(?:error|warning):|sorry:|FATAL:',text),
            'Unreviewed compiler diagnostics')
    warnings=[]
    locations=[]
    for line in text.splitlines():
        if not line.startswith('%Warning'):continue
        match=re.match(r'%Warning-([^:]+): (.*?):([0-9]+):([0-9]+):',line)
        require(match is not None,'Unrecognized Verilator warning: '+line)
        kind,path,row,column=match.groups();path=Path(path)
        require(path.is_absolute() and path.is_relative_to(root),'Warning source is outside the selected project')
        name=str(path.relative_to(root));key=(kind,name,int(row),int(column))
        require(key in REVIEWED_WARNING_LOCATIONS,'Unreviewed startup design/bench warning: '+line)
        locations.append(key)
        warnings.append({'kind':kind,'path':name,'line':int(row),'column':int(column)})
    require(sorted(locations)==sorted(REVIEWED_WARNING_LOCATIONS),'Reviewed startup warning inventory changed')
    return warnings


RESULT=re.compile(r'PASS full512_startup mode=(\d+) polarity=([01]) outcome=(success|fault|abort) error=([0-9a-f]{2}) hold=64 release=65 init=(\d+) checks=(\d+) cmd_reads=(\d+) operand_reads=(\d+) writes=(\d+) acks=(\d+) frames=(\d+) cycles=(\d+); configuration model only')


def validate_result(text,spec):
    require(not re.search(r'(?im)\b(?:warning|error):|sorry:|FATAL:|ERROR :',text),'Startup execution diagnostics require rejection/review')
    lines=[line for line in text.splitlines() if line.startswith('PASS ')]
    require(len(lines)==1,'Missing or ambiguous startup result')
    match=RESULT.fullmatch(lines[0]);require(match is not None,'Unexpected startup result format')
    mode,polarity,outcome,error,*numbers=match.groups();numbers=list(map(int,numbers))
    require((int(mode),int(polarity))==(spec['mode'],spec['polarity']),'Wrong startup execution mode/polarity')
    init,checks,commands,operands,writes,acks,frames,cycles=numbers
    require(0<cycles<1048576 and init==4096 and 0<=checks<=4096 and 0<=commands<=196 and
            0<=operands<=6528 and 0<=acks<=writes<=64 and 0<=frames<=12,'Invalid startup coverage counters')
    if spec['mode']==0:
        require(outcome=='success' and error=='00' and numbers[:-1]==[4096,4096,196,6528,64,64,12],
                'Full startup numerical workload incomplete')
    elif spec['mode'] in (1,2,3,4):
        require(outcome=='fault' and int(error,16)=={1:5,2:0xfd,3:0xfe,4:0xfd}[spec['mode']], 'Wrong startup fault expectation')
        if spec['mode']==1:
            require((checks,commands,operands,writes,acks,frames)==(0,1,0,0,0,0),'Command fault phase changed')
        elif spec['mode']==3:
            require(checks==writes==acks==frames==0 and commands==196 and 20<=operands<=21,'Watchdog fault phase changed')
        else:
            require((checks,commands,operands,writes,acks,frames)==(1,196,6528,64,64,12),'Readback fault phase changed')
    else:
        require(outcome=='abort' and error=='00' and init==4096,'Wrong partial-stop scope')
        if spec['mode']==10:
            require(20<=commands<196 and operands==writes==acks==frames==checks==0,'Command-fetch stop phase not reached')
        elif spec['mode']==11:
            require(commands==196 and frames==1 and writes==acks==checks==0,'First-frame stop phase not reached')
        else:
            require(commands==196 and operands==6528 and writes==acks==64 and frames==12 and 20<=checks<4096,
                    'Partial readback stop phase not reached')
    return lines[0]


def verify_report(path,source_root=ROOT,artifact_root=ROOT,require_parents=True):
    require(not sys.flags.optimize,'Startup verification requires assertions enabled')
    report=json.loads(Path(path).read_text())
    require(report.get('status')==STATUS and report.get('execution_schema')==1 and report.get('profile')==PROFILE,
            'A completed fresh startup-native report is required')
    require((report['channels'],report['kernels'],report['parallel_products'])==(32,16,512),'Startup report reduced geometry')
    require(report['source_revision']==source_revision(report['parent_preflight'],source_root),'Startup source changed')
    require(report['simulation_sources']==source_names(report['parent_preflight'],source_root),'Selected startup source composition changed')
    parent=json.loads(safe(source_root,report['parent_preflight']).read_text())
    require(digest(safe(source_root,report['parent_preflight']))==report['parent_preflight_sha256'] and
            parent['source']['sha256']==report['parent_source_sha256'],'Wrong startup parent binding')
    if require_parents:verify_parent(safe(ROOT,report['parent_preflight']))
    require(fingerprint(report['artifacts']['files'],artifact_root)==report['artifacts'],'Startup artifacts changed')
    commands={c['name']:c for c in report['commands']};require(len(commands)==len(report['commands']),'Duplicate startup command')
    for command in commands.values():
        require(command['status']=='PASS' and type(command['returncode']) is int and command['returncode']==0,'Failed startup command')
        require(report['artifacts']['files'].get(command['log'])==command['log_sha256'],'Startup command log not bound')
    sim=report['simulator'];expected=specs(sim)
    require([t['spec'] for t in report['tests']]==expected,'Startup test coverage changed')
    for polarity in (0,1):
        image=binary_path(sim,report['output_directory'],polarity);binding={'path':image,'sha256':report['artifacts']['files'][image]}
        compile=commands[f'compile_led{polarity}'];require(compile['argv']==build_argv(report,polarity) and compile['binary']==binding,'Selected startup compile changed')
        require(report['compiled_hierarchy'][str(polarity)]==EXPECTED_HIERARCHY,'Missing full startup hierarchy census')
        actual=hierarchy_vvp(safe(artifact_root,image).read_text()) if sim=='iverilog' else hierarchy_json(safe(artifact_root,str(Path(report['output_directory'])/f'led{polarity}/hierarchy.tree.json')))
        require(actual==EXPECTED_HIERARCHY,'Executed startup hierarchy changed')
        if sim=='verilator':
            for action in ('lint','hierarchy'):
                require(commands[f'{action}_led{polarity}']['argv']==build_argv(report,polarity,action),'Changed startup lint/elaboration')
    for test,spec in zip(report['tests'],expected):
        command=commands[spec['name']];binding={'path':binary_path(sim,report['output_directory'],spec['polarity']),
            'sha256':report['artifacts']['files'][binary_path(sim,report['output_directory'],spec['polarity'])]}
        require(command['argv']==run_argv(report,spec) and command['binary_before']==binding and command['binary_after']==binding,
                'Startup binary execution binding changed')
        line=validate_result(safe(artifact_root,command['log']).read_text(),spec)
        require(test.get('status')=='PASS' and test.get('result')==line,'Startup result not supported by execution log')
    version=commands['version'];require(version['argv']==[report['compiler']['path'],'--version' if sim=='verilator' else '-V'],'Wrong startup simulator version probe')
    version_lines=safe(artifact_root,version['log']).read_text().splitlines()
    require(version_lines and version_lines[0]==report['tool_version'] and report['tool_version'].startswith(
            'Verilator ' if sim=='verilator' else 'Icarus Verilog version '),'Missing startup version log')
    require(commands['rom_check']['argv']==[report['python_executable'],str(Path(report['execution_root'])/'tools/cmac/gen_array_board.py'),'--check'],
            'Raw board ROM validation command changed')
    unit=commands['controls']
    require(unit['argv']==[report['python_executable'],'-m','unittest','discover','-s','tests/cmac/startup','-p','test_qualification.py','-v'],
            'Startup control selection changed')
    unit_log=safe(artifact_root,unit['log']).read_text()
    require(re.search(r'Ran 8 tests in ',unit_log) is not None and unit_log.rstrip().endswith('OK'),'Startup admission controls did not pass')
    expected_commands={'version','rom_check','controls'}|{f'compile_led{p}' for p in (0,1)}|{s['name'] for s in expected}
    if sim=='iverilog':
        expected_commands.add('runtime_version')
        runtime=commands['runtime_version']
        require(runtime['argv']==[report['runtime']['path'],'-V'] and safe(artifact_root,runtime['log']).read_text().splitlines()[0]==report['runtime_version'],
                'Startup runtime version evidence changed')
    else:
        expected_commands|={'cxx_version'}|{f'{a}_led{p}' for p in (0,1) for a in ('lint','hierarchy')}
        cxx=commands['cxx_version']
        require(cxx['argv']==[report['cxx']['path'],'--version'] and safe(artifact_root,cxx['log']).read_text().splitlines()[0]==report['cxx_version'],
                'Startup compiler version evidence changed')
    require(set(commands)==expected_commands,'Unknown/missing startup command selection')
    if sim=='verilator':
        expected=report['reviewed_warning_locations']
        for polarity in (0,1):
            for action in ('lint','hierarchy','compile'):
                command=commands[f'{action}_led{polarity}']
                actual=reviewed_warnings(safe(artifact_root,command['log']).read_text(),report['execution_root'])
                require(sorted(actual,key=str)==sorted(expected,key=str) and command['reviewed_warnings']==actual,
                        'Unreviewed/changed startup warning set')
    require(all(report.get(n) is False for n in ('physical_fit_verified','bitstream_emitted','hardware_programmed','mapped_startup_board_verified')),
            'Native startup evidence cannot claim mapped/physical acceptance')
    return report
