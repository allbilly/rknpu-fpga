// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Strict terminal RK command stream -> physical C32/K16 arithmetic -> memory.
// This is the bounded profile, not complete CBUF/CSC or a PCIe/DDR endpoint.
module rk_cmac_array_core #(parameter int unsigned TIMEOUT_CYCLES=65536) (
    input wire clk,rst_n,cmd_valid,
    output wire cmd_ready,
    input wire [63:0] cmd_data,
    input wire cancel,
    input wire [7:0] cancel_code,
    output wire busy,acknowledged,frame_done,done,error,
    output wire [7:0] error_code,
    output wire mem_req_valid,
    input wire mem_req_ready,
    output wire mem_req_write,
    output wire [31:0] mem_req_addr,
    output wire [15:0] mem_req_wdata,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rsp_rdata,
    input wire mem_rsp_error
);
    wire front_ready,front_busy,front_error,unused_stream_done;
    wire data_busy,data_error,data_ack,data_frame_done,data_done;
    wire arb_busy,arb_error,arb_req_valid,arb_rsp_ready;
    wire [7:0] front_code,data_code,arb_code;
    wire frame_valid,frame_ready,frame_first,frame_last,frame_last_output;
    wire [511:0] frame_data,frame_weight_mask;
    wire [8191:0] frame_weight;
    wire [31:0] frame_data_mask,frame_output_address,unused_row,unused_oc,unused_ic;
    wire rd_req,rd_ready,rd_rsp,rd_rsp_ready,rd_error;
    wire wr_req,wr_ready,wr_rsp,wr_rsp_ready,wr_error,wr_write;
    wire [31:0] rd_address,wr_address;
    wire [15:0] rd_data,wr_data;
    logic fault;
    logic [7:0] saved_code,normalized_cancel;
    wire child_cancel=cancel||fault;
    wire [7:0] child_code=fault ? saved_code : normalized_cancel;
    wire write_violation=wr_req&&!wr_write;
    always @* begin
        case(cancel_code)
            1,2,3,4,5,6,7,8:normalized_cancel=cancel_code;
            default:normalized_cancel=6;
        endcase
    end
    // Errors gate all public and inter-unit handshakes immediately. Only the
    // registered root fault feeds child cancellation, avoiding feedback loops.
    assign error=rst_n&&(fault||cancel||front_error||data_error||arb_error||write_violation);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? normalized_cancel :
                      front_error ? front_code : data_error ? data_code : arb_error ? arb_code :
                      write_violation ? 8'd6 : 8'd0;
    assign cmd_ready=front_ready&&!error;
    assign busy=rst_n&&!error&&(front_busy||data_busy||arb_busy);
    assign acknowledged=data_ack&&!error;
    assign frame_done=data_frame_done&&!error;
    assign done=data_done&&!error;
    assign mem_req_valid=arb_req_valid&&!error;
    assign mem_rsp_ready=arb_rsp_ready&&!error;
    rk_cmac_array_front #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) front(
        .clk,.rst_n,.cmd_valid(cmd_valid&&!error),.cmd_ready(front_ready),.cmd_data,
        .downstream_busy(data_busy),.cancel(child_cancel),.cancel_code(child_code),
        .busy(front_busy),.error(front_error),.stream_done(unused_stream_done),.error_code(front_code),
        .mem_req_valid(rd_req),.mem_req_ready(rd_ready&&!error),.mem_req_addr(rd_address),
        .mem_rsp_valid(rd_rsp&&!error),.mem_rsp_ready(rd_rsp_ready),.mem_rsp_rdata(rd_data),.mem_rsp_error(rd_error),
        .frame_valid,.frame_ready(frame_ready&&!error),.frame_data,.frame_weight,.frame_data_mask,.frame_weight_mask,
        .frame_output_address,.frame_row(unused_row),.frame_oc(unused_oc),.frame_ic(unused_ic),
        .frame_first,.frame_last,.frame_last_output);
    rk_cmac_array_datapath #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) datapath(
        .clk,.rst_n,.in_valid(frame_valid&&!error),.in_ready(frame_ready),
        .in_data(frame_data),.in_weight(frame_weight),.in_data_mask(frame_data_mask),.in_weight_mask(frame_weight_mask),
        .in_first(frame_first),.in_last(frame_last),.in_last_frame(frame_last_output),.in_output_address(frame_output_address),
        .cancel(child_cancel),.cancel_code(child_code),.busy(data_busy),.acknowledged(data_ack),
        .frame_done(data_frame_done),.done(data_done),.error(data_error),.error_code(data_code),
        .mem_req_valid(wr_req),.mem_req_ready(wr_ready&&!error),.mem_req_write(wr_write),
        .mem_req_addr(wr_address),.mem_req_wdata(wr_data),.mem_rsp_valid(wr_rsp&&!error),
        .mem_rsp_ready(wr_rsp_ready),.mem_rsp_error(wr_error));
    rk_cmac_rw_arbiter arbiter(
        .clk,.rst_n,.cancel(child_cancel),.cancel_code(child_code),
        .read_req_valid(rd_req&&!error),.read_req_ready(rd_ready),.read_req_addr(rd_address),
        .read_rsp_valid(rd_rsp),.read_rsp_ready(rd_rsp_ready&&!error),.read_rsp_data(rd_data),.read_rsp_error(rd_error),
        .write_req_valid(wr_req&&!error),.write_req_ready(wr_ready),.write_req_addr(wr_address),.write_req_data(wr_data),
        .write_rsp_valid(wr_rsp),.write_rsp_ready(wr_rsp_ready&&!error),.write_rsp_error(wr_error),
        .mem_req_valid(arb_req_valid),.mem_req_ready(mem_req_ready&&!error),.mem_req_write,.mem_req_addr,.mem_req_data(mem_req_wdata),
        .mem_rsp_valid(mem_rsp_valid&&!error),.mem_rsp_ready(arb_rsp_ready),.mem_rsp_data(mem_rsp_rdata),.mem_rsp_error,
        .busy(arb_busy),.error(arb_error),.error_code(arb_code));
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin fault<=0;saved_code<=0;end
        else if(!fault&&error) begin fault<=1;saved_code<=error_code;end
    end
endmodule
