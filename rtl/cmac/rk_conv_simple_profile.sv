// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict decoder for one of the frozen `conv-simple` captures.
//
// The 52 raw QWORDs are consumed unchanged. QWORDs 18, 24 and 32 are the three
// job-declared input/weight/output addresses; every other field is compared
// against the generated per-capture template. The final QWORD is the capture's
// documented padding word and must be zero.
//
// The profile id is an elaboration-time choice. No runtime command field can
// widen the accepted geometry or select a different capture.
module rk_conv_simple_profile #(
    parameter int unsigned PROFILE = 0,
    parameter int unsigned WORDS = 52
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        cmd_valid,
    output logic        cmd_ready,
    input  logic [63:0] cmd_data,
    input  logic        cmd_last,
    output logic        config_valid,
    input  logic        config_ready,
    output logic [31:0] config_input_base,
    output logic [31:0] config_weight_base,
    output logic [31:0] config_output_base,
    output logic [31:0] input_bytes,
    output logic [31:0] weight_bytes,
    output logic [31:0] output_bytes,
    output logic        busy,
    output logic        error,
    output logic [7:0]  error_code
);
// The generated table is read with an explicit search path so the
// include does not depend on the tool working directory.
`include "cmac/rk_conv_simple_profiles.svh"

    // Target ids are checked through the generated per-profile table rather
    // than asserted here as separate constants: every field comparison below
    // covers them. Only the word indices the decoder itself acts on are named.
    localparam int unsigned LAST = WORDS - 2;  // PC trigger precedes padding

    typedef enum logic [1:0] {STREAM, VALIDATED, LOCKED, FAULT} state_t;
    state_t state;
    logic [5:0] word_index;
    logic [7:0] saved_code;
    logic [63:0] expected;
    logic address_field, padding_word, last_word;
    logic [32:0] input_end, weight_end, output_end;
    logic ranges_legal, fields_legal, value_legal, boundary_legal;

    always_comb begin
        expected = conv_simple_template_word(PROFILE, word_index);
        // The generated table keeps the address value fields at zero, so an
        // exact comparison is impossible there by construction. The remaining
        // fields must match bit for bit.
        address_field = conv_simple_address_word(word_index);
        padding_word = word_index == 6'(WORDS - 1);
        last_word = word_index == 6'(LAST);
        input_end = {1'b0, config_input_base} + conv_simple_input_bytes(PROFILE);
        weight_end = {1'b0, config_weight_base} + conv_simple_weight_bytes(PROFILE);
        output_end = {1'b0, config_output_base} + conv_simple_output_bytes(PROFILE);
        ranges_legal =
            config_input_base[3:0] == 0 &&
            config_weight_base[3:0] == 0 &&
            config_output_base[3:0] == 0 &&
            input_end <= 33'h100000000 && weight_end <= 33'h100000000 &&
            output_end <= 33'h100000000 &&
            (input_end <= {1'b0, config_weight_base} ||
             weight_end <= {1'b0, config_input_base}) &&
            (input_end <= {1'b0, config_output_base} ||
             output_end <= {1'b0, config_input_base}) &&
            (weight_end <= {1'b0, config_output_base} ||
             output_end <= {1'b0, config_weight_base});
        // The final padding QWORD is part of the captured file and must be
        // exactly zero; the generated template already holds that value, so a
        // plain comparison covers it without a special case.
        fields_legal = cmd_data[63:48] === expected[63:48] &&
                       cmd_data[15:0] === expected[15:0];
        // Relocated addresses carry a full 32-bit value; an upper nibble
        // outside the address field would be an unmodelled write and is
        // rejected. Every other word must equal the generated template.
        value_legal = address_field ? (cmd_data[19:16] === 4'd0 &&
                                       (^cmd_data[47:16]) !== 1'bx)
                    : (padding_word && cmd_data[47:16] === 32'd0) ||
                      cmd_data[47:16] === expected[47:16];
        boundary_legal = cmd_last === last_word;
    end

    assign cmd_ready = rst_n && !error && (state == STREAM || state == LOCKED);
    assign config_valid = rst_n && !error && state == VALIDATED;
    assign busy = rst_n && !error &&
                  ((state == STREAM && word_index != 0) || state == VALIDATED);
    assign error = rst_n && state == FAULT;
    assign error_code = !rst_n ? 8'd0 : error ? saved_code : 8'd0;
    assign input_bytes = conv_simple_input_bytes(PROFILE);
    assign weight_bytes = conv_simple_weight_bytes(PROFILE);
    assign output_bytes = conv_simple_output_bytes(PROFILE);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= STREAM;
            word_index <= 0;
            saved_code <= 0;
            config_input_base <= 0;
            config_weight_base <= 0;
            config_output_base <= 0;
        end else if (cmd_valid && cmd_ready) begin
            if (state == LOCKED) begin
                // One job per configuration; a second stream is a fault.
                saved_code <= 8'd7;
                state <= FAULT;
            end else if (!fields_legal) begin
                saved_code <= 8'd1;
                state <= FAULT;
            end else if (!value_legal) begin
                saved_code <= 8'd2;
                state <= FAULT;
            end else if (!boundary_legal) begin
                saved_code <= 8'd3;
                state <= FAULT;
            end else if (word_index == 6'(WORDS - 1) && !ranges_legal) begin
                saved_code <= 8'd4;
                state <= FAULT;
            end else begin
                case (word_index)
                    6'd18: config_input_base <= cmd_data[47:16];
                    6'd24: config_weight_base <= cmd_data[47:16];
                    6'd32: config_output_base <= cmd_data[47:16];
                    default: begin end
                endcase
                if (word_index == 6'(WORDS - 1)) begin
                    word_index <= 0;
                    state <= VALIDATED;
                end else begin
                    word_index <= word_index + 1'b1;
                end
            end
        end else if (state == VALIDATED && config_ready) begin
            // A single if/else chain: Vivado rejects a second, independent
            // assignment to the same register in an async-reset process
            // ("ambiguous clock in event control"), and it is also the clearer
            // reading of this one-job-per-configuration rule.
            state <= LOCKED;
        end
    end

    initial begin
        if (WORDS != 52)
            $fatal(1, "conv-simple captures are exactly 52 QWORDs");
        if (conv_simple_input_bytes(PROFILE) == 0 ||
            conv_simple_weight_bytes(PROFILE) == 0 ||
            conv_simple_output_bytes(PROFILE) == 0)
            $fatal(1, "unknown conv-simple profile id");
    end
endmodule
