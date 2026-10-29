"""Render an explicit private UI-domain service around the reviewed leaves."""
from pathlib import Path

OUT=Path(__file__).resolve().parent/'rk_ddr_capacity_service.sv'
# Direction is relative to the physical controller-facing master.
FIELDS=[]
for channel in ('aw','ar'):
    for tail,width in [('id',4),('addr',31),('len',8),('size',3),('burst',2),
                       ('lock',1),('cache',4),('prot',3),('qos',4),('valid',1)]:
        FIELDS.append((channel+tail,width,'output'))
    FIELDS.append((channel+'ready',1,'input'))
FIELDS += [('wdata',512,'output'),('wstrb',64,'output'),('wlast',1,'output'),('wvalid',1,'output'),
    ('wready',1,'input'),('bid',4,'input'),('bresp',2,'input'),('bvalid',1,'input'),('bready',1,'output'),
    ('rid',4,'input'),('rdata',512,'input'),('rresp',2,'input'),('rlast',1,'input'),
    ('rvalid',1,'input'),('rready',1,'output')]
CTRL=[('awaddr',32,'output'),('awvalid',1,'output'),('awready',1,'input'),
    ('wdata',32,'output'),('wvalid',1,'output'),('wready',1,'input'),
    ('bresp',2,'input'),('bvalid',1,'input'),('bready',1,'output'),
    ('araddr',32,'output'),('arvalid',1,'output'),('arready',1,'input'),
    ('rdata',32,'input'),('rresp',2,'input'),('rvalid',1,'input'),('rready',1,'output')]
MGMT=[('awaddr',32,'input'),('awprot',3,'input'),('awvalid',1,'input'),('awready',1,'output'),
    ('wdata',32,'input'),('wstrb',4,'input'),('wvalid',1,'input'),('wready',1,'output'),
    ('bresp',2,'output'),('bvalid',1,'output'),('bready',1,'input'),
    ('araddr',32,'input'),('arprot',3,'input'),('arvalid',1,'input'),('arready',1,'output'),
    ('rdata',32,'output'),('rresp',2,'output'),('rvalid',1,'output'),('rready',1,'input')]
def width(n):return '' if n==1 else f'[{n-1}:0] '
def port(direction,n,name):return f'    {direction} logic {width(n)}{name}'
def opposite(direction):return 'input' if direction=='output' else 'output'
def instance(module,name,connections,parameters=None):
    parameter='' if parameters is None else ' #('+','.join(f'.{k}({v})' for k,v in parameters)+')'
    return f'    {module}{parameter} {name} (\n'+',\n'.join(f'        .{k}({v})' for k,v in connections)+'\n    );\n'
lines=['// SPDX-License-Identifier: MIT','`timescale 1ns/1ps',
    '// Rendered by compose_service.py. Private UI-domain subsystem, not a board top.',
    '// Normal inputs are the unchanged raw-command fabric and ECC monitor masters.',
    '// The caller supplies true internal fabric/host/job/readback quiescence and',
    '// must allow previously owned readback/ACK to drain while blocking new work.',
    '// Management AXI-Lite is separately decoded; no RK register interpretation,',
    '// JTAG transport, controller PHY, PCIe, clock crossing or reset coordinator here.',
    '// Both controllers and every full512 product remain obligations of the parent.',
    'module rk_ddr_capacity_service #(',
    '    parameter logic [30:0] BASE_ADDR=0,',
    "    parameter logic [31:0] SPAN_BYTES=32'h80000000,",
    '    parameter int unsigned TIMEOUT_CYCLES=65536',') (']
ports=['    input logic clk, joint_rst_n, initialization_complete, calibration_complete, mig_interrupt',
    '    input logic normal_monitor_healthy, normal_monitor_fault',
    '    input logic normal_fabric_quiet, normal_job_owned, normal_host_busy, normal_engine_pending, normal_pending_response',
    '    output logic normal_admission_enable, normal_selected, diagnostic_selected, owner_busy, owner_done, owner_fault']
ports += [port(opposite(d),n,'n_axi_'+f) for f,n,d in FIELDS]
ports += [port(d,n,'m_axi_'+f) for f,n,d in FIELDS]
ports += [port(opposite(d),n,'n_ctrl_'+f) for f,n,d in CTRL]
ports += [port(d,n,'m_axi_ctrl_'+f) for f,n,d in CTRL]
ports += [port(d,n,'s_axil_'+f) for f,n,d in MGMT]
lines += [',\n'.join(ports),');']
for f,n,d in FIELDS:
    lines += [f'    logic {width(n)}d_axi_{f};',f'    logic [1:0]{width(n)}mem_{f};']
for f,n,d in CTRL:lines.append(f'    logic {width(n)}d_ctrl_{f};')
ctrl_widths={f:n for f,n,d in CTRL}
for f,n,d in FIELDS:
    n=ctrl_widths.get(f,1 if f in ('awid','arid','bid','rid') else 4 if f=='wstrb' else n)
    lines.append(f'    logic [1:0]{width(n)}ctrl_{f};')
    if f not in ctrl_widths:lines.append(f'    logic {width(n)}unused_ctrl_{f};')
lines += ['    logic request_valid, request_ready, diagnostic_reset_n, diagnostic_exclusive;',
    '    logic diagnostic_start_valid, diagnostic_start_ready, diagnostic_monitor_healthy;',
    '    logic bist_busy, bist_done, bist_fault, bist_trial, handoff_allowed, normal_unrouted_request;',
    '    logic [31:0] request_seed, diagnostic_seed, completed_writes, completed_reads;',
    '    logic [31:0] accepted_aw_count, accepted_w_count, accepted_b_count;',
    '    logic [30:0] mismatch_address, last_completed_write_address;',
    '    logic [511:0] mismatch_expected, mismatch_actual;',
    '    logic [2:0] bist_fault_sources;',
    '    logic [7:0] owner_fault_code, sweep_fault_code, adapter_fault_code, monitor_fault_code;',
    '    // Normal data/ECC payloads and attributes pass unchanged; no fault gates.',
]
for f,n,d in FIELDS:
    if d=='output':
        lines += [f'    assign mem_{f}[0]=n_axi_{f};',f'    assign mem_{f}[1]=d_axi_{f};']
    else:lines += [f'    assign n_axi_{f}=mem_{f}[0];',f'    assign d_axi_{f}=mem_{f}[1];']
control_constants={'awid':"1'b0",'arid':"1'b0",'awlen':"8'b0",'arlen':"8'b0",
    'awsize':"3'd2",'arsize':"3'd2",'awburst':"2'b01",'arburst':"2'b01",'awlock':"1'b0",
    'arlock':"1'b0",'awcache':"4'b0",'arcache':"4'b0",'awprot':"3'b0",'arprot':"3'b0",
    'awqos':"4'b0",'arqos':"4'b0",'wstrb':"4'hf",'wlast':"1'b1"}
for f,n,d in FIELDS:
    if f in ctrl_widths:
        if d=='output':lines += [f'    assign ctrl_{f}[0]=n_ctrl_{f};',f'    assign ctrl_{f}[1]=d_ctrl_{f};']
        else:lines += [f'    assign n_ctrl_{f}=ctrl_{f}[0];',f'    assign d_ctrl_{f}=ctrl_{f}[1];']
    elif d=='output':lines.append(f'    assign ctrl_{f}={{2{{{control_constants[f]}}}}};')
# Always-present valid-qualified response inputs for the ID-less AXI-Lite leaf.
lines += ["    assign unused_ctrl_bid=1'b0;", "    assign unused_ctrl_rid=1'b0;", "    assign unused_ctrl_rlast=1'b1;",
    '    assign normal_unrouted_request=diagnostic_selected && (n_axi_awvalid || n_axi_wvalid ||',
    '        n_axi_arvalid || n_ctrl_awvalid || n_ctrl_wvalid || n_ctrl_arvalid);',
    "    assign handoff_allowed=initialization_complete===1'b1 && calibration_complete===1'b1 &&",
    "        normal_monitor_healthy===1'b1 && normal_monitor_fault===1'b0 && normal_fabric_quiet===1'b1 &&",
    "        normal_job_owned===1'b0 && normal_host_busy===1'b0 && normal_engine_pending===1'b0 && normal_pending_response===1'b0;"]
lines.append(instance('rk_ddr_diagnostic_mux','memory_mux',
    [('joint_rst_n','joint_rst_n'),('diagnostic_selected','diagnostic_selected')]+
    [('s_axi_'+f,'mem_'+f) for f,n,d in FIELDS]+[('m_axi_'+f,'m_axi_'+f) for f,n,d in FIELDS]))
lines.append(instance('rk_ddr_diagnostic_mux','control_mux',
    [('joint_rst_n','joint_rst_n'),('diagnostic_selected','diagnostic_selected')]+
    [('s_axi_'+f,'ctrl_'+f) for f,n,d in FIELDS]+
    [('m_axi_'+f,'m_axi_ctrl_'+f if f in ctrl_widths else 'unused_ctrl_'+f) for f,n,d in FIELDS],
    [('ADDR_WIDTH','32'),('DATA_WIDTH','32'),('ID_WIDTH','1')]))
lines.append(instance('rk_ddr_capacity_owner','owner',[
    ('clk','clk'),('joint_rst_n','joint_rst_n'),('request_valid','request_valid'),('request_ready','request_ready'),('request_seed','request_seed'),
    ('initialization_complete','initialization_complete'),('calibration_complete','calibration_complete'),
    ('platform_monitor_healthy','normal_monitor_healthy'),('platform_monitor_fault','normal_monitor_fault')]+
    [(n,n) for n in ('normal_fabric_quiet','normal_job_owned','normal_host_busy','normal_engine_pending','normal_pending_response',
                     'normal_unrouted_request','normal_admission_enable','normal_selected','diagnostic_selected','diagnostic_reset_n','diagnostic_exclusive',
                     'diagnostic_start_valid','diagnostic_start_ready','diagnostic_seed','diagnostic_monitor_healthy')]+
    [('diagnostic_done','bist_done'),('diagnostic_fault','bist_fault'),('busy','owner_busy'),('done','owner_done'),('fault','owner_fault'),('fault_code','owner_fault_code')]+
    [('bus_'+f,'{m_axi_ctrl_'+f+',m_axi_'+f+'}') for f in ('awvalid','awready','wvalid','wready','bvalid','bready','arvalid','arready','rvalid','rready')]+
    [('bus_b_ok',"{(m_axi_ctrl_bresp===2'b00),(m_axi_bid===4'b0 && m_axi_bresp===2'b00)}"),
     ('bus_r_ok',"{(m_axi_ctrl_rresp===2'b00),(m_axi_rid===4'b0 && m_axi_rresp===2'b00 && m_axi_rlast===1'b1)}")],
    [('TIMEOUT_CYCLES','TIMEOUT_CYCLES')]))
common_params=[('BASE_ADDR','BASE_ADDR'),('SPAN_BYTES','SPAN_BYTES')]
lines.append(instance('rk_ddr_capacity_bist','bist',[
    ('clk','clk'),('joint_rst_n','diagnostic_reset_n'),('initialization_complete','initialization_complete'),
    ('calibration_complete','calibration_complete'),('owner_exclusive','diagnostic_exclusive'),('mig_interrupt','mig_interrupt'),
    ('start_valid','diagnostic_start_valid'),('start_ready','diagnostic_start_ready'),('seed','diagnostic_seed'),
    ('busy','bist_busy'),('done','bist_done'),('fault','bist_fault'),('trial','bist_trial'),('fault_sources','bist_fault_sources'),
    ('monitor_healthy','diagnostic_monitor_healthy')]+
    [(n,n) for n in ('sweep_fault_code','adapter_fault_code','monitor_fault_code','completed_writes','completed_reads',
        'accepted_aw_count','accepted_w_count','accepted_b_count','mismatch_address','last_completed_write_address','mismatch_expected','mismatch_actual')]+
    [('m_axi_'+f,'d_axi_'+f) for f,n,d in FIELDS]+[('m_axi_ctrl_'+f,'d_ctrl_'+f) for f,n,d in CTRL],
    common_params+[('TIMEOUT_CYCLES','TIMEOUT_CYCLES')]))
lines.append(instance('rk_ddr_capacity_regs','registers',[('clk','clk'),('joint_rst_n','joint_rst_n')]+
    [('s_axil_'+f,'s_axil_'+f) for f,n,d in MGMT]+
    [(n,n) for n in ('request_valid','request_ready','request_seed','handoff_allowed','owner_busy','owner_done','diagnostic_selected',
        'completed_writes','completed_reads','mismatch_address','last_completed_write_address','mismatch_expected','mismatch_actual')]+
    [('owner_fault','owner_fault || bist_fault'),('fault_sources','bist_fault_sources'),
     ('fault_codes','{owner_fault_code,sweep_fault_code,adapter_fault_code,monitor_fault_code}')],common_params))
# Preserve independent count/trial observations through explicit synthesis-safe
# diagnostic status consumers, rather than exporting extra physical board pins.
lines += ['    wire unused_diagnostic_activity = bist_busy ^ bist_trial ^ (^accepted_aw_count) ^',
          '        (^accepted_w_count) ^ (^accepted_b_count);','endmodule','']
with OUT.open('x') as stream:stream.write('\n'.join(lines))
print(OUT)
