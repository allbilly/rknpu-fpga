// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// FP32 GEMM replay of a frozen `conv-gemm-vendor` capture.
//
// This is the first bench where a raw GEMM command stream runs through real
// arithmetic and lands in an FP32 output BO:
//
//   raw 50-QWORD stream -> rk_cmac_nvdla_dma (OUTPUT_FP16=0)
//        -> rk_cmac_profile      (FP32 output register values)
//        -> rk_cmac_operand_front / reader
//        -> rk_nvdla_cmac_pipe   (CMAC groups, CACC accumulation)
//        -> rk_cmac_output_fp32  (no conversion, two halfwords per value)
//
// The command stream bytes are the capture's, with the three value32 fields
// relocated to the captured buffer bases by the runner. Nothing else is
// rewritten: no field is interpreted or repaired here.
//
// The memory model has explicit windows, so an access outside them is an error
// response and an out-of-window write is rejected — never silently absorbed.
// The comparison covers the complete 4096-byte output BO.
module tb_cmac_gemm_fp32 #(
    parameter integer START_ADDRESS = 0,
    parameter integer AMOUNT = 45,
    parameter integer ROWS = 2,
    parameter integer AI = 32,
    parameter integer AO = 32,
    parameter integer INPUT_BASE = 32'h0000_1000,
    parameter integer WEIGHT_BASE = 32'h0000_2000,
    parameter integer OUTPUT_BASE = 32'h0000_3000,
    parameter integer INPUT_HALFWORDS = 2048,
    parameter integer WEIGHT_HALFWORDS = 2048,
    parameter integer OUTPUT_BYTES = 4096,
    // Absolute tolerance for RTL-vs-device agreement. 0.0 demands byte-exact
    // output, which is only achievable when the shape has a single product per
    // output value (k=1). For deeper shapes the RTL's NVDLA CACC and the device
    // DPU round differently in the accumulator, so the family's declared
    // tolerance applies. The measured worst case is printed either way.
    parameter real TOLERANCE_ABS = 0.0
);
    localparam integer COMMAND_BYTES = 392;
    localparam integer MAX_HALFWORDS = 2048;

    logic clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0, start_valid = 0, start_ready;
    logic [31:0] start_address = START_ADDRESS, start_amount = AMOUNT;
    wire busy, address_done, operand_done, acknowledged, done, error;
    wire [7:0] error_code;
    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready, mem_rsp_valid, mem_rsp_error;
    logic [15:0] mem_rsp_rdata;

    logic [7:0] command_bytes [0:COMMAND_BYTES-1];
    logic [15:0] input_words [0:MAX_HALFWORDS-1];
    logic [15:0] weight_words [0:MAX_HALFWORDS-1];
    logic [7:0] output_mem [0:OUTPUT_BYTES-1];
    logic [7:0] expected [0:OUTPUT_BYTES-1];

    logic pending;
    logic [31:0] pending_address;
    logic pending_write;
    logic [15:0] pending_data;
    logic pending_error;
    integer reads, writes;
    integer i, guard, mismatched;
    logic [31:0] got_word, exp_word, word_gap, max_ulp;
    real got_float, exp_float, diff_abs, worst_abs;
    string fixture, dump_path;

    assign mem_req_ready = rst_n && !pending && !mem_rsp_valid;

    function automatic integer in_window(input logic [31:0] address,
                                         input integer base,
                                         input integer bytes);
        in_window = (address >= base) && (address < base + bytes);
    endfunction

    // Decode a 32-bit IEEE-754 word into a `real`. `$bitstoreal` expects 64
    // bits, so it would mis-decode a 32-bit value; this is explicit instead.
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
                // Icarus rejects a for-loop declaration inside a function,
                // so the index is declared in the function body.
                for (bit_index = 22; bit_index >= 0; bit_index = bit_index - 1)
                    if (word[bit_index])
                        mantissa = mantissa + (2.0 ** (bit_index - 23));
                value = mantissa * (2.0 ** exponent);
            end
            if (word[31]) value = -value;
            f32_to_real = value;
        end
    endfunction

    function automatic logic [15:0] read_halfword(input logic [31:0] address);
        integer index;
        begin
            read_halfword = 16'hxxxx;
            if (in_window(address, START_ADDRESS, COMMAND_BYTES) && !address[0]) begin
                index = (address - START_ADDRESS) >> 1;
                read_halfword = {command_bytes[2*index + 1], command_bytes[2*index]};
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
                  (in_window(address, START_ADDRESS, COMMAND_BYTES) ||
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
                        output_mem[mem_req_addr - OUTPUT_BASE] <= mem_req_wdata[7:0];
                        output_mem[mem_req_addr - OUTPUT_BASE + 1] <= mem_req_wdata[15:8];
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

    rk_cmac_nvdla_dma #(.TIMEOUT_CYCLES(65536), .OUTPUT_FP16(1'b0)) dut (
        .clk, .rst_n, .start_valid, .start_ready, .start_address, .start_amount,
        .busy, .done, .acknowledged, .address_done, .operand_done,
        .error, .error_code,
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata,
        .mem_rsp_error
    );

    task automatic load_fixture;
        begin
            if (!$value$plusargs("FIXTURE=%s", fixture))
                $fatal(1, "missing FIXTURE argument");
            for (i = 0; i < MAX_HALFWORDS; i = i + 1) begin
                input_words[i] = 16'd0;
                weight_words[i] = 16'd0;
            end
            for (i = 0; i < OUTPUT_BYTES; i = i + 1) output_mem[i] = 8'd0;
            $readmemh({fixture, "/command.hex"}, command_bytes);
            $readmemh({fixture, "/input.hex"}, input_words);
            $readmemh({fixture, "/weight.hex"}, weight_words);
            $readmemh({fixture, "/expected.hex"}, expected);
        end
    endtask

    initial begin : TEST
        load_fixture();
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);
        if (!start_ready) $fatal(1, "DMA never became ready");

        @(negedge clk);
        start_valid = 1;
        @(negedge clk);
        start_valid = 0;

        guard = 0;
        while (!(done || error) && guard < 4_000_000) begin
            @(negedge clk);
            guard = guard + 1;
        end
        if (error) $fatal(1, "GEMM job faulted with code %0d after %0d cycles",
                          error_code, guard);
        if (guard == 4_000_000) $fatal(1, "GEMM job produced no completion");
        if (!acknowledged) $fatal(1, "GEMM job did not acknowledge completion");

        repeat (4) @(negedge clk);

        // Report the scale of a mismatch, not just its first byte: a structural
        // error (wrong address/layout) and an arithmetic-order difference look
        // identical if only byte 0 is printed.
        mismatched = 0;
        max_ulp = 0;
        worst_abs = 0.0;
        for (i = 0; i < OUTPUT_BYTES; i = i + 1) begin
            if (output_mem[i] !== expected[i]) begin
                mismatched = mismatched + 1;
                if (mismatched <= 8)
                    $display("MISMATCH byte %0d got=%02x expected=%02x",
                             i, output_mem[i], expected[i]);
            end
        end
        for (i = 0; i + 3 < OUTPUT_BYTES; i = i + 4) begin
            got_word = {output_mem[i+3], output_mem[i+2],
                        output_mem[i+1], output_mem[i]};
            exp_word = {expected[i+3], expected[i+2],
                        expected[i+1], expected[i]};
            got_float = f32_to_real(got_word);
            exp_float = f32_to_real(exp_word);
            if (got_word != exp_word) begin
                if ((got_float - exp_float) > (exp_float - got_float))
                    diff_abs = got_float - exp_float;
                else
                    diff_abs = exp_float - got_float;
                if (diff_abs > worst_abs) worst_abs = diff_abs;
            end
            if (got_word >= exp_word)
                word_gap = got_word - exp_word;
            else
                word_gap = exp_word - got_word;
            if (word_gap > max_ulp)
                max_ulp = word_gap;
        end
        if ($value$plusargs("DUMP=%s", dump_path))
            $writememh(dump_path, output_mem, 0, OUTPUT_BYTES - 1);
        if (mismatched != 0) begin
            if (worst_abs <= TOLERANCE_ABS) begin
                $display("TOLERANCE CMAC_GEMM_FP32 bytes=%0d worst_abs=%0.9f limit=%0.9f",
                         mismatched, worst_abs, TOLERANCE_ABS);
            end else begin
                $fatal(1, "output BO differs in %0d of %0d bytes; worst abs=%0.9f exceeds limit %0.9f",
                       mismatched, OUTPUT_BYTES, worst_abs, TOLERANCE_ABS);
            end
        end
        // Two halfwords per logical output element: ROWS*AO values.
        if (writes !== ROWS * AO * 2)
            $fatal(1, "writes %0d is not two halfwords per output value (%0d)",
                   writes, ROWS * AO * 2);

        $display("PASS CMAC_GEMM_FP32 rows=%0d ai=%0d ao=%0d reads=%0d writes=%0d bo_bytes=%0d worst_abs=%0.9f tolerance=%0.9f",
                 ROWS, AI, AO, reads, writes, OUTPUT_BYTES, worst_abs, TOLERANCE_ABS);
        $finish;
    end

    initial begin
        #40_000_000;
        $fatal(1, "GEMM FP32 replay watchdog");
    end
endmodule
