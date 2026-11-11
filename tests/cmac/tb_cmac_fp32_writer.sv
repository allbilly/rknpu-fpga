// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unit bench for rk_cmac_fp32_writer.
//
// The writer is the first 32-bit output path in the repository, so this bench
// pins its exact byte contract: one 32-bit value becomes two halfwords at
// address and address+2, in that order, and nothing else is written.
module tb_cmac_fp32_writer;
    localparam int unsigned TIMEOUT_CYCLES = 64;
    localparam int unsigned MEM_HALFWORDS = 64;

    logic clk = 0;
    always #10 clk = ~clk;

    logic rst_n = 0, result_valid = 0, result_last = 0;
    wire result_ready, busy, acknowledged, done, error;
    logic [31:0] result_address = 0, result_value = 0;
    wire [7:0] error_code;

    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready, mem_rsp_valid, mem_rsp_error;

    logic [15:0] storage [0:MEM_HALFWORDS-1];
    logic pending;
    logic [31:0] pending_address;
    logic [15:0] pending_data;
    integer writes, stall;

    assign mem_req_ready = rst_n && !pending && !mem_rsp_valid && stall == 0;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pending <= 1'b0;
            mem_rsp_valid <= 1'b0;
            mem_rsp_error <= 1'b0;
            writes <= 0;
        end else begin
            if (mem_req_valid && mem_req_ready) begin
                pending <= 1'b1;
                pending_address <= mem_req_addr;
                pending_data <= storage[mem_req_addr[6:1]];
                if (mem_req_write && mem_req_addr < 32'h80) begin
                    storage[mem_req_addr[6:1]] <= mem_req_wdata;
                    writes <= writes + 1;
                end
            end
            if (pending && !mem_rsp_valid) begin
                pending <= 1'b0;
                mem_rsp_valid <= 1'b1;
                mem_rsp_error <= (pending_address >= 32'h80);
            end
            if (mem_rsp_valid && mem_rsp_ready) begin
                mem_rsp_valid <= 1'b0;
                mem_rsp_error <= 1'b0;
            end
        end
    end

    rk_cmac_fp32_writer #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) dut (
        .clk, .rst_n,
        .result_valid, .result_ready, .result_address, .result_value,
        .result_last, .busy, .acknowledged, .done, .error, .error_code,
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_error
    );

    task automatic commit(input logic [31:0] address, input logic [31:0] value,
                          input logic last);
        integer guard;
        begin
            guard = 0;
            while (!result_ready && guard < 200) begin
                @(negedge clk);
                guard = guard + 1;
            end
            if (!result_ready) $fatal(1, "writer never became ready");
            result_address = address;
            result_value = value;
            result_last = last;
            result_valid = 1;
            @(negedge clk);
            result_valid = 0;
            // Accept is only sampled at the clock edge, so wait for `busy`
            // to assert and then drop again. Checking busy straight after the
            // negedge would see the still-idle state and return immediately.
            guard = 0;
            while (!busy && !error && guard < 20) begin
                @(negedge clk);
                guard = guard + 1;
            end
            guard = 0;
            while (busy && !error && guard < 400) begin
                @(negedge clk);
                guard = guard + 1;
            end
            if (error) $fatal(1, "unexpected error %0d", error_code);
            if (guard == 400) $fatal(1, "value never completed");
        end
    endtask

    integer i, total_writes;
    logic [15:0] low, high;

    initial begin
        for (i = 0; i < MEM_HALFWORDS; i = i + 1) storage[i] = 16'h0;
        stall = 0;
        repeat (4) @(negedge clk);
        rst_n = 1;
        repeat (2) @(negedge clk);

        // 1. One value -> exactly two halfwords at address and address+2.
        commit(32'h0000_0020, 32'h3f80_0000, 1'b1);

        if (writes != 2) $fatal(1, "expected 2 halfword writes, saw %0d", writes);
        if (storage[16] !== 16'h0000) $fatal(1, "low halfword wrong");
        if (storage[17] !== 16'h3f80) $fatal(1, "high halfword wrong");
        if (!done) $fatal(1, "last value did not pulse done");

        // 2. Two values back to back, neither last.
        commit(32'h0000_0024, 32'hc049_0fdb, 1'b0);
        commit(32'h0000_0028, 32'h447a_0000, 1'b1);
        if (writes != 6) $fatal(1, "expected 6 writes total, saw %0d", writes);
        if (storage[18] !== 16'h0fdb) $fatal(1, "value 2 low wrong");
        if (storage[19] !== 16'hc049) $fatal(1, "value 2 high wrong");
        if (storage[20] !== 16'h0000) $fatal(1, "value 3 low wrong");
        if (storage[21] !== 16'h447a) $fatal(1, "value 3 high wrong");
        if (!done) $fatal(1, "final value did not pulse done");

        // 3. Misaligned address must be an explicit error (code 4), no write.
        result_address = 32'h0000_0031;
        result_value = 32'hdead_beef;
        result_last = 1'b1;
        result_valid = 1;
        @(negedge clk); result_valid = 0;
        repeat (3) @(negedge clk);
        if (!error || error_code !== 8'd4)
            $fatal(1, "misaligned address was not rejected with code 4 (got %0d/%0d)",
                   error, error_code);
        if (writes != 6) $fatal(1, "misaligned value reached memory");

        // 4. Reset clears the fault; a downstream error becomes code 5.
        // The reset clears the model's write counter, so remember the total.
        total_writes = writes;
        @(negedge clk); rst_n = 0;
        repeat (3) @(negedge clk); rst_n = 1;
        repeat (2) @(negedge clk);
        if (error || !result_ready) $fatal(1, "reset did not clear the fault");
        result_address = 32'h0000_0090;   // the model errors above 0x80
        result_value = 32'h1234_5678;
        result_last = 1'b1;
        result_valid = 1;
        @(negedge clk); result_valid = 0;
        repeat (5) @(negedge clk);
        if (!error || error_code !== 8'd5)
            $fatal(1, "downstream error was not code 5 (got %0d/%0d)",
                   error, error_code);

        $display("PASS CMAC_FP32_WRITER writes=%0d", total_writes);
        $finish;
    end

    initial begin
        #400000;
        $fatal(1, "fp32 writer watchdog");
    end
endmodule
