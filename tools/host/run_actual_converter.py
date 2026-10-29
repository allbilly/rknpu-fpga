#!/usr/bin/env python3
"""Optional public functional controls for the installed AMD AXI-Lite converter."""
from pathlib import Path
import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import resource
import shutil
import sys
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
TESTS=ROOT/'tests/host/actual_converter'
CONTRACT=TESTS/'source-contract.json'
BENCH=TESTS/'tb_actual_converter_reset.sv'
RTL=ROOT/'rtl/host/rk_pcie_bridge_reset.sv'
README=TESTS/'README.md'
OWNED=ROOT/'tools/owned_process.py'
XSIM_RUN_TCL=TESTS/'xsim-functional-run.tcl'
WARNING_RE=re.compile(r'^(%Warning-[A-Z0-9_-]+):\s+(.*?):(\d+):')
SUMMARY_RE=re.compile(
 r'^PASS_ACTUAL_CONVERTER_RETAINED_EPOCH_FUNCTIONAL checks=(\d+) epochs=(\d+) '
 r'glbl_gsr_released=1 s_aw=(\d+) m_aw=(\d+) s_w=(\d+) m_w=(\d+) '
 r's_b=(\d+) m_b=(\d+) s_ar=(\d+) m_ar=(\d+) s_r=(\d+) m_r=(\d+) write_effects=(\d+) '
 r'source=AMD_axi_clock_converter_v2_1_36_async_axilite scope=functional_native_only$',re.M)

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def need(ok,message):
    if not ok:raise RuntimeError(message)
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def jwrite(path,obj):Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
def jload(path):return json.loads(Path(path).read_text())
def inventory(root):
    result=[]
    for p in sorted(Path(root).rglob('*')):
        if p.is_file():result.append({'path':str(p),'relative_path':str(p.relative_to(root)),
            'bytes':p.stat().st_size,'sha256':sha(p)})
    return result

def normalize_root(raw,contract):
    p=Path(raw).expanduser().resolve();candidates=[p]
    if p.name.lower()!='vivado':candidates.append((p/'Vivado').resolve())
    for root in candidates:
        if (root/'bin').is_dir() and all((root/row['relative_path']).is_file() for row in contract['vendor_files']):
            return root
    raise RuntimeError('Vivado root lacks the exact contract-bound vendor files: '+str(p))

def resolve_roots(cli_root,contract):
    supplied=[]
    if cli_root:supplied.append(('--vivado-root',cli_root))
    env=os.environ.get('RK_VIVADO_ROOT')
    if env:supplied.append(('RK_VIVADO_ROOT',env))
    need(bool(supplied),'Provide --vivado-root or set RK_VIVADO_ROOT; no absolute path is built in')
    roots=[]
    for origin,value in supplied:
        root=normalize_root(value,contract)
        if root not in [p for _,p in roots]:roots.append((origin,root))
    locations={};primary_files={}
    for origin,root in roots:
        observed={}
        for row in contract['vendor_files']:
            path=(root/row['relative_path']).resolve();digest=sha(path)
            need(digest==row['sha256'],'Vendor file hash differs from the contract primary: '+str(path))
            observed[row['name']]={'path':str(path),'sha256':digest}
            primary_files.setdefault(row['name'],path)
        locations[str(root)]={'origin':origin,'vendor_files':observed}
    return roots,primary_files,locations

def validate_contract(contract,runner_text,bench_text):
    required={'schema','contract','top_module','converter_module','vendor_files','parameters',
        'bench_source_literals','expected_markers','expected_completion','limits','simulator_plan',
        'warning_policy','scope_exclusions'}
    need(required<=set(contract),'Missing source-contract fields: '+repr(sorted(required-set(contract))))
    need(contract['schema']==1 and contract['contract']=='installed-amd-axi-clock-converter-v2-1-actual-axilite-retained-epoch',
         'Unsupported source-contract schema')
    names={row.get('name') for row in contract['vendor_files']}
    expected={'axi_clock_converter_v2_1_vl_rfs.v','xpm_cdc.sv','axi_infrastructure_v1_1_vl_rfs.v',
              'axi_infrastructure_v1_1_0.vh','glbl.v'}
    need(len(names)==5 and names==expected and len({row.get('relative_path') for row in contract['vendor_files']})==5,
         'Expected exactly the five selected installed AMD source files')
    need(all(not Path(row['relative_path']).is_absolute() and re.fullmatch(r'[0-9a-f]{64}',row['sha256'])
             for row in contract['vendor_files']),'Malformed vendor source path/hash')
    ast.parse(runner_text,filename='run_actual_converter.py')
    for literal in contract['bench_source_literals']:
        need(literal in bench_text,'Bench does not satisfy contract literal '+literal)
    expected_parameters={'C_FAMILY':'kintex7','C_AXI_PROTOCOL':2,'C_AXI_IS_ACLK_ASYNC':1,
        'C_SYNCHRONIZER_STAGE':3,'C_AXI_ADDR_WIDTH':32,'C_AXI_DATA_WIDTH':32,
        'C_AXI_ID_WIDTH':1,'C_AXI_SUPPORTS_USER_SIGNALS':0,'C_AXI_SUPPORTS_READ':1,'C_AXI_SUPPORTS_WRITE':1}
    need(all(contract['parameters'].get(k)==v for k,v in expected_parameters.items()),
         'Contract converter parameter schema changed')

def classify_warnings(text,roots,sim='verilator'):
    vendor=[];authored=[];other=[]
    primary=jload(CONTRACT)['vendor_files']
    vendor_paths={str((root/row['relative_path']).resolve()) for _,root in roots for row in primary}
    vendor_labels={str(root/row['relative_path']) for _,root in roots for row in primary}
    prefixes=tuple(vendor_paths|vendor_labels)
    for line in text.splitlines():
        match=WARNING_RE.match(line)
        if match:
            source=match.group(2);row={'code':match.group(1),'source':source,'line':int(match.group(3)),'text':line}
            if str(Path(source).resolve()) in vendor_paths:vendor.append(row)
            elif source==str(BENCH) or source==str(RTL):authored.append(row)
            else:other.append(row)
        elif sim=='xsim' and re.search(r'(?i)\bWARNING\b',line):
            row={'text':line}
            if any(prefix in line for prefix in prefixes):vendor.append(row)
            elif str(BENCH) in line or str(RTL) in line:authored.append(row)
            else:other.append(row)
    return {'count':len(vendor)+len(authored)+len(other),'vendor_warnings':vendor,
            'authored_warnings':authored,'other_warnings':other}

def parse_completion(log,contract,simulator):
    text=Path(log).read_text(errors='replace')
    for marker in contract['expected_markers']:
        need(text.splitlines().count(marker)==1,simulator+' missing/duplicate marker '+marker)
    matches=SUMMARY_RE.findall(text);need(len(matches)==1,'Missing/duplicate completion summary for '+simulator)
    values=list(map(int,matches[0]))
    channel_order=('s_aw','m_aw','s_w','m_w','s_b','m_b','s_ar','m_ar','s_r','m_r','write_effects')
    counts=dict(zip(channel_order,values[2:]))
    need(values[0]==contract['expected_completion']['checks'] and values[1]==contract['expected_completion']['epochs'] and
         counts==contract['expected_completion']['handshakes'],simulator+' handshake/reset census mismatch')
    return {'checks':values[0],'epochs':values[1],'glbl_gsr_released':True,
            'handshakes':counts,'completion_line':matches[0]}

def command(name,argv,cwd,timeout,log,record,run_owned):
    row={'name':name,'argv':list(map(str,argv)),'cwd':str(cwd),'timeout_seconds':timeout,
         'started_utc':utc(),'status':'RUNNING','log_path':str(log)}
    record['commands'].append(row);start=time.monotonic()
    with log.open('xb') as stream:
        try:result=run_owned(argv,timeout=timeout,cwd=cwd,stdout=stream,stderr=stream)
        except BaseException as exc:
            meta=getattr(exc,'owned_process_cleanup',{})
            row.update(pid=meta.get('pid'),pgid=meta.get('pgid'),live_before_cleanup=meta.get('live_before_cleanup'),
                live_after_cleanup=meta.get('live_after_cleanup'),seconds=time.monotonic()-start,
                status='FAIL_OR_INTERRUPTED',error=repr(exc),completed_utc=utc());row['log_sha256']=sha(log);raise
    row.update(returncode=result.returncode,timed_out=result.timed_out,pid=result.pid,pgid=result.pid,
        live_before_cleanup=list(result.live_before_cleanup),live_after_cleanup=list(result.live_after_cleanup),
        seconds=time.monotonic()-start,completed_utc=utc())
    row['log_sha256']=sha(log);row['status']='PASS' if result.returncode==0 and not result.timed_out and not result.live_before_cleanup and not result.live_after_cleanup else 'FAIL'
    need(row['status']=='PASS',name+' failed/timed out/left an owned process group')
    return row

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vivado-root',help='Vivado root or parent containing Vivado/')
    parser.add_argument('--out',type=Path,required=True,help='fresh output path')
    parser.add_argument('--simulator',choices=('both','verilator','xsim'),default='both')
    args=parser.parse_args()
    contract=jload(CONTRACT);validate_contract(contract,Path(__file__).read_text(),BENCH.read_text())
    roots,vendor_files,location_hashes=resolve_roots(args.vivado_root,contract)
    out=Path(args.out);out=out if out.is_absolute() else ROOT/out;out=out.resolve();need(not out.exists(),'Fresh output required: '+str(out))
    include=roots[0][1]/'data/ip/xilinx/axi_infrastructure_v1_1/hdl';need(include.is_dir(),'AXI infrastructure include directory missing')
    source_paths=[]
    for _,root in roots:source_paths.extend((root/row['relative_path']).resolve() for row in contract['vendor_files'])
    source_paths.extend((BENCH,RTL,Path(__file__).resolve(),CONTRACT,README,OWNED,XSIM_RUN_TCL))
    source_paths=list(dict.fromkeys(Path(p).resolve() for p in source_paths))
    before={}
    for p in source_paths:need(p.is_file(),'Required input missing: '+str(p));before[str(p)]=sha(p)
    verilator=None
    if args.simulator in ('both','verilator'):
        found=shutil.which('verilator');need(found is not None,'Verilator is unavailable on PATH');verilator=Path(found).resolve();before[str(verilator)]=sha(verilator)
    xsim_tools={}
    if args.simulator in ('both','xsim'):
        for name in ('xvlog','xelab','xsim'):
            paths=[(root/'bin'/name).resolve() for _,root in roots]
            need(all(p.is_file() for p in paths),'Missing installed XSim tool '+name)
            need(len({sha(p) for p in paths})==1,'XSim tool differs across selected installations: '+name)
            xsim_tools[name]=paths[0];before[str(paths[0])]=sha(paths[0])
    out.mkdir(parents=True,exist_ok=False);simroot=out/'simulators';simroot.mkdir()
    revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip()
    dirty=bool(subprocess.run(['git','status','--porcelain','--untracked-files=normal'],cwd=ROOT,check=True,capture_output=True,text=True).stdout)
    record={'schema':1,'status':'RUNNING_PUBLIC_ACTUAL_CONVERTER_CONTROLS','started_utc':utc(),
        'source_revision':revision,'workspace_dirty':dirty,'vivado_roots':location_hashes,
        'primary_vendor_hashes':{k:v['sha256'] for k,v in location_hashes[str(roots[0][1])]['vendor_files'].items()},
        'source_hashes_before':before,'source_hashes_after':None,'simulator_selection':args.simulator,
        'tools':{},'commands':[],'simulator_results':{},'warning_inventory':{},'outputs':None,
        'seed':None,'stimulus':'Directed deterministic transactions; no PRNG.','runner_changed_limits':False,
        'resource_environment':None,'vivado_implementation_executed':False,'synthesis_executed':False,
        'hardware_accessed':False,'hardware_programmed':False,'flash_written':False,'bitstream_emitted':False,
        'scope':'Optional public native functional controls only; no PCIe integration, physical CDC/timing, NPU arithmetic, board/RK qualification or hardware access.'}
    report=out/'report.json'
    def save():jwrite(report,record)
    start_time=time.monotonic();cg={'runner_changed_limits':False}
    try:
        rel=next(x[3:] for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
        group=Path('/sys/fs/cgroup')/rel.lstrip('/');cg['path']=str(group)
        cg['values']={k:(group/k).read_text().strip() for k in ('cpu.max','memory.max','memory.high','memory.swap.max','pids.max')}
    except (OSError,StopIteration):cg['snapshot']='unavailable'
    try:
        cg['rlimits']={name:list(resource.getrlimit(getattr(resource,name)))
            for name in ('RLIMIT_CPU','RLIMIT_AS','RLIMIT_DATA','RLIMIT_STACK','RLIMIT_NPROC')
            if hasattr(resource,name)}
    except (OSError,ValueError):cg['rlimits_snapshot']='unavailable'
    record['resource_environment']=cg;save()
    try:
        from tools.owned_process import run_owned
        summaries=[]
        primary=roots[0][1]
        sources=[(primary/row['relative_path']).resolve() for row in contract['vendor_files'] if row['name']!='axi_infrastructure_v1_1_0.vh']
        if verilator is not None:
            d=simroot/'verilator';d.mkdir()
            version=command('verilator_version',[str(verilator),'--version'],d,30,d/'version.log',record,run_owned)
            record['tools']['verilator']={'path':str(verilator),'sha256':sha(verilator),
                'version':(d/'version.log').read_text(errors='replace'),'version_command':version}
            obj=d/'obj';argv=[str(verilator),'--binary','--timing','--assert','-Wall','-Wno-fatal','-j','2',
                '--top-module',contract['top_module'],'--Mdir',str(obj),'-I'+str(include),*map(str,sources),str(RTL),str(BENCH)]
            crow=command('verilator_compile',argv,d,600,d/'compile.log',record,run_owned)
            wins=classify_warnings((d/'compile.log').read_text(errors='replace'),roots,'verilator')
            record['warning_inventory']['verilator']=wins
            need(not wins['authored_warnings'],'Authored Verilator diagnostic must be fixed')
            need(not wins['other_warnings'],'Unclassified Verilator diagnostic must be reviewed')
            image=obj/('V'+contract['top_module']);need(image.is_file(),'Verilator executable missing')
            rrow=command('verilator_run',[str(image)],d,300,d/'run.log',record,run_owned)
            summary=parse_completion(d/'run.log',contract,'Verilator');summary.update(image_sha256=sha(image),run_log_sha256=rrow['log_sha256'])
            record['simulator_results']['verilator']=summary;summaries.append(summary)
        if xsim_tools:
            d=simroot/'xsim';d.mkdir();work=d/'work';work.mkdir();versions={}
            for name,path in xsim_tools.items():
                row=command(name+'_version',[str(path),'-version'],d,30,d/(name+'-version.log'),record,run_owned)
                versions[name]={'path':str(path),'sha256':sha(path),'version':(d/(name+'-version.log')).read_text(errors='replace'),'command':row}
            xv=command('xvlog_compile',[str(xsim_tools['xvlog']),'-sv','-i',str(include),*map(str,sources),str(RTL),str(BENCH)],
                work,600,d/'xvlog.log',record,run_owned)
            xv_w=classify_warnings((d/'xvlog.log').read_text(errors='replace'),roots,'xsim');record['warning_inventory']['xsim_xvlog']=xv_w
            need(not xv_w['authored_warnings'],'Authored XSim source diagnostic must be fixed')
            need(not xv_w['other_warnings'],'Unclassified XSim source diagnostic must be reviewed')
            xe=command('xelab',[str(xsim_tools['xelab']),'work.'+contract['top_module'],'-s','actual_converter_reset','-mt','2'],
                work,600,d/'xelab.log',record,run_owned)
            xe_w=classify_warnings((d/'xelab.log').read_text(errors='replace'),roots,'xsim');record['warning_inventory']['xsim_xelab']=xe_w
            need(not xe_w['authored_warnings'],'Authored XSim elaboration diagnostic must be fixed')
            need(not xe_w['other_warnings'],'Unclassified XSim elaboration diagnostic must be reviewed')
            xs=command('xsim_run',[str(xsim_tools['xsim']),'actual_converter_reset','-tclbatch',str(XSIM_RUN_TCL)],
                work,300,d/'xsim.log',record,run_owned)
            xs_w=classify_warnings((d/'xsim.log').read_text(errors='replace'),roots,'xsim');record['warning_inventory']['xsim']=xs_w
            need(not xs_w['authored_warnings'],'Authored XSim runtime diagnostic must be fixed')
            need(not xs_w['other_warnings'],'Unclassified XSim runtime diagnostic must be reviewed')
            summary=parse_completion(d/'xsim.log',contract,'XSim')
            summary.update(tool_versions=versions,xvlog_log_sha256=xv['log_sha256'],xelab_log_sha256=xe['log_sha256'],xsim_log_sha256=xs['log_sha256'])
            record['simulator_results']['xsim']=summary;summaries.append(summary)
        if len(summaries)>1:
            need(all(x['checks']==summaries[0]['checks'] and x['epochs']==summaries[0]['epochs'] and
                x['handshakes']==summaries[0]['handshakes'] for x in summaries[1:]),'Simulator completion/handshake summaries differ')
        after={path:sha(path) for path in before};need(after==before,'Bound vendor/public input changed during native run')
        record['source_hashes_after']=after;record['all_inputs_unchanged']=True
        record['all_owned_groups_stopped']=all(not c.get('live_after_cleanup') for c in record['commands'])
        need(record['all_owned_groups_stopped'],'An owned native simulator group remained live')
        record['outputs']=inventory(simroot);record['status']='PASS_PUBLIC_ACTUAL_CONVERTER_FUNCTIONAL_CONTROLS_REQUIRES_REVIEW'
    except BaseException as exc:
        record['status']='FAIL_PUBLIC_ACTUAL_CONVERTER_NATIVE_ATTEMPT';record['error']=repr(exc)
        try:record['source_hashes_after']={path:sha(path) for path in before};record['all_inputs_unchanged']=record['source_hashes_after']==before
        except BaseException as e:record['hash_error']=repr(e);record['all_inputs_unchanged']=False
        record['all_owned_groups_stopped']=all(not c.get('live_after_cleanup') for c in record['commands'])
        if simroot.exists():record['outputs']=inventory(simroot)
    finally:
        record['finished_utc']=utc();record['elapsed_seconds']=time.monotonic()-start_time;save()
    return 0 if record['status']=='PASS_PUBLIC_ACTUAL_CONVERTER_FUNCTIONAL_CONTROLS_REQUIRES_REVIEW' else 1

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('actual-converter controls refused/failed: '+repr(exc),file=sys.stderr);raise
