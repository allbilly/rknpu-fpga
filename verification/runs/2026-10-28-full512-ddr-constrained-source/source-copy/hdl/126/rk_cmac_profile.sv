// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// STAGED, UNCONNECTED raw CMAC profile decoder. No arithmetic or job completion.
// Facts: tinygrad 078eee94d8f1912bb63ce786c250d2c24984844a emit_cmac_stage
// and its actual standalone final writer. HALF output, no ReLU, terminal only.
// The separate DMA integration must account for 45 body + 4 tail QWORDs.
module rk_cmac_profile (
    input logic clk, rst_n,
    input logic cmd_valid,
    output logic cmd_ready,
    input logic [63:0] cmd_data,
    input logic engine_busy, engine_error,
    output logic config_valid,
    input logic config_ready,
    output logic [31:0] config_rows, config_input_channels, config_output_channels,
    output logic [31:0] config_input_base, config_weight_base, config_output_base,
    output logic error,
    output logic [7:0] error_code
);
    logic [47:0] seen;
    logic [31:0] regs [0:47];
    wire [31:0] key = {cmd_data[63:48], cmd_data[15:0]};
    wire [31:0] value = cmd_data[47:16];
    integer index;
    logic fixed_field;
    logic [31:0] fixed_value;
    logic shape_valid, address_valid;
    logic [31:0] rows, ai, ao, grains, banks, stride, notch;
    logic [63:0] input_bytes, weight_bytes, output_bytes;
    logic [63:0] input_end, weight_end, output_end;

    // No field is an ignored write. Fixed values are checked immediately;
    // redundant dimensions, capacities and physical ranges at the trigger.
    always_comb begin
        index = -1;
        fixed_field = 0;
        fixed_value = 0;
        case (key)
            32'h10014004: begin index=0; fixed_field=1; fixed_value=32'he; end
            32'h0201100c: begin index=1; fixed_field=1; fixed_value=32'h20000120; end
            32'h02011010: index=2;
            32'h02011014: begin index=3; fixed_field=1; fixed_value=9; end
            32'h02011020: index=4;
            32'h02011024: index=5;
            32'h02011028: begin index=6; fixed_field=1; fixed_value=1; end
            32'h0201102c: index=7;
            32'h02011030: index=8;
            32'h02011034: index=9;
            32'h02011038: index=10;
            32'h02011040: index=11;
            32'h02011044: index=12;
            32'h0201104c: begin index=13; fixed_field=1; fixed_value=11; end
            32'h02011050: begin index=14; fixed_field=1; fixed_value=32'h10000; end
            32'h02011054: begin index=15; fixed_field=1; fixed_value=32'h10000; end
            32'h02011058: begin index=16; fixed_field=1; fixed_value=32'h10000; end
            32'h0201105c: begin index=17; fixed_field=1; fixed_value=32'h10000; end
            32'h02011070: index=18;
            32'h02011078: begin index=19; fixed_field=1; fixed_value=32'hf000f; end
            32'h0201107c: index=20;
            32'h02011080: begin index=21; fixed_field=1; fixed_value=0; end
            32'h02011084: index=22;
            32'h02011088: index=23;
            32'h02011110: index=24;
            32'h08013010: begin index=25; fixed_field=1; fixed_value=32'h201; end
            32'h08013014: index=26;
            32'h08013018: index=27;
            32'h08013030: begin index=28; fixed_field=1; fixed_value=0; end
            32'h1001400c: begin index=29; fixed_field=1; fixed_value=32'h1e4; end
            32'h10014010: begin index=30; fixed_field=1; fixed_value=32'h48000002; end
            32'h10014020: index=31;
            32'h10014024: begin index=32; fixed_field=1; fixed_value=16; end
            32'h10014030: begin index=33; fixed_field=1; fixed_value=0; end
            32'h10014034: index=34;
            32'h10014038: index=35;
            32'h1001403c: index=36;
            32'h10014040: begin index=37; fixed_field=1; fixed_value=32'h53; end
            32'h10014050: begin index=38; fixed_field=1; fixed_value=32'h126; end
            32'h10014058: index=39;
            32'h1001405c: index=40;
            32'h10014060: begin index=41; fixed_field=1; fixed_value=32'h53; end
            32'h10014070: begin index=42; fixed_field=1; fixed_value=32'h383; end
            32'h10014084: begin index=43; fixed_field=1; fixed_value=32'h10001; end
            32'h100140c0: begin index=44; fixed_field=1; fixed_value=32'h40; end
            32'h00010000: begin index=45; fixed_field=1; fixed_value=0; end
            32'h01010014: begin index=46; fixed_field=1; fixed_value=0; end
            32'h00410000: begin index=47; fixed_field=1; fixed_value=0; end
            default: begin end
        endcase
    end

    assign rows = regs[7];
    assign ai = regs[23];
    assign ao = regs[10] & 32'hffff;
    assign config_rows = rows;
    assign config_input_channels = ai;
    assign config_output_channels = ao;
    assign config_input_base = regs[18];
    assign config_weight_base = regs[24];
    assign config_output_base = regs[31];
    // Width-limited products avoid a needless 64x64 multiplier. Full bounds
    // checks below must pass before any truncated product can be accepted.
    assign input_bytes = {53'b0, rows[10:0]} * {51'b0, ai[12:0]} * 64'd2;
    assign weight_bytes = {50'b0, ao[13:0]} * {51'b0, ai[12:0]} * 64'd2;
    assign output_bytes = {53'b0, rows[10:0]} * {50'b0, ao[13:0]} * 64'd4;
    assign banks = (32'(input_bytes) + 32767) >> 15;
    assign stride = (ai > 416 ? 32'd13 : ai >> 5) << 2;
    assign notch = ((ao > 416 ? 32'd13 : ao >> 5) << 3) - 1;
    // max(80, round_up(ceil(65536/(2*ai)),2)), ai multiple of 32.
    // >= 13 groups is clamped to 80. No run-time divide is needed.
    always_comb begin
        case (ai)
            32: grains=1024;
            64: grains=512;
            96: grains=342;
            128: grains=256;
            160: grains=206;
            192: grains=172;
            224: grains=148;
            256: grains=128;
            288: grains=114;
            320: grains=104;
            352: grains=94;
            384: grains=86;
            default: grains=80;
        endcase
    end
    assign shape_valid = rows > 0 && rows <= 2047 && ai >= 32 && ai <= 4096 &&
        ao >= 32 && ao <= 16383 && ai >= ao && ai[4:0] == 0 && ao[4:0] == 0 &&
        (rows == 1 || ai <= 384) && input_bytes <= 327680 && weight_bytes <= 360448 &&
        regs[2] == (grains << 4) &&
        regs[4] == (32'h10000 | rows) && regs[5] == (((ai-1) << 16) | ai) &&
        regs[8] == weight_bytes[31:0] && regs[9] == ai*2 && regs[10] == (32'h1010000 | ao) &&
        regs[11] == (((12-banks) << 4) | banks) && regs[12] == ai >> 5 &&
        regs[20] == stride && regs[22] == (32'h10000 | rows) &&
        regs[26] == (rows-1) << 16 && regs[27] == ao-1 && regs[34] == rows-1 &&
        regs[35] == ((notch << 16) | notch) && regs[36] == (((ao-1) << 16) | (ao-1)) &&
        regs[39] == ao-1 && regs[40] == (rows-1) << 16;
    assign input_end = {32'b0, config_input_base} + input_bytes;
    assign weight_end = {32'b0, config_weight_base} + weight_bytes;
    assign output_end = {32'b0, config_output_base} + output_bytes;
    assign address_valid = config_input_base[3:0] == 0 && config_weight_base[3:0] == 0 &&
        config_output_base[3:0] == 0 && input_end <= 64'h100000000 &&
        weight_end <= 64'h100000000 && output_end <= 64'h100000000 &&
        !(output_end > {32'b0, config_input_base} && input_end > {32'b0, config_output_base}) &&
        !(output_end > {32'b0, config_weight_base} && weight_end > {32'b0, config_output_base});
    assign cmd_ready = rst_n && !config_valid && !engine_busy && !engine_error && !error;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            seen <= 0;
            config_valid <= 0;
            error <= 0;
            error_code <= 0;
            for (integer i=0; i<48; i=i+1) regs[i] <= 0;
        end else begin
            if (config_valid && config_ready) begin
                config_valid <= 0;
                seen <= 0;
            end
            if (cmd_valid && cmd_ready) begin
                if (key == 32'h00810008) begin
                    if (value == 13) begin
                        if (&seen) begin
                            if (shape_valid) begin
                                if (address_valid) config_valid <= 1;
                                else begin error <= 1; error_code <= 4; end
                            end else begin error <= 1; error_code <= 6; end
                        end else begin error <= 1; error_code <= 3; end
                    end else begin error <= 1; error_code <= 2; end
                end else if (index >= 0) begin
                    if (!fixed_field || value == fixed_value) begin
                        regs[index] <= value;
                        seen[index] <= 1;
                    end else begin error <= 1; error_code <= 2; end
                end else begin error <= 1; error_code <= 1; end
            end
        end
    end
endmodule
