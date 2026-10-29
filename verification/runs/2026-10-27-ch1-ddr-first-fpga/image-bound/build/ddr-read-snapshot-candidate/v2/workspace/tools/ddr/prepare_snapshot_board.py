"""Prepare a boot-only USER2/DDR board shell; never invoke FPGA tools."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.ddr.interface import require,load_json
from tools.ddr.original_binding import ports
from tools.ddr.original_platform import declaration,interface_stub

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

TOP='ypcb_ddr_ew_top'
def validate_pin_ranges(source,board):
    """Width1 vectors must retain bit0 names used by the original XDC."""
    for name,port in board.items():
        if re.fullmatch(r'c[01]_ddr3_(?:ck_p|ck_n|cke|cs_n|odt)',name):
            require(port['width']==1 and re.search(r'output wire \[0:0\] '+re.escape(name)+r'\b',source),
                    'Original DDR one-bit bus range changed: '+name)

PRIMITIVES='''// Declaration-only interface check. NEVER select for synthesis or execute.
`timescale 1ns/1ps
module IBUF(input wire I,output wire O); endmodule
module BUFG(input wire I,output wire O); endmodule
module BSCANE2 #(parameter JTAG_CHAIN=2)(output wire CAPTURE,DRCK,RESET,RUNTEST,SEL,SHIFT,TCK,TDI,TMS,UPDATE,input wire TDO); endmodule
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--platform',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--mig-xdc',type=Path,required=True)
    args=ap.parse_args();platform=args.platform.resolve();out=args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh workspace board-preparation directory required')
    prepared=load_json(platform/'report.json')
    require(prepared['status']=='PREPARED_ORIGINAL_MIG_ASYNC_EW_PLATFORM_WIRING_ONLY' and
            prepared['stub_selected_for_real_design'] is False,'Actual original-MIG platform required')
    for n,h in prepared['source_inputs'].items():require(sha(n)==h,'Changed platform input '+n)
    bound={Path(n).resolve():h for n,h in prepared['source_inputs'].items()}
    for n in prepared['real_hdl_sources']:
        p=Path(n).resolve()
        expected=prepared['artifacts']['platform.sv'] if p==platform/'platform.sv' else bound.get(p)
        require(expected is not None and sha(p)==expected,'Unbound/changed real board source '+str(p))
    require(sha(platform/'platform.sv')==prepared['artifacts']['platform.sv'],'Changed actual platform wrapper')
    declared=ports((platform/'platform.sv').read_text(),'rk_original_mig_ew_platform')
    expected_frame={'req':('in',604),'req_valid':('in',1),'req_ready':('out',1),
        'rsp_data':('out',512),'rsp_status':('out',8),'rsp_seq':('out',16),
        'rsp_valid':('out',1),'frame_clk':('out',1),'frame_rst_n':('out',1)}
    require(all(n in declared and (declared[n]['direction'],declared[n]['width'])==shape
                for n,shape in expected_frame.items()),'Unsupported USER2 frame/clock interface')
    endpoints=[Path(n) for n in prepared['real_hdl_sources'] if Path(n).name=='rk_jtag_ew_ddr_async.sv']
    require(len(endpoints)==1 and re.search(r"32'h00:\s*s_axil_rdata\s*=\s*32'h524b4144\s*;",endpoints[0].read_text()),
            'Unsupported source identity: require explicit RKAD readback')
    physical=prepared['physical_ports']
    actual_physical={n:p for n,p in declared.items() if n.startswith(
        ('c0_ddr3_','c1_ddr3_','c0_sys_clk_','c1_sys_clk_'))}
    require({n:{'direction':p['direction'],'width':p['width']} for n,p in physical.items()}==actual_physical and
            all(p['binding']['kind'] in ('physical_pad','external_clock') and p['binding']['net']==n
                for n,p in physical.items()),'Physical board interface differs from actual platform declaration')
    special={'sys_clk':'sys_clk50','cfg_reset':'~startup_rst_n','reset_req_valid':"1'b0"}
    require(all(n in declared for n in special),'Missing board reset/clock binding')
    internal={n:p for n,p in declared.items() if n not in physical and n not in special}
    board={'SYS_CLK':dict(direction='in',width=1),'led_3bits_tri_o':dict(direction='out',width=3)}|physical
    mig_xdc=args.mig_xdc.resolve()
    require(sha(mig_xdc)=='5ea42669bed59d09cfad5c25a08aec20e0824d48895071ecd2acfbff8261b6fc',
            'Unchanged reviewed original MIG constraints required')
    pinmap={};pinports={}
    for line in mig_xdc.read_text().splitlines():
        if not line.startswith('set_property PACKAGE_PIN '):continue
        match=re.fullmatch(r'set_property PACKAGE_PIN ([A-Z]+[0-9]+) \[get_ports \{?([A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]+\])?)\}?\s*\]\s*',line)
        require(match is not None,'Unsupported original MIG pin statement')
        pin,port=match.groups();m=re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)(?:\[([0-9]+)\])?',port)
        name,index=m.groups();require(name in physical and (index is None or int(index)<physical[name]['width']),
            'MIG pin has no matching board port')
        require(pin not in pinmap and port not in pinports,'Duplicate MIG pin or physical bit')
        pinmap[pin]=port;pinports[port]=pin
    require(len(pinmap)==238,'Changed original MIG physical-pin count')
    for pin in ('AA28','P30','M30','N30'):require(pin not in pinmap,'Board clock/LED overlaps DDR pins')
    lines=['// Boot-only strict EW/DDR preparation; no PCIe or full512 in this shell.',
        '// Reconfiguration resets the whole epoch; no TAP reset or health signal initiates recovery.',
        '`timescale 1ns/1ps',f'module {TOP} #(parameter bit LED_ACTIVE_LOW=1\'b0) (',
        ',\n'.join('    '+declaration(n,p) for n,p in sorted(board.items())),');',
        '    wire sys_clk_ib,sys_clk50,startup_rst_n;',
        '    wire tck,capture,shift,update,sel,tdi,tdo;',
        '    logic [25:0] heartbeat;',"    initial heartbeat='0;"]
    lines+=['    '+declaration(n,p,'wire')+';' for n,p in sorted(internal.items())]
    lines+=['    IBUF u_ibuf50(.I(SYS_CLK),.O(sys_clk_ib));',
        '    BUFG u_bufg50(.I(sys_clk_ib),.O(sys_clk50));',
        "    rk_startup_reset startup(.clk(sys_clk50),.request_reset(1'b0),.rst_n(startup_rst_n));",
        '    (* DONT_TOUCH="TRUE" *) BSCANE2 #(.JTAG_CHAIN(2)) u_bscan(',
        '        .TCK(tck),.DRCK(),.CAPTURE(capture),.SHIFT(shift),.UPDATE(update),',
        '        .SEL(sel),.TDI(tdi),.TDO(tdo),.RESET(),.RUNTEST(),.TMS());',
        '    (* KEEP_HIERARCHY="TRUE" *) otpu_jtag_mailbox u_mailbox(',
        '        .clk(frame_clk),.rst(!frame_rst_n),.tck,.capture,.shift,.update,.sel,.tdi,.tdo,',
        '        .req_valid,.req_ready,.req,.rsp_valid,.rsp_data,.rsp_status,.rsp_seq);',
        '    (* KEEP_HIERARCHY="TRUE" *) rk_original_mig_ew_platform platform(']
    lines+=[',\n'.join(f'        .{n}({special.get(n,n)})' for n in sorted(declared)), '    );',
        '    always_ff @(posedge sys_clk50) begin',
        "        if(!startup_rst_n) heartbeat<='0; else heartbeat<=heartbeat+1'b1;",
        '    end',
        '    // Init/fault/heartbeat are status, never a workload PASS indicator.',
        '    assign led_3bits_tri_o={heartbeat[25],fault,init_complete}^{3{LED_ACTIVE_LOW}};',
        'endmodule','']
    source='\n'.join(lines);validate_pin_ranges(source,board)
    out.mkdir(parents=True);(out/'top.sv').write_text(source)
    (out/'interface-only').mkdir()
    (out/'interface-only/platform.sv').write_text(interface_stub('rk_original_mig_ew_platform',declared))
    (out/'interface-only/primitives.v').write_text(PRIMITIVES)
    local=[ROOT/'rtl/rk_startup_reset.sv',ROOT/'rtl/vendor/opentpu/otpu_jtag_mailbox.sv']
    (out/'interface-only/helpers.sv').write_text(''.join(interface_stub(module,ports(p.read_text(),module))
        for module,p in zip(('rk_startup_reset','otpu_jtag_mailbox'),local)))
    shutil.copyfile(mig_xdc,out/'mig-original.xdc')
    mailbox_cdc=ROOT/'fpga/ddr/mailbox_ui_cdc.tcl'
    require(mailbox_cdc.is_file(),'Selected UI mailbox constraint helper is missing')
    (out/'constraint-helpers').mkdir()
    shutil.copyfile(mailbox_cdc,out/'constraint-helpers/mailbox_ui_cdc.tcl')
    real=[Path(n) for n in prepared['real_hdl_sources']]+local+[out/'top.sv']
    require(sum(p.name=='rk_axi_mem_read_snapshot.sv' for p in real)==1 and
            sum(p.name=='rk_ddr_memory_fabric_snapshot.sv' for p in real)==1,
            'Explicit source-bound snapshot adapter and fabric required')
    require(len(real)==122 and len(set(real))==122 and all('interface-only' not in str(p) for p in real),
            'Real board source selection must contain122 actual HDL files')
    # The generator preserves the reviewed board pin names, including [0:0]
    # physical DDR buses. The original MIG XDC is copied byte-for-byte.
    (out/'board.xdc').write_text('''set_property PACKAGE_PIN AA28 [get_ports SYS_CLK]
set_property PACKAGE_PIN P30 [get_ports {led_3bits_tri_o[0]}]
set_property PACKAGE_PIN M30 [get_ports {led_3bits_tri_o[1]}]
set_property PACKAGE_PIN N30 [get_ports {led_3bits_tri_o[2]}]
set_property IOSTANDARD LVCMOS18 [get_ports {SYS_CLK led_3bits_tri_o[*]}]
create_clock -name sys_clock -period 20.000 [get_ports SYS_CLK]
set_false_path -to [get_ports {led_3bits_tri_o[*]}]
''')
    inputs=dict(prepared['source_inputs'])|{str(platform/'report.json'):sha(platform/'report.json'),
        str(platform/'platform.sv'):sha(platform/'platform.sv'),str(Path(__file__).resolve()):sha(__file__)}
    inputs.update({str(p):sha(p) for p in local})
    inputs[str(mig_xdc)]=sha(mig_xdc)
    inputs[str(mailbox_cdc)]=sha(mailbox_cdc)
    inputs[str(ROOT/'fpga/ddr/board_shell.mk')]=sha(ROOT/'fpga/ddr/board_shell.mk')
    record=dict(status='PREPARED_BOOT_ONLY_USER2_DDR_SNAPSHOT_SHELL_REQUIRES_QUALIFICATION',top=TOP,
        part='xc7k480tffg1156-2',source_inputs=inputs,real_hdl_sources=[str(p) for p in real],
        interface_check_sources=[str(out/'interface-only/primitives.v'),str(out/'interface-only/platform.sv'),
            str(out/'interface-only/helpers.sv'),str(out/'top.sv')],
        interface_check_scope='Port/width elaboration only; declaration stubs never executed or synthesized',
        artifacts={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()},
        memory_read_profile='packet_read64_snapshot',logical_contract_schema=3,board_ports=board,transport_id='0x524b4144',abi='0x00010000',jtag_chain=2,
        original_mig_pinmap=pinports,constraint_sources=[str(out/'mig-original.xdc'),str(out/'board.xdc')],
        constraint_helpers={'mailbox_ui':str(out/'constraint-helpers/mailbox_ui_cdc.tcl')},
        recovery='Audited whole-card volatile SRAM reconfiguration only; reset_req_valid tied0',
        source_clock_ns=20.0,mailbox_clock='Actual C0 UI clock,7.5ns; not SYS50',
        mailbox_required_bounds_ns=dict(request=15.0,response=333.332,tck_model=166.666),
        constraints_required=['Unchanged original MIG XDC','board.xdc','Source-bound UI-clock mailbox CDC',
                              'Status/job/memory and reset bridges with actual SYS cfg producer'],
        remaining_gates=['Full21-case new-source matrix','Physical-shell synthesis and registered-reset cone audit',
            'UI mailbox CDC and actual configuration-reset producer binding','Explicit RKAD host admission/health gate',
            'Source-bound board IO/configuration/clock review','Placement/routing/full setup hold pulse DRC signoff',
            'Exact-image and target review before any SRAM programming'],
        full512_integrated=False,pcie_present=False,stub_selected_for_real_design=False,
        simulated=False,vivado_executed=False,hardware_accessed=False,bitstream_emitted=False,physical_integration_ready=False)
    (out/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    print(record['status'],len(real),len(board))

if __name__=='__main__':main()
