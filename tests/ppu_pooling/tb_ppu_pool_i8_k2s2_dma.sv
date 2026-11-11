// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Whole-BO replay and fault controls for the strict 26-QWORD signed-INT8
// pooling descriptor endpoint.
//
// The bench supplies a serialized 16-bit memory model. The command stream is
// the frozen capture with only its two declared address relocations replaced
// by this bench's command/input/output windows. The output BO is compared
// against the frozen device capture byte for byte after the job completes.
//
// MODE selects the scenario:
//   0  full captured job, complete output BO
//   1  start_amount 25, rejected before any memory traffic
//   2  unaligned command address, rejected before any traffic
//   3  corrupt QWORD 9 field, profile rejects after command fetch
//   4  input base moved onto the command block, endpoint rejects overlap
//   5  output base outside the aperture, endpoint rejects
//   6  memory error on the first input read, endpoint faults
//   7  two sequential identical jobs, complete BO after each
//   8  memory never ready, endpoint timeout
module tb_ppu_pool_i8_k2s2_dma #(
    parameter integer MODE = 0,
    parameter integer TIMEOUT_CYCLES = 2048
);
    localparam logic [31:0] BASE = 32'h10000000;
    localparam int unsigned BO_BYTES = 4096;
    localparam int unsigned COMMAND_BYTES = 208;
    localparam logic [31:0] COMMAND_BASE = BASE + 32'h000;
    localparam logic [31:0] INPUT_BASE = BASE + 32'h200;
    localparam logic [31:0] OUTPUT_BASE = BASE + 32'h1000;
    localparam int unsigned MEMORY_BYTES = 8192;

    logic clk;
    initial clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0;
    logic start_valid = 0;
    wire start_ready;
    logic [31:0] start_address = COMMAND_BASE;
    logic [31:0] start_amount = 32'd26;
    wire quiescent, idle_quiet, busy, done, error;
    wire [7:0] error_code;
    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready;
    logic mem_rsp_valid, mem_rsp_error;
    logic [15:0] mem_rsp_rdata;

    logic [7:0] memory [0:MEMORY_BYTES-1];
    logic [7:0] command_bytes [0:COMMAND_BYTES-1];
    logic [7:0] input_bytes [0:BO_BYTES-1];
    logic [7:0] output_init [0:BO_BYTES-1];
    logic [7:0] expected_bytes [0:BO_BYTES-1];

    logic pending_q;
    logic [31:0] pending_addr_q;
    logic pending_write_q;
    logic [15:0] pending_rdata_q;
    logic pending_error_q;
    integer delay_q;
    integer cycles_q;
    integer transactions_q, responses_q, command_reads_q, input_reads_q, output_writes_q;
    integer i, fd, bytes_read, timeout_count;
    string command_path, input_path, output_init_path, expected_path;

    // Blend of accepted and stalled cycles; mode 8 never accepts.
    // Stall pattern must advance on every cycle, not on accepted transactions,
    // otherwise a rejected cycle would hold mem_req_ready low forever.
    assign mem_req_ready = rst_n && !pending_q && !mem_rsp_valid &&
                           ((MODE == 8) ? 1'b0 : (cycles_q % 3 != 1));

    rk_ppu_pool_i8_k2s2_dma #(
        .BASE(BASE), .BYTES(33'd8192), .MINIMUM(1'b0),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) dut (
        .clk, .rst_n,
        .start_valid, .start_ready, .start_address, .start_amount,
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
            pending_rdata_q <= 16'd0;
            pending_error_q <= 1'b0;
            delay_q <= 0;
            mem_rsp_valid <= 1'b0;
            mem_rsp_rdata <= 16'd0;
            mem_rsp_error <= 1'b0;
            cycles_q <= 0;
            transactions_q <= 0;
            responses_q <= 0;
            command_reads_q <= 0;
            input_reads_q <= 0;
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
                                   (mem_req_addr + 1 >= BASE + MEMORY_BYTES) ||
                                   (mem_req_addr[0] !== 1'b0) ||
                                   (MODE == 6 && !mem_req_write &&
                                    mem_req_addr >= INPUT_BASE &&
                                    mem_req_addr < INPUT_BASE + 64 &&
                                    input_reads_q == 0);
                delay_q <= (transactions_q % 2) + 1;
                transactions_q <= transactions_q + 1;
                if (!mem_req_write &&
                    mem_req_addr >= COMMAND_BASE &&
                    mem_req_addr < COMMAND_BASE + COMMAND_BYTES)
                    command_reads_q <= command_reads_q + 1;
                else if (!mem_req_write &&
                         mem_req_addr >= INPUT_BASE &&
                         mem_req_addr < INPUT_BASE + BO_BYTES)
                    input_reads_q <= input_reads_q + 1;
                else if (mem_req_write &&
                         mem_req_addr >= OUTPUT_BASE &&
                         mem_req_addr < OUTPUT_BASE + BO_BYTES)
                    output_writes_q <= output_writes_q + 1;
                if (mem_req_write && mem_req_addr + 1 < BASE + MEMORY_BYTES) begin
                    memory[mem_req_addr - BASE] <= mem_req_wdata[7:0];
                    memory[mem_req_addr + 1 - BASE] <= mem_req_wdata[15:8];
                end
            end
            if (pending_q && !mem_rsp_valid) begin
                if (delay_q > 0)
                    delay_q <= delay_q - 1;
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
            while (!done && !error && timeout_count < 200000) begin
                @(negedge clk);
                timeout_count = timeout_count + 1;
            end
            if (timeout_count == 200000) $fatal(1, "endpoint did not finish");
            @(negedge clk);
        end
    endtask

    task automatic expect_error(input integer code);
        begin
            if (error !== 1'b1 || done !== 1'b0 || error_code !== code) begin
                $fatal(1, "MODE %0d expected error %0d, got error=%b done=%b code=%0d",
                       MODE, code, error, done, error_code);
            end
        end
    endtask

    task automatic compare_bo;
        begin
            for (i = 0; i < BO_BYTES; i = i + 1)
                if (memory[OUTPUT_BASE + i - BASE] !== expected_bytes[i])
                    $fatal(1, "MODE %0d output BO byte %0d got=%02x expected=%02x",
                           MODE, i, memory[OUTPUT_BASE + i - BASE], expected_bytes[i]);
        end
    endtask

    initial begin : TEST
        if (!$value$plusargs("COMMAND_BIN=%s", command_path) ||
            !$value$plusargs("INPUT_BIN=%s", input_path) ||
            !$value$plusargs("OUTPUT_INIT_BIN=%s", output_init_path) ||
            !$value$plusargs("EXPECTED_BIN=%s", expected_path))
            $fatal(1, "missing fixture plusarg");

        for (i = 0; i < MEMORY_BYTES; i = i + 1) memory[i] = 8'd0;
        fd = $fopen(command_path, "rb");
        if (fd == 0) $fatal(1, "cannot open command stream");
        bytes_read = $fread(command_bytes, fd);
        $fclose(fd);
        if (bytes_read != COMMAND_BYTES) $fatal(1, "command stream is not 26 QWORDs");
        fd = $fopen(input_path, "rb");
        if (fd == 0) $fatal(1, "cannot open input BO");
        bytes_read = $fread(input_bytes, fd);
        $fclose(fd);
        if (bytes_read != BO_BYTES) $fatal(1, "input BO is not 4096 bytes");
        fd = $fopen(output_init_path, "rb");
        if (fd == 0) $fatal(1, "cannot open initial output BO");
        bytes_read = $fread(output_init, fd);
        $fclose(fd);
        if (bytes_read != BO_BYTES) $fatal(1, "initial output BO is not 4096 bytes");
        fd = $fopen(expected_path, "rb");
        if (fd == 0) $fatal(1, "cannot open expected output BO");
        bytes_read = $fread(expected_bytes, fd);
        $fclose(fd);
        if (bytes_read != BO_BYTES) $fatal(1, "expected output BO is not 4096 bytes");

        for (i = 0; i < COMMAND_BYTES; i = i + 1)
            memory[COMMAND_BASE + i - BASE] = command_bytes[i];
        for (i = 0; i < BO_BYTES; i = i + 1) begin
            memory[INPUT_BASE + i - BASE] = input_bytes[i];
            memory[OUTPUT_BASE + i - BASE] = output_init[i];
        end

        // Scenario rewrites of the buffered command stream or launch fields.
        if (MODE == 1) start_amount = 32'd25;
        if (MODE == 2) start_address = COMMAND_BASE + 32'd1;
        if (MODE == 3) memory[COMMAND_BASE + 9*8 + 4 - BASE] =
            memory[COMMAND_BASE + 9*8 + 4 - BASE] ^ 8'h01;
        if (MODE == 4) begin
            memory[COMMAND_BASE + 20*8 + 2 - BASE] = 8'h00;
            memory[COMMAND_BASE + 20*8 + 3 - BASE] = 8'h00; // input = command
            memory[COMMAND_BASE + 20*8 + 4 - BASE] = 8'h00;
            memory[COMMAND_BASE + 20*8 + 5 - BASE] = 8'h10;
        end
        if (MODE == 5) begin
            memory[COMMAND_BASE + 13*8 + 2 - BASE] = 8'h00;
            memory[COMMAND_BASE + 13*8 + 3 - BASE] = 8'h00; // 0x10200000
            memory[COMMAND_BASE + 13*8 + 4 - BASE] = 8'h20;
            memory[COMMAND_BASE + 13*8 + 5 - BASE] = 8'h10;
        end

        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        launch();
        wait_result();

        case (MODE)
            0: begin
                if (error !== 1'b0 || error_code !== 8'd0)
                    $fatal(1, "full job faulted code=%0d state=%0d gate=%0d beat=%0d out_hw=%0d rsp=%0d tx=%0d",
                           error_code, dut.state_q, dut.gate_qword_q,
                           dut.input_beat_q, dut.output_halfword_q, responses_q,
                           transactions_q, dut.profile_src_base, dut.profile_dst_base,
                           dut.command_base_q, dut.command_end_q,
                           dut.profile_input_bytes, dut.profile_output_bytes);
                compare_bo();
                if (transactions_q != 144 || command_reads_q != 104 ||
                    input_reads_q != 32 || output_writes_q != 8)
                    $fatal(1, "traffic differs tx=%0d cmd=%0d in=%0d out=%0d",
                           transactions_q, command_reads_q, input_reads_q, output_writes_q);
            end
            1: begin
                expect_error(1);
                if (transactions_q != 0) $fatal(1, "rejected launch issued traffic");
            end
            2: begin
                expect_error(3);
                if (transactions_q != 0) $fatal(1, "unaligned launch issued traffic");
            end
            3: begin
                expect_error(1);
                if (command_reads_q != 104 || input_reads_q != 0 || output_writes_q != 0)
                    $fatal(1, "profile rejection traffic cmd=%0d in=%0d out=%0d",
                           command_reads_q, input_reads_q, output_writes_q);
            end
            4, 5: begin
                expect_error(3);
                if (command_reads_q != 104 || input_reads_q != 0 || output_writes_q != 0)
                    $fatal(1, "address rejection traffic cmd=%0d in=%0d out=%0d",
                           command_reads_q, input_reads_q, output_writes_q);
            end
            6: begin
                expect_error(5);
                if (command_reads_q != 104 || input_reads_q != 1 || output_writes_q != 0)
                    $fatal(1, "bus fault traffic cmd=%0d in=%0d out=%0d",
                           command_reads_q, input_reads_q, output_writes_q);
                for (i = 0; i < BO_BYTES; i = i + 1)
                    if (memory[OUTPUT_BASE + i - BASE] !== output_init[i])
                        $fatal(1, "bus fault modified output BO byte %0d", i);
            end
            7: begin
                if (error !== 1'b0) $fatal(1, "first job of repeat pair faulted");
                compare_bo();
                repeat (2) @(negedge clk);
                if (!quiescent) $fatal(1, "endpoint did not return to quiescence");
                launch();
                wait_result();
                if (error !== 1'b0) $fatal(1, "second job faulted code=%0d", error_code);
                compare_bo();
                if (transactions_q != 288 || command_reads_q != 208 ||
                    input_reads_q != 64 || output_writes_q != 16)
                    $fatal(1, "repeat traffic differs tx=%0d cmd=%0d in=%0d out=%0d",
                           transactions_q, command_reads_q, input_reads_q, output_writes_q);
            end
            8: begin
                expect_error(8);
                if (transactions_q != 0)
                    $fatal(1, "timeout mode unexpectedly issued a transaction");
            end
            default: $fatal(1, "invalid MODE");
        endcase

        $display("PASS ppu_pool_i8_k2s2_dma mode=%0d error_code=%0d transactions=%0d command_reads=%0d input_reads=%0d output_writes=%0d",
                 MODE, error_code, transactions_q, command_reads_q, input_reads_q,
                 output_writes_q);
        $finish;
    end

    initial begin
        #20000000;
        $fatal(1, "signed-INT8 descriptor endpoint watchdog");
    end
endmodule
