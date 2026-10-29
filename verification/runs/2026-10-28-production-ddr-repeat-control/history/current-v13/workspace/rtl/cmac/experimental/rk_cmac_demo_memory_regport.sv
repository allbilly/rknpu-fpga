// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Same K65 trace apertures as rk_cmac_demo_memory, with registered RAM-facing
// address/data/enable/write controls. Only response ownership resets async.
// An accepted write may retire across reset; reset never promises rollback.
module rk_cmac_demo_memory_regport (
    input logic clk,rst_n,
    input logic req_valid,
    output logic req_ready,
    input logic req_write,
    input logic [31:0] req_addr,
    input logic [15:0] req_wdata,
    output logic rsp_valid,
    input logic rsp_ready,
    output logic [15:0] rsp_rdata,
    output logic rsp_error,
    input logic host_valid,
    output logic host_ready,
    input logic host_write,
    input logic [11:0] host_index,
    input logic [15:0] host_wdata,
    output logic host_rsp_valid,
    input logic host_rsp_ready,
    output logic [15:0] host_rdata
);
    (* ram_style="block" *) logic [15:0] storage [0:4095];
    logic [11:0] translated;
    logic mapped,core_pending,host_pending,pending_error;
    logic bram_core_en,bram_core_we,bram_host_en,bram_host_we;
    logic [11:0] bram_core_index,bram_host_index;
    logic [15:0] bram_core_data,bram_host_data;
    wire core_fire=req_valid&&req_ready;
    wire host_fire=host_valid&&host_ready;
    always @* begin
        mapped=0;translated=0;
        if (!req_addr[0]) begin
            if (req_addr>=32'h10010000&&req_addr<32'h100101c0) begin mapped=1;translated=12'((req_addr-32'h10010000)>>1);end
            else if (req_addr>=32'h10020000&&req_addr<32'h10021840) begin mapped=1;translated=12'((req_addr-32'h10020000+448)>>1);end
            else if (req_addr>=32'h10040000&&req_addr<32'h10040140) begin mapped=1;translated=12'((req_addr-32'h10040000+6656)>>1);end
            else if (req_addr>=32'h100e0000&&req_addr<32'h100e01c0) begin mapped=1;translated=12'((req_addr-32'h100e0000+6976)>>1);end
        end
    end
    assign req_ready=rst_n&&!core_pending&&!rsp_valid;
    assign host_ready=rst_n&&!host_pending&&!host_rsp_valid;
    initial begin
        bram_core_en=0;bram_core_we=0;bram_host_en=0;bram_host_we=0;
        bram_core_index=0;bram_host_index=0;bram_core_data=0;bram_host_data=0;
    end
    // These registers have no async set/reset. Reset blocks new admission;
    // an already captured operation remains stable until its RAM clock edge.
    always_ff @(posedge clk)begin
        bram_core_en<=core_fire&&mapped;
        bram_core_we<=core_fire&&mapped&&req_write;
        bram_host_en<=host_fire;
        bram_host_we<=host_fire&&host_write;
        if(core_fire)begin bram_core_index<=translated;bram_core_data<=req_wdata;end
        if(host_fire)begin bram_host_index<=host_index;bram_host_data<=host_wdata;end
    end
    always @(posedge clk)if(bram_core_en)begin
        if(bram_core_we)storage[bram_core_index]<=bram_core_data;
        rsp_rdata<=storage[bram_core_index];
    end
    always @(posedge clk)if(bram_host_en)begin
        if(bram_host_we)storage[bram_host_index]<=bram_host_data;
        host_rdata<=storage[bram_host_index];
    end
    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            core_pending<=0;host_pending<=0;pending_error<=0;
            rsp_valid<=0;rsp_error<=0;host_rsp_valid<=0;
        end else begin
            if(rsp_valid&&rsp_ready)rsp_valid<=0;
            if(host_rsp_valid&&host_rsp_ready)host_rsp_valid<=0;
            if(core_pending)begin rsp_valid<=1;rsp_error<=pending_error;core_pending<=0;end
            if(host_pending)begin host_rsp_valid<=1;host_pending<=0;end
            if(core_fire)begin core_pending<=1;pending_error<=!mapped;end
            if(host_fire)host_pending<=1;
        end
    end
endmodule
