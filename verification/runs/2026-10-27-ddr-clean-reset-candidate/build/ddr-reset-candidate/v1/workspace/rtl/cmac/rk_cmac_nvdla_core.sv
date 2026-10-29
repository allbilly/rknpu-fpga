// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Staged terminal raw-command path, NVDLA numerical working baseline.
// No host arithmetic/layout fallback. No EW, PC DMA, host or FPGA integration.
module rk_cmac_nvdla_core #(parameter int unsigned TIMEOUT_CYCLES=65536) (
    input logic clk,rst_n,cmd_valid,
    output logic cmd_ready,
    input logic [63:0] cmd_data,
    output logic busy,address_done,operand_done,acknowledged,done,error,
    output logic [7:0] error_code,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic [15:0] mem_rsp_rdata,
    input logic mem_rsp_error
);
    logic front_cmd_ready,front_busy,front_error,front_address_done,front_operand_done;
    logic read_req,read_ready,read_rsp,read_rsp_ready;
    logic write_req,write_ready,write_rsp,write_rsp_ready,write_kind;
    logic [31:0] read_address,write_address;
    logic [15:0] write_data;
    logic op_valid,op_ready,op_first,op_last,op_last_output;
    logic [15:0] op_data,op_weight;
    logic [31:0] op_address,op_row,op_oc,op_ic;
    logic [1023:0] frame_data,frame_weight;
    logic [31:0] frame_address,expected_ic,saved_address,saved_row,saved_oc;
    logic frame_valid,frame_ready,frame_first,frame_last,frame_last_output,saved_last_output;
    logic [5:0] fill;
    logic pipe_busy,pipe_error,pipe_ack,pipe_done,collector_fault,legal_operand;
    logic [7:0] front_code,pipe_code,saved_code;
    logic fault,transaction_pending,transaction_write,grant_locked,grant_write,choose_write;
    logic collector_busy;
    assign collector_busy=frame_valid||(fill!=0);
    assign error=rst_n&&(fault||front_error||collector_fault||pipe_error);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : front_error ? front_code :
                      collector_fault ? 8'd6 : pipe_error ? pipe_code : 8'd0;
    assign busy=rst_n&&!error&&(front_busy||collector_busy||pipe_busy||transaction_pending);
    assign cmd_ready=front_cmd_ready&&!error;
    assign address_done=front_address_done&&!error;
    assign operand_done=front_operand_done&&!error;
    assign acknowledged=pipe_ack&&!error;
    assign done=pipe_done&&!error;
    assign op_ready=!frame_valid&&!error;
    always @* begin
        legal_operand=1;
`ifndef SYNTHESIS
        if ((^{op_address,op_row,op_oc,op_ic,op_first,op_last,op_last_output})===1'bx) legal_operand=0;
`endif
        if (op_ic!=expected_ic || op_first!=(expected_ic==0)) legal_operand=0;
        if (expected_ic!=0 && (op_address!=saved_address || op_row!=saved_row || op_oc!=saved_oc || op_last_output!=saved_last_output)) legal_operand=0;
    end
    rk_cmac_operand_front #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) frontend(
        .clk,.rst_n,.cmd_valid(cmd_valid&&!error),.cmd_ready(front_cmd_ready),.cmd_data,
        .downstream_busy(collector_busy||pipe_busy||error),.busy(front_busy),
        .address_done(front_address_done),.stream_done(front_operand_done),.error(front_error),.error_code(front_code),
        .mem_req_valid(read_req),.mem_req_ready(read_ready),.mem_req_addr(read_address),
        .mem_rsp_valid(read_rsp),.mem_rsp_ready(read_rsp_ready),.mem_rsp_rdata,.mem_rsp_error,
        .operand_valid(op_valid),.operand_ready(op_ready),.operand_input(op_data),.operand_weight(op_weight),
        .operand_output_address(op_address),.operand_row(op_row),.operand_oc(op_oc),.operand_ic(op_ic),
        .operand_first(op_first),.operand_last(op_last),.operand_last_output(op_last_output));
    rk_nvdla_cmac_pipe #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) pipeline(
        .clk,.rst_n,.in_valid(frame_valid&&!error),.in_ready(frame_ready),
        .in_data(frame_data),.in_weight(frame_weight),.in_address(frame_address),
        .in_first(frame_first),.in_last(frame_last),.in_last_output(frame_last_output),
        .cancel(fault||front_error||collector_fault),
        .cancel_code(fault ? saved_code : front_error ? front_code : 8'd6),
        .busy(pipe_busy),.acknowledged(pipe_ack),.done(pipe_done),.error(pipe_error),.error_code(pipe_code),
        .mem_req_valid(write_req),.mem_req_ready(write_ready),.mem_req_write(write_kind),
        .mem_req_addr(write_address),.mem_req_wdata(write_data),
        .mem_rsp_valid(write_rsp),.mem_rsp_ready(write_rsp_ready),.mem_rsp_error);
    // One shared halfword transaction. Lock arbitration as soon as a request
    // is exposed, including when the external bus backpressures it.
    assign choose_write=grant_locked ? grant_write : write_req;
    assign mem_req_valid=rst_n&&!error&&!transaction_pending&&(choose_write ? write_req : read_req);
    assign mem_req_write=choose_write&&write_kind;
    assign mem_req_addr=choose_write ? write_address : read_address;
    assign mem_req_wdata=choose_write ? write_data : 16'd0;
    assign write_ready=rst_n&&!error&&!transaction_pending&&choose_write&&mem_req_ready;
    assign read_ready=rst_n&&!error&&!transaction_pending&&!choose_write&&mem_req_ready;
    assign write_rsp=mem_rsp_valid&&transaction_pending&&transaction_write&&!error;
    assign read_rsp=mem_rsp_valid&&transaction_pending&&!transaction_write&&!error;
    assign mem_rsp_ready=rst_n&&!error&&transaction_pending&&(transaction_write ? write_rsp_ready : read_rsp_ready);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fault<=0;saved_code<=0;collector_fault<=0;fill<=0;frame_valid<=0;
            frame_data<=0;frame_weight<=0;frame_address<=0;frame_first<=0;frame_last<=0;frame_last_output<=0;
            expected_ic<=0;saved_address<=0;saved_row<=0;saved_oc<=0;saved_last_output<=0;
            transaction_pending<=0;transaction_write<=0;grant_locked<=0;grant_write<=0;
        end else begin
            if (!fault&&error) begin fault<=1;saved_code<=error_code;end
            if (!error) begin
                if (mem_req_valid) begin
                    if (mem_req_ready) begin transaction_pending<=1;transaction_write<=choose_write;grant_locked<=0;end
                    else begin grant_locked<=1;grant_write<=choose_write;end
                end
                if (mem_rsp_valid&&mem_rsp_ready) transaction_pending<=0;
                if (frame_valid&&frame_ready) begin frame_valid<=0;fill<=0;frame_data<=0;frame_weight<=0;end
                if (op_valid&&op_ready) begin
                    if (!legal_operand) collector_fault<=1;
                    else begin
                        if (expected_ic==0) begin
                            saved_address<=op_address;saved_row<=op_row;saved_oc<=op_oc;saved_last_output<=op_last_output;
                        end
                        expected_ic<=op_last ? 32'd0 : expected_ic+1'b1;
                        if (fill==0) begin frame_address<=op_address;frame_first<=op_first;frame_last_output<=op_last_output;end
                        frame_data[{fill,4'b0}+:16]<=op_data;
                        frame_weight[{fill,4'b0}+:16]<=op_weight;
                        if (fill==63||op_last) begin frame_valid<=1;frame_last<=op_last;end
                        else fill<=fill+1'b1;
                    end
                end
            end
        end
    end
endmodule
