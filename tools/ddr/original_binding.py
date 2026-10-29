#!/usr/bin/env python3
"""Prepare a complete source-bound port map for original RZQ/7 MIG, not a shell.

The channel-0 logical endpoint remains independently qualified. This tool
neither runs vendor tools nor proves pad clocks, reset/PHY behavior or DDR.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.ddr.interface import require

WRAPPER_SHA='09c000b23396d629f924164b66e4bb8f289e369bf3ef274f1577d36a3892750d'
CORE_SHA='616d24bbcd3c5c57a1ac23d21488e80b8b3f16a29df65ed110f629f7d3c5e36e'
PROJECT_SHA='b15cb66fa67d8bb92630ca58dda609a85e4cef15d80ad7b2dd954a8fdc408d49'
XDC_SHA='5ea42669bed59d09cfad5c25a08aec20e0824d48895071ecd2acfbff8261b6fc'
PAD_WIDTHS=dict(dq=72,dqs_n=9,dqs_p=9,addr=15,ba=3,ras_n=1,cas_n=1,we_n=1,
                reset_n=1,ck_p=1,ck_n=1,cke=1,cs_n=1,odt=1)


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def parenthesized(text,start):
    require(text[start]=='(','Expected module-header parenthesis')
    depth=1;end=start+1
    while end<len(text) and depth:
        depth+=int(text[end]=='(')-int(text[end]==')');end+=1
    require(depth==0,'Truncated module header')
    return text[start+1:end-1],end


def ports(text,module):
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    declarations=list(re.finditer(r'\bmodule\s+([A-Za-z_]\w*)\s*',text))
    require(len(declarations)==1 and declarations[0][1]==module,'Unexpected/duplicate module')
    rest=text[declarations[0].end():].lstrip()
    if rest.startswith('#'):
        rest=rest[1:].lstrip();_,end=parenthesized(rest,0);rest=rest[end:].lstrip()
    header,end=parenthesized(rest,0)
    require(rest[end:].lstrip().startswith(';'),'Unsupported module header suffix')
    selected=[];skipping=False
    for line in header.splitlines():
        item=line.strip()
        if item.startswith('`'):
            if item=='`ifdef SKIP_CALIB':
                require(not skipping,'Nested conditional wrapper ABI');skipping=True
            elif item=='`endif':
                require(skipping,'Unexpected conditional wrapper end');skipping=False
            else:raise ValueError('Unsupported conditional wrapper ABI: '+item)
        elif not skipping:selected.append(line)
    require(not skipping,'Unclosed conditional wrapper ABI')
    result={};context=None
    for item in '\n'.join(selected).split(','):
        item=item.strip()
        if not item:continue
        match=re.fullmatch(r'(input|output|inout)\s+(?:(?:wire|logic)\s+)?'
            r'(?:\[\s*([0-9]+)\s*:\s*([0-9]+)\s*\]\s*)?([A-Za-z_]\w*)',item)
        if match:
            direction,high,low,name=match.groups();high,low=(int(high),int(low)) if high else (0,0)
            require(0<=low<=high<65536,'Unsupported port extent')
            context=dict(direction={'input':'in','output':'out','inout':'inout'}[direction],width=high-low+1)
        else:
            require(context is not None and re.fullmatch(r'[A-Za-z_]\w*',item) is not None,
                    'Unsupported port declaration: '+item)
            name=item
        require(name not in result,'Duplicate module port: '+name);result[name]=dict(context)
    return result


def binding_map(mig,endpoint):
    require(len(mig)==169,'Expected all169normal MIG ports')
    result={}
    def endpoint_net(name,net):
        require(net in endpoint,'Missing logical endpoint port: '+net)
        a,b=mig[name],endpoint[net]
        require(a['width']==b['width'] and {a['direction'],b['direction']}=={'in','out'},
                'MIG/endpoint direction or width differs: '+name)
        return dict(kind='endpoint',net=net)
    for name,port in mig.items():
        if name=='sys_rst':
            binding=endpoint_net(name,'mig_sys_rst_n');binding['active_level']=0
        else:
            match=re.fullmatch(r'(c[01])_(.+)',name);require(match is not None,'Unmodeled MIG port: '+name)
            channel,suffix=match.groups()
            if suffix.startswith('ddr3_'):
                pad=suffix[5:];require(pad in PAD_WIDTHS and port['width']==PAD_WIDTHS[pad],
                    'Unsupported DDR pad shape: '+name)
                expected='inout' if pad in ('dq','dqs_n','dqs_p') else 'out'
                require(port['direction']==expected,'Unsupported DDR pad direction')
                binding=dict(kind='physical_pad',net=name,source='Unchanged original MIG pad selection; board review required')
            elif suffix in ('sys_clk_p','sys_clk_n'):
                require(port==dict(direction='in',width=1),'Unsupported differential system clock')
                binding=dict(kind='external_clock',net=name,nominal_hz=200000000,board_delivery_qualified=False)
            elif suffix in ('ui_clk','ui_clk_sync_rst','aresetn') or name in ('c0_interrupt','c0_init_calib_complete'):
                binding=endpoint_net(name,name)
                if suffix=='aresetn':binding['active_level']=0
                elif suffix=='ui_clk_sync_rst':binding['active_level']=1
                elif suffix=='ui_clk':binding['nominal_period_ns']=7.5
            elif suffix.startswith('s_axi_'):
                field=suffix[6:];net='m_axi_'+field
                checked=endpoint_net(name,net)
                if channel=='c0':binding=checked
                elif port['direction']=='in':
                    value=6 if field in ('awsize','arsize') else 1 if field in ('awburst','arburst') else 0
                    require(value<1<<port['width'],'Inactive channel literal does not fit')
                    binding=dict(kind='inactive_channel_constant',value=value,
                        reason='C1 has no admitted master; all VALID and response READY inputs stay0')
                else:binding=dict(kind='diagnostic_output',net='unused_'+name,validity_qualified=False)
            elif suffix in ('app_sr_req','app_ref_req','app_zq_req'):
                require(port==dict(direction='in',width=1),'Unsupported application request shape')
                binding=dict(kind='inactive_request_constant',value=0,reason='No runtime low-power/refresh/ZQ request API')
            elif suffix in ('mmcm_locked','app_sr_active','app_ref_ack','app_zq_ack','init_calib_complete',
                            'device_temp','app_ecc_single_err','app_ecc_multiple_err','interrupt'):
                widths=dict(device_temp=12,app_ecc_single_err=8,app_ecc_multiple_err=8)
                require(port==dict(direction='out',width=widths.get(suffix,1)),'Unsupported diagnostic output shape')
                binding=dict(kind='diagnostic_output',net='unused_'+name,validity_qualified=False)
            else:raise ValueError('Unmodeled MIG port: '+name)
        result[name]=dict(port,binding=binding)
    require(set(result)==set(mig),'Incomplete original MIG port binding')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wrapper',type=Path,required=True)
    parser.add_argument('--endpoint',type=Path,default=ROOT/'rtl/ddr/rk_jtag_ew_ddr_async.sv')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh workspace port-map output required')
    require(sha(args.wrapper)==WRAPPER_SHA,'Changed original generated wrapper identity')
    companions={args.wrapper.parent/'top_mig_7series_0_0_mig.v':CORE_SHA,
        args.wrapper.parents[2]/'mig.prj':PROJECT_SHA,
        args.wrapper.parent.parent/'constraints/top_mig_7series_0_0.xdc':XDC_SHA}
    for path,expected in companions.items():
        require(path.is_file() and sha(path)==expected,'Changed/missing original clock/reset/electrical source: '+str(path))
    mig=ports(args.wrapper.read_text(),'top_mig_7series_0_0')
    endpoint=ports(args.endpoint.read_text(),'rk_jtag_ew_ddr_async')
    bindings=binding_map(mig,endpoint)
    record=dict(status='PREPARED_COMPLETE_ORIGINAL_MIG_PORT_MAP_ONLY',scope=__doc__,
        wrapper_sha256=WRAPPER_SHA,endpoint_sha256=sha(args.endpoint),ports=bindings,normal_ports=169,
        defines_required_undefined=['SKIP_CALIB'],selected_channel=0,c1_memory_admitted=False,
        original_profile=dict(sys_reset_active_level=0,system_clock_type='DIFFERENTIAL',
            system_clock_hz=200000000,ui_period_ns=7.5,output_drive='RZQ/7',ecc='ON'),
        physical_integration_ready=False,board_clock_delivery_qualified=False,hardware_accessed=False,
        implementation_started=False,simulated=False,
        unresolved=['Actual board clock/electrical delivery','Original generated PHY/model qualification',
            'Whole-platform reset/drain coverage including host/other masters','Full512/DDR/platform composition'],
        source_inputs={str(args.wrapper.resolve()):WRAPPER_SHA,str(args.endpoint.resolve()):sha(args.endpoint),
            str(Path(__file__).resolve()):sha(__file__)}|{str(p.resolve()):h for p,h in companions.items()})
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(record,indent=2)+'\n')
    print(record['status'],len(bindings))


if __name__=='__main__':main()
