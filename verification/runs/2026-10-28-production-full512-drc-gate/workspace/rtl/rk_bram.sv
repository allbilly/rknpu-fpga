// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Synchronous true-dual-port RAM with response backpressure and range checking.
// The host MUST NOT access this RAM while the accelerator is busy. Cross-port
// read/write collisions are deliberately not assigned a device-independent meaning.
// No array reset: resetting RAM contents prevents normal BRAM inference.
module rk_bram #(
    parameter int unsigned BYTES = 4096,
    parameter logic [31:0] BASE = 32'h10000000
) (
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
    // Legal configurations: BYTES is a power of two >= 4; BASE is even,
    // and BASE+BYTES fits the 32-bit device address space. Both ports share clk.
    // Plain clocked processes permit the two physical BRAM write ports.
    localparam int AW = $clog2(BYTES / 2);
    (* ram_style = "block" *) logic [15:0] storage [0:BYTES/2-1];
    initial begin
        if (BYTES < 4 || (BYTES & (BYTES - 1)) != 0 || BASE[0] ||
            ({1'b0, BASE} + 33'(BYTES)) > 33'h100000000)
            $fatal(1, "BRAM needs power-of-two BYTES >= 4 and an even, nonwrapping BASE");
    end
    wire [31:0] offset = req_addr - BASE;
    wire [31:0] host_offset = host_addr - BASE;
    wire addr_ok = (req_addr >= BASE) && (offset < BYTES) && !req_addr[0];
    wire host_addr_ok = (host_addr >= BASE) && (host_offset < BYTES) && !host_addr[0];
    assign req_ready = !rsp_valid || rsp_ready;
    assign host_ready = !host_rsp_valid || host_rsp_ready;
    // Memory accesses are outside the reset branch to retain BRAM inference.
    always @(posedge clk) begin
        if (rst_n && req_valid && req_ready && addr_ok) begin
            if (req_write) storage[offset[AW:1]] <= req_wdata;
            rsp_rdata <= storage[offset[AW:1]];
        end
        if (!rst_n) begin rsp_valid <= 0; rsp_error <= 0; end
        else if (req_ready) begin
            rsp_valid <= req_valid;
            if (req_valid) rsp_error <= !addr_ok;
        end
    end
    always @(posedge clk) begin
        if (rst_n && host_valid && host_ready && host_addr_ok) begin
            if (host_write) storage[host_offset[AW:1]] <= host_wdata;
            host_rdata <= storage[host_offset[AW:1]];
        end
        if (!rst_n) begin host_rsp_valid <= 0; host_error <= 0; end
        else if (host_ready) begin
            host_rsp_valid <= host_valid;
            if (host_valid) host_error <= !host_addr_ok;
        end
    end
endmodule
