// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Board-image replay for the dual-endpoint top. One AXI4-Lite slave port
// carries three address regions:
//
//   0x0000_0000 .. 0x0000_7fff   shared memory window (host load/read)
//   0x0000_8000 .. 0x0000_8fff   conv-simple page (RKCS, 0x524b4353)
//   0x0000_9000 .. 0x0000_9fff   pooling page    (RKPP, 0x524b5050)
//   0x0000_a000 .. 0x0000_afff   FP32 GEMM page  (RKCM, 0x524b434d)
//   0x0000_b000 .. 0x0000_bfff   conv FP32 page  (RKCS, 0x524b4415)
//   0x0000_c000 .. 0x0000_cfff   conv k5 page     (RKCS, 0x524b4416)
//   0x0000_d000 .. 0x0000_dfff   conv C16 page    (RKCS, 0x524b4417)
//
// The host here is a plain AXI4-Lite master: it writes every fixture byte
// through the memory window, submits the job through the transport page, waits
// for the completion line, and reads the complete output BO back through the
// same window. Nothing in this bench pokes engine internals; the only signal it
// samples besides the AXI port is the two completion lines and the status pages.
//
// Modes:
//  0  page identities, descriptor-register isolation, and an unmapped address
//     returning SLVERR instead of aliasing a page
//  1  conv-simple job end-to-end: load, submit, complete 4096-byte BO, ack
//  2  pooling job end-to-end: load, submit, complete 4096-byte BO, ack
//  3  sequential conv then pooling, both BOs complete; during the conv job the
//     pooling page must report submit-blocked and the host memory window must
//     be closed
module tb_ypcb_dual_endpoint #(
    parameter integer MODE = 0,
    parameter integer CONV_COMMAND_WORDS = 0,
    parameter integer CONV_INPUT_WORDS = 0,
    parameter integer CONV_WEIGHT_WORDS = 0,
    parameter integer CONV_OUTPUT_WORDS = 1024,
    parameter integer POOL_COMMAND_WORDS = 0,
    parameter integer POOL_INPUT_WORDS = 1024,
    parameter integer POOL_OUTPUT_WORDS = 1024,
    parameter integer GEMM_COMMAND_WORDS = 0,
    parameter integer GEMM_INPUT_WORDS = 1024,
    parameter integer GEMM_WEIGHT_WORDS = 1024,
    parameter integer GEMM_OUTPUT_WORDS = 1024,
    parameter real GEMM_TOLERANCE = 0.001,
    parameter integer CONV_FP32_COMMAND_WORDS = 104,
    parameter integer CONV_FP32_INPUT_WORDS = 256,
    parameter integer CONV_FP32_WEIGHT_WORDS = 128,
    parameter integer CONV_FP32_OUTPUT_WORDS = 1024,
    parameter integer CONV_K5_COMMAND_WORDS = 104,
    parameter integer CONV_K5_INPUT_WORDS = 128,
    parameter integer CONV_K5_WEIGHT_WORDS = 1600,
    parameter integer CONV_K5_OUTPUT_WORDS = 1024,
    // These two captures place their output above the default 0x3000 window
    // (0x4000 and 0x5000). The base comes from the fixture manifest, never a
    // hardcoded guess.
    parameter integer CONV_K5_OUTPUT_BASE = 32'h0000_4000,
    parameter integer CONV_C16_COMMAND_WORDS = 104,
    parameter integer CONV_C16_INPUT_WORDS = 512,
    parameter integer CONV_C16_WEIGHT_WORDS = 2304,
    parameter integer CONV_C16_OUTPUT_WORDS = 1024,
    parameter integer CONV_C16_OUTPUT_BASE = 32'h0000_5000
);
    localparam logic [31:0] CONV_PAGE = 32'h0000_8000;
    localparam logic [31:0] POOL_PAGE = 32'h0000_9000;
    localparam logic [31:0] GEMM_PAGE = 32'h0000_a000;
    localparam logic [31:0] CONV_FP32_PAGE = 32'h0000_b000;
    localparam logic [31:0] CONV_K5_PAGE = 32'h0000_c000;
    localparam logic [31:0] CONV_C16_PAGE = 32'h0000_d000;
    localparam logic [31:0] GEMM_COMMAND = 32'h0000_0000;
    localparam logic [31:0] GEMM_INPUT = 32'h0000_1000;
    localparam logic [31:0] GEMM_WEIGHT = 32'h0000_2000;
    localparam logic [31:0] GEMM_OUTPUT = 32'h0000_3000;
    localparam logic [31:0] CONV_COMMAND = 32'h0000_0000;
    localparam logic [31:0] CONV_INPUT = 32'h0000_1000;
    localparam logic [31:0] CONV_WEIGHT = 32'h0000_2000;
    localparam logic [31:0] CONV_OUTPUT = 32'h0000_3000;
    localparam logic [31:0] POOL_COMMAND = 32'h0000_0000;
    localparam logic [31:0] POOL_INPUT = 32'h0000_1000;
    localparam logic [31:0] POOL_OUTPUT = 32'h0000_2000;

    logic SYS_CLK;
    // axil_host.svh drives off `clk`, and the image's clock port is SYS_CLK.
    logic clk;
    assign clk = SYS_CLK;
    initial SYS_CLK = 0;
    always #10 SYS_CLK = ~SYS_CLK;

    wire [2:0] leds;
    `include "tests/axil_host.svh"

    ypcb_dual_endpoint_top dut (
        .SYS_CLK,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
        .conv_irq(), .pool_irq(), .gemm_irq(),
        .led_3bits_tri_o(leds)
    );

    // All host traffic is 32-bit, so the fixture images are word arrays.
    logic [31:0] conv_words [0:4095];
    logic [31:0] pool_words [0:4095];
    logic [31:0] expected_words [0:2047];
    string conv_dir, pool_dir, gemm_dir, conv_fp32_dir, conv_k5_dir,
           conv_c16_dir;
    integer mode, i, timeout_count;
    logic [31:0] value;

    task automatic load_words(input string dir, input string file_name,
                              input logic [31:0] base, input integer count);
        begin
            if (count <= 0) return;
            $readmemh({dir, "/", file_name}, conv_words);
            for (i = 0; i < count; i = i + 1)
                host_write(base + 32'(i) * 4, conv_words[i]);
        end
    endtask

    task automatic wait_completion(input integer which);
        begin
            timeout_count = 0;
            while (!(which == 0 ? dut.conv_irq :
                     which == 1 ? dut.pool_irq : dut.gemm_irq) &&
                   timeout_count < 400000) begin
                @(negedge SYS_CLK);
                timeout_count = timeout_count + 1;
            end
            if (timeout_count == 400000)
                $fatal(1, "endpoint %0d produced no completion", which);
        end
    endtask

    task automatic check_registers(input logic [31:0] page,
                                   input logic [31:0] tag);
        begin
            host_expect(page + 32'h1c, tag);
            host_expect(page + 32'h20, 32'd1);
            host_expect(page + 32'h24, 32'd0);
        end
    endtask

    task automatic read_and_compare(input logic [31:0] base,
                                    input string dir, input string file_name,
                                    input integer words,
                                    input real tolerance = 0.0);
        integer mismatched;
        real got_float, exp_float, diff_abs, worst_abs;
        begin
            $readmemh({dir, "/", file_name}, expected_words);
            mismatched = 0;
            worst_abs = 0.0;
            for (i = 0; i < words; i = i + 1) begin
                host_read(base + 32'(i) * 4, value);
                if (value !== expected_words[i]) begin
                    if (tolerance == 0.0)
                        $fatal(1, "output word %0d got=%08x expected=%08x",
                               i, value, expected_words[i]);
                    mismatched = mismatched + 1;
                    got_float = f32_to_real(value);
                    exp_float = f32_to_real(expected_words[i]);
                    if (got_float > exp_float) diff_abs = got_float - exp_float;
                    else diff_abs = exp_float - got_float;
                    if (diff_abs > worst_abs) worst_abs = diff_abs;
                end
            end
            if (mismatched != 0 && worst_abs > tolerance)
                $fatal(1, "output BO differs in %0d of %0d words; worst abs=%0.9f exceeds %0.9f",
                       mismatched, words, worst_abs, tolerance);
            if (mismatched != 0)
                $display("TOLERANCE YPCB_DUAL_ENDPOINT differing_words=%0d worst_abs=%0.9f limit=%0.9f",
                         mismatched, worst_abs, tolerance);
        end
    endtask

    function automatic real f32_to_real(input logic [31:0] word);
        real value;
        integer exponent, bit_index;
        real mantissa;
        begin
            if (word[30:23] == 8'd0)
                value = 0.0;
            else begin
                exponent = int'(word[30:23]) - 127;
                mantissa = 1.0;
                for (bit_index = 22; bit_index >= 0; bit_index = bit_index - 1)
                    if (word[bit_index])
                        mantissa = mantissa + (2.0 ** (bit_index - 23));
                value = mantissa * (2.0 ** exponent);
            end
            if (word[31]) value = -value;
            f32_to_real = value;
        end
    endfunction

    task automatic run_conv;
        begin
            load_words(conv_dir, "command_words.hex", CONV_COMMAND,
                       CONV_COMMAND_WORDS);
            load_words(conv_dir, "input_words.hex", CONV_INPUT,
                       CONV_INPUT_WORDS);
            load_words(conv_dir, "weight_words.hex", CONV_WEIGHT,
                       CONV_WEIGHT_WORDS);
            load_words(conv_dir, "output_init_words.hex", CONV_OUTPUT,
                       CONV_OUTPUT_WORDS);
            host_write(CONV_PAGE + 32'h10, CONV_COMMAND);
            host_write(CONV_PAGE + 32'h14, 32'd52);
            host_write(CONV_PAGE + 32'h18, 32'hc0de1001);
            host_write(CONV_PAGE + 32'h0c, 32'd1);
            wait_completion(0);
            check_registers(CONV_PAGE, 32'hc0de1001);
            read_and_compare(CONV_OUTPUT, conv_dir, "expected_words.hex",
                             CONV_OUTPUT_WORDS);
            host_write(CONV_PAGE + 32'h0c, 32'd2);
            if (dut.conv_irq) $fatal(1, "conv completion survived acknowledge");
        end
    endtask

    task automatic run_pool;
        begin
            load_words(pool_dir, "command_words.hex", POOL_COMMAND,
                       POOL_COMMAND_WORDS);
            load_words(pool_dir, "input_words.hex", POOL_INPUT,
                       POOL_INPUT_WORDS);
            load_words(pool_dir, "output_init_words.hex", POOL_OUTPUT,
                       POOL_OUTPUT_WORDS);
            host_write(POOL_PAGE + 32'h10, POOL_COMMAND);
            host_write(POOL_PAGE + 32'h14, 32'd26);
            host_write(POOL_PAGE + 32'h18, 32'hc0de2001);
            host_write(POOL_PAGE + 32'h0c, 32'd1);
            wait_completion(1);
            check_registers(POOL_PAGE, 32'hc0de2001);
            read_and_compare(POOL_OUTPUT, pool_dir, "expected_words.hex",
                             POOL_OUTPUT_WORDS);
            host_write(POOL_PAGE + 32'h0c, 32'd2);
            if (dut.pool_irq) $fatal(1, "pool completion survived acknowledge");
        end
    endtask

    task automatic run_conv_k5;
        begin
            load_words(conv_k5_dir, "command_words.hex", CONV_COMMAND,
                       CONV_K5_COMMAND_WORDS);
            load_words(conv_k5_dir, "input_words.hex", CONV_INPUT,
                       CONV_K5_INPUT_WORDS);
            load_words(conv_k5_dir, "weight_words.hex", CONV_WEIGHT,
                       CONV_K5_WEIGHT_WORDS);
            load_words(conv_k5_dir, "output_init_words.hex",
                       CONV_K5_OUTPUT_BASE, CONV_K5_OUTPUT_WORDS);
            host_write(CONV_K5_PAGE + 32'h10, CONV_COMMAND);
            host_write(CONV_K5_PAGE + 32'h14, 32'd52);
            host_write(CONV_K5_PAGE + 32'h18, 32'hc0de7001);
            host_write(CONV_K5_PAGE + 32'h0c, 32'd1);
            timeout_count = 0;
            while (dut.conv_k5_irq !== 1'b1 && timeout_count < 800000) begin
                @(negedge SYS_CLK);
                timeout_count = timeout_count + 1;
            end
            if (dut.conv_k5_irq !== 1'b1)
                $fatal(1, "k5 conv page produced no result");
            check_registers(CONV_K5_PAGE, 32'hc0de7001);
            read_and_compare(CONV_K5_OUTPUT_BASE, conv_k5_dir,
                             "expected_words.hex", CONV_K5_OUTPUT_WORDS, 0.0);
            host_write(CONV_K5_PAGE + 32'h0c, 32'd2);
            if (dut.conv_k5_irq)
                $fatal(1, "k5 conv completion survived acknowledge");
        end
    endtask

    task automatic run_conv_c16;
        begin
            load_words(conv_c16_dir, "command_words.hex", CONV_COMMAND,
                       CONV_C16_COMMAND_WORDS);
            load_words(conv_c16_dir, "input_words.hex", CONV_INPUT,
                       CONV_C16_INPUT_WORDS);
            load_words(conv_c16_dir, "weight_words.hex", CONV_WEIGHT,
                       CONV_C16_WEIGHT_WORDS);
            load_words(conv_c16_dir, "output_init_words.hex",
                       CONV_C16_OUTPUT_BASE, CONV_C16_OUTPUT_WORDS);
            host_write(CONV_C16_PAGE + 32'h10, CONV_COMMAND);
            host_write(CONV_C16_PAGE + 32'h14, 32'd52);
            host_write(CONV_C16_PAGE + 32'h18, 32'hc0de8001);
            host_write(CONV_C16_PAGE + 32'h0c, 32'd1);
            timeout_count = 0;
            while (dut.conv_c16_irq !== 1'b1 && timeout_count < 800000) begin
                @(negedge SYS_CLK);
                timeout_count = timeout_count + 1;
            end
            if (dut.conv_c16_irq !== 1'b1)
                $fatal(1, "C16 conv page produced no result");
            check_registers(CONV_C16_PAGE, 32'hc0de8001);
            read_and_compare(CONV_C16_OUTPUT_BASE, conv_c16_dir,
                             "expected_words.hex", CONV_C16_OUTPUT_WORDS, 0.0);
            host_write(CONV_C16_PAGE + 32'h0c, 32'd2);
            if (dut.conv_c16_irq)
                $fatal(1, "C16 conv completion survived acknowledge");
        end
    endtask

    task automatic run_conv_fp32;
        begin
            load_words(conv_fp32_dir, "command_words.hex", CONV_COMMAND,
                       CONV_FP32_COMMAND_WORDS);
            load_words(conv_fp32_dir, "input_words.hex", CONV_INPUT,
                       CONV_FP32_INPUT_WORDS);
            load_words(conv_fp32_dir, "weight_words.hex", CONV_WEIGHT,
                       CONV_FP32_WEIGHT_WORDS);
            load_words(conv_fp32_dir, "output_init_words.hex", CONV_OUTPUT,
                       CONV_FP32_OUTPUT_WORDS);
            host_write(CONV_FP32_PAGE + 32'h10, CONV_COMMAND);
            host_write(CONV_FP32_PAGE + 32'h14, 32'd52);
            host_write(CONV_FP32_PAGE + 32'h18, 32'hc0de6001);
            host_write(CONV_FP32_PAGE + 32'h0c, 32'd1);
            timeout_count = 0;
            while (dut.conv_fp32_irq !== 1'b1 && timeout_count < 800000) begin
                @(negedge SYS_CLK);
                timeout_count = timeout_count + 1;
                if (timeout_count % 200000 == 0)
                    $display("FP32WAIT %0d busy=%b ready=%b status=%08x code=%0d",
                             timeout_count, dut.conv_fp32_page.busy,
                             dut.conv_fp32_memory_ready,
                             dut.conv_fp32_page.status_word,
                             dut.conv_fp32_page.result_code);
            end
            if (dut.conv_fp32_irq !== 1'b1)
                $fatal(1, "FP32 conv page produced no result");
            check_registers(CONV_FP32_PAGE, 32'hc0de6001);
            read_and_compare(CONV_OUTPUT, conv_fp32_dir, "expected_words.hex",
                             CONV_FP32_OUTPUT_WORDS, 0.001);
            host_write(CONV_FP32_PAGE + 32'h0c, 32'd2);
            if (dut.conv_fp32_irq)
                $fatal(1, "FP32 conv completion survived acknowledge");
        end
    endtask

    task automatic run_gemm;
        begin
            load_words(gemm_dir, "command_words.hex", GEMM_COMMAND,
                       GEMM_COMMAND_WORDS);
            load_words(gemm_dir, "input_words.hex", GEMM_INPUT,
                       GEMM_INPUT_WORDS);
            load_words(gemm_dir, "weight_words.hex", GEMM_WEIGHT,
                       GEMM_WEIGHT_WORDS);
            load_words(gemm_dir, "output_init_words.hex", GEMM_OUTPUT,
                       GEMM_OUTPUT_WORDS);
            host_write(GEMM_PAGE + 32'h10, GEMM_COMMAND);
            host_write(GEMM_PAGE + 32'h14, 32'd45);
            host_write(GEMM_PAGE + 32'h18, 32'hc0de4001);
            host_write(GEMM_PAGE + 32'h0c, 32'd1);
            wait_completion(2);
            host_read(GEMM_PAGE + 32'h08, value);
            $display("GEMM status=%08x", value);
            host_read(GEMM_PAGE + 32'h24, value);
            $display("GEMM result_code=%0d", value);
            check_registers(GEMM_PAGE, 32'hc0de4001);
            read_and_compare(GEMM_OUTPUT, gemm_dir, "expected_words.hex",
                             GEMM_OUTPUT_WORDS, GEMM_TOLERANCE);
            host_write(GEMM_PAGE + 32'h0c, 32'd2);
            if (dut.gemm_irq) $fatal(1, "GEMM completion survived acknowledge");
        end
    endtask

    initial begin : TEST
        if (!$value$plusargs("MODE=%d", mode)) mode = MODE;
        if (!$value$plusargs("CONV_DIR=%s", conv_dir)) conv_dir = ".";
        if (!$value$plusargs("POOL_DIR=%s", pool_dir)) pool_dir = ".";
        if (!$value$plusargs("GEMM_DIR=%s", gemm_dir)) gemm_dir = ".";
        if (!$value$plusargs("CONV_FP32_DIR=%s", conv_fp32_dir))
            conv_fp32_dir = ".";
        if (!$value$plusargs("CONV_K5_DIR=%s", conv_k5_dir))
            conv_k5_dir = ".";
        if (!$value$plusargs("CONV_C16_DIR=%s", conv_c16_dir))
            conv_c16_dir = ".";

        // The image resets itself; wait for the release plus margin.
        repeat (64 + 16) @(negedge SYS_CLK);

        
        // Both pages always answer with their own identity.
        host_expect(CONV_PAGE + 32'h00, 32'h524b4353);
        
        host_expect(CONV_PAGE + 32'h04, 32'h0001_0000);
        host_expect(POOL_PAGE + 32'h00, 32'h524b5050);
        host_expect(POOL_PAGE + 32'h04, 32'h0001_0000);
        host_expect(GEMM_PAGE + 32'h00, 32'h524b434d);
        host_expect(GEMM_PAGE + 32'h04, 32'h0001_0000);
        host_expect(CONV_FP32_PAGE + 32'h00, 32'h524b4415);
        host_expect(CONV_FP32_PAGE + 32'h04, 32'h0001_0000);
        host_expect(CONV_K5_PAGE + 32'h00, 32'h524b4416);
        host_expect(CONV_K5_PAGE + 32'h04, 32'h0001_0000);
        host_expect(CONV_C16_PAGE + 32'h00, 32'h524b4417);
        host_expect(CONV_C16_PAGE + 32'h04, 32'h0001_0000);

        case (mode)
            0: begin
                // Register pages do not alias each other.
                host_write(CONV_PAGE + 32'h14, 32'd1234);
                host_expect(CONV_PAGE + 32'h14, 32'd1234);
                host_expect(POOL_PAGE + 32'h14, 32'd0);
                host_expect(GEMM_PAGE + 32'h14, 32'd0);
                host_write(POOL_PAGE + 32'h14, 32'd4321);
                host_expect(POOL_PAGE + 32'h14, 32'd4321);
                host_expect(CONV_PAGE + 32'h14, 32'd1234);
                host_expect(GEMM_PAGE + 32'h14, 32'd0);

                // Read-only registers reject writes on both pages.
                host_write(CONV_PAGE + 32'h00, 32'hdeadbeef, 2'b10);
                host_write(POOL_PAGE + 32'h00, 32'hdeadbeef, 2'b10);
                host_write(GEMM_PAGE + 32'h00, 32'hdeadbeef, 2'b10);
                host_write(CONV_FP32_PAGE + 32'h00, 32'hdeadbeef, 2'b10);
                host_expect(CONV_PAGE + 32'h00, 32'h524b4353);
                host_expect(POOL_PAGE + 32'h00, 32'h524b5050);
                host_expect(GEMM_PAGE + 32'h00, 32'h524b434d);
                host_expect(CONV_FP32_PAGE + 32'h00, 32'h524b4415);

                // An unmapped address is SLVERR, not an alias of anything.
                // 0xe000 is above the last real page now.
                host_read(32'h0000_e000, value, 2'b10);
                host_write(32'h0000_e000, 32'hdeadbeef, 2'b10);


                // Host memory window round-trips a word.
                host_write(32'h0000_0100, 32'hcafe1234);
                host_expect(32'h0000_0100, 32'hcafe1234);

                if (dut.conv_irq !== 1'b0 || dut.pool_irq !== 1'b0 ||
                    dut.gemm_irq !== 1'b0 || dut.conv_fp32_irq !== 1'b0)
                    $fatal(1, "completion line asserted with no job");
            end
            1: begin
                run_conv();
            end
            2: begin
                run_pool();
            end
            4: begin
                run_gemm();
            end
            6: begin
                run_conv_fp32();
            end
            7: begin
                run_conv_k5();
            end
            8: begin
                run_conv_c16();
            end
            5: begin
                // GEMM job: the other two pages and the host window must be
                // closed while it runs.
                load_words(gemm_dir, "command_words.hex", GEMM_COMMAND,
                           GEMM_COMMAND_WORDS);
                load_words(gemm_dir, "input_words.hex", GEMM_INPUT,
                           GEMM_INPUT_WORDS);
                load_words(gemm_dir, "weight_words.hex", GEMM_WEIGHT,
                           GEMM_WEIGHT_WORDS);
                load_words(gemm_dir, "output_init_words.hex", GEMM_OUTPUT,
                           GEMM_OUTPUT_WORDS);
                host_write(GEMM_PAGE + 32'h10, GEMM_COMMAND);
                host_write(GEMM_PAGE + 32'h14, 32'd45);
                host_write(GEMM_PAGE + 32'h18, 32'hc0de5001);
                host_write(GEMM_PAGE + 32'h0c, 32'd1);
                host_write(CONV_PAGE + 32'h10, CONV_COMMAND);
                host_write(CONV_PAGE + 32'h14, 32'd52);
                host_write(CONV_PAGE + 32'h18, 32'hc0de5002);
                @(negedge SYS_CLK);
                if (dut.gemm_page.busy) begin
                    host_read(CONV_PAGE + 32'h08, value);
                    if (value[0] !== 1'b0)
                        $fatal(1, "conv page accepted submit while GEMM runs");
                    if (dut.host_memory_enable !== 1'b0)
                        $fatal(1, "host memory window open during GEMM job");
                end else begin
                    $fatal(1, "GEMM job did not become busy");
                end
                wait_completion(2);
                check_registers(GEMM_PAGE, 32'hc0de5001);
                read_and_compare(GEMM_OUTPUT, gemm_dir, "expected_words.hex",
                                 GEMM_OUTPUT_WORDS, 0.001);
                host_write(GEMM_PAGE + 32'h0c, 32'd2);
            end
            3: begin
                // Start conv, then prove the pooling page and host window are
                // closed while it runs.
                load_words(conv_dir, "command_words.hex", CONV_COMMAND,
                           CONV_COMMAND_WORDS);
                load_words(conv_dir, "input_words.hex", CONV_INPUT,
                           CONV_INPUT_WORDS);
                load_words(conv_dir, "weight_words.hex", CONV_WEIGHT,
                           CONV_WEIGHT_WORDS);
                load_words(conv_dir, "output_init_words.hex", CONV_OUTPUT,
                           CONV_OUTPUT_WORDS);
                host_write(CONV_PAGE + 32'h10, CONV_COMMAND);
                host_write(CONV_PAGE + 32'h14, 32'd52);
                host_write(CONV_PAGE + 32'h18, 32'hc0de3001);
                host_write(CONV_PAGE + 32'h0c, 32'd1);
                host_write(POOL_PAGE + 32'h10, POOL_COMMAND);
                host_write(POOL_PAGE + 32'h14, 32'd26);
                host_write(POOL_PAGE + 32'h18, 32'hc0de3002);

                @(negedge SYS_CLK);
                if (dut.conv_page.busy) begin
                    host_read(POOL_PAGE + 32'h08, value);
                    // can_submit must be withdrawn: bit 0 clear.
                    if (value[0] !== 1'b0)
                        $fatal(1, "pooling page accepted submit while conv runs");
                    if (dut.host_memory_enable !== 1'b0)
                        $fatal(1, "host memory window open during conv job");
                    if (dut.mem_arready !== 1'b0 || dut.mem_awready !== 1'b0)
                        $fatal(1, "bridge claimed the port during a conv job");
                end else begin
                    $fatal(1, "conv job did not become busy");
                end

                wait_completion(0);
                check_registers(CONV_PAGE, 32'hc0de3001);
                read_and_compare(CONV_OUTPUT, conv_dir, "expected_words.hex",
                                 CONV_OUTPUT_WORDS);
                host_write(CONV_PAGE + 32'h0c, 32'd2);

                run_pool();
            end
            default: $fatal(1, "invalid MODE");
        endcase

        host_read(CONV_K5_PAGE + 32'h08, value);
        if (value[1] !== 1'b0 || value[2] !== 1'b0)
            $fatal(1, "k5 conv page not idle after ack: status=%08x", value);
        host_read(CONV_C16_PAGE + 32'h08, value);
        if (value[1] !== 1'b0 || value[2] !== 1'b0)
            $fatal(1, "C16 conv page not idle after ack: status=%08x", value);
        host_read(CONV_FP32_PAGE + 32'h08, value);
        if (value[1] !== 1'b0 || value[2] !== 1'b0)
            $fatal(1, "FP32 conv page not idle after ack: status=%08x", value);
        $display("STATUS conv_fp32=%08x", value);
        // STATUS bit 1 is active and bit 2 is result_valid. After a job is
        // acknowledged both must be 0; can_submit is 0 because ACK releases
        // the descriptor fields, which is the documented rk_job_control
        // behaviour rather than a stuck page.
        host_read(CONV_PAGE + 32'h08, value);
        if (value[1] !== 1'b0 || value[2] !== 1'b0)
            $fatal(1, "conv page not idle after ack: status=%08x", value);
        $display("STATUS conv=%08x", value);
        host_read(POOL_PAGE + 32'h08, value);
        if (value[1] !== 1'b0 || value[2] !== 1'b0)
            $fatal(1, "pool page not idle after ack: status=%08x", value);
        $display("STATUS pool=%08x", value);

        $display("PASS YPCB_DUAL_ENDPOINT mode=%0d conv_page=%08x pool_page=%08x",
                 mode, dut.conv_page.can_submit, dut.pool_page.can_submit);
        $finish;
    end

    initial begin
        #20000000;
        $fatal(1, "dual endpoint replay watchdog");
    end
endmodule
