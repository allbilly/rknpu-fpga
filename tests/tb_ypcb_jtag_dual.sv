// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Pin-free host path replay: USER2 JTAG mailbox frames drive the dual-endpoint
// AXI image, which runs the frozen conv and pooling jobs.
//
// The bench instantiates the same three RTL blocks the pin-free top wires
// together (mailbox -> JTAG/AXI adapter -> dual endpoint image) and talks to
// them only through 640-bit JTAG frames. It never pokes engine internals.
//
// Frame opcodes (frozen OpenTPU):
//   1 register read   2 register write   3 64-byte read   4 64-byte write
//
// Modes:
//  0  read both page identities, round-trip memory words, block round trip,
//     and confirm an unmapped access reports a downstream error
//  1  conv-simple job end to end: load 52-QWORD command + operands through
//     block writes, submit through the page, read back and compare the full
//     4096-byte output BO
//  2  pooling job end to end: same for the 26-QWORD signed-INT8 descriptor
//  3  FP32 GEMM job end to end: 49-QWORD body fetched, complete 4096-byte
//     output BO compared through the transport page
//  4  FP32 conv profile-3 job end to end on the second conv page at 0xb000
module tb_ypcb_jtag_dual #(
    parameter integer MODE = 0,
    parameter integer CONV_COMMAND_WORDS = 104,
    parameter integer CONV_INPUT_WORDS = 128,
    parameter integer CONV_WEIGHT_WORDS = 576,
    // Both cases compare the complete 4096-byte output BO. The conv capture
    // defines only 1152 bytes, so the expected image is that capture padded
    // with zeros: the comparison then also proves the engine wrote nowhere
    // outside its own window.
    parameter integer CONV_OUTPUT_WORDS = 1024,
    parameter integer POOL_COMMAND_WORDS = 52,
    parameter integer POOL_INPUT_WORDS = 1024,
    parameter integer POOL_OUTPUT_WORDS = 1024,
    parameter integer GEMM_COMMAND_WORDS = 0,
    parameter integer GEMM_INPUT_WORDS = 1024,
    parameter integer GEMM_WEIGHT_WORDS = 1024,
    parameter integer GEMM_OUTPUT_WORDS = 1024,
    // Absolute bound for the GEMM output compare. The k=1 capture has one
    // product per value and is byte-exact; deeper shapes are not.
    parameter real GEMM_TOLERANCE = 0.001,
    parameter integer CONV_FP32_COMMAND_WORDS = 104,
    parameter integer CONV_FP32_INPUT_WORDS = 256,
    parameter integer CONV_FP32_WEIGHT_WORDS = 128,
    parameter integer CONV_FP32_OUTPUT_WORDS = 1024,
    parameter integer CONV_K5_COMMAND_WORDS = 104,
    parameter integer CONV_K5_INPUT_WORDS = 128,
    parameter integer CONV_K5_WEIGHT_WORDS = 1600,
    parameter integer CONV_K5_OUTPUT_WORDS = 1024,
    parameter integer CONV_K5_OUTPUT_BASE = 32'h0000_4000,
    parameter integer CONV_C16_COMMAND_WORDS = 104,
    parameter integer CONV_C16_INPUT_WORDS = 512,
    parameter integer CONV_C16_WEIGHT_WORDS = 2304,
    parameter integer CONV_C16_OUTPUT_WORDS = 1024,
    parameter integer CONV_C16_OUTPUT_BASE = 32'h0000_5000
);
    localparam logic [31:0] CONV_PAGE = 32'h0000_8000;
    localparam logic [31:0] POOL_PAGE = 32'h0000_9000;
    localparam logic [31:0] CONV_COMMAND = 32'h0000_0000;
    localparam logic [31:0] CONV_INPUT = 32'h0000_1000;
    localparam logic [31:0] CONV_WEIGHT = 32'h0000_2000;
    localparam logic [31:0] CONV_OUTPUT = 32'h0000_3000;
    localparam logic [31:0] POOL_COMMAND = 32'h0000_0000;
    localparam logic [31:0] POOL_INPUT = 32'h0000_1000;
    localparam logic [31:0] POOL_OUTPUT = 32'h0000_2000;
    localparam logic [31:0] GEMM_PAGE = 32'h0000_a000;
    localparam logic [31:0] CONV_FP32_PAGE = 32'h0000_b000;
    localparam logic [31:0] CONV_K5_PAGE = 32'h0000_c000;
    localparam logic [31:0] CONV_C16_PAGE = 32'h0000_d000;
    localparam logic [31:0] GEMM_COMMAND = 32'h0000_0000;
    localparam logic [31:0] GEMM_INPUT = 32'h0000_1000;
    localparam logic [31:0] GEMM_WEIGHT = 32'h0000_2000;
    localparam logic [31:0] GEMM_OUTPUT = 32'h0000_3000;

    logic clk = 0;
    always #10 clk = ~clk;

    logic rst_n = 0;
    logic tck = 0, capture = 0, shift = 0, update = 0, sel = 0, tdi = 0;
    wire tdo;

    wire req_valid, req_ready, rsp_valid;
    wire [603:0] req;
    wire [511:0] rsp_data;
    wire [7:0] rsp_status;
    wire [15:0] rsp_seq;
    wire fault;

    wire [31:0] s_axil_awaddr, s_axil_wdata, s_axil_araddr, s_axil_rdata;
    wire [2:0] s_axil_awprot, s_axil_arprot;
    wire [3:0] s_axil_wstrb;
    wire [1:0] s_axil_bresp, s_axil_rresp;
    wire s_axil_awvalid, s_axil_awready, s_axil_wvalid, s_axil_wready;
    wire s_axil_bvalid, s_axil_bready, s_axil_arvalid, s_axil_arready;
    wire s_axil_rvalid, s_axil_rready;
    wire [2:0] leds;

    `include "tests/host/mailbox_scan.svh"

    otpu_jtag_mailbox mailbox (
        .clk, .rst(!rst_n), .tck, .capture, .shift, .update, .sel, .tdi, .tdo,
        .req_valid, .req_ready, .req,
        .rsp_valid, .rsp_data, .rsp_status, .rsp_seq
    );

    rk_jtag_axil_bridge #(.TIMEOUT_CYCLES(4096)) bridge (
        .clk, .rst_n,
        .req_valid, .req_ready, .req,
        .rsp_valid, .rsp_data, .rsp_status, .rsp_seq, .fault,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready
    );

    ypcb_dual_endpoint_top image (
        .SYS_CLK(clk),
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
        .led_3bits_tri_o(leds)
    );

    logic [15:0] sequence_q = 16'h0;
    integer mode, i, frames, loop;
    logic [31:0] value;
    logic [511:0] frame_data;
    // Sized for the largest staged BO: profile 2's 2304-word weight file.
    logic [31:0] conv_words [0:4095];
    logic [31:0] pool_words [0:2047];
    logic [31:0] expected_words [0:4095];
    string conv_dir, pool_dir, gemm_dir, conv_fp32_dir, conv_k5_dir,
           conv_c16_dir;

    // One mailbox frame, one transaction. Poll for the matching sequence.
    task automatic command(input logic [7:0] opcode, input logic [31:0] address,
                           input logic [511:0] data, input logic [3:0] strobes,
                           output logic [511:0] result,
                           input logic [7:0] status_expected = 0);
        logic [639:0] packet, received;
        integer polls;
        begin
            sequence_q = sequence_q + 1;
            packet = {36'b0, 32'h4f54504a, sequence_q, opcode, strobes,
                      address, data};
            scan_frame(packet, received);
            polls = 0;
            while ((received[567:536] != 32'h4f54504a ||
                    received[535:520] != sequence_q) && polls < 8) begin
                scan_frame(0, received);
                polls = polls + 1;
            end
            if (received[567:536] != 32'h4f54504a ||
                received[535:520] != sequence_q ||
                received[519:512] != status_expected)
                $fatal(1, "frame %0d op=%0d status=%02x expected=%02x",
                       sequence_q, opcode, received[519:512], status_expected);
            result = received[511:0];
            frames = frames + 1;
        end
    endtask

    task automatic write_block(input logic [31:0] address, input logic [511:0] data);
        logic [511:0] unused;
        command(8'd4, address, data, 4'hf, unused, 8'd0);
    endtask

    task automatic read_block(input logic [31:0] address, output logic [511:0] data);
        command(8'd3, address, 512'h0, 4'hf, data, 8'd0);
    endtask

    task automatic write_word(input logic [31:0] address, input logic [31:0] data);
        logic [511:0] unused;
        command(8'd2, address, {480'h0, data}, 4'hf, unused, 8'd0);
    endtask

    task automatic read_word(input logic [31:0] address, output logic [31:0] data);
        logic [511:0] value512;
        command(8'd1, address, 512'h0, 4'hf, value512, 8'd0);
        data = value512[31:0];
    endtask

    // Load a word array through 64-byte block writes.
    task automatic load_words(input string dir, input string file_name,
                              input logic [31:0] base, input integer words);
        integer block, word;
        logic [511:0] payload;
        begin
            if (words <= 0) return;
            $readmemh({dir, "/", file_name}, conv_words);
            for (block = 0; block < (words + 15) / 16; block = block + 1) begin
                payload = '0;
                for (word = 0; word < 16; word = word + 1)
                    if (block * 16 + word < words)
                        payload[word*32 +: 32] = conv_words[block*16 + word];
                write_block(base + 32'(block) * 64, payload);
            end
        end
    endtask

    // `tolerance == 0` demands byte equality. The FP32 conv capture's oracle is
    // float64 rounded to float32, so its 63 last-bit differences need an
    // explicit absolute bound instead.
    task automatic compare_words(input logic [31:0] base, input string dir,
                                 input integer words,
                                 input real tolerance = 0.0);
        integer block, word, mismatched;
        logic [511:0] payload;
        real got_float, exp_float, diff_abs, worst_abs;
        begin
            $readmemh({dir, "/expected_words.hex"}, expected_words);
            mismatched = 0;
            worst_abs = 0.0;
            for (block = 0; block < words / 16; block = block + 1) begin
                read_block(base + 32'(block) * 64, payload);
                for (word = 0; word < 16; word = word + 1)
                    if (payload[word*32 +: 32] !==
                        expected_words[block*16 + word]) begin
                        if (tolerance == 0.0)
                            $fatal(1, "output word %0d got=%08x expected=%08x",
                                   block*16 + word, payload[word*32 +: 32],
                                   expected_words[block*16 + word]);
                        mismatched = mismatched + 1;
                        got_float = f32_to_real(payload[word*32 +: 32]);
                        exp_float = f32_to_real(expected_words[block*16 + word]);
                        if (got_float > exp_float)
                            diff_abs = got_float - exp_float;
                        else
                            diff_abs = exp_float - got_float;
                        if (diff_abs > worst_abs) worst_abs = diff_abs;
                    end
            end
            if (mismatched != 0 && worst_abs > tolerance)
                $fatal(1, "output BO differs in %0d of %0d words; worst abs=%0.9f exceeds %0.9f",
                       mismatched, words, worst_abs, tolerance);
            if (mismatched != 0)
                $display("TOLERANCE YPCB_JTAG_DUAL differing_words=%0d worst_abs=%0.9f limit=%0.9f",
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

    task automatic check_page(input logic [31:0] page, input logic [31:0] id);
        begin
            read_word(page + 32'h00, value);
            if (value !== id) $fatal(1, "identity at %08x is %08x", page, value);
            read_word(page + 32'h04, value);
            if (value !== 32'h0001_0000) $fatal(1, "ABI version at %08x", page);
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
        frames = 0;

        repeat (8) @(negedge clk);
        rst_n = 1;
        repeat (80) @(negedge clk);

        check_page(CONV_PAGE, 32'h524b4353);
        check_page(POOL_PAGE, 32'h524b5050);
        check_page(GEMM_PAGE, 32'h524b434d);
        check_page(CONV_FP32_PAGE, 32'h524b4415);
        check_page(CONV_K5_PAGE, 32'h524b4416);
        check_page(CONV_C16_PAGE, 32'h524b4417);

        case (mode)
            5: begin
                load_words(conv_k5_dir, "command_words.hex", CONV_COMMAND,
                           CONV_K5_COMMAND_WORDS);
                load_words(conv_k5_dir, "input_words.hex", CONV_INPUT,
                           CONV_K5_INPUT_WORDS);
                load_words(conv_k5_dir, "weight_words.hex", CONV_WEIGHT,
                           CONV_K5_WEIGHT_WORDS);
                load_words(conv_k5_dir, "output_init_words.hex",
                           CONV_K5_OUTPUT_BASE, CONV_K5_OUTPUT_WORDS);
                write_word(CONV_K5_PAGE + 32'h10, CONV_COMMAND);
                write_word(CONV_K5_PAGE + 32'h14, 32'd52);
                write_word(CONV_K5_PAGE + 32'h18, 32'hc0de7001);
                write_word(CONV_K5_PAGE + 32'h0c, 32'd1);
                i = 0;
                while (image.conv_k5_irq !== 1'b1 && i < 1_500_000) begin
                    @(negedge clk);
                    i = i + 1;
                end
                if (image.conv_k5_irq !== 1'b1)
                    $fatal(1, "k5 conv page produced no result");
                read_word(CONV_K5_PAGE + 32'h1c, value);
                if (value !== 32'hc0de7001) $fatal(1, "k5 result tag %08x", value);
                read_word(CONV_K5_PAGE + 32'h20, value);
                if (value !== 32'd1) $fatal(1, "k5 result tasks %0d", value);
                read_word(CONV_K5_PAGE + 32'h24, value);
                if (value !== 32'd0) $fatal(1, "k5 result code %0d", value);
                compare_words(CONV_K5_OUTPUT_BASE, conv_k5_dir,
                              CONV_K5_OUTPUT_WORDS);
                write_word(CONV_K5_PAGE + 32'h0c, 32'd2);
                if (image.conv_k5_irq)
                    $fatal(1, "k5 conv completion survived acknowledge");
            end
            6: begin
                load_words(conv_c16_dir, "command_words.hex", CONV_COMMAND,
                           CONV_C16_COMMAND_WORDS);
                load_words(conv_c16_dir, "input_words.hex", CONV_INPUT,
                           CONV_C16_INPUT_WORDS);
                load_words(conv_c16_dir, "weight_words.hex", CONV_WEIGHT,
                           CONV_C16_WEIGHT_WORDS);
                load_words(conv_c16_dir, "output_init_words.hex",
                           CONV_C16_OUTPUT_BASE, CONV_C16_OUTPUT_WORDS);
                write_word(CONV_C16_PAGE + 32'h10, CONV_COMMAND);
                write_word(CONV_C16_PAGE + 32'h14, 32'd52);
                write_word(CONV_C16_PAGE + 32'h18, 32'hc0de8001);
                write_word(CONV_C16_PAGE + 32'h0c, 32'd1);
                i = 0;
                while (image.conv_c16_irq !== 1'b1 && i < 1_500_000) begin
                    @(negedge clk);
                    i = i + 1;
                end
                if (image.conv_c16_irq !== 1'b1)
                    $fatal(1, "C16 conv page produced no result");
                read_word(CONV_C16_PAGE + 32'h1c, value);
                if (value !== 32'hc0de8001) $fatal(1, "C16 result tag %08x", value);
                read_word(CONV_C16_PAGE + 32'h20, value);
                if (value !== 32'd1) $fatal(1, "C16 result tasks %0d", value);
                read_word(CONV_C16_PAGE + 32'h24, value);
                if (value !== 32'd0) $fatal(1, "C16 result code %0d", value);
                compare_words(CONV_C16_OUTPUT_BASE, conv_c16_dir,
                              CONV_C16_OUTPUT_WORDS);
                write_word(CONV_C16_PAGE + 32'h0c, 32'd2);
                if (image.conv_c16_irq)
                    $fatal(1, "C16 conv completion survived acknowledge");
            end
            4: begin
                load_words(conv_fp32_dir, "command_words.hex", CONV_COMMAND,
                           CONV_FP32_COMMAND_WORDS);
                load_words(conv_fp32_dir, "input_words.hex", CONV_INPUT,
                           CONV_FP32_INPUT_WORDS);
                load_words(conv_fp32_dir, "weight_words.hex", CONV_WEIGHT,
                           CONV_FP32_WEIGHT_WORDS);
                load_words(conv_fp32_dir, "output_init_words.hex", CONV_OUTPUT,
                           CONV_FP32_OUTPUT_WORDS);
                write_word(CONV_FP32_PAGE + 32'h10, CONV_COMMAND);
                write_word(CONV_FP32_PAGE + 32'h14, 32'd52);
                write_word(CONV_FP32_PAGE + 32'h18, 32'hc0de6001);
                write_word(CONV_FP32_PAGE + 32'h0c, 32'd1);
                i = 0;
                while (image.conv_fp32_irq !== 1'b1 && i < 1_500_000) begin
                    @(negedge clk);
                    i = i + 1;
                end
                if (image.conv_fp32_irq !== 1'b1)
                    $fatal(1, "FP32 conv page produced no result");
                read_word(CONV_FP32_PAGE + 32'h1c, value);
                if (value !== 32'hc0de6001)
                    $fatal(1, "conv fp32 result tag %08x", value);
                read_word(CONV_FP32_PAGE + 32'h20, value);
                if (value !== 32'd1)
                    $fatal(1, "conv fp32 result tasks %0d", value);
                read_word(CONV_FP32_PAGE + 32'h24, value);
                if (value !== 32'd0)
                    $fatal(1, "conv fp32 result code %0d", value);
                compare_words(CONV_OUTPUT, conv_fp32_dir, CONV_FP32_OUTPUT_WORDS,
                              0.001);
                write_word(CONV_FP32_PAGE + 32'h0c, 32'd2);
                if (image.conv_fp32_irq)
                    $fatal(1, "FP32 conv completion survived acknowledge");
            end
            3: begin
                load_words(gemm_dir, "command_words.hex", GEMM_COMMAND,
                           GEMM_COMMAND_WORDS);
                load_words(gemm_dir, "input_words.hex", GEMM_INPUT,
                           GEMM_INPUT_WORDS);
                load_words(gemm_dir, "weight_words.hex", GEMM_WEIGHT,
                           GEMM_WEIGHT_WORDS);
                load_words(gemm_dir, "output_init_words.hex", GEMM_OUTPUT,
                           GEMM_OUTPUT_WORDS);
                // Memory withheld: the descriptor completes but submit is
                // refused, exactly as the other pages behave.
                write_word(GEMM_PAGE + 32'h10, GEMM_COMMAND);
                write_word(GEMM_PAGE + 32'h14, 32'd45);
                write_word(GEMM_PAGE + 32'h18, 32'hc0de4003);
                // The image's memory_ready depends on the other engines being
                // idle, so wait for can_submit rather than assume it.
                i = 0;
                loop = 0;
                while (i < 50 && loop < 200) begin
                    read_word(GEMM_PAGE + 32'h08, value);
                    if (value[0] === 1'b1) i = 50;
                    loop = loop + 1;
                end
                if (i < 50) $fatal(1, "GEMM page never reported can_submit");
                write_word(GEMM_PAGE + 32'h0c, 32'd1);
                i = 0;
                while (image.gemm_irq !== 1'b1 && i < 1_500_000) begin
                    @(negedge clk);
                    i = i + 1;
                end
                if (image.gemm_irq !== 1'b1) $fatal(1, "GEMM produced no result");
                read_word(GEMM_PAGE + 32'h1c, value);
                if (value !== 32'hc0de4003) $fatal(1, "GEMM result tag %08x", value);
                read_word(GEMM_PAGE + 32'h20, value);
                if (value !== 32'd1) $fatal(1, "GEMM result tasks %0d", value);
                read_word(GEMM_PAGE + 32'h24, value);
                if (value !== 32'd0) $fatal(1, "GEMM result code %0d", value);
                compare_words(GEMM_OUTPUT, gemm_dir, GEMM_OUTPUT_WORDS,
                              GEMM_TOLERANCE);
                write_word(GEMM_PAGE + 32'h0c, 32'd2);
            end
            0: begin
                // Memory window round trip, word and block.
                write_word(32'h0000_0100, 32'hcafe_1234);
                read_word(32'h0000_0100, value);
                if (value !== 32'hcafe_1234) $fatal(1, "word round trip");

                frame_data = '0;
                for (i = 0; i < 16; i = i + 1)
                    frame_data[i*32 +: 32] = 32'ha5a5_0000 + 32'(i);
                write_block(32'h0000_0140, frame_data);
                read_block(32'h0000_0140, frame_data);
                for (i = 0; i < 16; i = i + 1)
                    if (frame_data[i*32 +: 32] !== 32'ha5a5_0000 + 32'(i))
                        $fatal(1, "block round trip word %0d", i);

                // Misaligned block address must be refused, not silently fixed.
                command(8'd3, 32'h0000_0122, 512'h0, 4'hf, frame_data, 8'd4);
                // Unmapped page reports a downstream error and quarantines.
                command(8'd1, 32'h0000_e000, 512'h0, 4'hf, frame_data, 8'd7);
                if (!fault) $fatal(1, "downstream error did not quarantine");
            end
            1: begin
                load_words(conv_dir, "command_words.hex", CONV_COMMAND,
                           CONV_COMMAND_WORDS);
                load_words(conv_dir, "input_words.hex", CONV_INPUT,
                           CONV_INPUT_WORDS);
                load_words(conv_dir, "weight_words.hex", CONV_WEIGHT,
                           CONV_WEIGHT_WORDS);
                load_words(conv_dir, "output_init_words.hex", CONV_OUTPUT,
                           CONV_OUTPUT_WORDS);
                write_word(CONV_PAGE + 32'h10, CONV_COMMAND);
                write_word(CONV_PAGE + 32'h14, 32'd52);
                write_word(CONV_PAGE + 32'h18, 32'hc0de4001);
                write_word(CONV_PAGE + 32'h0c, 32'd1);
                i = 0;
                while (image.conv_irq !== 1'b1 && i < 600_000) begin
                    @(negedge clk);
                    i = i + 1;
                end
                if (image.conv_irq !== 1'b1) $fatal(1, "conv produced no result");
                read_word(CONV_PAGE + 32'h1c, value);
                if (value !== 32'hc0de4001) $fatal(1, "conv result tag %08x", value);
                read_word(CONV_PAGE + 32'h20, value);
                if (value !== 32'd1) $fatal(1, "conv result tasks %0d", value);
                read_word(CONV_PAGE + 32'h24, value);
                if (value !== 32'd0) $fatal(1, "conv result code %0d", value);
                compare_words(CONV_OUTPUT, conv_dir, CONV_OUTPUT_WORDS);
                write_word(CONV_PAGE + 32'h0c, 32'd2);
            end
            2: begin
                load_words(pool_dir, "command_words.hex", POOL_COMMAND,
                           POOL_COMMAND_WORDS);
                load_words(pool_dir, "input_words.hex", POOL_INPUT,
                           POOL_INPUT_WORDS);
                load_words(pool_dir, "output_init_words.hex", POOL_OUTPUT,
                           POOL_OUTPUT_WORDS);
                write_word(POOL_PAGE + 32'h10, POOL_COMMAND);
                write_word(POOL_PAGE + 32'h14, 32'd26);
                write_word(POOL_PAGE + 32'h18, 32'hc0de4002);
                write_word(POOL_PAGE + 32'h0c, 32'd1);
                i = 0;
                while (image.pool_irq !== 1'b1 && i < 600_000) begin
                    @(negedge clk);
                    i = i + 1;
                end
                if (image.pool_irq !== 1'b1) $fatal(1, "pooling produced no result");
                read_word(POOL_PAGE + 32'h1c, value);
                if (value !== 32'hc0de4002) $fatal(1, "pool result tag %08x", value);
                read_word(POOL_PAGE + 32'h20, value);
                if (value !== 32'd1) $fatal(1, "pool result tasks %0d", value);
                read_word(POOL_PAGE + 32'h24, value);
                if (value !== 32'd0) $fatal(1, "pool result code %0d", value);
                compare_words(POOL_OUTPUT, pool_dir, POOL_OUTPUT_WORDS);
                write_word(POOL_PAGE + 32'h0c, 32'd2);
            end
            default: $fatal(1, "invalid MODE");
        endcase

        $display("PASS YPCB_JTAG_DUAL mode=%0d frames=%0d", mode, frames);
        $finish;
    end

    initial begin
        #600000000;
        $fatal(1, "JTAG dual replay watchdog");
    end
endmodule
