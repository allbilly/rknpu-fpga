// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Host-drivable endpoint replay: an AXI-Lite host submits one frozen conv-simple
// descriptor and must obtain the captured output BO.
//
// Modes:
//  0  full job: descriptor + COMMAND=1, complete output BO, result regs
//  1  submit before all three descriptor fields -> SLVERR, no engine start
//  2  wrong START_AMOUNT (51) -> engine rejects, RESULT_CODE=1, no traffic
//  3  acknowledge before a result exists -> SLVERR, slot unchanged
//  4  write a read-only register -> SLVERR, value unchanged
//  5  submit while a job is active -> SLVERR, exactly one engine start
//  6  two sequential jobs -> both complete, result ACK between them
//  7  memory never ready (memory_ready=0) -> can_submit stays 0
module tb_conv_simple_axi #(
    parameter integer PROFILE = 0,
    parameter integer WORDS = 52,
    parameter integer INPUT_HALFWORDS = 256,
    parameter integer WEIGHT_HALFWORDS = 1152,
    parameter integer OUTPUT_BYTES = 1152,
    parameter integer MODE = 0,
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
    // The capture's own BO placement. The 5x5 and C16 cases put the output
    // above the weight BO, so these cannot be hardcoded.
    parameter integer INPUT_BASE = 32'h00001000,
    parameter integer WEIGHT_BASE = 32'h00002000,
    parameter integer OUTPUT_BASE = 32'h00003000,
    // Output format: 1 = FP16 atom writer, 0 = FP32 [c1][pixel][c2] writer.
    parameter integer OUTPUT_FP16 = 1,
    // Absolute bound for the FP32 comparison. FP16 profiles compare byte-exact;
    // FP32 profiles carry the accumulation-order bound the fixture records.
    parameter real TOLERANCE_ABS = 0.0
);
    localparam int unsigned OUTPUT_H = INPUT_H - KH + 1;
    localparam int unsigned OUTPUT_W = INPUT_W - KW + 1;
    localparam int unsigned OUTPUT_HALFWORDS = OUTPUT_BYTES / 2;
    localparam logic [31:0] BASE = 32'h00000000;
    localparam logic [31:0] COMMAND_BASE = BASE + 32'h0000;
    localparam int unsigned MEM_BYTES = 32768;

    logic clk;
    initial clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0, memory_ready = 1, irq;
    `include "tests/axil_host.svh"

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
    integer delay_q, cycles_q, transactions_q;
    integer engine_starts_q, mode, i, timeout_count;
    string fixture;

    assign mem_req_ready = rst_n && !pending_q && !mem_rsp_valid &&
                           (cycles_q % 3 != 1);

    rk_conv_simple_axi #(
        .PROFILE(PROFILE), .BASE(BASE), .BYTES(33'd32768), .WORDS(WORDS),
        .INPUT_H(INPUT_H), .INPUT_W(INPUT_W), .KH(KH), .KW(KW),
        .INPUT_CHANNELS(INPUT_CHANNELS), .KERNELS(KERNELS),
        .C1_BLOCKS(C1_BLOCKS), .ALIGN_C(ALIGN_C), .PACK_C2(PACK_C2),
        .CHUNK_LANES(CHUNK_LANES),
        .OUTPUT_FP16(OUTPUT_FP16 != 0),
        .TIMEOUT_CYCLES(4096)
    ) dut (
        .clk, .rst_n, .memory_ready,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
        .irq,
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata,
        .mem_rsp_error
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
            mem_rsp_error <= 1'b0;
            mem_rsp_rdata <= 16'd0;
            cycles_q <= 0;
            transactions_q <= 0;
            engine_starts_q <= 0;
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
                                   (mem_req_addr[0] !== 1'b0);
                delay_q <= (transactions_q % 2) + 1;
                transactions_q <= transactions_q + 1;
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
            end
            if (dut.engine_start_valid && dut.engine_start_ready)
                engine_starts_q <= engine_starts_q + 1;
        end
    end

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
            for (i = 0; i < MEM_BYTES; i = i + 1) memory[i] = 8'd0;
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
        end
    endtask

    task automatic program_descriptor(input logic [31:0] amount,
                                      input logic [31:0] tag);
        begin
            host_write(32'h10, COMMAND_BASE);
            host_write(32'h14, amount);
            host_write(32'h18, tag);
        end
    endtask

    task automatic wait_for_result;
        begin
            timeout_count = 0;
            while (!irq && timeout_count < 400000) begin
                @(negedge clk);
                timeout_count = timeout_count + 1;
            end
            if (timeout_count == 400000) $fatal(1, "endpoint produced no result");
        end
    endtask

    task automatic compare_bo;
        integer mismatched;
        logic [31:0] got_word, exp_word;
        real got_float, exp_float, diff_abs, worst_abs;
        begin
            if (OUTPUT_FP16 != 0) begin
                // FP16 captures are byte-exact: every halfword must match.
                for (i = 0; i < OUTPUT_HALFWORDS; i = i + 1)
                    if ({memory[OUTPUT_BASE + 32'(i) * 2 - BASE + 1],
                         memory[OUTPUT_BASE + 32'(i) * 2 - BASE]} !== expected[i])
                        $fatal(1, "output halfword %0d got=%04x expected=%04x", i,
                               {memory[OUTPUT_BASE + 32'(i) * 2 - BASE + 1],
                                memory[OUTPUT_BASE + 32'(i) * 2 - BASE]}, expected[i]);
            end else begin
                // FP32: the device DPU and this RTL's CACC accumulate in
                // different orders, so a measured absolute bound applies.
                mismatched = 0;
                worst_abs = 0.0;
                for (i = 0; i < OUTPUT_BYTES / 4; i = i + 1) begin
                    got_word = {memory[OUTPUT_BASE + 32'(i) * 4 - BASE + 3],
                                memory[OUTPUT_BASE + 32'(i) * 4 - BASE + 2],
                                memory[OUTPUT_BASE + 32'(i) * 4 - BASE + 1],
                                memory[OUTPUT_BASE + 32'(i) * 4 - BASE]};
                    exp_word = {expected[2*i + 1], expected[2*i]};
                    if (got_word !== exp_word) begin
                        mismatched = mismatched + 1;
                        got_float = f32_to_real(got_word);
                        exp_float = f32_to_real(exp_word);
                        if (got_float > exp_float) diff_abs = got_float - exp_float;
                        else diff_abs = exp_float - got_float;
                        if (diff_abs > worst_abs) worst_abs = diff_abs;
                    end
                end
                if (mismatched != 0 && worst_abs > TOLERANCE_ABS)
                    $fatal(1, "output BO differs in %0d of %0d words; worst abs=%0.9f exceeds %0.9f",
                           mismatched, OUTPUT_BYTES / 4, worst_abs, TOLERANCE_ABS);
                if (mismatched != 0)
                    $display("TOLERANCE CONV_SIMPLE_AXI differing_words=%0d worst_abs=%0.9f limit=%0.9f",
                             mismatched, worst_abs, TOLERANCE_ABS);
            end
        end
    endtask

    task automatic check_result(input logic [31:0] tag, input logic [31:0] tasks,
                                input logic [31:0] code);
        logic [31:0] value;
        begin
            host_read(32'h1c, value);
            if (value !== tag) $fatal(1, "result tag %08x expected %08x", value, tag);
            host_read(32'h20, value);
            if (value !== tasks) $fatal(1, "result tasks %0d expected %0d", value, tasks);
            host_read(32'h24, value);
            if (value !== code) $fatal(1, "result code %0d expected %0d", value, code);
        end
    endtask

    task automatic acknowledge;
        begin
            host_write(32'h0c, 32'd2);
            host_read(32'h08, i);
            if (irq) $fatal(1, "acknowledge did not clear irq");
        end
    endtask

    initial begin : TEST
        if (!$value$plusargs("FIXTURE=%s", fixture))
            $fatal(1, "missing FIXTURE plusarg");
        if (!$value$plusargs("MODE=%d", mode)) mode = MODE;
        load_fixture();

        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);

        host_expect(32'h00, 32'h524b4353);
        host_expect(32'h04, 32'h00010000);

        case (mode)
            0: begin
                program_descriptor(32'(WORDS), 32'hc0de0001);
                host_expect(32'h08, 32'h0000_0711);   // fields 111 + memory_ready + can_submit
                host_write(32'h0c, 32'd1);
                wait_for_result();
                check_result(32'hc0de0001, 32'd1, 32'd0);
                compare_bo();
                acknowledge();
            end
            1: begin
                host_write(32'h10, COMMAND_BASE);
                host_write(32'h14, 32'(WORDS));
                // COMMAND=1 without JOB_TAG: fields_valid is incomplete.
                host_write(32'h0c, 32'd1, 2'b10);
                if (engine_starts_q != 0)
                    $fatal(1, "incomplete descriptor started the engine");
            end
            2: begin
                program_descriptor(32'(WORDS - 1), 32'hc0de0002);
                host_write(32'h0c, 32'd1);
                wait_for_result();
                check_result(32'hc0de0002, 32'd0, 32'd1);
                if (transactions_q != 0)
                    $fatal(1, "rejected job issued %0d memory transactions",
                           transactions_q);
                if (engine_starts_q != 1)
                    $fatal(1, "engine handshake count %0d expected 1",
                           engine_starts_q);
                // A faulted result is never ACKed or released: the established
                // contract (rk_job_control, rk_cmac_job_control, the PPU page)
                // holds the slot until the platform resets the endpoint. This
                // test pins that behaviour rather than inventing a recovery.
                host_write(32'h0c, 32'd2, 2'b10);
                if (!irq) $fatal(1, "faulted result was released without a reset");
                host_write(32'h10, 32'hdead0000, 2'b10);
                host_expect(32'h10, COMMAND_BASE);
            end
            3: begin
                host_write(32'h0c, 32'd2, 2'b10);
                if (irq) $fatal(1, "spurious result before any job");
                host_expect(32'h1c, 32'h0);
            end
            4: begin
                host_write(32'h00, 32'hdeadbeef, 2'b10);
                host_write(32'h08, 32'hffffffff, 2'b10);
                host_write(32'h24, 32'hffffffff, 2'b10);
                host_expect(32'h00, 32'h524b4353);
            end
            5: begin
                program_descriptor(32'(WORDS), 32'hc0de0005);
                host_write(32'h0c, 32'd1);
                // While the job runs, a second submit must be refused.
                repeat (4) @(negedge clk);
                if (dut.active) begin
                    host_write(32'h0c, 32'd1, 2'b10);
                    host_read(32'h08, i);
                    // Bit 0 must be 0 (cannot submit) and bit 1 must be 1
                    // (a job is active); the rest of the word reflects the
                    // engine's internal busy state and is not pinned here.
                    if (i[0] !== 1'b0 || i[1] !== 1'b1)
                        $fatal(1, "active-job status %08x did not withdraw submit", i);
                end
                wait_for_result();
                if (engine_starts_q != 1)
                    $fatal(1, "second submit started the engine (%0d starts)",
                           engine_starts_q);
                check_result(32'hc0de0005, 32'd1, 32'd0);
                compare_bo();
                acknowledge();
            end
            6: begin
                program_descriptor(32'(WORDS), 32'hc0de0006);
                host_write(32'h0c, 32'd1);
                wait_for_result();
                check_result(32'hc0de0006, 32'd1, 32'd0);
                compare_bo();
                acknowledge();
                repeat (4) @(negedge clk);
                program_descriptor(32'(WORDS), 32'hc0de0007);
                host_write(32'h0c, 32'd1);
                wait_for_result();
                check_result(32'hc0de0007, 32'd1, 32'd0);
                compare_bo();
                if (engine_starts_q != 2)
                    $fatal(1, "second job did not start (%0d starts)", engine_starts_q);
                acknowledge();
            end
            7: begin
                memory_ready = 0;
                program_descriptor(32'(WORDS), 32'hc0de0008);
                host_expect(32'h08, 32'h0000_0700);   // memory_ready=0 blocks submit
                host_write(32'h0c, 32'd1, 2'b10);
                if (engine_starts_q != 0)
                    $fatal(1, "job started without memory_ready");
            end
            default: $fatal(1, "invalid MODE");
        endcase

        $display("PASS CONV_SIMPLE_AXI mode=%0d starts=%0d transactions=%0d output_bytes=%0d",
                 mode, engine_starts_q, transactions_q, OUTPUT_BYTES);
        $finish;
    end

    initial begin
        #20000000;
        $fatal(1, "conv-simple AXI endpoint watchdog");
    end
endmodule
