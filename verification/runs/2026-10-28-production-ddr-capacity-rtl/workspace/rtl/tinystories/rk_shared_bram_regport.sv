// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One outstanding transaction per port. RAM-facing enables/address/data have
// no reset branch. A previously accepted write may commit across global reset;
// response ownership is flushed, not memory contents or accepted write effects.
module rk_shared_bram_regport #(
    parameter int unsigned BYTES=1048576,
    parameter logic [31:0] BASE=32'h10000000
) (
    input wire clk,rst_n,
    input wire req_valid,
    output wire req_ready,
    input wire req_write,
    input wire [31:0] req_addr,
    input wire [15:0] req_wdata,
    output logic rsp_valid,
    input wire rsp_ready,
    output wire [15:0] rsp_rdata,
    output logic rsp_error,
    input wire host_valid,
    output wire host_ready,
    input wire host_write,
    input wire [31:0] host_addr,
    input wire [15:0] host_wdata,
    output logic host_rsp_valid,
    input wire host_rsp_ready,
    output wire [15:0] host_rdata,
    output logic host_error,
    output wire engine_pending,host_pending
);
    localparam int AW=$clog2(BYTES/2);
    (* ram_style="block" *) logic [15:0] storage[0:BYTES/2-1];
    logic e_pending,h_pending,e_bad,h_bad;
    logic e_en,h_en,e_write,h_write;
    logic [AW-1:0] e_index,h_index;
    logic [15:0] e_data,h_data,e_read,h_read;
    wire [31:0] offset=req_addr-BASE;
    wire [31:0] host_offset=host_addr-BASE;
    logic address_ok,host_address_ok;
    always @* begin
        address_ok=req_addr>=BASE&&offset<BYTES&&!req_addr[0];
        host_address_ok=host_addr>=BASE&&host_offset<BYTES&&!host_addr[0];
`ifndef SYNTHESIS
        if((^req_addr)===1'bx)address_ok=0;
        if((^host_addr)===1'bx)host_address_ok=0;
`endif
    end
    initial begin
        e_en=0;h_en=0;
        if(BYTES<4||(BYTES&(BYTES-1))!=0||BASE[0]||
           ({1'b0,BASE}+33'(BYTES))>33'h100000000)
            $fatal(1,"Invalid shared registered BRAM range");
    end
    assign req_ready=rst_n&&!e_pending&&!rsp_valid;
    assign host_ready=rst_n&&!h_pending&&!host_rsp_valid;
    assign engine_pending=e_pending||rsp_valid;
    assign host_pending=h_pending||host_rsp_valid;
    assign rsp_rdata=e_read;
    assign host_rdata=h_read;
    // RAM access at B uses only the request controls registered at A. Even
    // reset cannot asynchronously alter a RAM enable/address/data register.
    always @(posedge clk) begin
        e_en<=rst_n&&req_valid&&req_ready&&address_ok;
        if(rst_n&&req_valid&&req_ready)begin
            e_index<=offset[AW:1];e_write<=req_write;e_data<=req_wdata;
        end
        if(e_en)begin
            if(e_write)storage[e_index]<=e_data;
            e_read<=storage[e_index];
        end
    end
    always @(posedge clk) begin
        h_en<=rst_n&&host_valid&&host_ready&&host_address_ok;
        if(rst_n&&host_valid&&host_ready)begin
            h_index<=host_offset[AW:1];h_write<=host_write;h_data<=host_wdata;
        end
        if(h_en)begin
            if(h_write)storage[h_index]<=h_data;
            h_read<=storage[h_index];
        end
    end
    always @(posedge clk)begin
        if(!rst_n)begin e_pending<=0;e_bad<=0;rsp_valid<=0;rsp_error<=0;end
        else begin
            if(rsp_valid&&rsp_ready)rsp_valid<=0;
            if(req_valid&&req_ready)begin e_pending<=1;e_bad<=!address_ok;end
            if(e_pending)begin e_pending<=0;rsp_valid<=1;rsp_error<=e_bad;end
        end
    end
    always @(posedge clk)begin
        if(!rst_n)begin h_pending<=0;h_bad<=0;host_rsp_valid<=0;host_error<=0;end
        else begin
            if(host_rsp_valid&&host_rsp_ready)host_rsp_valid<=0;
            if(host_valid&&host_ready)begin h_pending<=1;h_bad<=!host_address_ok;end
            if(h_pending)begin h_pending<=0;host_rsp_valid<=1;host_error<=h_bad;end
        end
    end
endmodule
