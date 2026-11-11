// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Synthesis-only explicit simple-dual-port BRAM for the runtime front's operand
// stores. Vivado 2026.1 refuses to infer block RAM for the prototype's plain
// unpacked-array pattern in out-of-context synthesis, so the area estimate uses
// this explicit mapping instead. It is instantiated only under `ifdef
// SYNTHESIS` (see rk_conv_runtime_front.sv): simulation keeps the original
// arrays, so the accepted equivalence receipts are unchanged behaviourally.
//
// Semantics mirror the arrays exactly: one synchronous write port and one
// synchronous (registered) read port, read data holds its previous value when
// `re` is low. No scheduling, gating or arithmetic is added here.
module rk_runtime_sdp_bram #(
    parameter int unsigned DATA_W = 16,
    parameter int unsigned ADDR_W = 15,
    parameter int unsigned DEPTH  = 1
) (
    input  logic              clk,
    input  logic              we,
    input  logic [ADDR_W-1:0] waddr,
    input  logic [DATA_W-1:0] wdata,
    input  logic              re,
    input  logic [ADDR_W-1:0] raddr,
    output logic [DATA_W-1:0] rdata
);
    (* ram_style = "block" *) logic [DATA_W-1:0] mem [0:DEPTH-1];

    always @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
        if (re) rdata <= mem[raddr];
    end
endmodule
