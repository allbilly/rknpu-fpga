// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Fixed trace-only aperture, NOT a general device memory allocator or RK CBUF.
// Translation preserves command/data bytes; gaps and odd addresses fault.
module rk_demo_memory (
    input logic clk, rst_n,
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
    input logic [31:0] host_addr,
    input logic [15:0] host_wdata,
    output logic host_rsp_valid,
    input logic host_rsp_ready,
    output logic [15:0] host_rdata,
    output logic host_error
);
    function automatic logic [31:0] translate(input logic [31:0] device_address);
        begin
            if      (device_address>=32'h10001000 && device_address<32'h10001020) translate=device_address-32'h10001000;
            else if (device_address>=32'h10020000 && device_address<32'h10020020) translate=device_address-32'h10020000+32'h020;
            else if (device_address>=32'h10040000 && device_address<32'h10040020) translate=device_address-32'h10040000+32'h040;
            else if (device_address>=32'h10060000 && device_address<32'h10060020) translate=device_address-32'h10060000+32'h060;
            else if (device_address>=32'h10061000 && device_address<32'h10061020) translate=device_address-32'h10061000+32'h080;
            else if (device_address>=32'h100e0000 && device_address<32'h100e0200) translate=device_address-32'h100e0000+32'h100;
            else translate=32'hffffffff;
            if (translate!=32'hffffffff) translate=translate+32'h10000000;
        end
    endfunction
    rk_bram #(.BASE(32'h10000000), .BYTES(4096)) ram (
        .clk(clk), .rst_n(rst_n), .req_valid(req_valid), .req_ready(req_ready),
        .req_write(req_write), .req_addr(translate(req_addr)), .req_wdata(req_wdata),
        .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata), .rsp_error(rsp_error),
        .host_valid(host_valid), .host_ready(host_ready), .host_write(host_write),
        .host_addr(translate(host_addr)), .host_wdata(host_wdata), .host_rsp_valid(host_rsp_valid),
        .host_rsp_ready(host_rsp_ready), .host_rdata(host_rdata), .host_error(host_error)
    );
endmodule
