// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Contract testbench for the conv-simple 52-QWORD descriptor endpoint.
//
// The endpoint is exercised against a serialized 16-bit memory model that
// holds the frozen fixture's operands and output BO. Modes:
//   0  captured job, complete output BO
//   1  start_amount 51, rejected before any traffic
//   2  unaligned command base, rejected before any traffic
//   3  command block outside the aperture, rejected before any traffic
//   4  command/input overlap, rejected after the profile publishes
//   5  memory error on the first command read
//   6  memory never ready, endpoint timeout
//   7  two sequential identical jobs, complete BO after each
module tb_conv_simple_dma #(
    parameter integer PROFILE = 0,
    parameter integer TIMEOUT_CYCLES = 64,
    parameter integer WORDS = 52,
    parameter integer INPUT_HALFWORDS = 256,
    parameter integer WEIGHT_HALFWORDS = 1152,
    parameter integer OUTPUT_BYTES = 1152,
    parameter integer INPUT_H = 8,
    parameter integer INPUT_W = 8,
    parameter integer KH = 3,
    parameter integer KW = 3,
    parameter integer INPUT_CHANNELS = 4,
    parameter integer KERNELS = 8,
    parameter integer C1_BLOCKS = 2,
    parameter integer ALIGN_C = 8,
    parameter integer PACK_C2 = 4,
    parameter integer CHUNK_LANES = 16,
    parameter integer MODE = 0
);
    localparam int unsigned OUTPUT_H = INPUT_H - KH + 1;
    localparam int unsigned OUTPUT_W = INPUT_W - KW + 1;
    localparam int unsigned OUTPUT_PIXELS = OUTPUT_H * OUTPUT_W;
    localparam int unsigned OUTPUT_HALFWORDS = OUTPUT_BYTES / 2;
    // The capture places its command block at address 0.
    localparam logic [31:0] BASE = 32'h00000000;
    localparam logic [31:0] COMMAND_BASE = BASE + 32'h0000;
    localparam logic [31:0] INPUT_BASE = BASE + 32'h1000;
    localparam logic [31:0] WEIGHT_BASE = BASE + 32'h2000;
    localparam logic [31:0] OUTPUT_BASE = BASE + 32'h3000;
    // Largest captured placement is 0x5000 + 2304 (C16), so 32 KiB.
    localparam int unsigned MEM_BYTES = 32768;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start_valid = 1'b0;
    wire start_ready;
    logic [31:0] start_address = COMMAND_BASE;
    logic [31:0] start_amount = 32'(WORDS);
    wire quiescent, idle_quiet, busy, done, error;
    wire [7:0] error_code;
    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready, mem_rsp_valid, mem_rsp_error;
    logic [15:0] mem_rsp_rdata;

    logic [7:0] memory [0:MEM_BYTES-1];
    logic [15:0] command_memory [0:WORDS*4-1];
    logic [15:0] input_memory [0:INPUT_HALFWORDS-1];
    logic [15:0] weight_memory [0:WEIGHT_HALFWORDS-1];
    logic [15:0] expected [0:OUTPUT_HALFWORDS-1];

    logic pending_q;
    logic [31:0] pending_addr_q;
    logic pending_write_q;
    logic [15:0] pending_rdata_q;
    logic pending_error_q;
    integer delay_q, cycles_q, transactions_q, responses_q;
    integer command_reads_q, input_reads_q, weight_reads_q, output_writes_q;
    integer mode, i, fd, bytes_read, timeout_count, expect_error_code;
    string fixture;

    always #5 clk = ~clk;

    // Diagnostic trace, enabled by +TRACE=1. Kept out of the pass criteria.
    logic trace_on = 1'b0;
    integer trace_cycles = 0;
    always @(posedge clk) begin
        if (trace_on && rst_n && trace_cycles > 0) begin
            $display("CYC %0d st=%0d pend=%b out=%b req=%b rdy=%b rsp=%b rsp_rdy=%b addr=%08x word=%0d hw=%0d wait=%0d",
                     trace_cycles, dut.state_q, dut.request_pending_q,
                     dut.outstanding_q, mem_req_valid, mem_req_ready,
                     mem_rsp_valid, dut.mem_rsp_ready, mem_req_addr,
                     dut.send_index_q, dut.halfword_index_q, dut.wait_cycles_q);
            trace_cycles = trace_cycles + 1;
        end
    end
    initial if ($value$plusargs("TRACE=%d", trace_cycles)) trace_on = 1'b1;

    assign mem_req_ready = rst_n && !pending_q && !mem_rsp_valid &&
                           ((MODE == 6) ? 1'b0 : (cycles_q % 3 != 1));

    rk_conv_simple_dma #(
        .PROFILE(PROFILE), .BASE(BASE), .BYTES(33'd32768),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) dut (
        .clk, .rst_n, .start_valid, .start_ready, .start_address, .start_amount,
        .quiescent, .idle_quiet, .busy, .done, .error, .error_code,
        .result_ready(1'b1),
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata,
        .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata, .mem_rsp_error
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pending_q <= 1'b0;
            pending_addr_q <= 32'd0;
            pending_write_q <= 1'b0;
            pending_error_q <= 1'b0;
            pending_rdata_q <= 16'd0;
            delay_q <= 0;
            mem_rsp_valid <= 1'b0;
            mem_rsp_error <= 1'b0;
            mem_rsp_rdata <= 16'd0;
            cycles_q <= 0;
            transactions_q <= 0;
            responses_q <= 0;
            command_reads_q <= 0;
            input_reads_q <= 0;
            weight_reads_q <= 0;
            output_writes_q <= 0;
        end else begin
            cycles_q <= cycles_q + 1;
            if (mem_req_valid && mem_req_ready) begin
                pending_q <= 1'b1;
                pending_addr_q <= mem_req_addr;
                pending_write_q <= mem_req_write;
                pending_rdata_q <= {memory[mem_req_addr + 1 - BASE],
                                    memory[mem_req_addr - BASE]};
                pending_error_q <= (mem_req_addr < BASE) ||
                                   (mem_req_addr + 1 >= BASE + MEM_BYTES) ||
                                   (mem_req_addr[0] !== 1'b0) ||
                                   (MODE == 5 && !mem_req_write && command_reads_q == 0);
                delay_q <= (transactions_q % 2) + 1;
                transactions_q <= transactions_q + 1;
                if (!mem_req_write &&
                    mem_req_addr >= COMMAND_BASE &&
                    mem_req_addr < COMMAND_BASE + 32'(WORDS) * 32'd8)
                    command_reads_q <= command_reads_q + 1;
                else if (!mem_req_write &&
                         mem_req_addr >= INPUT_BASE &&
                         mem_req_addr < INPUT_BASE + 32'(INPUT_HALFWORDS) * 32'd2)
                    input_reads_q <= input_reads_q + 1;
                else if (!mem_req_write &&
                         mem_req_addr >= WEIGHT_BASE &&
                         mem_req_addr < WEIGHT_BASE + 32'(WEIGHT_HALFWORDS) * 32'd2)
                    weight_reads_q <= weight_reads_q + 1;
                else if (mem_req_write &&
                         mem_req_addr >= OUTPUT_BASE &&
                         mem_req_addr < OUTPUT_BASE + 32'(OUTPUT_BYTES))
                    output_writes_q <= output_writes_q + 1;
                if (mem_req_write && mem_req_addr + 1 - BASE < MEM_BYTES) begin
                    memory[mem_req_addr - BASE] <= mem_req_wdata[7:0];
                    memory[mem_req_addr + 1 - BASE] <= mem_req_wdata[15:8];
                end
            end
            if (pending_q && !mem_rsp_valid) begin
                if (delay_q > 0) delay_q <= delay_q - 1;
                else begin
                    mem_rsp_valid <= 1'b1;
                    mem_rsp_rdata <= pending_rdata_q;
                    mem_rsp_error <= pending_error_q;
                end
            end
            if (mem_rsp_valid && mem_rsp_ready) begin
                mem_rsp_valid <= 1'b0;
                mem_rsp_error <= 1'b0;
                pending_q <= 1'b0;
                responses_q <= responses_q + 1;
            end
        end
    end

    task automatic launch;
        begin
            @(negedge clk);
            start_valid = 1'b1;
            do @(posedge clk); while (!start_ready);
            @(negedge clk);
            start_valid = 1'b0;
        end
    endtask

    task automatic wait_result;
        begin
            timeout_count = 0;
            while (!done && !error && timeout_count < 400000) begin
                @(negedge clk);
                timeout_count = timeout_count + 1;
            end
            if (timeout_count == 400000) $fatal(1, "endpoint did not finish");
            @(negedge clk);
        end
    endtask

    task automatic expect_error(input integer code);
        begin
            if (error !== 1'b1 || done !== 1'b0 || error_code !== code)
                $fatal(1, "MODE %0d expected error %0d, got error=%b done=%b code=%0d",
                       MODE, code, error, done, error_code);
        end
    endtask

    task automatic compare_bo;
        begin
            for (i = 0; i < OUTPUT_HALFWORDS; i = i + 1)
                if ({memory[OUTPUT_BASE + 32'(i) * 2 - BASE + 1],
                     memory[OUTPUT_BASE + 32'(i) * 2 - BASE]} !== expected[i])
                    $fatal(1, "MODE %0d output halfword %0d got=%04x expected=%04x",
                           MODE, i,
                           {memory[OUTPUT_BASE + 32'(i) * 2 - BASE + 1],
                            memory[OUTPUT_BASE + 32'(i) * 2 - BASE]}, expected[i]);
        end
    endtask

    initial begin : TEST
        if ($value$plusargs("MODE=%d", mode)) ;
        else mode = MODE;
        if (!$value$plusargs("FIXTURE=%s", fixture))
            $fatal(1, "missing FIXTURE plusarg");
        if (!$value$plusargs("EXPECT_ERROR=%d", expect_error_code))
            expect_error_code = 0;
        for (i = 0; i < MEM_BYTES; i = i + 1) memory[i] = 8'd0;

        // The fixture directory holds $readmemh text, one halfword per line.
        // $fread would read the ASCII bytes instead of the hex values.
        $readmemh({fixture, "/commands.hex"}, command_memory);
        $readmemh({fixture, "/input.hex"}, input_memory);
        $readmemh({fixture, "/weight.hex"}, weight_memory);
        $readmemh({fixture, "/expected.hex"}, expected);

        for (i = 0; i < WORDS * 4; i = i + 1) begin
            memory[COMMAND_BASE + 32'(i) * 2 - BASE] = command_memory[i][7:0];
            memory[COMMAND_BASE + 32'(i) * 2 - BASE + 1] = command_memory[i][15:8];
        end
        for (i = 0; i < INPUT_HALFWORDS; i = i + 1) begin
            memory[INPUT_BASE + 32'(i) * 2 - BASE] = input_memory[i][7:0];
            memory[INPUT_BASE + 32'(i) * 2 - BASE + 1] = input_memory[i][15:8];
        end
        for (i = 0; i < WEIGHT_HALFWORDS; i = i + 1) begin
            memory[WEIGHT_BASE + 32'(i) * 2 - BASE] = weight_memory[i][7:0];
            memory[WEIGHT_BASE + 32'(i) * 2 - BASE + 1] = weight_memory[i][15:8];
        end

        case (MODE)
            1: start_amount = 32'(WORDS - 1);
            2: start_address = COMMAND_BASE + 32'd1;
            // 0x8000 is exactly the aperture end, so the 416-byte command
            // block cannot fit; the wrapper must reject before any traffic.
            3: start_address = BASE + 32'h8000;
            4: begin
                // Move the input base onto the command block.
                memory[COMMAND_BASE + 18*8 + 2 - BASE] = 8'h00;
                memory[COMMAND_BASE + 18*8 + 3 - BASE] = 8'h00;
                memory[COMMAND_BASE + 18*8 + 4 - BASE] = 8'h00;
                memory[COMMAND_BASE + 18*8 + 5 - BASE] = 8'h10;
            end
            default: begin end
        endcase

        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        launch();
        wait_result();

        case (MODE)
            0, 7: begin
                if (error !== 1'b0 || error_code !== 8'd0)
                    $fatal(1, "MODE %0d faulted code=%0d state=%0d word=%0d hw=%0d wait=%0d core_state=%0d corecode=%0d",
                           MODE, error_code, dut.state_q, dut.send_index_q,
                           dut.halfword_index_q, dut.wait_cycles_q,
                           dut.core.profile.state, dut.core_error_code);
                compare_bo();
                if (command_reads_q != WORDS * 4)
                    $fatal(1, "command read count %0d", command_reads_q);
                if (input_reads_q != INPUT_HALFWORDS ||
                    weight_reads_q != WEIGHT_HALFWORDS ||
                    output_writes_q != OUTPUT_HALFWORDS)
                    $fatal(1, "operand traffic in=%0d w=%0d out=%0d",
                           input_reads_q, weight_reads_q, output_writes_q);
                if (MODE == 7) begin
                    repeat (2) @(negedge clk);
                    if (!quiescent) $fatal(1, "endpoint did not return to quiescence");
                    launch();
                    wait_result();
                    if (error !== 1'b0)
                        $fatal(1, "second job faulted code=%0d", error_code);
                    compare_bo();
                end
            end
            1: begin
                expect_error(8'd1);
                if (transactions_q != 0) $fatal(1, "rejected launch issued traffic");
            end
            2: begin
                expect_error(8'd3);
                if (transactions_q != 0) $fatal(1, "unaligned launch issued traffic");
            end
            3: begin
                expect_error(8'd3);
                if (transactions_q != 0) $fatal(1, "out-of-aperture launch issued traffic");
            end
            4: begin
                expect_error(8'd3);
                if (output_writes_q != 0)
                    $fatal(1, "overlap rejection wrote the output BO");
            end
            5: begin
                expect_error(8'd5);
                if (command_reads_q != 1) $fatal(1, "fault after %0d reads", command_reads_q);
                if (output_writes_q != 0) $fatal(1, "fault wrote output");
            end
            6: begin
                expect_error(8'd8);
                if (transactions_q != 0) $fatal(1, "timeout issued a transaction");
            end
            default: $fatal(1, "invalid MODE");
        endcase

        $display("PASS CONV_SIMPLE_DMA mode=%0d commands=%0d input_reads=%0d weight_reads=%0d output_writes=%0d error_code=%0d",
                 MODE, command_reads_q, input_reads_q, weight_reads_q,
                 output_writes_q, error_code);
        $finish;
    end

    initial begin
        #20000000;
        $fatal(1, "conv-simple DMA watchdog");
    end
endmodule
