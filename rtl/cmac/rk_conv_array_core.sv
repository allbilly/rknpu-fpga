// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One capture-backed 1x1 valid FP16 convolution task. This is a raw QWORD
// stream endpoint with a separate task-boundary sideband, not a tensor API,
// GEMM schedule, general CNA profile, DMA descriptor parser or full CBUF/CSC.
module rk_conv_array_core #(
    parameter int unsigned TIMEOUT_CYCLES=65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        cmd_valid,
    output logic        cmd_ready,
    input  logic [63:0] cmd_data,
    input  logic        cmd_last,
    output logic        busy,
    output logic        acknowledged,
    output logic        frame_done,
    output logic        done,
    output logic        error,
    output logic [7:0]  error_code,
    output logic        mem_req_valid,
    input  logic        mem_req_ready,
    output logic        mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input  logic        mem_rsp_valid,
    output logic        mem_rsp_ready,
    input  logic [15:0] mem_rsp_rdata,
    input  logic        mem_rsp_error
);
    logic config_valid, config_ready, profile_busy, profile_error;
    logic [31:0] input_base, weight_base, output_base;
    logic front_busy, front_error, frame_valid, frame_ready;
    logic [7:0] profile_code, front_code, arithmetic_code, atom_code, arbiter_code;
    logic [511:0] frame_data;
    logic [8191:0] frame_weight;
    logic [31:0] frame_data_mask;
    logic [511:0] frame_weight_mask;
    logic [31:0] frame_output_address;
    logic frame_first, frame_last, frame_last_output;
    logic arithmetic_ready, arithmetic_valid, arithmetic_busy, arithmetic_error;
    logic atom_ready, atom_busy, atom_error, atom_ack, atom_frame_done, atom_done;
    logic [511:0] arithmetic_values;
    logic [32:0] arithmetic_tag;
    logic arbiter_busy, arbiter_error;
    logic read_req, read_req_ready, read_rsp, read_rsp_ready, read_rsp_error;
    logic write_req, write_req_ready, write_rsp, write_rsp_ready, write_rsp_error;
    logic write_req_write;
    logic [31:0] read_address, write_address;
    logic [15:0] read_data, write_data;
    logic fault;
    logic [7:0] saved_code;
    logic write_violation;
    logic child_cancel;
    logic profile_ready, arbiter_req_valid, arbiter_rsp_ready;

    assign child_cancel = fault || profile_error;
    assign write_violation = write_req && !write_req_write;
    assign error = rst_n && (fault || profile_error || front_error || arithmetic_error ||
                             atom_error || arbiter_error || write_violation);
    assign error_code = !rst_n ? 8'd0 : fault ? saved_code :
                        profile_error ? profile_code : front_error ? front_code :
                        arithmetic_error ? arithmetic_code : atom_error ? atom_code :
                        arbiter_error ? arbiter_code :
                        write_violation ? 8'd6 : 8'd0;
    assign cmd_ready = profile_ready && !error;
    assign busy = rst_n && !error &&
                  (profile_busy || front_busy || arithmetic_busy || atom_busy || arbiter_busy);
    assign acknowledged = atom_ack && !error;
    assign frame_done = atom_frame_done && !error;
    assign done = atom_done && !error;
    assign frame_ready = arithmetic_ready && !error;
    assign mem_req_valid = arbiter_req_valid && !error;
    assign mem_rsp_ready = arbiter_rsp_ready && !error;

    rk_conv_profile profile(
        .clk, .rst_n, .cmd_valid(cmd_valid && !error), .cmd_ready(profile_ready),
        .cmd_data, .cmd_last, .config_valid, .config_ready(config_ready && !error),
        .config_input_base(input_base), .config_weight_base(weight_base),
        .config_output_base(output_base), .busy(profile_busy), .error(profile_error),
        .error_code(profile_code));

    rk_conv_array_front #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) front(
        .clk, .rst_n, .config_valid(config_valid && !error),
        .config_ready, .config_input_base(input_base), .config_weight_base(weight_base),
        .config_output_base(output_base), .cancel(child_cancel),
        .cancel_code(fault ? saved_code : profile_code), .busy(front_busy),
        .error(front_error), .error_code(front_code),
        .mem_req_valid(read_req), .mem_req_ready(read_req_ready && !error),
        .mem_req_addr(read_address), .mem_rsp_valid(read_rsp && !error),
        .mem_rsp_ready(read_rsp_ready), .mem_rsp_rdata(read_data),
        .mem_rsp_error(read_rsp_error), .frame_valid, .frame_ready,
        .frame_data, .frame_weight, .frame_data_mask, .frame_weight_mask,
        .frame_output_address, .frame_first, .frame_last, .frame_last_output);

    rk_cmac_cacc_fp16_array #(.ATOMIC_C(32), .ATOMIC_K(16), .TAG_WIDTH(33)) arithmetic(
        .clk, .rst_n, .in_valid(frame_valid && !error), .in_ready(arithmetic_ready),
        .in_data(frame_data), .in_weight(frame_weight), .in_data_mask(frame_data_mask),
        .in_weight_mask(frame_weight_mask), .in_first(frame_first), .in_last(frame_last),
        .in_tag({frame_output_address, frame_last_output}), .out_valid(arithmetic_valid),
        .out_ready(atom_ready && !error), .out_values(arithmetic_values), .out_tag(arithmetic_tag),
        .cancel(child_cancel), .cancel_code(fault ? saved_code : profile_code),
        .busy(arithmetic_busy), .error(arithmetic_error), .error_code(arithmetic_code));

    rk_conv_output_atom #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) output_atom(
        .clk, .rst_n, .in_valid(arithmetic_valid && !error), .in_ready(atom_ready),
        .in_values(arithmetic_values), .in_address(arithmetic_tag[32:1]),
        .in_last(arithmetic_tag[0]), .cancel(child_cancel),
        .cancel_code(fault ? saved_code : profile_code), .busy(atom_busy),
        .acknowledged(atom_ack), .frame_done(atom_frame_done), .done(atom_done),
        .error(atom_error), .error_code(atom_code), .mem_req_valid(write_req),
        .mem_req_ready(write_req_ready && !error), .mem_req_write(write_req_write),
        .mem_req_addr(write_address), .mem_req_wdata(write_data),
        .mem_rsp_valid(write_rsp && !error), .mem_rsp_ready(write_rsp_ready),
        .mem_rsp_error(write_rsp_error));

    rk_cmac_rw_arbiter arbiter(
        .clk, .rst_n, .cancel(child_cancel),
        .cancel_code(fault ? saved_code : profile_code),
        .read_req_valid(read_req && !error), .read_req_ready,
        .read_req_addr(read_address), .read_rsp_valid(read_rsp),
        .read_rsp_ready(read_rsp_ready && !error), .read_rsp_data(read_data),
        .read_rsp_error(read_rsp_error), .write_req_valid(write_req && !error),
        .write_req_ready, .write_req_addr(write_address), .write_req_data(write_data),
        .write_rsp_valid(write_rsp), .write_rsp_ready(write_rsp_ready && !error),
        .write_rsp_error, .mem_req_valid(arbiter_req_valid),
        .mem_req_ready(mem_req_ready && !error), .mem_req_write, .mem_req_addr,
        .mem_req_data(mem_req_wdata), .mem_rsp_valid(mem_rsp_valid && !error),
        .mem_rsp_ready(arbiter_rsp_ready), .mem_rsp_data(mem_rsp_rdata), .mem_rsp_error,
        .busy(arbiter_busy), .error(arbiter_error), .error_code(arbiter_code));

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fault <= 0;
            saved_code <= 0;
        end else if (!fault && error) begin
            fault <= 1;
            saved_code <= error_code;
        end
    end
endmodule
