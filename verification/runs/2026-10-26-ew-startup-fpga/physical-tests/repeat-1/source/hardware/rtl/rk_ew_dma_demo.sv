// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Load a captured raw command chain and BO prefixes, then verify all mapped bytes.
module rk_ew_dma_demo (
    input logic clk, rst_n,
    output logic pass, fail,
    output logic [7:0] error_code
);
    typedef enum logic [3:0] {INIT_REQ,INIT_WAIT,START,RUN,CHECK_REQ,CHECK_WAIT,PASS,FAIL} state_t;
    state_t state;
    logic [8:0] index;
    logic [31:0] address, start_address, start_amount, expected_tasks, completed_tasks;
    logic [31:0] watchdog;
    logic [15:0] initial_data, expected_data;
    logic last, start_valid, start_ready, busy, done, unused_task_done, error;
    logic [7:0] dma_error_code;
    logic mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready,mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata,mem_rsp_rdata;
    logic host_valid,host_ready,host_write,host_rsp_valid,host_rsp_ready,host_error;
    logic [31:0] host_addr;
    logic [15:0] host_wdata,host_rdata;
    assign pass = state==PASS;
    assign fail = state==FAIL;
    assign start_valid = state==START;
    rk_dma_demo_rom rom(.*);
    rk_ew_dma core (
        .clk(clk), .rst_n(rst_n), .start_valid(start_valid), .start_ready(start_ready),
        .start_address(start_address), .start_amount(start_amount), .busy(busy), .done(done),
        .task_done(unused_task_done), .completed_tasks(completed_tasks), .error(error), .error_code(dma_error_code),
        .mem_req_valid(mem_req_valid), .mem_req_ready(mem_req_ready), .mem_req_write(mem_req_write),
        .mem_req_addr(mem_req_addr), .mem_req_wdata(mem_req_wdata), .mem_rsp_valid(mem_rsp_valid),
        .mem_rsp_ready(mem_rsp_ready), .mem_rsp_rdata(mem_rsp_rdata), .mem_rsp_error(mem_rsp_error)
    );
    rk_demo_memory memory (
        .clk(clk),.rst_n(rst_n),.req_valid(mem_req_valid),.req_ready(mem_req_ready),
        .req_write(mem_req_write),.req_addr(mem_req_addr),.req_wdata(mem_req_wdata),
        .rsp_valid(mem_rsp_valid),.rsp_ready(mem_rsp_ready),.rsp_rdata(mem_rsp_rdata),.rsp_error(mem_rsp_error),
        .host_valid(host_valid),.host_ready(host_ready),.host_write(host_write),
        .host_addr(host_addr),.host_wdata(host_wdata),.host_rsp_valid(host_rsp_valid),
        .host_rsp_ready(host_rsp_ready),.host_rdata(host_rdata),.host_error(host_error)
    );
    always_comb begin
        host_valid=0; host_write=0; host_addr=address; host_wdata=initial_data; host_rsp_ready=0;
        if (state==INIT_REQ) begin host_valid=1; host_write=1; end
        if (state==CHECK_REQ) host_valid=1;
        if (state==INIT_WAIT || state==CHECK_WAIT) host_rsp_ready=1;
    end
    always_ff @(posedge clk) begin
        if (!rst_n) begin state<=INIT_REQ; index<=0; watchdog<=0; error_code<=0; end
        else begin
            if (state!=PASS && state!=FAIL) watchdog<=watchdog+1;
            case (state)
                INIT_REQ: if (host_valid && host_ready) state<=INIT_WAIT;
                INIT_WAIT: if (host_rsp_valid) begin
                    if (last) state<=START;
                    else begin index<=index+1; state<=INIT_REQ; end
                end
                START: if (start_ready) state<=RUN;
                RUN: if (done) begin
                    if (completed_tasks!=expected_tasks || busy) begin state<=FAIL; error_code<=8'he4; end
                    else begin index<=0; state<=CHECK_REQ; end
                end
                CHECK_REQ: if (host_valid && host_ready) state<=CHECK_WAIT;
                CHECK_WAIT: if (host_rsp_valid) begin
                    if (host_rdata!==expected_data) begin state<=FAIL; error_code<=8'he1; end
                    else if (last) state<=PASS;
                    else begin index<=index+1; state<=CHECK_REQ; end
                end
                PASS,FAIL: begin end
                default: begin state<=FAIL; error_code<=8'hef; end
            endcase
            if (error) begin state<=FAIL; error_code<=dma_error_code; end
            else if (host_rsp_valid && host_rsp_ready && host_error) begin state<=FAIL; error_code<=8'he2; end
            else if (state!=PASS && state!=FAIL && watchdog>=32'd1000000) begin state<=FAIL; error_code<=8'he3; end
        end
    end
endmodule
