// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One-outstanding halfword bus arbiter for the array operand reader and
// result writer. Snapshot a request before exposing it; retain its owner
// through the response. Alternate when both clients request service.
module rk_cmac_rw_arbiter (
    input wire clk,rst_n,cancel,
    input wire [7:0] cancel_code,
    input wire read_req_valid,
    output wire read_req_ready,
    input wire [31:0] read_req_addr,
    output wire read_rsp_valid,
    input wire read_rsp_ready,
    output wire [15:0] read_rsp_data,
    output wire read_rsp_error,
    input wire write_req_valid,
    output wire write_req_ready,
    input wire [31:0] write_req_addr,
    input wire [15:0] write_req_data,
    output wire write_rsp_valid,
    input wire write_rsp_ready,
    output wire write_rsp_error,
    output wire mem_req_valid,
    input wire mem_req_ready,
    output wire mem_req_write,
    output wire [31:0] mem_req_addr,
    output wire [15:0] mem_req_data,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rsp_data,
    input wire mem_rsp_error,
    output wire busy,error,
    output wire [7:0] error_code
);
    typedef enum logic [1:0] {IDLE,REQUEST,RESPONSE} state_t;
    state_t state;
    logic owner_write,last_write,fault;
    logic [31:0] address;
    logic [15:0] data;
    logic [7:0] saved_code,normalized_cancel;
    wire select_write=write_req_valid&&(!read_req_valid||!last_write);
    always @* begin
        case(cancel_code)
            1,2,3,4,5,6,7,8:normalized_cancel=cancel_code;
            default:normalized_cancel=6;
        endcase
    end
    assign error=rst_n&&(fault||cancel);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? normalized_cancel : 8'd0;
    assign busy=rst_n&&!error&&state!=IDLE;
    assign mem_req_valid=rst_n&&!error&&state==REQUEST;
    assign mem_req_write=owner_write;
    assign mem_req_addr=address;
    assign mem_req_data=data;
    assign read_req_ready=mem_req_valid&&!owner_write&&mem_req_ready;
    assign write_req_ready=mem_req_valid&&owner_write&&mem_req_ready;
    assign read_rsp_valid=rst_n&&!error&&state==RESPONSE&&!owner_write&&mem_rsp_valid;
    assign write_rsp_valid=rst_n&&!error&&state==RESPONSE&&owner_write&&mem_rsp_valid;
    assign read_rsp_data=mem_rsp_data;
    assign read_rsp_error=mem_rsp_error;
    assign write_rsp_error=mem_rsp_error;
    assign mem_rsp_ready=rst_n&&!error&&state==RESPONSE&&(owner_write ? write_rsp_ready : read_rsp_ready);
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin state<=IDLE;owner_write<=0;last_write<=1;address<=0;data<=0;fault<=0;saved_code<=0;end
        else begin
            if(!fault&&cancel) begin fault<=1;saved_code<=normalized_cancel;end
            if(!error) begin
                case(state)
                    IDLE: if(read_req_valid||write_req_valid) begin
                        owner_write<=select_write;
                        address<=select_write ? write_req_addr : read_req_addr;
                        data<=select_write ? write_req_data : 16'd0;
                        state<=REQUEST;
                    end
                    REQUEST: if(mem_req_ready) state<=RESPONSE;
                    RESPONSE: if(mem_rsp_valid&&mem_rsp_ready) begin last_write<=owner_write;state<=IDLE;end
                    default:begin fault<=1;saved_code<=6;end
                endcase
                // Responses are legal only after an accepted request, never
                // in the same cycle or in an idle/canceled transaction.
                if(mem_rsp_valid&&state!=RESPONSE) begin fault<=1;saved_code<=6;end
            end
        end
    end
endmodule
