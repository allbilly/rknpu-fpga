// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// GEMM FP32 replay through the host-drivable AXI endpoint, wired exactly as the
// board image wires it:
//
//   host AXI4-Lite -> rk_cmac_job_control -> rk_cmac_nvdla_dma(OUTPUT_FP16=0)
//        -> rk_cmac_profile(OUTPUT_FP16=0) -> operand front -> CACC
//        -> rk_cmac_output_fp32
//   rk_cmac_nvdla_axi's AXI4 memory master
//        -> rk_axi_mem_slave  (verified unit bridge)
//        -> halfword memory model
//
// Modes:
//  0  full job: descriptor + memory admission + COMMAND=1, complete 4096-byte
//     output BO compared, result registers, ACK release
//  1  memory never ready -> submit refused, no traffic
//  2  body amount 44 -> descriptor rejected with code 7 before any request;
//     faulted slot stays held
//  3  ACK before any result -> SLVERR, no result created
//  4  write to read-only registers -> SLVERR, values unchanged
module tb_cmac_gemm_fp32_axi #(
    parameter integer MODE = 0,
    // The k=1 fixture has one product per output value, so it must be
    // byte-exact. Deeper shapes carry the family's declared absolute bound.
    parameter real TOLERANCE_ABS = 0.0,
    // Expected logical output shape. The page itself learns the shape from the
    // command stream; these are only for the write-count assertion.
    parameter integer ROWS = 2,
    parameter integer AO = 32,
    // Status polling budget. The deep GEMM shapes sweep far more address space
    // than k=1, so a fixed small budget produced a false timeout.
    parameter integer POLL_LIMIT = 200000
);
    localparam logic [31:0] BASE = 32'h0000_0000;
    localparam integer MEM_BYTES = 32768;

    logic clk;
    initial clk = 0;
    always #5 clk = ~clk;

    logic rst_n = 0, memory_ready = 0, irq;
    `include "tests/axil_host.svh"

    // AXI4 master from the endpoint, consumed by rk_axi_mem_slave.
    logic [3:0] m_axi_awid, m_axi_arid, m_axi_bid, m_axi_rid;
    logic [30:0] m_axi_awaddr, m_axi_araddr;
    logic [7:0] m_axi_awlen, m_axi_arlen;
    logic [2:0] m_axi_awsize, m_axi_arsize, m_axi_awprot, m_axi_arprot;
    logic [1:0] m_axi_awburst, m_axi_arburst, m_axi_bresp, m_axi_rresp;
    logic m_axi_awlock, m_axi_arlock;
    logic [3:0] m_axi_awcache, m_axi_arcache, m_axi_awqos, m_axi_arqos;
    logic m_axi_awvalid, m_axi_awready, m_axi_wlast, m_axi_wvalid, m_axi_wready;
    logic m_axi_bvalid, m_axi_bready, m_axi_arvalid, m_axi_arready;
    logic m_axi_rlast, m_axi_rvalid, m_axi_rready;
    logic [511:0] m_axi_wdata, m_axi_rdata;
    logic [63:0] m_axi_wstrb;

    localparam integer START_ADDRESS = 0;
    localparam integer AMOUNT = 45;          // body QWORDs; the tail is appended
    // Expected logical output shape. The page itself learns the shape from the
    // command stream; these are only for the write-count assertion.
    localparam integer INPUT_BASE = 4096;
    localparam integer WEIGHT_BASE = 8192;
    localparam integer OUTPUT_BASE = 12288;
    localparam integer OUTPUT_BYTES = 4096;
    localparam integer COMMAND_BYTES = 392;  // 45 body + 4 tail QWORDs fetched

    rk_cmac_nvdla_axi #(.TIMEOUT_CYCLES(65536), .OUTPUT_FP16(1'b0)) dut (
        .clk, .rst_n, .memory_ready,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
        .irq,
        .m_axi_awid, .m_axi_arid, .m_axi_awaddr, .m_axi_araddr,
        .m_axi_awlen, .m_axi_arlen, .m_axi_awsize, .m_axi_arsize,
        .m_axi_awburst, .m_axi_arburst, .m_axi_awlock, .m_axi_arlock,
        .m_axi_awcache, .m_axi_arcache, .m_axi_awprot, .m_axi_arprot,
        .m_axi_awqos, .m_axi_arqos,
        .m_axi_awvalid, .m_axi_awready,
        .m_axi_wdata, .m_axi_wstrb, .m_axi_wlast, .m_axi_wvalid, .m_axi_wready,
        .m_axi_bid, .m_axi_bresp, .m_axi_bvalid, .m_axi_bready,
        .m_axi_arvalid, .m_axi_arready,
        .m_axi_rid, .m_axi_rdata, .m_axi_rresp, .m_axi_rlast, .m_axi_rvalid,
        .m_axi_rready
    );

    // The bridge the image uses, between the endpoint's AXI4 master and the
    // halfword memory port.
    wire bridge_req_valid, bridge_req_write, bridge_rsp_ready;
    wire [31:0] bridge_req_addr;
    wire [15:0] bridge_req_wdata;
    logic bridge_req_ready, bridge_rsp_valid, bridge_rsp_error;
    logic [15:0] bridge_rsp_rdata;

    rk_axi_mem_slave #(
        .TIMEOUT_CYCLES(65536), .BASE(BASE), .BYTES(33'(MEM_BYTES))
    ) bridge (
        .clk, .rst_n,
        .mem_req_valid(bridge_req_valid), .mem_req_ready(bridge_req_ready),
        .mem_req_write(bridge_req_write), .mem_req_addr(bridge_req_addr),
        .mem_req_wdata(bridge_req_wdata),
        .mem_rsp_valid(bridge_rsp_valid), .mem_rsp_ready(bridge_rsp_ready),
        .mem_rsp_rdata(bridge_rsp_rdata), .mem_rsp_error(bridge_rsp_error),
        .s_axi_awid(m_axi_awid), .s_axi_awaddr(m_axi_awaddr),
        .s_axi_awlen(m_axi_awlen), .s_axi_awsize(m_axi_awsize),
        .s_axi_awburst(m_axi_awburst), .s_axi_awlock(m_axi_awlock),
        .s_axi_awcache(m_axi_awcache), .s_axi_awprot(m_axi_awprot),
        .s_axi_awqos(m_axi_awqos), .s_axi_awvalid(m_axi_awvalid),
        .s_axi_awready(m_axi_awready),
        .s_axi_wdata(m_axi_wdata), .s_axi_wstrb(m_axi_wstrb),
        .s_axi_wlast(m_axi_wlast), .s_axi_wvalid(m_axi_wvalid),
        .s_axi_wready(m_axi_wready),
        .s_axi_bid(m_axi_bid), .s_axi_bresp(m_axi_bresp),
        .s_axi_bvalid(m_axi_bvalid), .s_axi_bready(m_axi_bready),
        .s_axi_arid(m_axi_arid), .s_axi_araddr(m_axi_araddr),
        .s_axi_arlen(m_axi_arlen), .s_axi_arsize(m_axi_arsize),
        .s_axi_arburst(m_axi_arburst), .s_axi_arlock(m_axi_arlock),
        .s_axi_arcache(m_axi_arcache), .s_axi_arprot(m_axi_arprot),
        .s_axi_arqos(m_axi_arqos), .s_axi_arvalid(m_axi_arvalid),
        .s_axi_arready(m_axi_arready),
        .s_axi_rid(m_axi_rid), .s_axi_rdata(m_axi_rdata),
        .s_axi_rresp(m_axi_rresp), .s_axi_rlast(m_axi_rlast),
        .s_axi_rvalid(m_axi_rvalid), .s_axi_rready(m_axi_rready)
    );

    logic [15:0] memory [0:MEM_BYTES/2-1];
    logic [7:0] command_bytes [0:COMMAND_BYTES-1];
    logic [15:0] input_words [0:2047];
    logic [15:0] weight_words [0:2047];
    logic [7:0] expected [0:OUTPUT_BYTES-1];

    // Halfword memory model: no stalls, one-cycle response, explicit error on
    // any address the bridge should never have emitted.
    logic pending;
    logic [31:0] pending_addr;
    logic [15:0] pending_data;
    integer reads, writes;

    assign bridge_req_ready = rst_n && !pending && !bridge_rsp_valid;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pending <= 1'b0;
            bridge_rsp_valid <= 1'b0;
            bridge_rsp_error <= 1'b0;
            pending_addr <= 32'd0;
            pending_data <= 16'd0;
            reads <= 0;
            writes <= 0;
        end else begin
            if (bridge_req_valid && bridge_req_ready) begin
                pending <= 1'b1;
                pending_addr <= bridge_req_addr;
                pending_data <= memory[bridge_req_addr >> 1];
                if (bridge_req_write) begin
                    memory[bridge_req_addr >> 1] <= bridge_req_wdata;
                    writes <= writes + 1;
                end else reads <= reads + 1;
            end
            if (pending && !bridge_rsp_valid) begin
                pending <= 1'b0;
                bridge_rsp_valid <= 1'b1;
                bridge_rsp_rdata <= pending_data;
                bridge_rsp_error <= (pending_addr >= MEM_BYTES) ||
                                    pending_addr[0];
            end
            if (bridge_rsp_valid && bridge_rsp_ready) begin
                bridge_rsp_valid <= 1'b0;
                bridge_rsp_error <= 1'b0;
            end
        end
    end

    task automatic reset_all;
        @(negedge clk); rst_n = 0; memory_ready = 0; host_idle();
        repeat (4) @(negedge clk);
        if (irq || m_axi_awvalid || m_axi_wvalid || m_axi_arvalid ||
            m_axi_bready || m_axi_rready || s_axil_bvalid || s_axil_rvalid)
            $fatal(1, "activity during joint reset");
        rst_n = 1;
        host_expect(32'h08, 32'h0);
    endtask

    task automatic stage(input logic [31:0] address, input logic [31:0] amount,
                         input logic [31:0] tag);
        host_write(32'h10, address, 0, 1);
        host_write(32'h14, amount, 0, 2);
        host_write(32'h18, tag);
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

    task automatic load_fixture(input string fixture);
        integer i;
        begin
            for (i = 0; i < MEM_BYTES/2; i = i + 1) memory[i] = 16'd0;
            $readmemh({fixture, "/command.hex"}, command_bytes);
            for (i = 0; i < COMMAND_BYTES/2; i = i + 1)
                memory[(START_ADDRESS >> 1) + i] =
                    {command_bytes[2*i + 1], command_bytes[2*i]};
            $readmemh({fixture, "/input.hex"}, input_words);
            for (i = 0; i < 2048; i = i + 1)
                memory[(INPUT_BASE >> 1) + i] = input_words[i];
            $readmemh({fixture, "/weight.hex"}, weight_words);
            for (i = 0; i < 2048; i = i + 1)
                memory[(WEIGHT_BASE >> 1) + i] = weight_words[i];
            $readmemh({fixture, "/expected.hex"}, expected);
        end
    endtask

    integer mode, i, polls, mismatched;
    logic [31:0] backend_code;
    logic [31:0] status;
    logic [31:0] got_word, exp_word;
    real got_float, exp_float, diff_abs, worst_abs;
    string fixture;

    initial begin : TEST
        if (!$value$plusargs("FIXTURE=%s", fixture))
            $fatal(1, "missing FIXTURE plusarg");
        mode = MODE;
        if (!$value$plusargs("MODE=%d", mode)) mode = mode;
        load_fixture(fixture);

        reset_all();
        host_expect(32'h00, 32'h524b434d);
        host_expect(32'h04, 32'h00010000);

        case (mode)
            0: begin
                stage(32'(START_ADDRESS), 32'(AMOUNT), 32'h6e6d0001);
                // Descriptor complete, memory withheld: submit must be refused.
                host_expect(32'h08, 32'h0000_0700);
                host_write(32'h0c, 32'd1, 2'b10);
                if (m_axi_arvalid || m_axi_awvalid || irq)
                    $fatal(1, "job launched before memory admission");
                memory_ready = 1;
                host_expect(32'h08, 32'h0000_0711);
                host_write(32'h0c, 32'd1);
                status = 0; polls = 0;
                while (!status[2] && polls < POLL_LIMIT) begin
                    host_read(32'h08, status);
                    polls = polls + 1;
                end
                host_read(32'h24, backend_code);
                if (!status[2] || !irq || status[1] || status[3])
                    $fatal(1, "bad completion status %08h (result code %0d)",
                           status, backend_code);
                host_expect(32'h1c, 32'h6e6d0001);
                host_expect(32'h20, 32'd1);
                host_expect(32'h24, 32'd0);
                repeat (5) @(negedge clk);
                if (!irq) $fatal(1, "IRQ was a pulse instead of a held result");
                if (m_axi_awvalid || m_axi_wvalid || m_axi_arvalid ||
                    m_axi_bvalid || m_axi_rvalid)
                    $fatal(1, "outstanding AXI traffic after completion");
                // Two halfword writes per logical output value.
                if (writes != ROWS * AO * 2)
                    $fatal(1, "wrote %0d halfwords, expected %0d",
                           writes, ROWS * AO * 2);

                mismatched = 0;
                worst_abs = 0.0;
                for (i = 0; i < OUTPUT_BYTES/4; i = i + 1) begin
                    got_word = {memory[(OUTPUT_BASE >> 1) + 2*i + 1],
                                memory[(OUTPUT_BASE >> 1) + 2*i]};
                    exp_word = {expected[4*i + 3], expected[4*i + 2],
                                expected[4*i + 1], expected[4*i]};
                    if (got_word !== exp_word) begin
                        mismatched = mismatched + 1;
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
                    $fatal(1, "output BO differs in %0d of %0d words; worst abs=%0.9f exceeds %0.9f",
                           mismatched, OUTPUT_BYTES/4, worst_abs, TOLERANCE_ABS);
                if (mismatched != 0)
                    $display("TOLERANCE CMAC_GEMM_FP32_AXI differing_words=%0d worst_abs=%0.9f limit=%0.9f",
                             mismatched, worst_abs, TOLERANCE_ABS);

                host_write(32'h0c, 32'd2);
                host_expect(32'h08, 32'h0000_0010);
                if (irq) $fatal(1, "ACK did not release result");
            end
            1: begin
                stage(32'(START_ADDRESS), 32'(AMOUNT), 32'h6e6d0002);
                host_write(32'h0c, 32'd1, 2'b10);
                if (m_axi_arvalid || m_axi_awvalid || irq)
                    $fatal(1, "job launched without memory_ready");
                if (reads != 0 || writes != 0)
                    $fatal(1, "refused submit still touched memory");
            end
            2: begin
                stage(32'(START_ADDRESS), 32'(AMOUNT - 1), 32'h6e6d0003);
                memory_ready = 1;
                host_write(32'h0c, 32'd1);
                status = 0; polls = 0;
                while (!status[2] && polls < 20000) begin
                    host_read(32'h08, status);
                    polls = polls + 1;
                end
                if (!status[2] || status[3] !== 1'b1)
                    $fatal(1, "wrong amount was not rejected: %08h", status);
                host_expect(32'h24, 32'd7);
                if (reads != 0 || writes != 0)
                    $fatal(1, "rejected descriptor issued memory traffic");
                host_write(32'h0c, 32'd2, 2'b10);
                if (!irq) $fatal(1, "faulted result was released without a reset");
            end
            3: begin
                host_write(32'h0c, 32'd2, 2'b10);
                if (irq) $fatal(1, "spurious ACK created a result");
                host_expect(32'h1c, 32'h0);
            end
            4: begin
                host_write(32'h00, 32'hdeadbeef, 2'b10);
                host_write(32'h08, 32'hffffffff, 2'b10);
                host_write(32'h24, 32'hffffffff, 2'b10);
                host_expect(32'h00, 32'h524b434d);
            end
            default: $fatal(1, "invalid MODE");
        endcase

        $display("PASS CMAC_GEMM_FP32_AXI mode=%0d reads=%0d writes=%0d bo_bytes=%0d",
                 mode, reads, writes, OUTPUT_BYTES);
        $finish;
    end

    initial begin
        #400000000;
        $fatal(1, "GEMM FP32 AXI global timeout");
    end
endmodule
