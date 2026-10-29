// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Autonomous BRAM-only smoke test: initialize operands, issue real RK commands,
// and read back eight FP16 results for each of ADD, SUB and MUL. This is NOT a
// PCIe device, an RK driver, or an implementation of the full tinygrad backend.
module rk_ew_demo (
    input logic clk, rst_n,
    output logic pass, fail,
    output logic [7:0] error_code
);
    typedef enum logic [3:0] {INIT_REQ,INIT_WAIT,CMD,RUN,CHECK_REQ,CHECK_WAIT,PASS,FAIL} state_t;
    state_t state;
    logic [4:0] init_index,check_index;
    logic [6:0] cmd_index;
    logic [2:0] check_lane;
    logic [1:0] operation;
    logic [31:0] watchdog;
    logic [31:0] init_addr;
    logic [15:0] init_data,expected_data;
    logic cmd_valid,cmd_ready,unused_busy,done,error;
    logic [63:0] cmd_data;
    logic [7:0] core_error_code;
    logic mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready,mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata,mem_rsp_rdata;
    logic host_valid,host_ready,host_write,host_rsp_valid,host_rsp_ready,host_error;
    logic [31:0] host_addr;
    logic [15:0] host_wdata,host_rdata;

    assign pass = (state==PASS);
    assign fail = (state==FAIL);
    assign cmd_valid = (state==CMD);
    assign check_index = {operation,check_lane};
    rk_demo_rom rom(.*);
    rk_ew_core core (
        .clk(clk),.rst_n(rst_n),.cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.cmd_data(cmd_data),
        .busy(unused_busy),.done(done),.error(error),.error_code(core_error_code),
        .mem_req_valid(mem_req_valid),.mem_req_ready(mem_req_ready),.mem_req_write(mem_req_write),
        .mem_req_addr(mem_req_addr),.mem_req_wdata(mem_req_wdata),
        .mem_rsp_valid(mem_rsp_valid),.mem_rsp_ready(mem_rsp_ready),
        .mem_rsp_rdata(mem_rsp_rdata),.mem_rsp_error(mem_rsp_error)
    );
    rk_bram #(.BYTES(4096),.BASE(32'h10000000)) ram (
        .clk(clk),.rst_n(rst_n),.req_valid(mem_req_valid),.req_ready(mem_req_ready),
        .req_write(mem_req_write),.req_addr(mem_req_addr),.req_wdata(mem_req_wdata),
        .rsp_valid(mem_rsp_valid),.rsp_ready(mem_rsp_ready),.rsp_rdata(mem_rsp_rdata),.rsp_error(mem_rsp_error),
        .host_valid(host_valid),.host_ready(host_ready),.host_write(host_write),
        .host_addr(host_addr),.host_wdata(host_wdata),.host_rsp_valid(host_rsp_valid),
        .host_rsp_ready(host_rsp_ready),.host_rdata(host_rdata),.host_error(host_error)
    );
    always_comb begin
        host_valid=0; host_write=0; host_addr=0; host_wdata=0; host_rsp_ready=0;
        if (state==INIT_REQ) begin
            host_valid=1; host_write=1; host_addr=init_addr; host_wdata=init_data;
        end
        if (state==CHECK_REQ) begin
            host_valid=1; host_addr=32'h10000200 + {28'b0,check_lane,1'b0};
        end
        if (state==INIT_WAIT || state==CHECK_WAIT) host_rsp_ready=1;
    end
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state<=INIT_REQ; init_index<=0; cmd_index<=0; check_lane<=0;
            operation<=0; error_code<=0; watchdog<=0;
        end else begin
            if (state!=PASS && state!=FAIL) watchdog<=watchdog+1;
            case (state)
                INIT_REQ: if (host_valid && host_ready) state<=INIT_WAIT;
                INIT_WAIT: if (host_rsp_valid) begin
                    if (init_index==23) state<=CMD;
                    else begin init_index<=init_index+1; state<=INIT_REQ; end
                end
                CMD: if (cmd_ready) begin
                    cmd_index<=cmd_index+1;
                    if (cmd_index==21 || cmd_index==43 || cmd_index==65) state<=RUN;
                end
                RUN: if (done) begin check_lane<=0; state<=CHECK_REQ; end
                CHECK_REQ: if (host_valid && host_ready) state<=CHECK_WAIT;
                CHECK_WAIT: if (host_rsp_valid) begin
                    // Case inequality also rejects unknown/uninitialized readback
                    // in four-state simulation. For physical bits it is ordinary !=.
                    if (host_rdata!==expected_data) begin state<=FAIL; error_code<=8'he1; end
                    else if (check_lane!=7) begin check_lane<=check_lane+1; state<=CHECK_REQ; end
                    else if (operation==2) state<=PASS;
                    else begin operation<=operation+1; state<=CMD; end
                end
                PASS,FAIL: begin end
                default: begin state<=FAIL; error_code<=8'hef; end
            endcase
            if (error) begin state<=FAIL; error_code<=core_error_code; end
            else if (host_rsp_valid && host_rsp_ready && host_error) begin state<=FAIL; error_code<=8'he2; end
            else if ((state!=PASS && state!=FAIL) && watchdog>=32'd1000000) begin
                state<=FAIL; error_code<=8'he3;
            end
        end
    end
endmodule
