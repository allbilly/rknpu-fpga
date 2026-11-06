// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Capture-specific valid 1x1 convolution gather/scheduler. It reads the RK
// C8/align-C16 and OC8/align-C16 BOs unchanged, expands them into a C32/K16
// frame in hardware, and emits one 16-byte flat_1x1 atom per output pixel.
module rk_conv_array_front #(
    parameter int unsigned TIMEOUT_CYCLES=65536
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         config_valid,
    output logic         config_ready,
    input  logic [31:0]  config_input_base,
    input  logic [31:0]  config_weight_base,
    input  logic [31:0]  config_output_base,
    input  logic         cancel,
    input  logic [7:0]   cancel_code,
    output logic         busy,
    output logic         error,
    output logic [7:0]   error_code,
    output logic         mem_req_valid,
    input  logic         mem_req_ready,
    output logic [31:0]  mem_req_addr,
    input  logic         mem_rsp_valid,
    output logic         mem_rsp_ready,
    input  logic [15:0]  mem_rsp_rdata,
    input  logic         mem_rsp_error,
    output logic         frame_valid,
    input  logic         frame_ready,
    output logic [511:0] frame_data,
    output logic [8191:0] frame_weight,
    output logic [31:0]  frame_data_mask,
    output logic [511:0] frame_weight_mask,
    output logic [31:0]  frame_output_address,
    output logic         frame_first,
    output logic         frame_last,
    output logic         frame_last_output
);
    typedef enum logic [2:0] {IDLE, WEIGHT_REQ, WEIGHT_WAIT, DATA_REQ,
                              DATA_WAIT, EMIT, FINISHED, FAULT} state_t;
    state_t state;
    logic [31:0] input_base, output_base;
    logic [5:0] read_index;
    logic [4:0] atom_index;
    logic [31:0] stalled_cycles;
    logic [7:0] saved_code, normalized_cancel;
    logic response_status_bad, response_data_bad;

    initial if (TIMEOUT_CYCLES == 0) $fatal(1, "conv front timeout must be positive");

    always @* begin
        case (cancel_code)
            1,2,3,4,5,6,7,8: normalized_cancel = cancel_code;
            default: normalized_cancel = 6;
        endcase
        response_status_bad = mem_rsp_error;
        response_data_bad = 1'b0;
`ifndef SYNTHESIS
        if (mem_rsp_error !== 1'b0) response_status_bad = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx) response_data_bad = 1'b1;
`endif
    end

    assign config_ready = rst_n && !error && state == IDLE;
    assign busy = rst_n && !error && state != IDLE && state != FINISHED;
    assign error = rst_n && (state == FAULT || cancel);
    assign error_code = !rst_n ? 8'd0 : state == FAULT ? saved_code :
                        cancel ? normalized_cancel : 8'd0;
    assign mem_req_valid = rst_n && !error && (state == WEIGHT_REQ || state == DATA_REQ);
    assign mem_rsp_ready = rst_n && !error && (state == WEIGHT_WAIT || state == DATA_WAIT);
    assign frame_valid = rst_n && !error && state == EMIT;
    assign frame_data_mask = 32'h000000ff;
    assign frame_weight_mask = {
        32'h00000000,32'h00000000,32'h00000000,32'h00000000,
        32'h00000000,32'h00000000,32'h00000000,32'h00000000,
        32'h000000ff,32'h000000ff,32'h000000ff,32'h000000ff,
        32'h000000ff,32'h000000ff,32'h000000ff,32'h000000ff
    };
    assign frame_output_address = output_base + {22'd0, atom_index, 4'b0000};
    assign frame_first = 1'b1;
    assign frame_last = 1'b1;
    assign frame_last_output = atom_index == 5'd24;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            input_base <= 0;
            output_base <= 0;
            read_index <= 0;
            atom_index <= 0;
            stalled_cycles <= 0;
            saved_code <= 0;
            mem_req_addr <= 0;
            frame_data <= 0;
            frame_weight <= 0;
        end else begin
            if (!error) begin
                if ((state != WEIGHT_REQ && state != WEIGHT_WAIT &&
                     state != DATA_REQ && state != DATA_WAIT) ||
                    (mem_req_valid && mem_req_ready) ||
                    (mem_rsp_valid && mem_rsp_ready)) stalled_cycles <= 0;
                else stalled_cycles <= stalled_cycles + 1'b1;

                case (state)
                    IDLE: if (config_valid && config_ready) begin
                        input_base <= config_input_base;
                        output_base <= config_output_base;
                        read_index <= 0;
                        atom_index <= 0;
                        frame_data <= 0;
                        frame_weight <= 0;
                        mem_req_addr <= config_weight_base;
                        state <= WEIGHT_REQ;
                    end
                    WEIGHT_REQ: if (mem_req_ready) state <= WEIGHT_WAIT;
                    DATA_REQ: if (mem_req_ready) state <= DATA_WAIT;
                    WEIGHT_WAIT, DATA_WAIT: if (mem_rsp_valid) begin
                        if (response_status_bad) begin
                            saved_code <= 5;
                            state <= FAULT;
                        end else if (response_data_bad) begin
                            saved_code <= 6;
                            state <= FAULT;
                        end else if (state == WEIGHT_WAIT) begin
                            // Original RK rows are [OC][align_C=16]. Fetch
                            // only the real C8 values; padded IC and OC lanes
                            // remain zero in the hardware frame.
                            frame_weight[((read_index >> 3) * 32 + (read_index & 6'd7)) * 16 +: 16]
                                <= mem_rsp_rdata;
                            if (read_index == 6'd63) begin
                                read_index <= 0;
                                atom_index <= 0;
                                frame_data <= 0;
                                mem_req_addr <= input_base;
                                state <= DATA_REQ;
                            end else begin
                                read_index <= read_index + 1'b1;
                                mem_req_addr <= mem_req_addr +
                                    (read_index[2:0] == 3'd7 ? 32'd18 : 32'd2);
                                state <= WEIGHT_REQ;
                            end
                        end else begin
                            frame_data[read_index[2:0] * 16 +: 16] <= mem_rsp_rdata;
                            if (read_index[2:0] == 3'd7) state <= EMIT;
                            else begin
                                read_index <= read_index + 1'b1;
                                mem_req_addr <= mem_req_addr + 32'd2;
                                state <= DATA_REQ;
                            end
                        end
                    end
                    EMIT: if (frame_ready) begin
                        if (atom_index == 5'd24) begin
                            state <= FINISHED;
                        end else begin
                            atom_index <= atom_index + 1'b1;
                            read_index <= 0;
                            frame_data <= 0;
                            mem_req_addr <= input_base +
                                {22'd0, (atom_index + 5'd1), 4'b0000};
                            state <= DATA_REQ;
                        end
                    end
                    FINISHED: begin end
                    default: begin
                        saved_code <= 6;
                        state <= FAULT;
                    end
                endcase

                if ((state == WEIGHT_REQ || state == WEIGHT_WAIT ||
                     state == DATA_REQ || state == DATA_WAIT) &&
                    !(mem_req_valid && mem_req_ready) &&
                    !(mem_rsp_valid && mem_rsp_ready) &&
                    stalled_cycles >= TIMEOUT_CYCLES - 1) begin
                    saved_code <= 8;
                    state <= FAULT;
                end
            end
        end
    end
endmodule
