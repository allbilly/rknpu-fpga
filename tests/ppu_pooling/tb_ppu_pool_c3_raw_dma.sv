// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// The PPU dispatch test deliberately stubs only the independent EW/CMAC child.
// Kind 3 selects the real C3 engine below; the numerical branch must remain idle.
/* verilator lint_off UNUSEDSIGNAL */
/* verilator lint_off UNUSEDPARAM */
/* verilator lint_off DECLFILENAME */
module rk_dual_async_dispatch #(
    parameter int unsigned ATOMIC_C = 32,
    parameter int unsigned ATOMIC_K = 16,
    parameter int unsigned TIMEOUT_CYCLES = 32,
    parameter int unsigned MAX_TASKS = 4095,
    parameter int unsigned SYNC_STAGES = 3
) (
    input wire ui_clk,ui_rst_n,ui_admission_enable,ui_rearm_permit,
    input wire ui_start_valid,ui_start_cmac,
    output wire ui_start_ready,ui_start_slot_ready,ui_ew_start_ready,ui_cmac_start_ready,
    output wire ui_ew_start_slot_ready,ui_cmac_start_slot_ready,
    input wire [31:0] ui_start_address,ui_start_amount,
    output wire ui_result_valid,ui_result_error,
    output wire [7:0] ui_result_code,
    output wire [31:0] ui_result_tasks,
    input wire ui_result_ready,
    output wire ui_fault,ui_quiet,ui_idle_quiet,core_quiet,core_restart_ready,
    input wire core_clk,core_rst_n,
    output wire ui_mem_req_valid,ui_mem_req_write,
    output wire [31:0] ui_mem_req_addr,
    output wire [15:0] ui_mem_req_wdata,
    input wire ui_mem_req_ready,ui_mem_rsp_valid,
    input wire [15:0] ui_mem_rsp_rdata,
    input wire ui_mem_rsp_error,
    output wire ui_mem_rsp_ready
);
    assign ui_start_ready=ui_admission_enable&&ui_start_slot_ready;
    assign ui_start_slot_ready=ui_rst_n;
    assign ui_ew_start_ready=ui_admission_enable&&ui_rst_n;
    assign ui_cmac_start_ready=ui_admission_enable&&ui_rst_n;
    assign ui_ew_start_slot_ready=ui_rst_n;
    assign ui_cmac_start_slot_ready=ui_rst_n;
    assign ui_result_valid=1'b0;
    assign ui_result_error=1'b0;
    assign ui_result_code=8'd0;
    assign ui_result_tasks=32'd0;
    assign ui_fault=1'b0;
    assign ui_quiet=ui_rst_n;
    assign ui_idle_quiet=ui_rst_n;
    assign core_quiet=core_rst_n;
    assign core_restart_ready=core_rst_n;
    assign ui_mem_req_valid=1'b0;
    assign ui_mem_req_write=1'b0;
    assign ui_mem_req_addr=32'd0;
    assign ui_mem_req_wdata=16'd0;
    assign ui_mem_rsp_ready=1'b0;
endmodule
/* verilator lint_on DECLFILENAME */
/* verilator lint_on UNUSEDPARAM */
/* verilator lint_on UNUSEDSIGNAL */

/* verilator lint_off SYNCASYNCNET */
module tb_ppu_pool_c3_raw_dma;
    localparam integer COMMAND_BASE = 'h3000;
    localparam integer INPUT_BASE = 'h1000;
    localparam integer OUTPUT_BASE = 'h2000;
    localparam integer BO_BYTES = 4096;
    localparam integer COMMAND_BYTES = 208;

    logic clk;
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    logic rst_n = 1'b0;
    logic start_valid = 1'b0;
    wire start_ready, start_slot_ready;
    logic [1:0] start_kind = 2'd3;
    logic start_offer = 1'b0;
    logic [31:0] start_address = COMMAND_BASE;
    logic [31:0] start_amount = 32'd26;
    wire ui_quiet, ui_idle_quiet, core_quiet, core_restart_ready;
    wire ui_restart_ready, ui_idle_restart_ready, ui_fault;
    wire ew_start_ready, cmac_start_ready, layout_start_ready;
    wire ew_start_slot_ready, cmac_start_slot_ready, layout_start_slot_ready;
    wire ui_result_valid, ui_result_error;
    wire [7:0] error_code;
    wire [31:0] result_tasks;
    logic result_ready = 1'b1;
    wire mem_req_valid, mem_req_write;
    logic mem_req_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_rsp_valid;
    wire mem_rsp_ready;
    logic [15:0] mem_rsp_rdata;
    logic mem_rsp_error;

    logic [7:0] memory [0:65535];
    logic [7:0] command_bytes [0:COMMAND_BYTES-1];
    logic [7:0] input_bytes [0:BO_BYTES-1];
    logic [7:0] output_init_bytes [0:BO_BYTES-1];
    logic [7:0] expected_bytes [0:BO_BYTES-1];
    logic memory_pending_q;
    logic [31:0] pending_address_q;
    logic pending_write_q;
    logic [15:0] pending_rdata_q;
    logic pending_error_q;
    integer response_delay_q;
    integer cycle_count_q;
    integer transaction_count_q;
    integer response_count_q;
    integer command_read_count_q;
    integer input_read_count_q;
    integer output_write_count_q;
    integer mode = 0;
    integer expected_error = 0;
    integer fd;
    integer bytes_read;
    integer i;
    integer timeout_count;
    string command_path, input_path, output_init_path, expected_path;

    assign mem_req_ready = rst_n && !memory_pending_q && !mem_rsp_valid &&
                           (cycle_count_q[1:0] != 2'b00);

    rk_layout_compute_dispatch #(
        .BASE(32'h00001000), .BYTES(33'd12288), .TIMEOUT_CYCLES(32),
        .ATOMIC_C(32), .ATOMIC_K(16), .MAX_TASKS(4), .SYNC_STAGES(3)
    ) dut (
        .ui_clk(clk), .ui_rst_n(rst_n), .ui_admission_enable(1'b1),
        .ui_rearm_permit(1'b1), .ui_start_valid(start_valid), .ui_start_offer(start_offer),
        .ui_start_kind(start_kind), .ui_start_ready(start_ready),
        .ui_start_slot_ready(start_slot_ready), .ui_ew_start_ready(ew_start_ready),
        .ui_cmac_start_ready(cmac_start_ready), .ui_layout_start_ready(layout_start_ready),
        .ui_ew_start_slot_ready(ew_start_slot_ready),
        .ui_cmac_start_slot_ready(cmac_start_slot_ready),
        .ui_layout_start_slot_ready(layout_start_slot_ready),
        .ui_start_address(start_address), .ui_start_amount(start_amount),
        .ui_result_valid, .ui_result_error, .ui_result_code(error_code),
        .ui_result_tasks(result_tasks), .ui_result_ready(result_ready),
        .ui_fault, .ui_quiet, .ui_idle_quiet, .core_quiet, .core_restart_ready,
        .ui_restart_ready, .ui_idle_restart_ready, .core_clk(clk), .core_rst_n(rst_n),
        .ui_mem_req_valid(mem_req_valid), .ui_mem_req_ready(mem_req_ready),
        .ui_mem_req_write(mem_req_write), .ui_mem_req_addr(mem_req_addr),
        .ui_mem_req_wdata(mem_req_wdata), .ui_mem_rsp_valid(mem_rsp_valid),
        .ui_mem_rsp_ready(mem_rsp_ready), .ui_mem_rsp_rdata(mem_rsp_rdata),
        .ui_mem_rsp_error(mem_rsp_error)
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            memory_pending_q <= 1'b0;
            pending_address_q <= 32'd0;
            pending_write_q <= 1'b0;
            pending_rdata_q <= 16'd0;
            pending_error_q <= 1'b0;
            response_delay_q <= 0;
            mem_rsp_valid <= 1'b0;
            mem_rsp_rdata <= 16'd0;
            mem_rsp_error <= 1'b0;
            cycle_count_q <= 0;
            transaction_count_q <= 0;
            response_count_q <= 0;
            command_read_count_q <= 0;
            input_read_count_q <= 0;
            output_write_count_q <= 0;
        end else begin
            cycle_count_q <= cycle_count_q + 1;

            if (mem_req_valid && mem_req_ready) begin
                memory_pending_q <= 1'b1;
                pending_address_q <= mem_req_addr;
                pending_write_q <= mem_req_write;
                pending_rdata_q <= {memory[mem_req_addr + 1], memory[mem_req_addr]};
                pending_error_q <= (mode == 1) ||
                                   (mem_req_addr >= 65536) ||
                                   (mem_req_addr + 1 >= 65536);
                response_delay_q <= (transaction_count_q % 3) + 1;
                transaction_count_q <= transaction_count_q + 1;

                if (!mem_req_write && mem_req_addr >= COMMAND_BASE &&
                    mem_req_addr < COMMAND_BASE + COMMAND_BYTES)
                    command_read_count_q <= command_read_count_q + 1;
                else if (!mem_req_write && mem_req_addr >= INPUT_BASE &&
                         mem_req_addr < INPUT_BASE + BO_BYTES)
                    input_read_count_q <= input_read_count_q + 1;
                else if (mem_req_write && mem_req_addr >= OUTPUT_BASE &&
                         mem_req_addr < OUTPUT_BASE + BO_BYTES)
                    output_write_count_q <= output_write_count_q + 1;

                if (mem_req_write && mem_req_addr < 65535) begin
                    memory[mem_req_addr] <= mem_req_wdata[7:0];
                    memory[mem_req_addr + 1] <= mem_req_wdata[15:8];
                end
            end

            if (memory_pending_q && !mem_rsp_valid) begin
                if (response_delay_q > 0)
                    response_delay_q <= response_delay_q - 1;
                else begin
                    mem_rsp_valid <= 1'b1;
                    mem_rsp_rdata <= pending_rdata_q;
                    mem_rsp_error <= pending_error_q;
                    if (!pending_write_q && mode == 4 &&
                        pending_address_q == COMMAND_BASE + (8 * 8) + 2)
                        mem_rsp_rdata <= pending_rdata_q ^ 16'h0001;
                end
            end

            if (mem_rsp_valid && mem_rsp_ready) begin
                mem_rsp_valid <= 1'b0;
                mem_rsp_error <= 1'b0;
                memory_pending_q <= 1'b0;
                response_count_q <= response_count_q + 1;
            end
        end
    end

    task automatic launch_job;
        begin
            @(negedge clk);
            start_valid = 1'b1;
            @(posedge clk);
            if (start_ready !== 1'b1) $fatal(1, "DMA start was not ready");
            @(negedge clk);
            start_valid = 1'b0;
        end
    endtask

    initial begin : TEST
        if (!$value$plusargs("COMMAND_BIN=%s", command_path) ||
            !$value$plusargs("INPUT_BIN=%s", input_path) ||
            !$value$plusargs("OUTPUT_INIT_BIN=%s", output_init_path) ||
            !$value$plusargs("EXPECTED_BIN=%s", expected_path))
            $fatal(1, "missing fixture plusarg");
        if (!$value$plusargs("MODE=%d", mode)) mode = 0;
        if (!$value$plusargs("EXPECT_ERROR=%d", expected_error)) expected_error = 0;
        if (mode < 0 || mode > 5) $fatal(1, "invalid MODE");

        for (i = 0; i < 65536; i = i + 1) memory[i] = 8'd0;
        fd = $fopen(command_path, "rb");
        if (fd == 0) $fatal(1, "cannot open command stream");
        bytes_read = $fread(command_bytes, fd);
        $fclose(fd);
        if (bytes_read != COMMAND_BYTES) $fatal(1, "command stream is not 208 bytes");
        fd = $fopen(input_path, "rb");
        if (fd == 0) $fatal(1, "cannot open input BO");
        bytes_read = $fread(input_bytes, fd);
        $fclose(fd);
        if (bytes_read != BO_BYTES) $fatal(1, "input BO is not 4096 bytes");
        fd = $fopen(output_init_path, "rb");
        if (fd == 0) $fatal(1, "cannot open initial output BO");
        bytes_read = $fread(output_init_bytes, fd);
        $fclose(fd);
        if (bytes_read != BO_BYTES) $fatal(1, "initial output BO is not 4096 bytes");
        fd = $fopen(expected_path, "rb");
        if (fd == 0) $fatal(1, "cannot open expected output BO");
        bytes_read = $fread(expected_bytes, fd);
        $fclose(fd);
        if (bytes_read != BO_BYTES) $fatal(1, "expected output BO is not 4096 bytes");

        for (i = 0; i < COMMAND_BYTES; i = i + 1)
            memory[COMMAND_BASE + i] = command_bytes[i];
        for (i = 0; i < BO_BYTES; i = i + 1) begin
            memory[INPUT_BASE + i] = input_bytes[i];
            memory[OUTPUT_BASE + i] = output_init_bytes[i];
        end
        if (mode == 2) start_amount = 32'd25;
        if (mode == 3) start_address = 32'hfffffff8;

        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        if (ew_start_ready !== 1'b1 || cmac_start_ready !== 1'b1 ||
            layout_start_ready !== 1'b1 || ew_start_slot_ready !== 1'b1 ||
            cmac_start_slot_ready !== 1'b1 || layout_start_slot_ready !== 1'b1 ||
            ui_restart_ready !== 1'b1 || ui_idle_restart_ready !== 1'b1 ||
            core_quiet !== 1'b1 || core_restart_ready !== 1'b1)
            $fatal(1, "dispatcher did not publish all idle readiness witnesses");
        launch_job();
        start_offer = 1'b0;
        if (mode == 0 || mode == 5) begin
            start_kind = 2'd0;
            start_offer = 1'b1;
            repeat (4) begin
                @(negedge clk);
                if (start_ready !== 1'b0 || start_slot_ready !== 1'b0)
                    $fatal(1, "EW attempted to take an owned PPU memory slot");
            end
            start_kind = 2'd3;
            start_offer = 1'b0;
        end

        timeout_count = 0;
        while (!ui_result_valid && timeout_count < 30000) begin
            @(negedge clk);
            timeout_count = timeout_count + 1;
        end
        if (timeout_count == 30000) $fatal(1, "DMA test timed out");

        if (expected_error != 0) begin
            if (ui_result_error !== 1'b1 || error_code !== expected_error[7:0] ||
                ui_fault !== 1'b1 || result_tasks !== 32'd0)
                $fatal(1, "mode %0d result_error=%b code=%0d fault=%b tasks=%0d expected=%0d",
                       mode, ui_result_error, error_code, ui_fault, result_tasks, expected_error);
            for (i = 0; i < BO_BYTES; i = i + 1)
                if (memory[OUTPUT_BASE + i] !== output_init_bytes[i])
                    $fatal(1, "fault mode %0d modified output BO byte %0d",
                           mode, i);
            if (output_write_count_q != 0)
                $fatal(1, "fault mode %0d issued %0d output writes", mode,
                       output_write_count_q);
            if ((mode == 2 || mode == 3) && transaction_count_q != 0)
                $fatal(1, "invalid descriptor generated memory traffic");
            $display("PASS ppu_c3_raw_dma mode=%0d error_code=%0d transactions=%0d responses=%0d output_writes=0",
                     mode, error_code, transaction_count_q, response_count_q);
        end else begin
            if (ui_result_error !== 1'b0 || ui_fault !== 1'b0 ||
                error_code !== 8'd0 || result_tasks !== 32'd1)
                $fatal(1, "owned PPU completion mismatch result_error=%b fault=%b code=%0d tasks=%0d",
                       ui_result_error, ui_fault, error_code, result_tasks);
            repeat (3) @(negedge clk);
            if (ui_quiet !== 1'b1 || ui_idle_quiet !== 1'b1)
                $fatal(1, "successful PPU owner did not retire to quiet");
            if (mode == 5) begin
                launch_job();
                timeout_count = 0;
                while (!ui_result_valid && timeout_count < 30000) begin
                    @(negedge clk);
                    timeout_count = timeout_count + 1;
                end
                if (timeout_count == 30000)
                    $fatal(1, "second same-epoch PPU job timed out state=%0d leaf_reset=%b leaf_ready=%b owned=%b owner_ppu=%b tx=%0d rsp=%0d cmd=%0d input=%0d output=%0d",
                           dut.ppu_engine.state_q, dut.ppu_engine.pool_leaf_rst_n_q,
                           dut.ppu_engine.pool_in_ready, dut.owned, dut.owner_ppu,
                           transaction_count_q, response_count_q, command_read_count_q,
                           input_read_count_q, output_write_count_q);
                if (ui_result_error !== 1'b0 || ui_fault !== 1'b0 ||
                    error_code !== 8'd0 || result_tasks !== 32'd1)
                    $fatal(1, "second PPU completion mismatch result_error=%b fault=%b code=%0d tasks=%0d",
                           ui_result_error, ui_fault, error_code, result_tasks);
            end
            if (transaction_count_q != (mode == 5 ? 288 : 144) ||
                response_count_q != (mode == 5 ? 288 : 144) ||
                command_read_count_q != (mode == 5 ? 208 : 104) ||
                input_read_count_q != (mode == 5 ? 64 : 32) ||
                output_write_count_q != (mode == 5 ? 16 : 8))
                $fatal(1, "serialized traffic mismatch tx=%0d rsp=%0d cmd=%0d in=%0d out=%0d",
                       transaction_count_q, response_count_q, command_read_count_q,
                       input_read_count_q, output_write_count_q);
            for (i = 0; i < BO_BYTES; i = i + 1)
                if (memory[OUTPUT_BASE + i] !== expected_bytes[i])
                    $fatal(1, "complete output BO mismatch at byte %0d got=%02x expected=%02x",
                           i, memory[OUTPUT_BASE + i], expected_bytes[i]);
            repeat (3) @(negedge clk);
            if (ui_quiet !== 1'b1 || ui_idle_quiet !== 1'b1)
                $fatal(1, "successful PPU owner did not retire to quiet");
            if (mode == 5)
                $display("PASS ppu_c3_raw_dma mode=5 error_code=0 transactions=288 command_reads=208 input_reads=64 output_writes=16 complete_output_bytes=4096 repeated_jobs=2");
            else
                $display("PASS ppu_c3_raw_dma mode=0 transactions=144 command_reads=104 input_reads=32 output_writes=8 complete_output_bytes=4096");
        end
        $finish;
    end

    initial begin
        #10000000;
        $fatal(1, "raw DMA testbench timeout");
    end
endmodule
/* verilator lint_on SYNCASYNCNET */
