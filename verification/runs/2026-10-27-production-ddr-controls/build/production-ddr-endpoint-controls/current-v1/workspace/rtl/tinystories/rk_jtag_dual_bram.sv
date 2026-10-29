// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Raw EW at CSR0x000, raw terminal CMAC at CSR0x100. Same USER2 byte framing.
// The backend serializes its private AXI-Lite source and holds each address
// through the response; this routing is not a general concurrent AXI fabric.
module rk_jtag_dual_bram #(
    parameter int unsigned BYTES=1048576,
    parameter logic [31:0] BASE=32'h10000000,
    parameter int unsigned TIMEOUT_CYCLES=65536,
    parameter int unsigned MAX_TASKS=4095
)(
    input wire clk,rst_n,req_valid,
    output wire req_ready,
    input wire [603:0] req,
    output wire rsp_valid,
    output wire [511:0] rsp_data,
    output wire [7:0] rsp_status,
    output wire [15:0] rsp_seq,
    output wire irq,fault,
    output wire [31:0] cmac_rearm_count
);
    wire [31:0] s_axil_awaddr;
    wire [31:0] s_axil_wdata;
    wire [31:0] s_axil_araddr;
    wire [31:0] s_axil_rdata;
    wire [2:0] s_axil_awprot;
    wire [2:0] s_axil_arprot;
    wire [3:0] s_axil_wstrb;
    wire [1:0] s_axil_bresp;
    wire [1:0] s_axil_rresp;
    wire s_axil_awvalid;
    wire s_axil_awready;
    wire s_axil_wvalid;
    wire s_axil_wready;
    wire s_axil_bvalid;
    wire s_axil_bready;
    wire s_axil_arvalid;
    wire s_axil_arready;
    wire s_axil_rvalid;
    wire s_axil_rready;
    wire [31:0] ew_awaddr;
    wire [31:0] ew_wdata;
    wire [31:0] ew_araddr;
    wire [31:0] ew_rdata;
    wire [2:0] ew_awprot;
    wire [2:0] ew_arprot;
    wire [3:0] ew_wstrb;
    wire [1:0] ew_bresp;
    wire [1:0] ew_rresp;
    wire ew_awvalid;
    wire ew_awready;
    wire ew_wvalid;
    wire ew_wready;
    wire ew_bvalid;
    wire ew_bready;
    wire ew_arvalid;
    wire ew_arready;
    wire ew_rvalid;
    wire ew_rready;
    wire ew_start,ew_ready,ew_busy,ew_done,ew_error,ew_irq;
    wire [31:0] ew_address,ew_amount,ew_tasks;
    wire [7:0] ew_code;
    wire ew_req,ew_req_ready,ew_write,ew_rsp,ew_rsp_ready;
    wire [31:0] ew_mem_address;
    wire [15:0] ew_data;
    wire [31:0] cm_awaddr;
    wire [31:0] cm_wdata;
    wire [31:0] cm_araddr;
    wire [31:0] cm_rdata;
    wire [2:0] cm_awprot;
    wire [2:0] cm_arprot;
    wire [3:0] cm_wstrb;
    wire [1:0] cm_bresp;
    wire [1:0] cm_rresp;
    wire cm_awvalid;
    wire cm_awready;
    wire cm_wvalid;
    wire cm_wready;
    wire cm_bvalid;
    wire cm_bready;
    wire cm_arvalid;
    wire cm_arready;
    wire cm_rvalid;
    wire cm_rready;
    wire cm_start,cm_ready,cm_busy,cm_done,cm_error,cm_irq;
    wire [31:0] cm_address,cm_amount,cm_tasks;
    wire [7:0] cm_code;
    wire cm_req,cm_req_ready,cm_write,cm_rsp,cm_rsp_ready;
    wire [31:0] cm_mem_address;
    wire [15:0] cm_data;
    wire host_valid,host_ready,host_write,host_rsp_valid,host_rsp_ready,host_error;
    wire [31:0] host_addr;
    wire [15:0] host_wdata,host_rdata;
    wire memory_busy,backend_fault,engine_pending,host_pending;
    logic owner_valid,owner_cmac,result_seen,scheduler_fault;
    wire combined_error=ew_error||cm_error||scheduler_fault;
    wire [7:0] combined_code=scheduler_fault ? 8'd6 : ew_error ? ew_code : cm_code;
    wire memory_available=rst_n&&!ew_start&&!cm_start&&!ew_busy&&!cm_busy&&
                          !engine_pending&&!combined_error&&!backend_fault;
    wire ew_memory_ready=rst_n&&!memory_busy&&!host_pending&&!combined_error&&
                         (!owner_valid||!owner_cmac);
    wire cm_memory_ready=rst_n&&!memory_busy&&!host_pending&&!combined_error&&
                         (!owner_valid||owner_cmac);
    wire grant_ew=!scheduler_fault&&!backend_fault&&(!owner_valid ? !cm_start : !owner_cmac);
    wire grant_cm=!scheduler_fault&&!backend_fault&&(!owner_valid ? !ew_start : owner_cmac);
    wire ew_engine_ready,cm_engine_ready,unused_ew_task_done;
    wire ew_can_start=grant_ew&&!memory_busy&&!host_pending;
    wire cm_can_start=grant_cm&&!memory_busy&&!host_pending;
    assign ew_ready=ew_engine_ready&&ew_can_start;
    assign cm_ready=cm_engine_ready&&cm_can_start;
    assign irq=ew_irq||cm_irq;
    assign fault=backend_fault||combined_error;
    // A job owns both compute admission and its result slot through ACK.
    // Observing IRQ fall after seeing IRQ rise proves successful ACK; faults
    // cannot clear either controller's result and never release this owner.
    always @(posedge clk)begin
        if(!rst_n)begin owner_valid<=0;owner_cmac<=0;result_seen<=0;scheduler_fault<=0;end
        else if(!scheduler_fault)begin
            if(ew_start&&cm_start) scheduler_fault<=1;
            else if(!owner_valid)begin
                if(ew_start||cm_start)begin owner_valid<=1;owner_cmac<=cm_start;result_seen<=0;end
            end else begin
                if((owner_cmac&&ew_start)||(!owner_cmac&&cm_start))scheduler_fault<=1;
                if(owner_cmac ? cm_irq : ew_irq)result_seen<=1;
                if(result_seen&&!(owner_cmac ? cm_irq : ew_irq)&&!ew_start&&!cm_start&&
                   !ew_busy&&!cm_busy&&!engine_pending&&!memory_busy&&!combined_error&&!backend_fault)begin
                    owner_valid<=0;result_seen<=0;
                end
            end
        end
    end
    rk_jtag_backend #(.BYTES(BYTES),.BASE(BASE),.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) backend(
        .fault(backend_fault),.*);
    wire write_cmac=s_axil_awaddr[31:8]==24'h000001;
    wire read_cmac=s_axil_araddr[31:8]==24'h000001;
    assign ew_awaddr=s_axil_awaddr;
    assign ew_awprot=s_axil_awprot;
    assign ew_awvalid=s_axil_awvalid&&(!write_cmac);
    assign ew_wdata=s_axil_wdata;
    assign ew_wstrb=s_axil_wstrb;
    assign ew_wvalid=s_axil_wvalid&&(!write_cmac);
    assign ew_bready=s_axil_bready&&(!write_cmac);
    assign cm_awaddr={24'b0,s_axil_awaddr[7:0]};
    assign cm_awprot=s_axil_awprot;
    assign cm_awvalid=s_axil_awvalid&&(write_cmac);
    assign cm_wdata=s_axil_wdata;
    assign cm_wstrb=s_axil_wstrb;
    assign cm_wvalid=s_axil_wvalid&&(write_cmac);
    assign cm_bready=s_axil_bready&&(write_cmac);
    assign ew_araddr=s_axil_araddr;
    assign ew_arprot=s_axil_arprot;
    assign ew_arvalid=s_axil_arvalid&&(!read_cmac);
    assign ew_rready=s_axil_rready&&(!read_cmac);
    assign cm_araddr={24'b0,s_axil_araddr[7:0]};
    assign cm_arprot=s_axil_arprot;
    assign cm_arvalid=s_axil_arvalid&&(read_cmac);
    assign cm_rready=s_axil_rready&&(read_cmac);
    assign s_axil_awready=write_cmac ? cm_awready : ew_awready;
    assign s_axil_wready=write_cmac ? cm_wready : ew_wready;
    assign s_axil_bvalid=write_cmac ? cm_bvalid : ew_bvalid;
    assign s_axil_bresp=write_cmac ? cm_bresp : ew_bresp;
    assign s_axil_arready=read_cmac ? cm_arready : ew_arready;
    assign s_axil_rvalid=read_cmac ? cm_rvalid : ew_rvalid;
    assign s_axil_rresp=read_cmac ? cm_rresp : ew_rresp;
    assign s_axil_rdata=read_cmac ? cm_rdata : ew_rdata;
    rk_job_control #(.DEVICE_ID(32'h524b4557)) ew_control(
        .clk,.rst_n,.memory_ready(ew_memory_ready),
        .s_axil_awaddr(ew_awaddr),
        .s_axil_wdata(ew_wdata),
        .s_axil_araddr(ew_araddr),
        .s_axil_rdata(ew_rdata),
        .s_axil_awprot(ew_awprot),
        .s_axil_arprot(ew_arprot),
        .s_axil_wstrb(ew_wstrb),
        .s_axil_bresp(ew_bresp),
        .s_axil_rresp(ew_rresp),
        .s_axil_awvalid(ew_awvalid),
        .s_axil_awready(ew_awready),
        .s_axil_wvalid(ew_wvalid),
        .s_axil_wready(ew_wready),
        .s_axil_bvalid(ew_bvalid),
        .s_axil_bready(ew_bready),
        .s_axil_arvalid(ew_arvalid),
        .s_axil_arready(ew_arready),
        .s_axil_rvalid(ew_rvalid),
        .s_axil_rready(ew_rready),
        .irq(ew_irq),.core_start_valid(ew_start),.core_start_ready(ew_ready),
        .core_start_address(ew_address),.core_start_amount(ew_amount),
        .core_busy(ew_busy),.core_done(ew_done),.core_error(combined_error),
        .core_error_code(combined_code),.core_completed_tasks(ew_tasks));
    rk_job_control #(.DEVICE_ID(32'h524b434d)) cm_control(
        .clk,.rst_n,.memory_ready(cm_memory_ready),
        .s_axil_awaddr(cm_awaddr),
        .s_axil_wdata(cm_wdata),
        .s_axil_araddr(cm_araddr),
        .s_axil_rdata(cm_rdata),
        .s_axil_awprot(cm_awprot),
        .s_axil_arprot(cm_arprot),
        .s_axil_wstrb(cm_wstrb),
        .s_axil_bresp(cm_bresp),
        .s_axil_rresp(cm_rresp),
        .s_axil_awvalid(cm_awvalid),
        .s_axil_awready(cm_awready),
        .s_axil_wvalid(cm_wvalid),
        .s_axil_wready(cm_wready),
        .s_axil_bvalid(cm_bvalid),
        .s_axil_bready(cm_bready),
        .s_axil_arvalid(cm_arvalid),
        .s_axil_arready(cm_arready),
        .s_axil_rvalid(cm_rvalid),
        .s_axil_rready(cm_rready),
        .irq(cm_irq),.core_start_valid(cm_start),.core_start_ready(cm_ready),
        .core_start_address(cm_address),.core_start_amount(cm_amount),
        .core_busy(cm_busy),.core_done(cm_done),.core_error(combined_error),
        .core_error_code(combined_code),.core_completed_tasks(cm_tasks));
    wire mem_req_valid=owner_valid&&(owner_cmac ? cm_req : ew_req);
    wire mem_req_write=owner_cmac ? cm_write : ew_write;
    wire [31:0] mem_req_addr=owner_cmac ? cm_mem_address : ew_mem_address;
    wire [15:0] mem_req_wdata=owner_cmac ? cm_data : ew_data;
    wire mem_req_ready,mem_rsp_valid,mem_rsp_error;
    wire mem_rsp_ready=owner_valid&&(owner_cmac ? cm_rsp_ready : ew_rsp_ready);
    wire [15:0] mem_rsp_rdata;
    rk_ew_dma #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES),.MAX_TASKS(MAX_TASKS)) ew_engine(
        .clk,.rst_n,.start_valid(ew_start&&ew_can_start),.start_ready(ew_engine_ready),
        .start_address(ew_address),.start_amount(ew_amount),.busy(ew_busy),.done(ew_done),
        .task_done(unused_ew_task_done),.completed_tasks(ew_tasks),.error(ew_error),.error_code(ew_code),
        .mem_req_valid(ew_req),.mem_req_ready(ew_req_ready),.mem_req_write(ew_write),
        .mem_req_addr(ew_mem_address),.mem_req_wdata(ew_data),.mem_rsp_valid(ew_rsp),
        .mem_rsp_ready(ew_rsp_ready),.mem_rsp_rdata(mem_rsp_rdata),.mem_rsp_error);
    rk_cmac_success_rearm #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) cm_engine(
        .clk,.rst_n,.start_valid(cm_start&&cm_can_start),.start_ready(cm_engine_ready),
        .start_address(cm_address),.start_amount(cm_amount),.busy(cm_busy),.done(cm_done),
        .rearm_allowed(!backend_fault&&!scheduler_fault&&!ew_error),.memory_pending(engine_pending),
        .completed_tasks(cm_tasks),.rearm_count(cmac_rearm_count),.error(cm_error),.error_code(cm_code),
        .mem_req_valid(cm_req),.mem_req_ready(cm_req_ready),.mem_req_write(cm_write),
        .mem_req_addr(cm_mem_address),.mem_req_wdata(cm_data),.mem_rsp_valid(cm_rsp),
        .mem_rsp_ready(cm_rsp_ready),.mem_rsp_rdata(mem_rsp_rdata),.mem_rsp_error);
    assign ew_req_ready=owner_valid&&!owner_cmac&&mem_req_ready;
    assign cm_req_ready=owner_valid&&owner_cmac&&mem_req_ready;
    assign ew_rsp=owner_valid&&!owner_cmac&&mem_rsp_valid;
    assign cm_rsp=owner_valid&&owner_cmac&&mem_rsp_valid;
    rk_shared_bram_regport #(.BYTES(BYTES),.BASE(BASE)) memory(
        .clk,.rst_n,.req_valid(mem_req_valid),.req_ready(mem_req_ready),.req_write(mem_req_write),
        .req_addr(mem_req_addr),.req_wdata(mem_req_wdata),.rsp_valid(mem_rsp_valid),.rsp_ready(mem_rsp_ready),
        .rsp_rdata(mem_rsp_rdata),.rsp_error(mem_rsp_error),
        .host_valid,.host_ready,.host_write,.host_addr,.host_wdata,.host_rsp_valid,.host_rsp_ready,
        .host_rdata,.host_error,.engine_pending,.host_pending);
endmodule
