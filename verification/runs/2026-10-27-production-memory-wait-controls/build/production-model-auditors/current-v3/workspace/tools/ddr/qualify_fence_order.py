#!/usr/bin/env python3
"""Run the archived MC ordering premise against an independent PHY return model.

This is controller scheduling/ECC bookkeeping simulation, not the MIG PHY,
an AXI bridge test, a memory contents test or a hardware retirement result.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr.interface import canonical, load_json, require
from tools.ddr.run_monitor import diagnostics, ENVIRONMENT, manifest, tool_identity
from tools.evidence import timestamp

LOCAL = ('tools/ddr/qualify_fence_order.py', 'tools/ddr/interface.py',
         'tests/ddr/tb_mig_fence_order.sv', 'fpga/ddr/xdma_archive_reference.json',
         'fpga/ddr/xdma_retirement_contract.json', 'tools/ddr/run_monitor.py',
         'tools/ddr/__init__.py', 'tools/evidence.py',
         'tests/ddr/fence_mc/warnings.json', 'tests/ddr/fence_mc/test_qualifier.py',
         'tests/ddr/fence_mc/tb_round_robin_width.sv', 'tests/ddr/fence_mc/check_round_robin.sv',
         'fpga/ddr/patches/round_robin_width_one.json')
SCOPE = 'Separately identified WIDTH1-fixed archived MC scheduling/ECC bookkeeping with modeled PHY returns; no original-controller, AXI/UI bridge, MIG PHY, memory-content or global-drain qualification'
PRIMITIVES = {
    'RAM32M.v': '109bf9683d22755429ad95a9ad19547b79f4afc90064cb2f7621e0c4f114a4e6',
    'SRLC32E.v': '9837e9e530292cc0976c5e8a3ca7914a60696bb08148191bbf3f7e5f488f2d10',
}
PARAMETERS = dict(TCQ=100, ADDR_CMD_MODE='1T', BANK_WIDTH=3, BM_CNT_WIDTH=2,
    BURST_MODE='8', CL=7, CMD_PIPE_PLUS1='ON', COL_WIDTH=10, CS_WIDTH=1, CWL=6,
    DATA_BUF_ADDR_WIDTH=5, DATA_BUF_OFFSET_WIDTH=1, DATA_WIDTH=64, DQ_WIDTH=72,
    DQS_WIDTH=9, DRAM_TYPE='DDR3', ECC='ON', ECC_WIDTH=8,
    MAINT_PRESCALER_PERIOD=200000, MC_ERR_ADDR_WIDTH=29, nBANK_MACHS=4,
    nCK_PER_CLK=4, nCS_PER_RANK=1, nREFRESH_BANK=1, nSLOTS=1, ORDERING='NORM',
    PAYLOAD_WIDTH=64, RANK_WIDTH=1, RANKS=1, REG_CTRL='OFF', ROW_WIDTH=15,
    RTT_NOM='60', RTT_WR='OFF', SLOT_0_CONFIG=15, SLOT_1_CONFIG=0, STARVE_LIMIT=2,
    tCK=1875, tCKE=5000, tFAW=30000, tRAS=35000, tRCD=13750, tREFI=7800000,
    CKE_ODT_AUX='FALSE', tRFC=160000, tRP=13750, tRRD=6000, tRTP=7500,
    tWTR=7500, tZQCS=64, tZQI=128000000, tPRDI=1000000, USER_REFRESH='OFF')
MODES = {0:'same_last_address_cross_bank', 1:'unrelated_bank_negative_control',
         2:'same_bank_different_row', 3:'repeated_same_address',
         4:'phy_full_backpressure', 5:'rmw_uncorrectable_error',
         6:'full_zero_write_same_last_address', 7:'full_zero_write_unrelated_bank_negative'}
RESULT = re.compile(r'PASS mig_fence_order mode=(\d+) accepted=(\d+) read_columns=(\d+) '
    r'write_columns=(\d+) phy_returns=(\d+) native_returns=(\d+) w1=(\d+) w2=(\d+) '
    r'rmw2=(\d+) fence=(\d+) ue=(\d+) scope=actual_MC_modeled_PHY_only')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(path):
    return dict(path=os.path.abspath(path), sha256=sha(path))


def fingerprints(paths):
    files = {str(Path(p).relative_to(ROOT)): sha(p) for p in sorted(paths)}
    return dict(files=files, sha256=hashlib.sha256(canonical(files)).hexdigest())


def source_revision():
    return fingerprints([ROOT/name for name in LOCAL])


def safe_path(name):
    require(type(name) is str, 'Artifact path must be a string')
    path=Path(name)
    require(path.parts and not path.is_absolute() and '..' not in path.parts and str(path)==name,
            'Unsafe relative artifact path')
    require((ROOT/path).resolve().is_relative_to(ROOT.resolve()),'Artifact path escapes copied root')
    return ROOT/path


def parameter_include(producer, output):
    name=str(Path(producer)/output/'mc_parameters.svh')
    require(Path(name).is_absolute() and not any(c in name for c in ('"','\\')) and
            all(ord(c)>=32 and ord(c)!=127 for c in name),'Unsupported absolute parameter include path')
    return '-DRK_MIG_MC_PARAMS_HEADER='+json.dumps(name,ensure_ascii=False)


def version_plan(simulator, tools):
    result=[('simulator-version',[tools['simulator']['path'],'-V' if simulator=='iverilog' else '--version'],'simulator')]
    return result+([('runtime-version',[tools['runtime']['path'],'-V'],'runtime')] if simulator=='iverilog' else
                   [('cxx-version',[tools['cxx']['path'],'--version'],'cxx')])


def compile_plan(simulator, producer, output, tools, compiled):
    producer=Path(producer);directory=producer/output
    define=parameter_include(producer,output)
    sources=[str(producer/'tests/ddr/tb_mig_fence_order.sv')]+[str(producer/name) for name in compiled]
    if simulator=='iverilog':
        image=str(Path(output)/'mc.vvp')
        build=[tools['simulator']['path'],'-g2012','-Wall','-s','tb_mig_fence_order',define,
               '-o',str(producer/image),*sources]
        run=[tools['runtime']['path'],str(producer/image)]
    else:
        image=str(Path(output)/'obj/sim')
        build=[tools['simulator']['path'],'--binary','--timing','--assert','-Wall','-Wno-fatal',
               '--top-module','tb_mig_fence_order','-j','2','-MAKEFLAGS','CXX='+shlex.quote(tools['cxx']['path']),
               '--Mdir',str(directory/'obj'),'-o','sim',define,*sources]
        run=[str(producer/image)]
    return dict(build=build,run=run,image=image)


def arbiter_plans(simulator, producer, output, tools, variant):
    producer=Path(producer);plans={}
    selections=[('arbiter-original-multi',variant['original'],0),('arbiter-variant',variant['derived'],1)]
    if simulator=='iverilog':selections.append(('arbiter-original-one',variant['original'],1))
    for name,source,include_one in selections:
        sources=[str(producer/'tests/ddr/fence_mc/tb_round_robin_width.sv'),
                 str(producer/'tests/ddr/fence_mc/check_round_robin.sv'),str(producer/source)]
        if simulator=='iverilog':
            image=str(Path(output)/(name+'.vvp'))
            build=[tools['simulator']['path'],'-g2012','-Wall','-s','tb_round_robin_width',
                   '-Ptb_round_robin_width.INCLUDE_WIDTH_ONE='+str(include_one),'-o',str(producer/image),*sources]
            run=[tools['runtime']['path'],str(producer/image)]
        else:
            image=str(Path(output)/name/'sim')
            build=[tools['simulator']['path'],'--binary','--timing','--assert','-Wall','-Wno-fatal',
                '--top-module','tb_round_robin_width','-GINCLUDE_WIDTH_ONE='+str(include_one),'-j','2',
                '-MAKEFLAGS','CXX='+shlex.quote(tools['cxx']['path']),
                '--Mdir',str(producer/output/name),'-o','sim',*sources]
            run=[str(producer/image)]
        plans[name]=dict(build=build,run=run,image=image,expected_returncode=1 if name=='arbiter-original-one' else 0)
    return plans


def validate_arbiter(text, name):
    if name=='arbiter-original-one':
        failures=[l for l in text.splitlines() if re.match(r'^(FATAL:|FAIL|ERROR:|%Error)',l)]
        require(len(failures)==1 and failures[0].endswith('WIDTH1_UNDRIVEN_INHIBIT_GROUP') and
                not any(l.startswith('PASS ') for l in text.splitlines()),
                'Original WIDTH1 failure was not reproduced')
        return dict(name=name,expected_failure=True,marker='WIDTH1_UNDRIVEN_INHIBIT_GROUP'),[]
    widths=[2,3,4] if name=='arbiter-original-multi' else [1,2,3,4]
    expected=f'PASS round_robin_width widths={len(widths)} cases_per_width=128 scope=actual_arbiter_only'
    require([l for l in text.splitlines() if l.startswith('PASS ')]==[expected],'Arbiter result inventory changed')
    rows=[]
    for line in text.splitlines():
        if not line.startswith('TRACE '):continue
        match=re.fullmatch(r'TRACE ARBITER width=(\d+) step=(\d+) req=([0-9a-f]+) reset=(\d+) disable=(\d+) update=(\d+) current=([0-9a-f]+) grant=([0-9a-f]+) registered=([0-9a-f]+)',line)
        require(match is not None,'Malformed arbiter trace')
        row=[int(match[i],16 if i in (3,7,8,9) else 10) for i in range(1,10)];rows.append(row)
    rows.sort();require(len(rows)==128*len(widths),'Arbiter trace inventory changed')
    for width in widths:
        last=width-1;subset=[r for r in rows if r[0]==width]
        require([r[1] for r in subset]==list(range(128)),'Arbiter step coverage changed')
        for _,step,req,rst,disable,update,current,grant,registered in subset:
            require((req,rst,disable,update,current)==(((step*13)^(step>>2))&((1<<width)-1),int(step%31==0),int(step%7==3),int(step%3!=0),1<<(step%width)),
                    'Arbiter stimulus changed')
            basis=width-1 if rst else step%width if update else last
            expected_grant=0
            for offset in range(1,width+1):
                candidate=(basis+offset)%width
                if not disable and not expected_grant and req&(1<<candidate):expected_grant=1<<candidate
            require(grant==registered==expected_grant,'Arbiter truth/registered timing changed');last=basis
    return dict(name=name,widths=widths,cases_per_width=128,events=len(rows),trace_sha256=hashlib.sha256(canonical(rows)).hexdigest()),rows


def apply_variant(data, descriptor):
    require(hashlib.sha256(data).hexdigest()==descriptor['original_sha256'],'Variant original source differs')
    old=descriptor['replace_once']['old'].encode();new=descriptor['replace_once']['new'].encode()
    require(data.count(old)==1,'Variant replacement must match exactly once')
    patched=data.replace(old,new)
    require(hashlib.sha256(patched).hexdigest()==descriptor['patched_sha256'],'Variant patched identity differs')
    return patched


def expected_inputs(output):
    catalog=load_json(ROOT/'fpga/ddr/xdma_archive_reference.json');files={};members={};compiled=[]
    contract=load_json(ROOT/'fpga/ddr/xdma_retirement_contract.json')
    require(contract['catalog']['sha256']==sha(ROOT/'fpga/ddr/xdma_archive_reference.json') and
            contract['catalog']['archive_sha256']==catalog['archive']['sha256'],'Retirement/catalog binding changed')
    for member,entry in catalog['members'].items():
        name=member.removeprefix(catalog['member_prefix'])
        require(name!=member and not Path(name).is_absolute() and '..' not in Path(name).parts,'Unsafe archive member')
        name=str(Path(output)/'source'/name);safe_path(name)
        files[name]=entry['sha256'];members[member]=name
        if '/user_design/rtl/controller/' in member or '/user_design/rtl/ecc/' in member:compiled.append(name)
    for name,value in PRIMITIVES.items():
        relative=str(Path(output)/'primitives'/name);files[relative]=value;compiled.append(relative)
    descriptor=load_json(ROOT/'fpga/ddr/patches/round_robin_width_one.json')
    require(descriptor['archive_sha256']==catalog['archive']['sha256'] and
            descriptor['original_sha256']==catalog['members'][descriptor['member']]['sha256'],
            'Variant/archive source binding differs')
    original=members[descriptor['member']]
    require(original in compiled,'Patched arbiter is not a compiled source')
    variant=str(Path(output)/'variant'/Path(original).name)
    files[variant]=descriptor['patched_sha256'];compiled.remove(original);compiled.append(variant)
    variant_info=dict(descriptor_sha256=sha(ROOT/'fpga/ddr/patches/round_robin_width_one.json'),
        variant_id=descriptor['variant_id'],original=original,derived=variant,
        original_sha256=descriptor['original_sha256'],patched_sha256=descriptor['patched_sha256'])
    header=',\n'.join('.'+name+'('+json.dumps(value)+')' for name,value in PARAMETERS.items())+'\n'
    header_name=str(Path(output)/'mc_parameters.svh');files[header_name]=hashlib.sha256(header.encode()).hexdigest()
    return dict(files=files,members=members,compiled=sorted(compiled),header=header,header_name=header_name,
                archive_sha256=catalog['archive']['sha256'],variant=variant_info)


def check_copied_parameters(output):
    base=Path(output)/'source/top_mig_7series_0_0/user_design/rtl'
    check_parameters(safe_path(str(base/'top_mig_7series_0_0_mig.v')).read_text(),
                     safe_path(str(base/'controller/mig_7series_v4_2_mc.v')).read_text(),
                     safe_path(str(base/'ip_top/mig_7series_v4_2_mem_intfc.v')).read_text())


def check_variant(plan):
    descriptor=load_json(ROOT/'fpga/ddr/patches/round_robin_width_one.json')
    require(apply_variant(safe_path(plan['variant']['original']).read_bytes(),descriptor)==
            safe_path(plan['variant']['derived']).read_bytes(),'Derived source does not reproduce the patch')


def check_inputs(expected):
    require(fingerprints([safe_path(p) for p in expected['files']])==expected,'Execution input changed')


def literal_parameter(text, name):
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    values = re.findall(r'\bparameter\s+(?:(?:integer|real)\s+)?'+re.escape(name)+r'\s*=\s*([^,;\n]+)', text)
    require(len(values)==1, 'Missing/duplicate source parameter '+name)
    value=values[0].strip()
    if re.fullmatch(r'"[^"\n]+"',value): return value[1:-1]
    if re.fullmatch(r'[0-9][0-9_]*',value): return int(value.replace('_',''))
    match=re.fullmatch(r"[0-9]+'([bdh])([0-9a-fA-F_]+)",value)
    require(match is not None,'Unsupported source parameter '+name+': '+value)
    return int(match[2].replace('_',''),{'b':2,'d':10,'h':16}[match[1]])


def check_parameters(core, mc, memory_interface):
    derived={'BM_CNT_WIDTH','DATA_BUF_OFFSET_WIDTH','ECC_WIDTH','MC_ERR_ADDR_WIDTH',
             'PAYLOAD_WIDTH','RANK_WIDTH','nSLOTS','SLOT_0_CONFIG','SLOT_1_CONFIG'}
    defaults={'MAINT_PRESCALER_PERIOD','nREFRESH_BANK','DRAM_TYPE'}
    for name,expected in PARAMETERS.items():
        if name in derived: continue
        if name in defaults: actual=literal_parameter(mc,name)
        elif name=='STARVE_LIMIT': actual=literal_parameter(core,name)
        else: actual=literal_parameter(core,'C0_'+name)
        require(type(actual) is type(expected) and actual==expected,'MC parameter mismatch: '+name)
    require(literal_parameter(core,'C0_RANKS')==1 and literal_parameter(core,'C0_CS_WIDTH')==1 and
            literal_parameter(core,'C0_SLOT_1_CONFIG')==0,'Unsupported rank/slot profile')
    # These fixed expressions are part of the separately hashed generated inputs.
    require('localparam C0_DATA_BUF_OFFSET_WIDTH = 1;' in core and
            'localparam C0_MC_ERR_ADDR_WIDTH = ((C0_CS_WIDTH == 1) ? 0 : C0_RANK_WIDTH)' in core,
            'Derived address-width source changed')
    require("localparam SLOT_0_CONFIG_MC = (nSLOTS == 2)? 8'b0000_0101 : 8'b0000_1111;" in memory_interface,
            'MC slot mapping source changed')


def prepare(archive, unisim, out):
    catalog=load_json(ROOT/'fpga/ddr/xdma_archive_reference.json')
    require(sha(archive)==catalog['archive']['sha256'],'Archive identity differs')
    paths=[];compiled=[];mapping={}
    with zipfile.ZipFile(archive) as bundle:
        require(len(bundle.namelist())==len(set(bundle.namelist())),'Duplicate archive member')
        for member,entry in catalog['members'].items():
            data=bundle.read(member)
            require(len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256'],
                    'Archive member identity differs: '+member)
            name=member.removeprefix(catalog['member_prefix'])
            require(name!=member and '..' not in Path(name).parts and not Path(name).is_absolute(),'Unsafe archive path')
            path=out/'source'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            paths.append(path);mapping[member]=str(path.relative_to(ROOT))
            if '/user_design/rtl/controller/' in member or '/user_design/rtl/ecc/' in member:compiled.append(path)
    base=out/'source/top_mig_7series_0_0/user_design/rtl'
    check_parameters((base/'top_mig_7series_0_0_mig.v').read_text(),
                     (base/'controller/mig_7series_v4_2_mc.v').read_text(),
                     (base/'ip_top/mig_7series_v4_2_mem_intfc.v').read_text())
    for name,expected in PRIMITIVES.items():
        require(sha(unisim/name)==expected,'Primitive model identity differs: '+name)
        path=out/'primitives'/name;path.parent.mkdir(exist_ok=True);shutil.copyfile(unisim/name,path)
        paths.append(path);compiled.append(path)
    plan=expected_inputs(str(out.relative_to(ROOT)))
    descriptor=load_json(ROOT/'fpga/ddr/patches/round_robin_width_one.json')
    variant=safe_path(plan['variant']['derived']);variant.parent.mkdir(parents=True,exist_ok=True)
    variant.write_bytes(apply_variant(safe_path(plan['variant']['original']).read_bytes(),descriptor))
    paths.append(variant);compiled.remove(safe_path(plan['variant']['original']));compiled.append(variant)
    header=out/'mc_parameters.svh'
    header.write_text(',\n'.join('.'+name+'('+json.dumps(value)+')' for name,value in PARAMETERS.items())+'\n')
    paths.append(header)
    return paths,sorted(compiled),header,mapping


def validate_result(text, mode):
    require(mode in MODES,'Unknown MC scenario')
    full=mode>=6;negative=mode in (1,7)
    matches=[RESULT.fullmatch(line) for line in text.splitlines() if line.startswith('PASS ')]
    require(len(matches)==1 and matches[0] is not None,'Missing/unknown MC ordering result')
    values=list(map(int,matches[0].groups()))
    m,accepted,reads,writes,phy,native,w1,w2,rmw,fence,ue=values
    require(m==mode and (accepted,reads,writes,phy,native)==(4,2 if full else 4,2,2 if full else 4,2),'MC test inventory changed')
    require(0<w1<w2 and (rmw==0 if full else 0<rmw<w2) and fence>0,'Invalid actual command/return ordering')
    require((fence<w1) if negative else (fence>w2),'Fence/negative-control ordering failed')
    require(ue==(1 if mode==5 else 0),'ECC outcome differs')
    accepts=[];columns=[];returns=[];responses=[];zero_data=[]
    patterns={
        'ACCEPT':r'TRACE ACCEPT cycle=(\d+) tag=(\d+) bank=(\d+) row=(\d+) col=(\d+) op=(\d+)',
        'COLUMN':r'TRACE COLUMN cycle=(\d+) tag=(\d+) bank=(\d+) row=(\d+) col=(\d+) read=(\d+) rmw=(\d+)',
        'PHY':r'TRACE PHY cycle=(\d+) tag=(\d+) rmw=(\d+) periodic=(\d+)',
        'RESPONSE':r'TRACE RESPONSE cycle=(\d+) tag=(\d+)',
        'FULL_WRITE_DATA':r'TRACE FULL_WRITE_DATA cycle=(\d+) data=0 mask=0'}
    buckets={'ACCEPT':accepts,'COLUMN':columns,'PHY':returns,'RESPONSE':responses,'FULL_WRITE_DATA':zero_data}
    for line in text.splitlines():
        if not line.startswith('TRACE '):continue
        kind=line.split()[1];require(kind in patterns,'Unknown MC trace event')
        match=re.fullmatch(patterns[kind],line);require(match is not None,'Malformed MC trace event')
        event=tuple(map(int,match.groups()));require(0<event[0]<5000,'Trace exceeds bench watchdog')
        buckets[kind].append(event)
    expected=[(4,2,0,8,1),(1,1 if mode in (2,3) else 0,0,0,0 if full else 3),
              (2,1,1 if mode==2 else 0,0 if mode==3 else 8,0 if full else 3),
              (3,2 if negative else 1,1 if mode==2 else 0,0 if mode==3 else 8,1)]
    require([v[1:] for v in accepts]==expected and all(0<v[0]<5000 for v in accepts),'Native acceptance trace changed')
    require(all(a[0]<b[0] for a,b in zip(accepts,accepts[1:])),'Native acceptance times changed')
    accepted_by_tag={v[1]:v for v in accepts};read_by_tag={};write_by_tag={}
    require(len(columns)==(4 if full else 6) and len(responses)==2,'Actual column/response inventory changed')
    require(len(zero_data)==(2 if full else 0) and all(a[0]<b[0] for a,b in zip(zero_data,zero_data[1:])),
            'Full zero-write data/ECC beat inventory changed')
    for event in columns:
        cycle,tag,bank,row,col,read,is_rmw=event
        require(tag in accepted_by_tag and read in (0,1) and is_rmw in (0,1),'Unknown column request')
        request=accepted_by_tag[tag]
        require(cycle>request[0] and (bank,row,col&1023)==request[2:5],'Column/source address association changed')
        bucket=read_by_tag if read else write_by_tag
        require(tag not in bucket,'Duplicate column request');bucket[tag]=cycle
        require(is_rmw==int(read and tag in (1,2) and not full),'RMW classification changed')
    require(set(read_by_tag)==({3,4} if full else {1,2,3,4}) and list(write_by_tag)==[1,2],'Actual read/write column coverage changed')
    if not negative:require(read_by_tag[3]>write_by_tag[2],'Same-address read issued before final write')
    if full:
        require(all(zero_data[index][0]>write_by_tag[index+1] for index in (0,1)),
                'Encoded data beat preceded its ordered WRITE column')
        require(fence<zero_data[0][0] if negative else zero_data[1][0]<read_by_tag[3],
                'Full-write fence/data ordering changed')
    user_returns={}
    for cycle,tag,is_rmw,periodic in returns:
        require(periodic in (0,1),'Invalid periodic return flag')
        if periodic:continue
        require(tag in read_by_tag and tag not in user_returns and cycle>read_by_tag[tag],
                'PHY return did not follow unique actual read column')
        require(is_rmw==int(tag in (1,2) and not full),'PHY RMW association changed');user_returns[tag]=cycle
    require(set(user_returns)==({3,4} if full else {1,2,3,4}),'Missing modeled PHY return')
    if not full:require(all(write_by_tag[tag]>user_returns[tag] for tag in (1,2)),'Write column preceded its RMW return')
    require([tag for _,tag in responses]==[4,3] and
            all(cycle>user_returns[tag] for cycle,tag in responses),'Native response ordering changed')
    require(responses[0][0]<accepted_by_tag[1][0],'Priming read overlaps the write epoch')
    require((w1,w2,rmw,fence)==(write_by_tag[1],write_by_tag[2],0 if full else user_returns[2],responses[-1][0]),
            'Summary differs from actual column/return trace')
    result=dict(mode=mode,name=MODES[mode],accepted=accepted,read_columns=reads,write_columns=writes,
                phy_returns=phy,native_returns=native,write_cycles=[w1,w2],final_rmw_return=rmw,
                fence_return=fence,ue_cycles=ue,
                outcome='UE_OBSERVED_NOT_JOB_SUCCESS' if mode==5 else
                        'UNRELATED_ADDRESS_BYPASS_OBSERVED' if negative else 'ORDERING_CONDITION_OBSERVED')
    if full:result.update(native_write_opcode=0,user_rmw_read_columns=0,zero_data_ecc_beats=2)
    return result


def warning_policy(plan):
    policy=load_json(ROOT/'tests/ddr/fence_mc/warnings.json')
    require(policy['review_status']=='REVIEWED_FOR_BOUNDED_MC_MODEL','Warning inventory awaits review')
    expected={Path(name).name:value for name,value in plan['files'].items() if name in plan['compiled']}
    require(policy['compiled_source_sha256']==expected,'Warning/source identity differs')
    require(policy['bench_sha256']==sha(ROOT/'tests/ddr/tb_mig_fence_order.sv'),'Warning/bench identity differs')
    require(policy['arbiter_bench_sha256']==sha(ROOT/'tests/ddr/fence_mc/tb_round_robin_width.sv') and
            policy['arbiter_helper_sha256']==sha(ROOT/'tests/ddr/fence_mc/check_round_robin.sv') and
            policy['original_arbiter_sha256']==plan['variant']['original_sha256'],'Arbiter warning/source identity differs')
    return policy


def verify_record(report):
    require(type(report.get('schema_version')) is int and report['schema_version']==3,'Incomplete eight-mode execution binding')
    require(report['status']=='PASS_ACTUAL_MC_MODELED_PHY_ORDERING_CASES' and report['complete_matrix'] is True,
            'Complete MC ordering matrix required')
    require(report['scope']==SCOPE and report['source']==source_revision(),'Source/scope changed')
    require(canonical(report['parameters'])==canonical(PARAMETERS),'MC parameters changed')
    require(report['actual_mc_source_variant_simulated'] is True,'Actual MC source variant execution required')
    for key in ('controller_phy_simulated','axi_ui_bridge_simulated','hardware_accessed','vivado_executed',
                'vendor_ip_generated','physical_integration_ready','joint_reset_drain_verified','original_controller_qualified'):
        require(report[key] is False,'Unsupported integration claim: '+key)
    require(report['seed'] is None and report['stimuli']=='Directed; no PRNG','Stimulus contract changed')
    simulator=report['simulator'];require(simulator in ('iverilog','verilator'),'Unknown simulator')
    output=report['output_directory'];safe_path(output)
    producer=Path(report['execution_root']);require(producer.is_absolute(),'Producer root missing')
    plan=expected_inputs(output);policy=warning_policy(plan)
    require(report['archive_sha256']==plan['archive_sha256'] and report['archive_members']==plan['members'],
            'Archived source inventory changed')
    inputs=manifest(report['source']['files']|plan['files'])
    require(report['execution_inputs']==inputs,'Input inventory changed');check_inputs(inputs)
    check_copied_parameters(output)
    check_variant(plan)
    require(report['source_variant']==plan['variant'],'Original/derived controller identity changed')
    require(safe_path(plan['header_name']).read_text()==plan['header'],'Parameter header changed')
    tools=report['tools'];require(set(tools)=={'simulator','runtime' if simulator=='iverilog' else 'cxx'},'Tool inventory changed')
    for role,item in tools.items():
        basename=simulator if role=='simulator' else 'vvp' if role=='runtime' else 'c++'
        require(set(item)=={'path','sha256'} and Path(item['path']).is_absolute() and
                Path(item['path']).name==basename,'Tool executable identity invalid')
        require(re.fullmatch('[0-9a-f]{64}',item['sha256']) is not None,'Malformed executable digest')
    build=compile_plan(simulator,producer,output,tools,plan['compiled'])
    arbiters=arbiter_plans(simulator,producer,output,tools,plan['variant'])
    versions=version_plan(simulator,tools)
    names=[name for name,_,_ in versions]+[name+'-'+phase for name in arbiters for phase in ('build','run')]+['build']+['mode'+str(mode) for mode in MODES]
    require([c['name'] for c in report['commands']]==names,'Command selection/order changed')
    commands={c['name']:c for c in report['commands']}
    files=report['artifacts']['files'];require(manifest(files)==report['artifacts'],'Artifact manifest changed')
    expected_files=set(plan['files'])|{str(Path(output)/(name+'.log')) for name in names}|{build['image']}|{p['image'] for p in arbiters.values()}
    require(set(files)==expected_files,'Artifact closure changed')
    for name,value in files.items():require(sha(safe_path(name))==value,'Artifact changed: '+name)
    image=dict(path=build['image'],sha256=files[build['image']])
    require(report['binary_sha256']==image['sha256'],'Binary receipt changed')
    def command(name,argv,executable,expected_returncode=0):
        item=commands[name];log=str(Path(output)/(name+'.log'))
        require(item['argv']==argv and item['environment_overrides']==ENVIRONMENT,'Execution command changed: '+name)
        require(type(item['returncode']) is int and item['returncode']==expected_returncode and
                item['expected_returncode']==expected_returncode and
                item['status']==('PASS' if expected_returncode==0 else 'EXPECTED_FAILURE'),'Command outcome changed')
        require(item['executable_before']==item['executable_after']==executable,'Executable linkage changed')
        require(item['log']==log and item['log_sha256']==files[log],'Log linkage changed')
        text=safe_path(log).read_text()
        if expected_returncode==0:require(not re.search(r'(?m)^(FATAL:|FAIL|ERROR:|%Error)',text),'Failure marker in log')
        return item,text
    for name,argv,role in versions:
        _,text=command(name,argv,tools[role]);field={'simulator':'simulator_version','runtime':'runtime_version','cxx':'cxx_version'}[role]
        require(text.splitlines() and text.splitlines()[0]==report[field],'Version/log linkage changed')
    require(report['simulator_version']==policy[simulator+'_version'],'Warning tool version changed')
    controls=[];traces={}
    for name,arb in arbiters.items():
        arb_image=dict(path=arb['image'],sha256=files[arb['image']])
        built,text=command(name+'-build',arb['build'],tools['simulator'])
        require(built['inputs_before']==built['inputs_after']==inputs and built['output_image']==arb_image,'Arbiter build binding changed')
        require(diagnostics(text,simulator)==policy['arbiter'][simulator][name]==built['admitted_diagnostics'],'Arbiter warning inventory changed')
        executable=tools['runtime'] if simulator=='iverilog' else dict(path=str(producer/arb_image['path']),sha256=arb_image['sha256'])
        ran,text=command(name+'-run',arb['run'],executable,arb['expected_returncode'])
        require(ran['inputs_before']==ran['inputs_after']==inputs and ran['image']==arb_image['path'] and
                ran['image_before']==ran['image_after']==arb_image['sha256'],'Arbiter execution binding changed')
        result,rows=validate_arbiter(text,name);controls.append(result);traces[name]=rows
    require(traces['arbiter-original-multi']==[r for r in traces['arbiter-variant'] if r[0]>=2],
            'Variant changed multi-requestor behavior')
    require(report['arbiter_controls']==controls,'Arbiter control result changed')
    built,text=command('build',build['build'],tools['simulator'])
    require(built['inputs_before']==built['inputs_after']==inputs and built['output_image']==image,'Compiled input/image linkage changed')
    require(diagnostics(text,simulator)==policy[simulator]==built['admitted_diagnostics'],'Warning inventory changed')
    tests=[]
    for mode in MODES:
        executable=tools['runtime'] if simulator=='iverilog' else dict(path=str(producer/image['path']),sha256=image['sha256'])
        item,text=command('mode'+str(mode),build['run']+['+MODE='+str(mode)],executable)
        require(item['inputs_before']==item['inputs_after']==inputs and item['image']==image['path'] and
                item['image_before']==item['image_after']==image['sha256'],'Runtime input/image linkage changed')
        tests.append(validate_result(text,mode))
    require(report['tests']==tests,'MC trace/result linkage changed')
    return dict(status='VERIFIED_ACTUAL_MC_MODELED_PHY_ORDERING_CASES',modes=list(MODES),
                source_variant=plan['variant']['variant_id'],arbiter_controls=[r['name'] for r in controls],
                axi_ui_bridge_simulated=False,physical_integration_ready=False,joint_reset_drain_verified=False)


def verify_report(path):
    return verify_record(load_json(path))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--primitive-library',type=Path,help='Pinned official Vivado XECLIB functional sources')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--simulator',choices=('iverilog','verilator'),default='iverilog')
    parser.add_argument('--mode',type=int,choices=tuple(MODES))
    parser.add_argument('--verify',type=Path,help='Verify copied evidence without the original tools/archive')
    args=parser.parse_args()
    if args.verify:
        require(args.archive is None and args.out is None and args.mode is None,'Verification does not run tools')
        print(json.dumps(verify_report(args.verify),indent=2));return 0
    require(args.archive is not None,'--archive is required for native execution')
    out=(args.out or ROOT/'build/ddr-fence-order'/f'{args.simulator}-{time.time_ns()}').resolve()
    require(out.is_relative_to(ROOT) and not out.exists(),'Fresh in-workspace output required');out.mkdir(parents=True)
    report=dict(schema_version=3,status='RUNNING',scope=SCOPE,source=source_revision(),
                execution_root=str(ROOT),output_directory=str(out.relative_to(ROOT)),started_utc=timestamp(),
                simulator=args.simulator,commands=[],tests=[],arbiter_controls=[],tools={},parameters=PARAMETERS,
                seed=None,stimuli='Directed; no PRNG',controller_phy_simulated=False,
                actual_mc_source_variant_simulated=True,original_controller_qualified=False,
                axi_ui_bridge_simulated=False,complete_matrix=args.mode is None,
                hardware_accessed=False,vivado_executed=False,vendor_ip_generated=False,
                physical_integration_ready=False,joint_reset_drain_verified=False)
    report_path=out/'report.json';artifacts=[]
    def save():report_path.write_text(json.dumps(report,indent=2)+'\n')
    def execute(name,argv,inputs=None,image=None,expected_returncode=0):
        for item in report['tools'].values():require(identity(item['path'])==item,'Selected tool changed')
        entry=dict(name=name,argv=[str(x) for x in argv],executable_before=identity(argv[0]),
                   status='RUNNING',expected_returncode=expected_returncode,environment_overrides=ENVIRONMENT,
                   log=str((out/(name+'.log')).relative_to(ROOT)))
        if inputs is not None:
            check_inputs(report['execution_inputs']);entry['inputs_before']=fingerprints(inputs)
        if image is not None:entry.update(image=str(image.relative_to(ROOT)),image_before=sha(image))
        report['commands'].append(entry);save();start=time.monotonic()
        try:
            with (ROOT/entry['log']).open('w') as log:
                result=subprocess.run(entry['argv'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                                      timeout=180,env=dict(os.environ,**ENVIRONMENT))
            entry.update(returncode=result.returncode,status=('PASS' if expected_returncode==0 else 'EXPECTED_FAILURE') if result.returncode==expected_returncode else 'FAIL',
                         executable_after=identity(argv[0]))
            require(entry['executable_before']==entry['executable_after'],'Executable changed')
            for item in report['tools'].values():require(identity(item['path'])==item,'Selected tool changed during execution')
            if inputs is not None:
                check_inputs(report['execution_inputs']);entry['inputs_after']=fingerprints(inputs)
                require(entry['inputs_before']==entry['inputs_after'],'Source/input changed')
            if image is not None:
                entry['image_after']=sha(image);require(entry['image_before']==entry['image_after'],'Executed image changed')
        except subprocess.TimeoutExpired:
            entry['status']='TIMEOUT';raise
        finally:
            entry['seconds']=round(time.monotonic()-start,3)
            path=ROOT/entry['log']
            if path.exists():entry['log_sha256']=sha(path);artifacts.append(path)
            save()
        require(result.returncode==expected_returncode,'Native command outcome differed: '+name)
        text=(ROOT/entry['log']).read_text()
        if expected_returncode==0:require(not re.search(r'(?m)^(FATAL:|FAIL|ERROR:|%Error)',text),'Failure marker')
        return text
    save()
    try:
        sim=shutil.which(args.simulator);require(sim is not None,'Simulator unavailable')
        report['tools']['simulator']=identity(sim)
        role='runtime' if args.simulator=='iverilog' else 'cxx'
        tool=shutil.which('vvp' if role=='runtime' else 'c++');require(tool is not None,'Runtime/compiler unavailable')
        report['tools'][role]=identity(tool)
        for name,argv,role in version_plan(args.simulator,report['tools']):
            field={'simulator':'simulator_version','runtime':'runtime_version','cxx':'cxx_version'}[role]
            report[field]=execute(name,argv).splitlines()[0]
        if args.primitive_library:unisim=args.primitive_library.expanduser().resolve()
        else:
            vivado=shutil.which('vivado');require(vivado is not None,'Use --primitive-library for the pinned functional model directory')
            unisim=Path(vivado).resolve().parents[1]/'data/verilog/src/xeclib'
        inputs,compiled,header,mapping=prepare(args.archive.expanduser().resolve(),unisim,out)
        artifacts+=inputs;inputs += [ROOT/p for p in LOCAL]
        report['archive_sha256']=sha(args.archive.expanduser().resolve());report['archive_members']=mapping
        report['execution_inputs']=fingerprints(inputs)
        expected=expected_inputs(report['output_directory']);policy=warning_policy(expected)
        report['source_variant']=expected['variant']
        require(report['execution_inputs']==manifest(report['source']['files']|expected['files']),'Extracted closure differs')
        require(report['simulator_version']==policy[args.simulator+'_version'],'Warning policy tool version differs')
        arb_traces={}
        for name,arb in arbiter_plans(args.simulator,ROOT,report['output_directory'],report['tools'],expected['variant']).items():
            image_path=ROOT/arb['image'];text=execute(name+'-build',arb['build'],inputs=inputs)
            actual=diagnostics(text,args.simulator)
            require(actual==policy['arbiter'][args.simulator][name],'Unexpected arbiter compiler diagnostic')
            image=dict(path=arb['image'],sha256=sha(image_path))
            report['commands'][-1].update(output_image=image,admitted_diagnostics=actual);artifacts.append(image_path)
            text=execute(name+'-run',arb['run'],inputs=inputs,image=image_path,expected_returncode=arb['expected_returncode'])
            result,rows=validate_arbiter(text,name);report['arbiter_controls'].append(result);arb_traces[name]=rows
            require(sha(image_path)==image['sha256'],'Arbiter compiled/executed image differs')
        require(arb_traces['arbiter-original-multi']==[r for r in arb_traces['arbiter-variant'] if r[0]>=2],
                'Variant changed original multi-requestor behavior')
        plan=compile_plan(args.simulator,ROOT,report['output_directory'],report['tools'],expected['compiled'])
        binary=ROOT/plan['image'];build_text=execute('build',plan['build'],inputs=inputs)
        actual=diagnostics(build_text,args.simulator);require(actual==policy[args.simulator],'Unexpected compiler diagnostic')
        report['commands'][-1]['admitted_diagnostics']=actual
        image=dict(path=plan['image'],sha256=sha(binary));report['commands'][-1]['output_image']=image
        artifacts.append(binary);report['binary_sha256']=image['sha256']
        for mode in ([args.mode] if args.mode is not None else MODES):
            text=execute('mode'+str(mode),plan['run']+['+MODE='+str(mode)],inputs=inputs,image=binary)
            require(sha(binary)==image['sha256'],'Compiled/executed image differs')
            report['tests'].append(validate_result(text,mode))
        require(report['source']==source_revision() and report['execution_inputs']==fingerprints(inputs),'Source changed across suite')
        report['status']='PASS_ACTUAL_MC_MODELED_PHY_ORDERING_CASES' if report['complete_matrix'] else 'PASS_DEVELOPMENT_MC_SUBSET'
        report['artifacts']=fingerprints(artifacts);report['finished_utc']=timestamp()
        if report['complete_matrix']:verify_record(report)
        save()
        if report['complete_matrix']:verify_report(report_path)
        print(report_path)
    except BaseException as error:
        report.update(status='FAIL',error=repr(error));save();raise
    return 0


if __name__=='__main__':raise SystemExit(main())
