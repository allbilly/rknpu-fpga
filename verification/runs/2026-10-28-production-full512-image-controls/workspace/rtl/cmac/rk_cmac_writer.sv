// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// INTERNAL candidate: commit an already converted result, not arithmetic.
// One outstanding halfword write. Completion means successful write response,
// never just input acceptance or memory request acceptance. Joint memory reset
// is mandatory after cancellation/fault; partial writes are not rolled back.
module rk_cmac_writer #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, rst_n,
    input logic result_valid,
    output logic result_ready,
    input logic [31:0] result_address,
    input logic [15:0] result_data,
    input logic result_last,
    output logic busy, acknowledged, done, error,
    output logic [7:0] error_code,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic mem_rsp_error
);
    typedef enum logic [1:0] {IDLE, WRITE_REQ, WRITE_WAIT} state_t;
    state_t state;
    logic [31:0] address, stalled_cycles;
    logic [15:0] data;
    logic last_result, memory_state, progress;
    initial begin
        if (TIMEOUT_CYCLES == 0) $fatal(1,"TIMEOUT_CYCLES must be positive");
    end
    assign result_ready = rst_n && !error && state == IDLE;
    assign busy = rst_n && !error && state != IDLE;
    assign mem_req_valid = rst_n && !error && state == WRITE_REQ;
    assign mem_req_write = 1'b1;
    assign mem_req_addr = address;
    assign mem_req_wdata = data;
    assign mem_rsp_ready = rst_n && !error && state == WRITE_WAIT;
    assign memory_state = state == WRITE_REQ || state == WRITE_WAIT;
    assign progress = (mem_req_valid && mem_req_ready) || (mem_rsp_valid && mem_rsp_ready);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE;address<=0;data<=0;last_result<=0;stalled_cycles<=0;
            acknowledged<=0;done<=0;error<=0;error_code<=0;
        end else begin
            acknowledged<=0;done<=0;
            if (!error) begin
                if (!memory_state || progress) stalled_cycles<=0;
                else stalled_cycles<=stalled_cycles+1;
                case (state)
                    IDLE: if (result_valid && result_ready) begin
                        // Exclusive end may equal 2^32, but must not wrap.
                        // Unknown address/last fields also fail in simulation.
                        if (result_address[0]==0 && result_address<=32'hfffffffe) begin
                            if (result_last==0 || result_last==1) begin
                                address<=result_address;data<=result_data;last_result<=result_last;
                                state<=WRITE_REQ;
                            end else begin error<=1;error_code<=6;end
                        end else begin error<=1;error_code<=4;end
                    end
                    WRITE_REQ: if (mem_req_valid && mem_req_ready) state<=WRITE_WAIT;
                    WRITE_WAIT: if (mem_rsp_valid && mem_rsp_ready) begin
                        state<=IDLE;
                        if (mem_rsp_error==0) begin acknowledged<=1;done<=last_result;end
                        else begin error<=1;error_code<=5;end
                    end
                    default: begin state<=IDLE;error<=1;error_code<=6;end
                endcase
                if (memory_state && !progress && stalled_cycles>=TIMEOUT_CYCLES-1) begin
                    state<=IDLE;error<=1;error_code<=8;
                    acknowledged<=0;done<=0;
                end
            end
        end
    end
endmodule
