// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One-deep register slice for a CMAC operand frame.
//
// Why this exists. `rk_conv_3x3_valid_c4_front` drives a registered
// `frame_weight`/`frame_data` bus straight into the CMAC cells. The bus is
// 8192 + 512 bits with a fanout of sixteen kernel lanes, so once the front's
// registers are packed next to its block RAM the net has to cross the die and
// still leave time for the multiply, the CACC reduction and the output
// register. On the six-page image that measured -1.645 ns, with 81% of the
// delay in routing.
//
// This slice puts one register stage on the boundary, which gives the placer a
// natural place to put the operand registers next to the cells and splits the
// path into a route-only leg and a logic-only leg. It adds exactly one cycle of
// latency per frame; the frame *sequence* is unchanged.
//
// Contract preserved:
//   * `in_first`/`in_last`/`in_last_output` and the address travel with the
//     payload, so the CACC tag stays stable across all taps of an atom;
//   * a frame is accepted only when both sides handshake, so no frame is
//     dropped or duplicated;
//   * cancel/error clears the slice and never emits a stale frame.
module rk_runtime_frame_stage #(
    // Corpus-verified geometry: max 16 channel lanes and 16 kernel lanes.
    parameter int unsigned ATOMIC_C = 16,
    parameter int unsigned ATOMIC_K = 16
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         cancel,
    // Upstream (front) side.
    input  logic         in_valid,
    output logic         in_ready,
    input  logic [ATOMIC_C*16-1:0] in_data,
    input  logic [ATOMIC_K*ATOMIC_C*16-1:0] in_weight,
    input  logic [ATOMIC_C-1:0] in_data_mask,
    input  logic [ATOMIC_K*ATOMIC_C-1:0] in_weight_mask,
    input  logic [31:0]  in_address,
    input  logic         in_first,
    input  logic         in_last,
    input  logic         in_last_output,
    // Downstream (arithmetic) side.
    output logic         out_valid,
    input  logic         out_ready,
    output logic [ATOMIC_C*16-1:0] out_data,
    output logic [ATOMIC_K*ATOMIC_C*16-1:0] out_weight,
    output logic [ATOMIC_C-1:0] out_data_mask,
    output logic [ATOMIC_K*ATOMIC_C-1:0] out_weight_mask,
    output logic [31:0]  out_address,
    output logic         out_first,
    output logic         out_last,
    output logic         out_last_output
);
    logic full_q;
    logic [ATOMIC_C*16-1:0] data_q;
    logic [ATOMIC_K*ATOMIC_C*16-1:0] weight_q;
    logic [ATOMIC_C-1:0] data_mask_q;
    logic [ATOMIC_K*ATOMIC_C-1:0] weight_mask_q;
    logic [31:0] address_q;
    logic first_q, last_q, last_output_q;

    assign in_ready  = rst_n && !cancel && (!full_q || out_ready);
    assign out_valid = rst_n && !cancel && full_q;

    assign out_data        = data_q;
    assign out_weight      = weight_q;
    assign out_data_mask   = data_mask_q;
    assign out_weight_mask = weight_mask_q;
    assign out_address     = address_q;
    assign out_first       = first_q;
    assign out_last        = last_q;
    assign out_last_output = last_output_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            full_q <= 1'b0;
            data_q <= '0;
            weight_q <= '0;
            data_mask_q <= '0;
            weight_mask_q <= '0;
            address_q <= '0;
            first_q <= 1'b0;
            last_q <= 1'b0;
            last_output_q <= 1'b0;
        end else if (cancel) begin
            // A cancelled frame must never reach the accumulator.
            full_q <= 1'b0;
        end else begin
            if (in_valid && in_ready) begin
                full_q <= 1'b1;
                data_q <= in_data;
                weight_q <= in_weight;
                data_mask_q <= in_data_mask;
                weight_mask_q <= in_weight_mask;
                address_q <= in_address;
                first_q <= in_first;
                last_q <= in_last;
                last_output_q <= in_last_output;
            end else if (full_q && out_ready) begin
                full_q <= 1'b0;
            end
        end
    end
endmodule
