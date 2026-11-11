// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// FP32 conv-simple replay: the frozen `conv_simple_fp16_1x1_c4_h8_w8_oc16`
// capture through the real conv datapath and the NCHW FP32 output stage.
//
// This is the last conv-simple fixture that had no execution path at all: its
// device output is FP32, so every halfword writer in the repository would have
// produced the wrong bytes.
module tb_conv_simple_fp32 #(
    parameter integer PROFILE = 3,
    parameter integer OUTPUT_FP16 = 0,
    parameter integer INPUT_H = 8,
    parameter integer INPUT_W = 8,
    parameter integer KH = 1,
    parameter integer KW = 1,
    parameter integer INPUT_CHANNELS = 4,
    parameter integer KERNELS = 8,
    parameter integer C1_BLOCKS = 2,
    parameter integer ALIGN_C = 8,
    parameter integer PACK_C2 = 4,
    parameter integer CHUNK_LANES = 16,
    parameter integer WORDS = 52,
    parameter integer INPUT_BASE = 32'h0000_1000,
    parameter integer WEIGHT_BASE = 32'h0000_2000,
    parameter integer OUTPUT_BASE = 32'h0000_3000,
    parameter integer INPUT_HALFWORDS = 256,
    parameter integer WEIGHT_HALFWORDS = 128,
    parameter integer OUTPUT_BYTES = 4096,
    // Absolute tolerance for RTL-vs-device agreement. The device DPU and this
    // RTL's NVDLA CACC accumulate in different orders, so a small bound is
    // required; the measured worst case is printed on every run.
    parameter real TOLERANCE_ABS = 0.0
);
    localparam integer MEM_BYTES = 16384;
    localparam integer OUTPUT_H = INPUT_H - KH + 1;
    localparam integer OUTPUT_W = INPUT_W - KW + 1;

    logic clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0, start_valid = 0, start_ready;
    logic [31:0] start_address = 0, start_amount = WORDS;
    wire busy, done, error;
    wire [7:0] error_code;
    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready, mem_rsp_valid, mem_rsp_error;
    logic [15:0] mem_rsp_rdata;

    logic [7:0] memory [0:MEM_BYTES-1];
    logic [31:0] command_words [0:WORDS*2-1];
    logic [15:0] input_words [0:INPUT_HALFWORDS-1];
    logic [15:0] weight_words [0:WEIGHT_HALFWORDS-1];
    logic [31:0] expected [0:OUTPUT_BYTES/4-1];

    logic pending;
    logic [31:0] pending_address;
    logic pending_write;
    logic [15:0] pending_data;
    logic pending_error;
    integer reads, writes;
    integer i, guard, mismatched;
    logic [31:0] got_word, exp_word;
    real got_float, exp_float, diff_abs, worst_abs;
    string dump_path;
    integer fd;
    string fixture;

    assign mem_req_ready = rst_n && !pending && !mem_rsp_valid;

    function automatic logic in_window(input logic [31:0] address,
                                       input integer base,
                                       input integer bytes);
        in_window = (address >= base) && (address < base + bytes);
    endfunction

    function automatic logic [15:0] read_halfword(input logic [31:0] address);
        integer index;
        begin
            read_halfword = 16'hxxxx;
            if (in_window(address, 0, WORDS*8) && !address[0]) begin
                index = address >> 1;
                read_halfword = {memory[2*index + 1], memory[2*index]};
            end else if (in_window(address, INPUT_BASE, INPUT_HALFWORDS*2) &&
                         !address[0]) begin
                read_halfword = input_words[(address - INPUT_BASE) >> 1];
            end else if (in_window(address, WEIGHT_BASE, WEIGHT_HALFWORDS*2) &&
                         !address[0]) begin
                read_halfword = weight_words[(address - WEIGHT_BASE) >> 1];
            end
        end
    endfunction

    function automatic logic write_ok(input logic [31:0] address);
        write_ok = !address[0] && in_window(address, OUTPUT_BASE, OUTPUT_BYTES);
    endfunction

    function automatic logic read_ok(input logic [31:0] address);
        read_ok = !address[0] &&
                  (in_window(address, 0, WORDS*8) ||
                   in_window(address, INPUT_BASE, INPUT_HALFWORDS*2) ||
                   in_window(address, WEIGHT_BASE, WEIGHT_HALFWORDS*2));
    endfunction

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pending <= 1'b0;
            pending_address <= 32'd0;
            pending_write <= 1'b0;
            pending_data <= 16'd0;
            pending_error <= 1'b0;
            mem_rsp_valid <= 1'b0;
            mem_rsp_error <= 1'b0;
            mem_rsp_rdata <= 16'd0;
            reads <= 0;
            writes <= 0;
        end else begin
            if (mem_req_valid && mem_req_ready) begin
                pending <= 1'b1;
                pending_address <= mem_req_addr;
                pending_write <= mem_req_write;
                if (mem_req_write) begin
                    pending_error <= !write_ok(mem_req_addr);
                    if (write_ok(mem_req_addr)) begin
                        memory[mem_req_addr] <= mem_req_wdata[7:0];
                        memory[mem_req_addr + 1] <= mem_req_wdata[15:8];
                        writes <= writes + 1;
                    end
                end else begin
                    pending_error <= !read_ok(mem_req_addr);
                    pending_data <= read_halfword(mem_req_addr);
                    reads <= reads + 1;
                end
            end
            if (pending && !mem_rsp_valid) begin
                pending <= 1'b0;
                mem_rsp_valid <= 1'b1;
                mem_rsp_rdata <= pending_data;
                mem_rsp_error <= pending_error;
            end
            if (mem_rsp_valid && mem_rsp_ready) begin
                if (mem_rsp_error)
                    $display("ERR t=%0t addr=%h write=%b", $time,
                             pending_address, pending_write);
                mem_rsp_valid <= 1'b0;
                mem_rsp_error <= 1'b0;
            end
        end
    end

    rk_conv_simple_dma #(
        .PROFILE(PROFILE), .TIMEOUT_CYCLES(65536),
        .INPUT_H(INPUT_H), .INPUT_W(INPUT_W), .KH(KH), .KW(KW),
        .INPUT_CHANNELS(INPUT_CHANNELS), .KERNELS(KERNELS),
        .C1_BLOCKS(C1_BLOCKS), .ALIGN_C(ALIGN_C), .PACK_C2(PACK_C2),
        .CHUNK_LANES(CHUNK_LANES), .OUTPUT_FP16(OUTPUT_FP16),
        .BASE(32'h0000_0000), .BYTES(33'(MEM_BYTES))
    ) dut (
        .clk, .rst_n,
        .start_valid, .start_ready, .start_address, .start_amount,
        .busy, .done, .error, .error_code,
        .result_ready(1'b1),
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata,
        .mem_rsp_error
    );

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

    task automatic load_fixture;
        begin
            if (!$value$plusargs("FIXTURE=%s", fixture))
                $fatal(1, "missing FIXTURE argument");
            for (i = 0; i < MEM_BYTES; i = i + 1) memory[i] = 8'd0;
            $readmemh({fixture, "/command.hex"}, command_words);
            for (i = 0; i < WORDS*2; i = i + 1) begin
                memory[4*i] = command_words[i][7:0];
                memory[4*i + 1] = command_words[i][15:8];
                memory[4*i + 2] = command_words[i][23:16];
                memory[4*i + 3] = command_words[i][31:24];
            end
            $readmemh({fixture, "/input.hex"}, input_words);
            for (i = 0; i < INPUT_HALFWORDS; i = i + 1) begin
                memory[INPUT_BASE + 2*i] = input_words[i][7:0];
                memory[INPUT_BASE + 2*i + 1] = input_words[i][15:8];
            end
            $readmemh({fixture, "/weight.hex"}, weight_words);
            for (i = 0; i < WEIGHT_HALFWORDS; i = i + 1) begin
                memory[WEIGHT_BASE + 2*i] = weight_words[i][7:0];
                memory[WEIGHT_BASE + 2*i + 1] = weight_words[i][15:8];
            end
            $readmemh({fixture, "/expected.hex"}, expected);
        end
    endtask

    initial begin : TEST
        load_fixture();
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);
        if (!start_ready) $fatal(1, "conv DMA never became ready");

        @(negedge clk);
        start_valid = 1;
        @(negedge clk);
        start_valid = 0;

        guard = 0;
        while (!(done || error) && guard < 4_000_000) begin
            @(negedge clk);
            guard = guard + 1;
        end
        if (error) $fatal(1, "conv job faulted with code %0d after %0d cycles",
                          error_code, guard);
        if (guard == 4_000_000) $fatal(1, "conv job produced no completion");
        repeat (4) @(negedge clk);

        if ($value$plusargs("DUMP=%s", dump_path)) begin
            fd = $fopen(dump_path, "w");
            for (i = 0; i < OUTPUT_BYTES/4; i = i + 1)
                $fdisplay(fd, "%08x", {memory[OUTPUT_BASE + 4*i + 3],
                                       memory[OUTPUT_BASE + 4*i + 2],
                                       memory[OUTPUT_BASE + 4*i + 1],
                                       memory[OUTPUT_BASE + 4*i]});
            $fclose(fd);
        end
        // Complete 4096-byte output BO comparison.
        mismatched = 0;
        worst_abs = 0.0;
        for (i = 0; i < OUTPUT_BYTES/4; i = i + 1) begin
            got_word = {memory[OUTPUT_BASE + 4*i + 3],
                        memory[OUTPUT_BASE + 4*i + 2],
                        memory[OUTPUT_BASE + 4*i + 1],
                        memory[OUTPUT_BASE + 4*i]};
            exp_word = expected[i];
            if (got_word !== exp_word) begin
                mismatched = mismatched + 1;
                // Explicit FP32 decode: $bitstoshortreal does not take a 32-bit word.
                got_float = f32_to_real(got_word);
                                exp_float = f32_to_real(exp_word);
                if (got_float > exp_float) diff_abs = got_float - exp_float;
                else diff_abs = exp_float - got_float;
                if (diff_abs > worst_abs) worst_abs = diff_abs;
                if (mismatched <= 4)
                    $display("MISMATCH word %0d got=%08x expected=%08x",
                             i, got_word, exp_word);
            end
        end
        if (mismatched != 0 && worst_abs > TOLERANCE_ABS)
            $fatal(1, "output BO differs in %0d of %0d words; worst abs=%0.9f exceeds limit %0.9f",
                   mismatched, OUTPUT_BYTES/4, worst_abs, TOLERANCE_ABS);
        // Two halfwords per captured value: one per output element.
        if (writes !== 2 * OUTPUT_BYTES / 4)
            $fatal(1, "wrote %0d halfwords, expected %0d",
                   writes, 2 * OUTPUT_BYTES / 4);

        $display("PASS CONV_SIMPLE_FP32 profile=%0d bo_bytes=%0d writes=%0d differing_words=%0d worst_abs=%0.9f tolerance=%0.9f",
                 PROFILE, OUTPUT_BYTES, writes, mismatched, worst_abs, TOLERANCE_ABS);
        $finish;
    end

    initial begin
        #40_000_000;
        $fatal(1, "FP32 conv-simple replay watchdog");
    end
endmodule
