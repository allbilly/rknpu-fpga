// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private diagnostic 64-byte transaction source. No tensor operations or
// arithmetic/layout conversion. Every effectful request requires joint reset
// before ordinary memory ownership can return, even for a zero FI mask.
module rk_mig_fi_line_access #(
    parameter logic [31:0] BASE=0,
    parameter logic [32:0] BYTES=33'h080000000,
    parameter int unsigned TIMEOUT_CYCLES=65536
) (
    input logic clk,joint_rst_n,diagnostic_owned,sequence_ready,calib_complete,request_enable,
    input logic req_valid,req_write,
    output logic req_ready,
    input logic [31:0] req_address,
    input logic [511:0] req_data,
    input logic [1:0] req_expected_response,
    output logic rsp_valid,
    input logic rsp_ready,
    output logic [511:0] rsp_data,
    output logic [1:0] rsp_response,
    output logic rsp_matched,
    output logic quiet,recovery_required,fault,
    output logic [7:0] fault_code,
    output logic [3:0] m_axi_awid,m_axi_arid,
    output logic [30:0] m_axi_awaddr,m_axi_araddr,
    output logic [7:0] m_axi_awlen,m_axi_arlen,
    output logic [2:0] m_axi_awsize,m_axi_arsize,
    output logic [1:0] m_axi_awburst,m_axi_arburst,
    output logic m_axi_awlock,m_axi_arlock,
    output logic [3:0] m_axi_awcache,m_axi_arcache,
    output logic [2:0] m_axi_awprot,m_axi_arprot,
    output logic [3:0] m_axi_awqos,m_axi_arqos,
    output logic m_axi_awvalid,
    input logic m_axi_awready,
    output logic [511:0] m_axi_wdata,
    output logic [63:0] m_axi_wstrb,
    output logic m_axi_wlast,m_axi_wvalid,
    input logic m_axi_wready,
    input logic [3:0] m_axi_bid,
    input logic [1:0] m_axi_bresp,
    input logic m_axi_bvalid,
    output logic m_axi_bready,
    output logic m_axi_arvalid,
    input logic m_axi_arready,
    input logic [3:0] m_axi_rid,
    input logic [511:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    input logic m_axi_rlast,m_axi_rvalid,
    output logic m_axi_rready
);
    logic active,write_operation,aw_pending,w_pending,ar_pending,return_pending;
    logic [30:0] address;
    logic [511:0] data;
    logic [1:0] expected_response;
    logic [31:0] wait_count;
    logic request_ok,owner_ok,rsp_protected;
    logic [7:0] fault_now;
    wire below_base;
    if(BASE==0)begin: zero_base
        assign below_base=0;
    end else begin: nonzero_base
        assign below_base={1'b0,req_address}<{1'b0,BASE};
    end
    wire b_take=m_axi_bvalid&&m_axi_bready;
    wire r_take=m_axi_rvalid&&m_axi_rready;
    initial begin
        if(BASE[31]||BASE[5:0]!=0||BYTES<64||BYTES[5:0]!=0||
           {1'b0,BASE}+BYTES>33'h080000000||TIMEOUT_CYCLES==0)
            $fatal(1,"Invalid private FI line geometry/timeout");
    end
    assign owner_ok=diagnostic_owned===1'b1&&sequence_ready===1'b1&&calib_complete===1'b1;
    assign req_ready=joint_rst_n&&!active&&!rsp_valid&&!fault&&request_enable===1'b1;
    assign quiet=joint_rst_n&&!active&&!rsp_valid&&!aw_pending&&!w_pending&&!ar_pending&&!return_pending&&
        m_axi_bvalid===1'b0&&m_axi_rvalid===1'b0;
    always_comb begin
        request_ok=owner_ok && (req_write===1'b0||req_write===1'b1) &&
            (^req_address)!==1'bx && req_address[5:0]===0 &&
            !below_base && {1'b0,req_address}+33'd64<={1'b0,BASE}+BYTES &&
            (req_expected_response===2'b00||(!req_write&&req_expected_response===2'b10)) &&
            (!req_write||(^req_data)!==1'bx);
        fault_now=0;
        if(req_valid!==1'b0&&req_valid!==1'b1)fault_now=5;
        else if((active||(rsp_valid&&rsp_protected)) && !owner_ok)fault_now=1;
        else if(m_axi_bvalid!==1'b0 && (m_axi_bvalid!==1'b1||!active||!write_operation||
                aw_pending||w_pending||!return_pending||m_axi_bid!==0||m_axi_bresp!==0))fault_now=2;
        else if(m_axi_rvalid!==1'b0 && (m_axi_rvalid!==1'b1||!active||write_operation||ar_pending||
                !return_pending||m_axi_rid!==0||m_axi_rlast!==1'b1||m_axi_rresp!==expected_response||
                (^m_axi_rdata)===1'bx))fault_now=3;
        else if(active&&wait_count>=TIMEOUT_CYCLES-1)fault_now=4;
    end
    assign m_axi_awid=0;
    assign m_axi_arid=0;
    assign m_axi_awaddr=address[30:0];
    assign m_axi_araddr=address[30:0];
    assign m_axi_awlen=0;
    assign m_axi_arlen=0;
    assign m_axi_awsize=6;
    assign m_axi_arsize=6;
    assign m_axi_awburst=1;
    assign m_axi_arburst=1;
    assign m_axi_awlock=0;
    assign m_axi_arlock=0;
    assign m_axi_awcache=0;
    assign m_axi_arcache=0;
    assign m_axi_awprot=0;
    assign m_axi_arprot=0;
    assign m_axi_awqos=0;
    assign m_axi_arqos=0;
    assign m_axi_wdata=data;
    assign m_axi_wstrb='1;
    assign m_axi_wlast=1;
    // Faults never withdraw an asserted request or change its payload.
    assign m_axi_awvalid=joint_rst_n&&aw_pending;
    assign m_axi_wvalid=joint_rst_n&&w_pending;
    assign m_axi_arvalid=joint_rst_n&&ar_pending;
    assign m_axi_bready=joint_rst_n&&return_pending&&write_operation&&!aw_pending&&!w_pending;
    assign m_axi_rready=joint_rst_n&&return_pending&&!write_operation&&!ar_pending;
    always_ff @(posedge clk)begin
        if(!joint_rst_n)begin
            active<=0;write_operation<=0;aw_pending<=0;w_pending<=0;ar_pending<=0;return_pending<=0;
            address<=0;data<=0;expected_response<=0;wait_count<=0;
            rsp_valid<=0;rsp_data<=0;rsp_response<=0;rsp_matched<=0;rsp_protected<=0;
            recovery_required<=0;fault<=0;fault_code<=0;
        end else begin
            if(!fault&&fault_now!=0)begin fault<=1;fault_code<=fault_now;end
            if(rsp_valid&&rsp_ready)rsp_valid<=0;
            if(active)begin if(wait_count<TIMEOUT_CYCLES)wait_count<=wait_count+1'b1;end
            else wait_count<=0;
            if(req_valid&&req_ready)begin
                if(request_ok&&fault_now==0)begin
                    active<=1;write_operation<=req_write;address<=req_address[30:0];data<=req_data;
                    expected_response<=req_expected_response;wait_count<=0;return_pending<=1;
                    aw_pending<=req_write;w_pending<=req_write;ar_pending<=!req_write;
                    recovery_required<=1;
                end else begin
                    rsp_valid<=1;rsp_data<=0;rsp_response<=2'b10;rsp_matched<=0;rsp_protected<=0;
                end
            end
            if(m_axi_awvalid&&m_axi_awready)aw_pending<=0;
            if(m_axi_wvalid&&m_axi_wready)w_pending<=0;
            if(m_axi_arvalid&&m_axi_arready)ar_pending<=0;
            if(b_take||r_take)begin
                active<=0;return_pending<=0;rsp_valid<=1;rsp_protected<=1;
                rsp_data<=r_take?m_axi_rdata:512'b0;
                rsp_response<=r_take?m_axi_rresp:m_axi_bresp;
                rsp_matched<=!fault&&fault_now==0;
            end
        end
    end
endmodule
