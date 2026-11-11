// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Host-drivable pooling endpoint replay: an AXI-Lite host submits one frozen
// 26-QWORD signed-INT8 descriptor and must obtain the captured output BO.
//
// Modes:
//  0  full job: complete output BO and result registers
//  1  submit before all descriptor fields are written -> SLVERR
//  2  wrong START_AMOUNT (25) -> engine rejects with code 1, no traffic
//  3  acknowledge before any result -> SLVERR
//  4  write a read-only register -> SLVERR, value unchanged
//  5  submit while a job is active -> SLVERR, exactly one start
//  6  two sequential jobs -> both complete
//  7  memory never ready -> can_submit stays 0
module tb_ppu_pool_axi #(
    parameter integer MODE = 0,
    parameter integer WORDS = 26
);
    localparam int unsigned BO_BYTES = 4096;
    localparam logic [31:0] BASE = 32'h00000000;
    localparam logic [31:0] COMMAND_BASE = BASE + 32'h0000;
    localparam logic [31:0] INPUT_BASE = BASE + 32'h1000;
    localparam logic [31:0] OUTPUT_BASE = BASE + 32'h2000;
    // Output BO starts at 0x2000, so the aperture must extend past it.
    localparam int unsigned MEM_BYTES = 16384;

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
    logic [7:0] command_bytes [0:WORDS*8-1];
    logic [7:0] input_bo [0:BO_BYTES-1];
    logic [7:0] output_init [0:BO_BYTES-1];
    logic [7:0] expected [0:BO_BYTES-1];

    logic pending_q;
    logic [31:0] pending_addr_q;
    logic pending_write_q;
    logic [15:0] pending_rdata_q;
    logic pending_error_q;
    integer delay_q, cycles_q, transactions_q, engine_starts_q;
    integer mode, i, timeout_count, output_writes_q;
    string fixture;

    assign mem_req_ready = rst_n && !pending_q && !mem_rsp_valid &&
                           (cycles_q % 3 != 1);

    rk_ppu_pool_axi #(
        .BASE(BASE), .BYTES(33'd16384), .WORDS(WORDS), .TIMEOUT_CYCLES(4096)
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
                                   (mem_req_addr[0] !== 1'b0);
                delay_q <= (transactions_q % 2) + 1;
                transactions_q <= transactions_q + 1;
                if (mem_req_write) begin
                    if (mem_req_addr >= OUTPUT_BASE)
                        output_writes_q <= output_writes_q + 1;
                    if (mem_req_addr + 1 - BASE < MEM_BYTES) begin
                        memory[mem_req_addr - BASE] <= mem_req_wdata[7:0];
                        memory[mem_req_addr + 1 - BASE] <= mem_req_wdata[15:8];
                    end
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

    task automatic load_fixture;
        begin
            for (i = 0; i < MEM_BYTES; i = i + 1) memory[i] = 8'd0;
            $readmemh({fixture, "/commands.hex"}, command_bytes);
            $readmemh({fixture, "/input.hex"}, input_bo);
            $readmemh({fixture, "/out_init.hex"}, output_init);
            $readmemh({fixture, "/expected.hex"}, expected);
            for (i = 0; i < WORDS * 8; i = i + 1)
                memory[COMMAND_BASE + i - BASE] = command_bytes[i];
            for (i = 0; i < BO_BYTES; i = i + 1) begin
                memory[INPUT_BASE + i - BASE] = input_bo[i];
                memory[OUTPUT_BASE + i - BASE] = output_init[i];
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
        begin
            for (i = 0; i < BO_BYTES; i = i + 1)
                if (memory[OUTPUT_BASE + i - BASE] !== expected[i])
                    $fatal(1, "output byte %0d got=%02x expected=%02x", i,
                           memory[OUTPUT_BASE + i - BASE], expected[i]);
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

        host_expect(32'h00, 32'h524b5050);
        host_expect(32'h04, 32'h00010000);

        case (mode)
            0: begin
                program_descriptor(32'(WORDS), 32'h00500001);

                host_expect(32'h08, 32'h0000_0711);
                host_write(32'h0c, 32'd1);
                wait_for_result();

                check_result(32'h00500001, 32'd1, 32'd0);
                compare_bo();
                acknowledge();
            end
            1: begin
                host_write(32'h10, COMMAND_BASE);
                host_write(32'h14, 32'(WORDS));
                host_write(32'h0c, 32'd1, 2'b10);
                if (engine_starts_q != 0)
                    $fatal(1, "incomplete descriptor started the engine");
            end
            2: begin
                program_descriptor(32'(WORDS - 1), 32'h00500002);
                host_write(32'h0c, 32'd1);
                wait_for_result();
                check_result(32'h00500002, 32'd0, 32'd1);
                if (output_writes_q != 0)
                    $fatal(1, "rejected job wrote the output BO");
                host_write(32'h0c, 32'd2, 2'b10);   // fault holds the slot
                if (!irq) $fatal(1, "faulted result was released");
            end
            3: begin
                host_write(32'h0c, 32'd2, 2'b10);
                host_expect(32'h1c, 32'h0);
            end
            4: begin
                host_write(32'h00, 32'hdeadbeef, 2'b10);
                host_write(32'h08, 32'hffffffff, 2'b10);
                host_write(32'h24, 32'hffffffff, 2'b10);
                host_expect(32'h00, 32'h524b5050);
            end
            5: begin
                program_descriptor(32'(WORDS), 32'h00500005);
                host_write(32'h0c, 32'd1);
                repeat (4) @(negedge clk);
                if (dut.active) begin
                    host_write(32'h0c, 32'd1, 2'b10);
                    host_read(32'h08, i);
                    if (i[0] !== 1'b0 || i[1] !== 1'b1)
                        $fatal(1, "active-job status %08x did not withdraw submit", i);
                end
                wait_for_result();
                if (engine_starts_q != 1)
                    $fatal(1, "second submit started the engine (%0d starts)",
                           engine_starts_q);
                check_result(32'h00500005, 32'd1, 32'd0);
                compare_bo();
                acknowledge();
            end
            6: begin
                program_descriptor(32'(WORDS), 32'h00500006);
                host_write(32'h0c, 32'd1);
                wait_for_result();
                check_result(32'h00500006, 32'd1, 32'd0);
                compare_bo();
                acknowledge();
                repeat (4) @(negedge clk);
                program_descriptor(32'(WORDS), 32'h00500007);
                host_write(32'h0c, 32'd1);
                wait_for_result();
                check_result(32'h00500007, 32'd1, 32'd0);
                compare_bo();
                if (engine_starts_q != 2)
                    $fatal(1, "second job did not start (%0d starts)", engine_starts_q);
                acknowledge();
            end
            7: begin
                memory_ready = 0;
                program_descriptor(32'(WORDS), 32'h00500008);
                host_expect(32'h08, 32'h0000_0700);
                host_write(32'h0c, 32'd1, 2'b10);
                if (engine_starts_q != 0)
                    $fatal(1, "job started without memory_ready");
            end
            default: $fatal(1, "invalid MODE");
        endcase

        $display("PASS PPU_POOL_AXI mode=%0d starts=%0d transactions=%0d output_writes=%0d",
                 mode, engine_starts_q, transactions_q, output_writes_q);
        $finish;
    end

    initial begin
        #2000000;
        $fatal(1, "pooling AXI endpoint watchdog");
    end
endmodule
