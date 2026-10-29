#!/usr/bin/env python3
"""Prepare original-MIG/async-EW platform wiring; no vendor/device action.

The emitted stub is exclusively for interface elaboration and is explicitly
excluded from the real HDL source list. Pad clocks, PHY, timing, full512 and
host transport retain their independent qualification gates.
"""
from pathlib import Path
import argparse
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.ddr.interface import load_json,require
from tools.ddr.original_binding import ports,binding_map,sha
from tools.ddr.run_async_endpoint import RTL

TOP='rk_original_mig_ew_platform'


def interface_stub(module,declared):
    return ('// INTERFACE ELABORATION ONLY: no behavior. NEVER synthesize.\n'
            '`timescale 1ns/1ps\nmodule '+module+' (\n'+
            ',\n'.join('    '+declaration(n,p) for n,p in sorted(declared.items()))+
            '\n);\nendmodule\n')


def declaration(name,port,direction=None):
    require(type(port['width']) is int and port['width']>0 and port['direction'] in ('in','out','inout'),
            'Unsupported platform declaration')
    kind=direction or {'in':'input','out':'output','inout':'inout'}[port['direction']]
    extent='' if port['width']==1 else f"[{port['width']-1}:0] "
    # The vendor XDC addresses bit0 of these physical buses explicitly. A
    # scalar is width-equivalent in RTL but has a different constraint name.
    if re.fullmatch(r'c[01]_ddr3_(?:ck_p|ck_n|cke|cs_n|odt)',name):
        require(port['width']==1,'Changed original single-bit DDR pad bus')
        extent='[0:0] '
    if kind=='wire':return f'wire {extent}{name}'
    return f'{kind} wire {extent}{name}'


def render(endpoint,mapping):
    require(len(mapping)==169,'Every actual MIG port must be bound')
    require('frame_clk' not in endpoint and 'frame_rst_n' not in endpoint,'Reserved platform frame aliases')
    # MIG output signals replace the endpoint's external clock/health inputs.
    supplied={p['binding']['net'] for p in mapping.values()
              if p['binding']['kind']=='endpoint' and p['direction']=='out'}
    top={n:p for n,p in endpoint.items() if not n.startswith('m_axi_') and n not in supplied}
    top['frame_clk']=dict(direction='out',width=1)
    top['frame_rst_n']=dict(direction='out',width=1)
    internals={n:p for n,p in endpoint.items() if n not in top}
    for n,p in mapping.items():
        b=p['binding'];kind=b['kind']
        if kind in ('physical_pad','external_clock'):
            require(b['net'] not in top,'Duplicate physical platform port');top[b['net']]=p
        elif kind=='diagnostic_output':
            require(p['direction']=='out' and b['validity_qualified'] is False,'Unqualified diagnostic contract changed')
            require(b['net'] not in top,'Duplicate diagnostic platform port');top[b['net']]=p
        elif kind=='endpoint':
            net=b['net'];require(net in endpoint,'Missing endpoint connection')
            require(endpoint[net]['width']==p['width'] and {endpoint[net]['direction'],p['direction']}=={'in','out'},
                    'Platform connection width/direction differs')
        elif kind in ('inactive_channel_constant','inactive_request_constant'):
            require(p['direction']=='in' and type(b['value']) is int and 0<=b['value']<1<<p['width'],
                    'Invalid inactive input literal')
        else:raise ValueError('Unmodeled platform binding: '+kind)
    lines=['// Prepared source wiring only; no physical or full512 qualification.','`timescale 1ns/1ps',
        '// Host frames are synchronous to frame_clk; reset/recovery owns the whole epoch.',
        f'module {TOP} (',',\n'.join('    '+declaration(n,p) for n,p in sorted(top.items())),');']
    lines += ['    '+declaration(n,p,'wire')+';'
              for n,p in sorted(internals.items())]
    lines += ['    assign frame_clk=c0_ui_clk;', '    assign frame_rst_n=c0_clients_rst_n;',
              '    top_mig_7series_0_0 mig (']
    connections=[]
    for n,p in sorted(mapping.items()):
        b=p['binding']
        value=(f"{p['width']}'h{b['value']:x}" if b['kind'] in
               ('inactive_channel_constant','inactive_request_constant') else b['net'])
        connections.append(f'        .{n}({value})')
    lines += [',\n'.join(connections),'    );','    rk_jtag_ew_ddr_async endpoint (',
        ',\n'.join(f'        .{n}({n})' for n in sorted(endpoint)), '    );','endmodule','']
    # This declaration-only module is never selected for the real design.
    stub=interface_stub('top_mig_7series_0_0',mapping)
    return '\n'.join(lines),stub,top


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();package=args.selection.resolve();out=args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh source-only platform package required')
    selected=load_json(package/'report.json')
    require(selected['status']=='PREPARED_CORRECTED_ORIGINAL_MIG_RTL_SELECTION_ONLY' and
            selected['arbiter_definition_count']==1 and selected['cached_checkpoint_allowed'] is False,
            'Original corrected source selection required')
    for name,h in selected['source_inputs'].items():require(sha(name)==h,'Changed source-selection input '+name)
    for key in ('copied_source_hashes','copied_metadata_hashes'):
        for name,h in selected[key].items():require(sha(package/name)==h,'Changed frozen selection '+name)
    mapping=load_json(package/'evidence/port-map.json')
    for name,h in mapping['source_inputs'].items():require(sha(name)==h,'Changed interface source '+name)
    endpoint_path=ROOT/'rtl/ddr/rk_jtag_ew_ddr_async.sv'
    endpoint=ports(endpoint_path.read_text(),'rk_jtag_ew_ddr_async')
    mig={n:dict(direction=p['direction'],width=p['width']) for n,p in mapping['ports'].items()}
    require(mapping['ports']==binding_map(mig,endpoint),'Platform map differs from source-derived bindings')
    source,stub,top=render(endpoint,mapping['ports']);out.mkdir(parents=True)
    (out/'platform.sv').write_text(source);(out/'mig_interface_only.sv').write_text(stub)
    (out/'endpoint_interface_only.sv').write_text(interface_stub('rk_jtag_ew_ddr_async',endpoint))
    logic=[ROOT/name for name in RTL if not name.startswith('tests/')]
    real_sources=[str(package/name) for name in selected['compile_sources']]+[str(p) for p in logic]+[str(out/'platform.sv')]
    require(str(out/'mig_interface_only.sv') not in real_sources,'Interface stub must never enter actual HDL selection')
    require(str(out/'endpoint_interface_only.sv') not in real_sources,'Endpoint stub must never enter actual HDL selection')
    inputs={str(package/'report.json'):sha(package/'report.json'),str(Path(__file__).resolve()):sha(__file__)}
    inputs.update(selected['source_inputs']);inputs.update(mapping['source_inputs'])
    inputs.update({str(package/n):h for n,h in selected['copied_source_hashes'].items()})
    inputs.update({str(package/n):h for n,h in selected['copied_metadata_hashes'].items()})
    inputs.update({str(p):sha(p) for p in logic})
    for name in ('tools/ddr/interface.py','tools/ddr/original_binding.py','tools/ddr/run_async_endpoint.py'):
        inputs[str(ROOT/name)]=sha(ROOT/name)
    record=dict(status='PREPARED_ORIGINAL_MIG_ASYNC_EW_PLATFORM_WIRING_ONLY',scope=__doc__,
        source_inputs=inputs,real_hdl_sources=real_sources,interface_check_sources=[str(out/n) for n in
            ('mig_interface_only.sv','endpoint_interface_only.sv','platform.sv')],
        interface_check_scope='Declaration-only port/width elaboration; actual endpoint behavior uses separate native suite',
        artifacts={n:sha(out/n) for n in ('platform.sv','mig_interface_only.sv','endpoint_interface_only.sv')},top=TOP,
        physical_ports={n:p for n,p in top.items() if n.startswith(('c0_ddr3_','c1_ddr3_','c0_sys_clk_','c1_sys_clk_'))},
        normal_mig_ports=169,stub_is_interface_only=True,stub_selected_for_real_design=False,
        required_undefined=['SKIP_CALIB'],hardware_accessed=False,vivado_executed=False,simulated=False,
        physical_integration_ready=False,full512_integrated=False,
        unresolved=['Complete new endpoint runtime matrix','Matched original PHY/model qualification',
            'Board clock/electrical/constraint scope','BSCAN/TCK and PCIe ownership/reset integration',
            'Full512 DDR datapath and physical timing/image review'])
    (out/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    print(record['status'],len(mapping['ports']))


if __name__=='__main__':main()
