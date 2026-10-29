// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Fixed K65 trace apertures, NOT an allocator, runtime gather engine or CBUF.
// Host port uses flat halfword indices only before/after engine ownership.
module rk_cmac_demo_memory (
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
    logic mapped,core_fire,host_fire;
    always @* begin
        mapped=0;translated=0;
        if (!req_addr[0]) begin
            if (req_addr>=32'h10010000&&req_addr<32'h100101c0) begin mapped=1;translated=12'((req_addr-32'h10010000)>>1);end
            else if (req_addr>=32'h10020000&&req_addr<32'h10021840) begin mapped=1;translated=12'((req_addr-32'h10020000+448)>>1);end
            else if (req_addr>=32'h10040000&&req_addr<32'h10040140) begin mapped=1;translated=12'((req_addr-32'h10040000+6656)>>1);end
            else if (req_addr>=32'h100e0000&&req_addr<32'h100e01c0) begin mapped=1;translated=12'((req_addr-32'h100e0000+6976)>>1);end
        end
    end
    assign req_ready=rst_n&&!rsp_valid;
    assign host_ready=rst_n&&!host_rsp_valid;
    assign core_fire=req_valid&&req_ready&&mapped;
    assign host_fire=host_valid&&host_ready;
    // Keep both memory ports synchronous and without array/data reset for
    // true block-RAM inference. Only response ownership resets asynchronously.
    always @(posedge clk) if (core_fire) begin
        if (req_write) storage[translated]<=req_wdata;
        rsp_rdata<=storage[translated];
    end
    always @(posedge clk) if (host_fire) begin
        if (host_write) storage[host_index]<=host_wdata;
        host_rdata<=storage[host_index];
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin rsp_valid<=0;rsp_error<=0;host_rsp_valid<=0;end
        else begin
            if (rsp_valid&&rsp_ready) rsp_valid<=0;
            if (req_valid&&req_ready) begin rsp_valid<=1;rsp_error<=!mapped;end
            if (host_rsp_valid&&host_rsp_ready) host_rsp_valid<=0;
            if (host_fire) host_rsp_valid<=1;
        end
    end
endmodule
