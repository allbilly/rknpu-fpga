// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict decoder for one of the captured FP16 3x3 spatial tasks.
// The 54 raw QWORDs and task-end sideband are consumed unchanged; only the
// three job-declared DMA address values are relocatable.
module rk_conv_3x3_valid_c4_profile #(
    // Elaboration-time selection only. Runtime commands do not select shape.
    parameter bit STRIDE2 = 1'b0,
    parameter bit PAD1_ZERO_FRAME = 1'b0,
    parameter bit GROUPED_C2 = 1'b0,
    parameter bit SPLIT_OC_C16 = 1'b0,
    parameter bit DEPTHWISE_C3 = 1'b0
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
    output logic        busy,
    output logic        error,
    output logic [7:0]  error_code
);
    typedef enum logic [1:0] {STREAM, VALIDATED, LOCKED, FAULT} state_t;
    state_t state;
    logic [5:0] word_index;
    logic [7:0] saved_code;
    logic [15:0] expected_target, expected_offset;
    logic [31:0] expected_value;
    logic field_exists, address_field, address_value_known;
    logic [32:0] input_end, weight_end, output_end;
    logic [32:0] input_bytes, output_bytes, weight_bytes;
    logic ranges_legal, word_fields_legal, word_value_legal, boundary_legal;
    logic [7:0] word_error_code;

    always @* begin
        expected_target = 16'h0000;
        expected_offset = 16'h0000;
        expected_value = 32'h00000000;
        field_exists = 1'b1;
        address_field = 1'b0;
        case (word_index)
            0:  begin expected_target=16'h1001; expected_offset=16'h4004; expected_value=32'h0000000e; end
            1:  begin expected_target=16'h2001; expected_offset=16'h5004; expected_value=32'h00000000; end
            2:  begin expected_target=16'h2001; expected_offset=16'h5034; expected_value=32'h00000000; end
            3:  begin expected_target=16'h2001; expected_offset=16'h5044; expected_value=32'h00000000; end
            4:  begin expected_target=16'h0201; expected_offset=16'h100c; expected_value=DEPTHWISE_C3 ? 32'h00000123 : 32'h00000120; end
            5:  begin expected_target=16'h0201; expected_offset=16'h1010; expected_value=DEPTHWISE_C3 ? 32'h000000d0 : (STRIDE2 || PAD1_ZERO_FRAME) ? 32'h000000e0 : GROUPED_C2 ? 32'h00000080 : 32'h000000c0; end
            6:  begin expected_target=16'h0201; expected_offset=16'h1014; expected_value=STRIDE2 ? 32'h00000012 : 32'h00000009; end
            7:  begin expected_target=16'h0201; expected_offset=16'h1020; expected_value=DEPTHWISE_C3 ? 32'h001c000b : GROUPED_C2 ? 32'h00050005 : (STRIDE2 || PAD1_ZERO_FRAME) ? 32'h000b000b : 32'h00090009; end
            8:  begin expected_target=16'h0201; expected_offset=16'h1024; expected_value=DEPTHWISE_C3 ? 32'h00020008 : GROUPED_C2 ? 32'h00010010 : SPLIT_OC_C16 ? 32'h000f0010 : 32'h00030010; end
            9:  begin expected_target=16'h0201; expected_offset=16'h1028; expected_value=DEPTHWISE_C3 ? 32'h0000001a : GROUPED_C2 ? 32'h00000003 : PAD1_ZERO_FRAME ? 32'h00000009 : STRIDE2 ? 32'h00000005 : 32'h00000007; end
            10: begin expected_target=16'h0201; expected_offset=16'h102c; expected_value=DEPTHWISE_C3 ? 32'h000000ea : GROUPED_C2 ? 32'h00000009 : PAD1_ZERO_FRAME ? 32'h00000051 : STRIDE2 ? 32'h00000019 : 32'h00000031; end
            11: begin expected_target=16'h0201; expected_offset=16'h1030; expected_value=DEPTHWISE_C3 ? 32'h00000090 : SPLIT_OC_C16 ? 32'h00000900 : 32'h00000480; end
            12: begin expected_target=16'h0201; expected_offset=16'h1034; expected_value=DEPTHWISE_C3 ? 32'h00000090 : 32'h00000120; end
            13: begin expected_target=16'h0201; expected_offset=16'h1038; expected_value=DEPTHWISE_C3 ? 32'h03030001 : SPLIT_OC_C16 ? 32'h03030008 : 32'h03030004; end
            14: begin expected_target=16'h0201; expected_offset=16'h1040; expected_value=DEPTHWISE_C3 ? 32'h0000001b : SPLIT_OC_C16 ? 32'h0000001b : 32'h000000b1; end
            15: begin expected_target=16'h0201; expected_offset=16'h1044; expected_value=DEPTHWISE_C3 ? 32'h00000007 : (STRIDE2 || PAD1_ZERO_FRAME) ? 32'h00000006 : GROUPED_C2 ? 32'h00000003 : 32'h00000005; end
            16: begin expected_target=16'h0201; expected_offset=16'h104c; expected_value=32'h00000001; end
            17: begin expected_target=16'h0201; expected_offset=16'h1050; expected_value=32'h00010000; end
            18: begin expected_target=16'h0201; expected_offset=16'h1054; expected_value=32'h00010000; end
            19: begin expected_target=16'h0201; expected_offset=16'h1058; expected_value=32'h00010000; end
            20: begin expected_target=16'h0201; expected_offset=16'h105c; expected_value=32'h00010000; end
            21: begin expected_target=16'h0201; expected_offset=16'h1070; address_field=1'b1; end
            22: begin expected_target=16'h0201; expected_offset=16'h1078; expected_value=32'h000f000f; end
            23: begin expected_target=16'h0201; expected_offset=16'h107c; expected_value=DEPTHWISE_C3 ? 32'h00000070 : GROUPED_C2 ? 32'h00000014 : (STRIDE2 || PAD1_ZERO_FRAME) ? 32'h0000002c : 32'h00000024; end
            24: begin expected_target=16'h0201; expected_offset=16'h1080; expected_value=DEPTHWISE_C3 ? 32'h000000c4 : GROUPED_C2 ? 32'h00000005 : (STRIDE2 || PAD1_ZERO_FRAME) ? 32'h0000004d : 32'h0000002d; end
            25: begin expected_target=16'h0201; expected_offset=16'h1084; expected_value=DEPTHWISE_C3 ? 32'h001c000b : GROUPED_C2 ? 32'h00050005 : (STRIDE2 || PAD1_ZERO_FRAME) ? 32'h000b000b : 32'h00090009; end
            26: begin expected_target=16'h0201; expected_offset=16'h1088; expected_value=DEPTHWISE_C3 ? 32'h00000008 : 32'h00000010; end
            27: begin expected_target=16'h0201; expected_offset=16'h1110; address_field=1'b1; end
            28: begin expected_target=16'h0201; expected_offset=16'h1180; expected_value=DEPTHWISE_C3 ? 32'h00000007 : 32'h00000000; end
            29: begin expected_target=16'h0801; expected_offset=16'h3010; expected_value=DEPTHWISE_C3 ? 32'h00000203 : 32'h00000201; end
            30: begin expected_target=16'h0801; expected_offset=16'h3014; expected_value=DEPTHWISE_C3 ? 32'h00080019 : GROUPED_C2 ? 32'h00020002 : PAD1_ZERO_FRAME ? 32'h00080008 : STRIDE2 ? 32'h00040004 : 32'h00060006; end
            31: begin expected_target=16'h0801; expected_offset=16'h3018; expected_value=32'h0000001f; end
            32: begin expected_target=16'h0801; expected_offset=16'h3030; expected_value=32'h00000000; end
            33: begin expected_target=16'h1001; expected_offset=16'h400c; expected_value=DEPTHWISE_C3 ? 32'h000001fc : 32'h000001e4; end
            34: begin expected_target=16'h1001; expected_offset=16'h4010; expected_value=32'h48000002; end
            35: begin expected_target=16'h1001; expected_offset=16'h4020; address_field=1'b1; end
            36: begin expected_target=16'h1001; expected_offset=16'h4024; expected_value=DEPTHWISE_C3 ? 32'h00000ec0 : GROUPED_C2 ? 32'h000000c0 : PAD1_ZERO_FRAME ? 32'h00000540 : STRIDE2 ? 32'h000001c0 : 32'h00000340; end
            37: begin expected_target=16'h1001; expected_offset=16'h4030; expected_value=DEPTHWISE_C3 ? 32'h00000019 : GROUPED_C2 ? 32'h00000002 : PAD1_ZERO_FRAME ? 32'h00000008 : STRIDE2 ? 32'h00000004 : 32'h00000006; end
            38: begin expected_target=16'h1001; expected_offset=16'h4034; expected_value=DEPTHWISE_C3 ? 32'h00000008 : GROUPED_C2 ? 32'h00000002 : PAD1_ZERO_FRAME ? 32'h00000008 : STRIDE2 ? 32'h00000004 : 32'h00000006; end
            39: begin expected_target=16'h1001; expected_offset=16'h4038; expected_value=32'h00000000; end
            40: begin expected_target=16'h1001; expected_offset=16'h403c; expected_value=DEPTHWISE_C3 ? 32'h0002001f : SPLIT_OC_C16 ? 32'h0007001f : 32'h0003001f; end
            41: begin expected_target=16'h1001; expected_offset=16'h4040; expected_value=32'h00000053; end
            42: begin expected_target=16'h1001; expected_offset=16'h4050; expected_value=DEPTHWISE_C3 ? 32'h0000036e : 32'h00000126; end
            43: begin expected_target=16'h1001; expected_offset=16'h4058; expected_value=32'h0000001f; end
            44: begin expected_target=16'h1001; expected_offset=16'h405c; expected_value=DEPTHWISE_C3 ? 32'h00080019 : GROUPED_C2 ? 32'h00020002 : PAD1_ZERO_FRAME ? 32'h00080008 : STRIDE2 ? 32'h00040004 : 32'h00060006; end
            45: begin expected_target=16'h1001; expected_offset=16'h4060; expected_value=32'h00000053; end
            46: begin expected_target=16'h1001; expected_offset=16'h4070; expected_value=32'h00000383; end
            47: begin expected_target=16'h1001; expected_offset=16'h4078; expected_value=32'h00000001; end
            48: begin expected_target=16'h1001; expected_offset=16'h4084; expected_value=32'h00010001; end
            49: begin expected_target=16'h1001; expected_offset=16'h40c0; expected_value=DEPTHWISE_C3 ? 32'h00001d80 : GROUPED_C2 ? 32'h00000180 : PAD1_ZERO_FRAME ? 32'h00000a80 : STRIDE2 ? 32'h00000380 : 32'h00000680; end
            50: begin expected_target=16'h0101; expected_offset=16'h0010; expected_value=32'h00000000; end
            51: begin expected_target=16'h0101; expected_offset=16'h0014; expected_value=32'h00000000; end
            52: begin expected_target=16'h0041; expected_offset=16'h0000; expected_value=32'h00000000; end
            53: begin expected_target=16'h0081; expected_offset=16'h0008; expected_value=32'h0000000d; end
            default: begin field_exists=1'b0; end
        endcase

        // Packed BO sizes are the donor's own allocations, not arbitrary
        // limits: C2 gives 25 pixels x 16 bytes in each of two C1 planes,
        // C4 3x3 gives 81 pixels, and each output BO carries 32 aligned
        // output atoms. Only the C4 stride-1 and explicit-zero-frame cases
        // differ in plane count.
        input_bytes = (GROUPED_C2 ? 33'd800 : 33'd2592) +
                      ((STRIDE2 || PAD1_ZERO_FRAME) ? 33'd1280 : 33'd0) +
                      (DEPTHWISE_C3 ? 33'd2336 : 33'd0);
        // The split-OC tasks reuse the 2,592-byte C16/H9/W9 input BO and the
        // 2,304-byte kh-major weight BO; only weight_range differs.
        weight_bytes = DEPTHWISE_C3 ? 33'd144 :
                       SPLIT_OC_C16 ? 33'd2304 : 33'd1152;
        output_bytes = (GROUPED_C2 ? 33'd768 : 33'd3328) +
                       (PAD1_ZERO_FRAME ? 33'd2048 : 33'd0) +
                       (DEPTHWISE_C3 ? 33'd11776 : 33'd0) -
                       (STRIDE2 ? 33'd1536 : 33'd0);
        input_end = {1'b0, config_input_base} + input_bytes;
        weight_end = {1'b0, config_weight_base} + weight_bytes;
        output_end = {1'b0, config_output_base} + output_bytes;
        ranges_legal = config_input_base[3:0] == 0 &&
                       config_weight_base[3:0] == 0 &&
                       config_output_base[3:0] == 0 &&
                       input_end <= 33'h100000000 &&
                       weight_end <= 33'h100000000 &&
                       output_end <= 33'h100000000 &&
                       (input_end <= {1'b0, config_weight_base} ||
                        weight_end <= {1'b0, config_input_base}) &&
                       (input_end <= {1'b0, config_output_base} ||
                        output_end <= {1'b0, config_input_base}) &&
                       (weight_end <= {1'b0, config_output_base} ||
                        output_end <= {1'b0, config_weight_base});

        word_fields_legal = field_exists &&
                            cmd_data[63:48] === expected_target &&
                            cmd_data[15:0] === expected_offset;
        address_value_known = (^cmd_data[47:16]) !== 1'bx;
        word_value_legal = address_field || cmd_data[47:16] === expected_value;
        boundary_legal = cmd_last === (word_index == 6'd53);
        if (!word_fields_legal) word_error_code = word_index >= 50 ? 8'd3 : 8'd1;
        else if (!word_value_legal) word_error_code = word_index >= 50 ? 8'd3 : 8'd2;
        else if (address_field &&
                 (!address_value_known || cmd_data[19:16] !== 4'b0000))
            word_error_code = 8'd4;
        else if (!boundary_legal) word_error_code = 8'd3;
        else word_error_code = 8'd0;
    end

    assign cmd_ready = rst_n && !error && (state == STREAM || state == LOCKED);
    assign config_valid = rst_n && !error && state == VALIDATED;
    assign busy = rst_n && !error &&
                  ((state == STREAM && word_index != 0) || state == VALIDATED);
    assign error = rst_n && state == FAULT;
    assign error_code = !rst_n ? 8'd0 : error ? saved_code : 8'd0;

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
                saved_code <= 7;
                state <= FAULT;
            end else if (word_error_code != 0) begin
                saved_code <= word_error_code;
                state <= FAULT;
            end else if (word_index == 6'd53 && !ranges_legal) begin
                saved_code <= 4;
                state <= FAULT;
            end else begin
                case (word_index)
                    21: config_input_base <= cmd_data[47:16];
                    27: config_weight_base <= cmd_data[47:16];
                    35: config_output_base <= cmd_data[47:16];
                    default: begin end
                endcase
                if (word_index == 6'd53) begin
                    word_index <= 0;
                    state <= VALIDATED;
                end else word_index <= word_index + 1'b1;
            end
        end
        if (state == VALIDATED && config_valid && config_ready)
            state <= LOCKED;
    end

    initial if ((int'(STRIDE2) + int'(PAD1_ZERO_FRAME) + int'(GROUPED_C2) +
                 int'(SPLIT_OC_C16) + int'(DEPTHWISE_C3)) > 1)
        $fatal(1, "select one exact 3x3 capture profile");
endmodule
