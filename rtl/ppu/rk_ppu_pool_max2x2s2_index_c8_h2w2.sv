// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Capture-bounded standalone PPU candidate for
// fp16_max_k2s2_index_c8_h2w2 only.
//
// It consumes one captured 2x2 C8 surface and emits one value atom paired
// with the eight captured local-position indices. There is no PPU register
// decode, DMA/RDMA, AXI or full-top admission. The capture has finite FP16
// values and a unique maximum in every channel; other numerical policy is not
// inferred.
module rk_ppu_pool_max2x2s2_index_c8_h2w2 (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         in_valid,
    output logic         in_ready,
    input  logic [127:0] in_atom,
    output logic         out_valid,
    input  logic         out_ready,
    output logic [127:0] out_value_atom,
    output logic [127:0] out_index_atom,
    output logic [7:0]   out_unique,
    output logic         out_last
);
    logic [127:0] input_atom [0:2];
    logic [1:0] input_count_q;
    logic frame_done_q;
    logic [127:0] value_atom_q;
    logic [127:0] index_atom_q;
    logic [7:0] unique_mask_q;
    logic out_valid_q;
    logic out_last_q;

    logic [31:0] pair01 [0:7];
    logic [31:0] pair23 [0:7];
    logic [31:0] pair_final [0:7];
    logic [127:0] value_atom_next;
    logic [127:0] index_atom_next;
    logic [7:0] unique_mask_next;

    // Return {16-bit source position, selected FP16 value}. On equal finite
    // values choose the earlier input, matching row-major np.argmax for this
    // candidate. Non-finite values and opposite signed-zero ties are unknown.
    function automatic logic [31:0] fp16_max_pick(
        input logic [15:0] a,
        input logic [15:0] a_index,
        input logic [15:0] b,
        input logic [15:0] b_index
    );
        logic choose_a;
        begin
            if ((a[14:10] == 5'h1f) || (b[14:10] == 5'h1f) ||
                ((a[14:0] == 15'b0) && (b[14:0] == 15'b0) && (a[15] != b[15]))) begin
                fp16_max_pick = 32'hxxxxxxxx;
            end else if (a[15] != b[15]) begin
                choose_a = !a[15];
                fp16_max_pick = choose_a ? {a_index, a} : {b_index, b};
            end else if (!a[15]) begin
                choose_a = (a[14:0] >= b[14:0]);
                fp16_max_pick = choose_a ? {a_index, a} : {b_index, b};
            end else begin
                choose_a = (a[14:0] <= b[14:0]);
                fp16_max_pick = choose_a ? {a_index, a} : {b_index, b};
            end
        end
    endfunction

    always_comb begin : COMPUTE_OUTPUT
        integer match_count;
        for (integer lane = 0; lane < 8; lane = lane + 1) begin
            pair01[lane] = fp16_max_pick(
                input_atom[0][lane*16 +: 16], 16'd0,
                input_atom[1][lane*16 +: 16], 16'd1
            );
            pair23[lane] = fp16_max_pick(
                input_atom[2][lane*16 +: 16], 16'd8,
                in_atom[lane*16 +: 16], 16'd9
            );
            pair_final[lane] = fp16_max_pick(
                pair01[lane][15:0], pair01[lane][31:16],
                pair23[lane][15:0], pair23[lane][31:16]
            );
            value_atom_next[lane*16 +: 16] = pair_final[lane][15:0];
            index_atom_next[lane*16 +: 16] = pair_final[lane][31:16];
            match_count = 0;
            if (input_atom[0][lane*16 +: 16] == pair_final[lane][15:0])
                match_count = match_count + 1;
            if (input_atom[1][lane*16 +: 16] == pair_final[lane][15:0])
                match_count = match_count + 1;
            if (input_atom[2][lane*16 +: 16] == pair_final[lane][15:0])
                match_count = match_count + 1;
            if (in_atom[lane*16 +: 16] == pair_final[lane][15:0])
                match_count = match_count + 1;
            unique_mask_next[lane] = (match_count == 1);
        end
    end

    assign in_ready       = rst_n && !frame_done_q && (!out_valid_q || out_ready);
    assign out_valid      = out_valid_q;
    assign out_value_atom = value_atom_q;
    assign out_index_atom = index_atom_q;
    assign out_unique     = unique_mask_q;
    assign out_last       = out_last_q;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            input_count_q <= 2'd0;
            frame_done_q  <= 1'b0;
            value_atom_q  <= 128'b0;
            index_atom_q  <= 128'b0;
            unique_mask_q <= 8'b0;
            out_valid_q   <= 1'b0;
            out_last_q    <= 1'b0;
        end else begin
            if (out_valid_q && out_ready) begin
                out_valid_q <= 1'b0;
                out_last_q  <= 1'b0;
            end
            if (in_valid && in_ready) begin
                if (input_count_q == 2'd3) begin
                    value_atom_q <= value_atom_next;
                    index_atom_q <= index_atom_next;
                    unique_mask_q <= unique_mask_next;
                    out_valid_q  <= 1'b1;
                    out_last_q   <= 1'b1;
                    frame_done_q <= 1'b1;
                end else begin
                    input_atom[input_count_q] <= in_atom;
                    input_count_q <= input_count_q + 1'b1;
                end
            end
        end
    end
endmodule
