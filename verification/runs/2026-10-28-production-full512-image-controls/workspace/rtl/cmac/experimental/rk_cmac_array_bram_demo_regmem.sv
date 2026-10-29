// Separate registered-BRAM-control candidate; no prior image qualification transfers.
// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// C32/K16 parallel-array finite K65 numerical demo: initialize, raw DMA, full BRAM check.
module rk_cmac_array_bram_demo_regmem (
    input logic clk,rst_n,
    output logic pass,fail,
    output logic [7:0] error_code
);
    typedef enum logic [3:0] {INIT_ROM,INIT_SEND,INIT_WAIT,START,RUN,DRAIN,
                             CHECK_ROM,CHECK_SEND,CHECK_WAIT,PASSED,FAILED} state_t;
    state_t state;
    logic [11:0] index;
    logic [19:0] watchdog;
    logic [15:0] initial_value,expected_value,host_rdata;
    logic host_valid,host_ready,host_write,host_rsp_valid,host_rsp_ready;
    logic start_ready,core_busy,core_done,core_error,engine_rst_n;
    logic unused_ack,unused_frame_done;
    logic [7:0] core_code;
    logic mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready,mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata,mem_rsp_rdata;
    assign pass=rst_n&&state==PASSED;
    assign fail=rst_n&&state==FAILED;
    // A demo watchdog/readback failure aborts the engine and its local BRAM
    // response ownership together. RAM contents are intentionally not reset.
    assign engine_rst_n=rst_n&&state!=FAILED;
    assign host_valid=rst_n&&(state==INIT_SEND||state==CHECK_SEND);
    assign host_write=state==INIT_SEND;
    assign host_rsp_ready=rst_n&&(state==INIT_WAIT||state==CHECK_WAIT);
    rk_cmac_array_demo_rom rom(.clk,.index,.initial_value,.expected_value);
    rk_cmac_demo_memory_regport memory(
        .clk,.rst_n(engine_rst_n),.req_valid(mem_req_valid),.req_ready(mem_req_ready),.req_write(mem_req_write),
        .req_addr(mem_req_addr),.req_wdata(mem_req_wdata),.rsp_valid(mem_rsp_valid),
        .rsp_ready(mem_rsp_ready),.rsp_rdata(mem_rsp_rdata),.rsp_error(mem_rsp_error),
        .host_valid,.host_ready,.host_write,.host_index(index),.host_wdata(initial_value),
        .host_rsp_valid,.host_rsp_ready,.host_rdata);
    rk_cmac_array_dma engine(.clk,.rst_n(engine_rst_n),.start_valid(rst_n&&state==START),.start_ready,
        .start_address(32'h100e0000),.start_amount(32'd45),.busy(core_busy),.done(core_done),
        .acknowledged(unused_ack),.frame_done(unused_frame_done),
        .error(core_error),.error_code(core_code),
        .mem_req_valid,.mem_req_ready,.mem_req_write,.mem_req_addr,.mem_req_wdata,
        .mem_rsp_valid,.mem_rsp_ready,.mem_rsp_rdata,.mem_rsp_error);
    // The ROM address and the host RAM index are clocked, with no async
    // set/reset path into either BRAM. Request ownership remains separately reset.
    always_ff @(posedge clk)begin
        if(!rst_n)index<=0;
        else if(state!=PASSED&&state!=FAILED&&!core_error&&watchdog!=20'hfffff)begin
            case(state)
                INIT_WAIT:if(host_rsp_valid&&index!=4095)index<=index+1'b1;
                DRAIN:if(!core_busy&&!mem_req_valid&&!mem_rsp_valid)index<=0;
                CHECK_WAIT:if(host_rsp_valid&&host_rdata===expected_value&&index!=4095)index<=index+1'b1;
                default:begin end
            endcase
        end
    end
    // This startup-only controller samples reset on its continuously running clock.
    // Outputs/admission are gated by rst_n; subordinate ownership still aborts immediately.
    always_ff @(posedge clk) begin
        if (!rst_n) begin state<=INIT_ROM;watchdog<=0;error_code<=0;end
        else if (state!=PASSED&&state!=FAILED) begin
            watchdog<=watchdog+1'b1;
            if (core_error) begin state<=FAILED;error_code<=core_code;end
            else if (watchdog==20'hfffff) begin state<=FAILED;error_code<=8'hfe;end
            else case (state)
                INIT_ROM:state<=INIT_SEND;
                INIT_SEND:if (host_ready) state<=INIT_WAIT;
                INIT_WAIT:if (host_rsp_valid) begin
                    if (index==4095) state<=START;
                    else state<=INIT_ROM;
                end
                START:if (start_ready) state<=RUN;
                RUN:if (core_done) state<=DRAIN;
                DRAIN:if (!core_busy&&!mem_req_valid&&!mem_rsp_valid) state<=CHECK_ROM;
                CHECK_ROM:state<=CHECK_SEND;
                CHECK_SEND:if (host_ready) state<=CHECK_WAIT;
                CHECK_WAIT:if (host_rsp_valid) begin
                    if (host_rdata!==expected_value) begin state<=FAILED;error_code<=8'hfd;end
                    else if (index==4095) state<=PASSED;
                    else state<=CHECK_ROM;
                end
                default:begin state<=FAILED;error_code<=8'hfc;end
            endcase
        end
    end
endmodule
