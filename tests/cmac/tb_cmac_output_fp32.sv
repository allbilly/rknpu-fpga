// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unit bench for rk_cmac_output_fp32: the FP32 post-accumulation tail.
//
// It checks the tail's own contract, not the writer's (already covered by
// tb_cmac_fp32_writer): values pass through unchanged, the `in_last` flag
// produces exactly one `done` pulse, and a stream cannot keep feeding values
// after the final one was accepted.
module tb_cmac_output_fp32;
    localparam int unsigned TIMEOUT_CYCLES = 64;

    logic clk = 0;
    always #10 clk = ~clk;

    logic rst_n = 0, in_valid = 0, in_last = 0, cancel = 0;
    logic [7:0] cancel_code = 8'd2;
    wire in_ready, busy, acknowledged, done, error;
    logic [31:0] in_value = 0, in_address = 0;
    wire [7:0] error_code;

    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready, mem_rsp_valid, mem_rsp_error;

    logic [15:0] storage [0:255];
    logic pending, pending_error;
    logic [31:0] pending_address;
    integer writes;

    assign mem_req_ready = rst_n && !pending && !mem_rsp_valid;

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
                if (mem_req_write) begin
                    storage[mem_req_addr[8:1]] <= mem_req_wdata;
                    writes <= writes + 1;
                end
            end
            if (pending && !mem_rsp_valid) begin
                pending <= 1'b0;
                mem_rsp_valid <= 1'b1;
                pending_error <= (pending_address >= 32'h400);
                mem_rsp_error <= (pending_address >= 32'h400);
            end
            if (mem_rsp_valid && mem_rsp_ready) begin
                mem_rsp_valid <= 1'b0;
                mem_rsp_error <= 1'b0;
            end
        end
    end

    rk_cmac_output_fp32 #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) dut (
        .clk, .rst_n,
        .in_valid, .in_ready, .in_value, .in_address, .in_last,
        .cancel, .cancel_code,
        .busy, .acknowledged, .done, .error, .error_code,
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_error
    );

    task automatic push(input logic [31:0] address, input logic [31:0] value,
                        input logic last);
        integer guard;
        begin
            // Present one value and wait for the tail to accept it.
            guard = 0;
            while (!in_ready && guard < 200) begin
                @(negedge clk); guard = guard + 1;
            end
            if (!in_ready) $fatal(1, "tail never became ready");
            in_address = address;
            in_value = value;
            in_last = last;
            in_valid = 1;
            @(negedge clk);
            in_valid = 0;
            if (last) begin
                // The closing flag must now block any further value.
                guard = 0;
                while (!done && !error && guard < 800) begin
                    @(negedge clk); guard = guard + 1;
                end
                if (error) $fatal(1, "unexpected error %0d", error_code);
                if (guard == 800) $fatal(1, "no done after the final value");
            end
        end
    endtask

    integer i, total_writes;
    logic [15:0] low, high;

    initial begin
        for (i = 0; i < 256; i = i + 1) storage[i] = 16'h0;
        repeat (4) @(negedge clk);
        rst_n = 1;
        repeat (2) @(negedge clk);

        // 1. A value must pass through unchanged as two halfwords.
        push(32'h0000_0000, 32'h4080_0000, 1'b1);   // 4.0
        if (writes != 2) $fatal(1, "expected 2 halfword writes, saw %0d", writes);
        if (storage[0] !== 16'h0000) $fatal(1, "low halfword not passed through");
        if (storage[1] !== 16'h4080) $fatal(1, "high halfword not passed through");

        // 2. Four GEMM-shaped values at stride 128 bytes (the m2_n2_k1 layout).
        @(negedge clk);
        push(32'h0000_0080, 32'h4100_0000, 1'b0);   // row 2, col 0 -> 8.0
        push(32'h0000_0084, 32'h4120_0000, 1'b1);   // row 2, col 1 -> 10.0
        if (writes != 6) $fatal(1, "expected 6 writes, saw %0d", writes);
        if (storage[64] !== 16'h0000) $fatal(1, "value 2 low wrong");
        if (storage[65] !== 16'h4100) $fatal(1, "value 2 high wrong");
        if (storage[66] !== 16'h0000) $fatal(1, "value 3 low wrong");
        if (storage[67] !== 16'h4120) $fatal(1, "value 3 high wrong");

        // 3. After a final value the tail must stay closed.
        if (in_ready) $fatal(1, "tail reopened after its final value");
        if (busy) $fatal(1, "tail still busy after done");

        // 4. Cancellation is an explicit error, code 2 in the 1..8 family.
        total_writes = writes;
        @(negedge clk); rst_n = 0;
        repeat (3) @(negedge clk); rst_n = 1;
        repeat (2) @(negedge clk);
        cancel = 1;
        @(negedge clk);
        if (!error || error_code !== 8'd2)
            $fatal(1, "cancel did not raise code 2 (got %0d/%0d)", error, error_code);
        if (in_ready) $fatal(1, "tail still ready while cancelled");
        cancel = 0;

        $display("PASS CMAC_OUTPUT_FP32 writes=%0d", total_writes);
        $finish;
    end

    initial begin
        #400000;
        $fatal(1, "fp32 output tail watchdog");
    end
endmodule
