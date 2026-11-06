// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Internal atomic-K output frame: capture ATOMIC_K FP32 CACC results, convert
// each once using the donor, and acknowledge ATOMIC_K halfword writes. The
// enclosing raw-command scheduler supplies the physical atom base (including
// the OC16 block stride and the 16-halfword gap). K16 is the reference; K8
// writes one OC8 half within an OC16 block.
module rk_cmac_frame_output #(parameter int unsigned ATOMIC_K=16,TIMEOUT_CYCLES=65536) (
    input wire clk,rst_n,in_valid,
    output wire in_ready,
    input wire [ATOMIC_K*32-1:0] in_values,
    input wire [31:0] in_address,
    input wire in_last,
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
    input wire mem_rsp_error
);
    typedef enum logic [1:0] {IDLE,EMIT,WAIT_ACK} state_t;
    localparam int unsigned LANE_WIDTH = ATOMIC_K <= 2 ? 1 : $clog2(ATOMIC_K);
    state_t state;
    logic [ATOMIC_K*32-1:0] values;
    logic [31:0] address;
    logic [LANE_WIDTH-1:0] lane;
    logic last_frame,fault,address_legal,data_legal;
    initial if(ATOMIC_K!=8&&ATOMIC_K!=16) $fatal(1,"unsupported output atomic K");
    logic [7:0] saved_code,normalized_cancel;
    wire tail_ready,tail_busy,tail_ack,tail_done,tail_error,tail_req,tail_rsp;
    wire [7:0] tail_code;
    always @* begin
        case(cancel_code)
            1,2,3,4,5,6,7,8:normalized_cancel=cancel_code;
            default:normalized_cancel=6;
        endcase
        // The raw profile permits 16-byte aligned bases. K16 consumes 32 bytes
        // per atom; K8 consumes 16 bytes and the scheduler supplies the second
        // OC8 base at +16 bytes inside the same 64-byte OC16 block.
        address_legal=in_address[3:0]==0&&in_address<=32'hffffffe0;
        data_legal=1;
`ifndef SYNTHESIS
        if((^in_address)===1'bx) address_legal=0;
        if((^in_values)===1'bx||(in_last!==1'b0&&in_last!==1'b1)) data_legal=0;
`endif
    end
    assign error=rst_n&&(fault||cancel||tail_error);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? normalized_cancel : tail_error ? tail_code : 8'd0;
    assign in_ready=rst_n&&!error&&state==IDLE;
    assign busy=rst_n&&!error&&(state!=IDLE||tail_busy);
    assign acknowledged=tail_ack&&!error;
    assign frame_done=tail_done&&!error&&state==WAIT_ACK;
    assign done=frame_done&&last_frame;
    assign mem_req_valid=tail_req&&!error;
    assign mem_rsp_ready=tail_rsp&&!error;
    rk_cmac_output_nvdla #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) tail(
        .clk,.rst_n,.in_valid(state==EMIT&&!error),.in_ready(tail_ready),
        .in_value(values[lane*32+:32]),.in_address(address+32'(lane)*32'd2),
        .in_last(lane==ATOMIC_K-1),.cancel(cancel||fault),.cancel_code(fault ? saved_code : normalized_cancel),
        .busy(tail_busy),.acknowledged(tail_ack),.done(tail_done),.error(tail_error),.error_code(tail_code),
        .mem_req_valid(tail_req),.mem_req_ready(mem_req_ready&&!error),.mem_req_write,.mem_req_addr,.mem_req_wdata,
        .mem_rsp_valid(mem_rsp_valid&&!error),.mem_rsp_ready(tail_rsp),.mem_rsp_error);
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin state<=IDLE;values<=0;address<=0;lane<=0;last_frame<=0;fault<=0;saved_code<=0;end
        else begin
            if(!fault&&error) begin fault<=1;saved_code<=error_code;end
            if(!error) begin
                case(state)
                    IDLE: if(in_valid&&in_ready) begin
                        if(!address_legal) begin fault<=1;saved_code<=4;end
                        else if(!data_legal) begin fault<=1;saved_code<=6;end
                        else begin values<=in_values;address<=in_address;last_frame<=in_last;lane<=0;state<=EMIT;end
                    end
                    EMIT: if(tail_ready) state<=WAIT_ACK;
                    WAIT_ACK: if(tail_ack) begin
                        if(tail_done!=(lane==ATOMIC_K-1)) begin fault<=1;saved_code<=6;end
                        else if(lane==ATOMIC_K-1) state<=IDLE;
                        else begin lane<=lane+1'b1;state<=EMIT;end
                    end
                    default:begin fault<=1;saved_code<=6;end
                endcase
                if(tail_ack&&state!=WAIT_ACK) begin fault<=1;saved_code<=6;end
            end
        end
    end
endmodule
