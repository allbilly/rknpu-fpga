// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Whole-image replay of ONE frozen pooling-corpus case through AXI4-Lite.
//
// The runner invokes the bench once per corpus page and passes the case files
// as byte-hex memories plus the case's captured geometry/identity:
//
//   +PAGE=<n> +CMD_WORDS=<32-bit words> +CRC32=<32-bit> +DTYPE=<0 exact | 1 fp16>
//   +TOL_UNITS=<abs tolerance in FP16 2^-24 units> +VALUE_BYTES=<n>
//   +INDEX_EN=<0|1> +INDEX_OFFSET=<byte> +INDEX_BYTES=<byte>
//   +CMD_HEX=<file> +IN_HEX=<file> +INIT_HEX=<file> +EXPECTED_HEX=<file>
//
// The bench checks the page identity, loads the patched raw command stream and
// the fixture's in/out_init BOs through the memory window, submits the unchanged
// raw descriptor, checks the result registers and compares the COMPLETE
// 4096-byte BO in hardware: exact for integer/max/min/index lanes and untouched
// bytes, and the capture's declared absolute tolerance for FP16 average lanes
// (compared exactly in FP16 2^-24 fixed-point units, so no real arithmetic and
// no tolerance rounding is involved).
//
// On page 0 it also runs the image-level refusals: unmapped addresses are
// SLVERR, a second page refuses a submit while the first is active, and a
// tampered captured command field faults the page instead of succeeding.
module tb_ypcb_ppu_corpus #(
    parameter integer N_PAGES = 19
);
    localparam integer BO_BYTES = 4096;
    localparam integer BO_WORDS = BO_BYTES / 4;
    localparam integer CMD_BYTES_MAX = 256;
    localparam logic [31:0] CMD_BASE = 32'h0000_0000;
    localparam logic [31:0] IN_BASE = 32'h0000_1000;
    localparam logic [31:0] OUT_BASE = 32'h0000_2000;
    localparam logic [31:0] PAGE_BASE = 32'h0000_8000;
    localparam logic [31:0] PAGE_STRIDE = 32'h0000_1000;

    logic SYS_CLK;
    initial SYS_CLK = 0;
    always #10 SYS_CLK = ~SYS_CLK;

    logic clk;
    assign clk = SYS_CLK;

    wire [N_PAGES-1:0] page_irq;

    `include "tests/axil_host.svh"

    ypcb_ppu_corpus_top #(.N_PAGES(N_PAGES)) dut (
        .SYS_CLK,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
        .page_irq
    );

    logic [7:0] cmd_bytes [0:CMD_BYTES_MAX-1];
    logic [7:0] in_bo [0:BO_BYTES-1];
    logic [7:0] init_bo [0:BO_BYTES-1];
    logic [7:0] expected_bo [0:BO_BYTES-1];
    logic [7:0] observed [0:BO_BYTES-1];

    integer page, cmd_words, crc32, dtype, tol_units, value_bytes;
    integer index_en, index_offset, index_bytes;
    integer index, half_i, poll_cycles, mismatches, over_tolerance, tag;
    integer got_units, ref_units, diff_units;
    logic [31:0] value, status;
    string cmd_hex, in_hex, init_hex, expected_hex;

    function automatic longint fp16_units(input logic [15:0] half);
        begin
            if (half[14:10] == 5'd0)
                fp16_units = 0;
            else
                fp16_units = (half[15] ? -longint'(1024 + {22'd0, half[9:0]})
                                       : longint'(1024 + {22'd0, half[9:0]}))
                             <<< (half[14:10] - 1);
        end
    endfunction

    function automatic logic in_value_region(input integer byte_index);
        in_value_region = (byte_index < value_bytes);
    endfunction

    function automatic logic in_index_region(input integer byte_index);
        in_index_region = (index_en != 0) &&
                          (byte_index >= index_offset) &&
                          (byte_index < index_offset + index_bytes);
    endfunction

    task automatic load_hex_command;
        begin
            for (index = 0; index < CMD_BYTES_MAX; index = index + 1)
                cmd_bytes[index] = 8'd0;
            $readmemh(cmd_hex, cmd_bytes);
            for (index = 0; index < cmd_words; index = index + 1) begin
                value = {cmd_bytes[4*index + 3], cmd_bytes[4*index + 2],
                         cmd_bytes[4*index + 1], cmd_bytes[4*index + 0]};
                host_write(CMD_BASE + 4*index, value);
            end
        end
    endtask

    task automatic load_hex_bo(input logic [31:0] base);
        begin
            if (base == IN_BASE) $readmemh(in_hex, in_bo);
            else $readmemh(init_hex, init_bo);
            for (index = 0; index < BO_WORDS; index = index + 1) begin
                if (base == IN_BASE)
                    value = {in_bo[4*index + 3], in_bo[4*index + 2],
                             in_bo[4*index + 1], in_bo[4*index + 0]};
                else
                    value = {init_bo[4*index + 3], init_bo[4*index + 2],
                             init_bo[4*index + 1], init_bo[4*index + 0]};
                host_write(base + 4*index, value);
            end
        end
    endtask

    task automatic wait_result(output integer cycles);
        begin
            cycles = 0;
            status = 0;
            while (!status[2] && cycles < 500_000) begin
                host_read(PAGE_BASE + PAGE_STRIDE*page + 32'h08, status);
                cycles = cycles + 1;
            end
            if (!status[2])
                $fatal(1, "page %0d timed out waiting for its result", page);
        end
    endtask

    task automatic compare_bo;
        begin
            mismatches = 0;
            over_tolerance = 0;
            if (dtype != 0 && tol_units > 0) begin
                // FP16 value area: exact fixed-point comparison of the declared
                // absolute tolerance; index area and untouched bytes stay exact.
                for (half_i = 0; half_i < value_bytes / 2; half_i = half_i + 1) begin
                    got_units = fp16_units(
                        {observed[2*half_i + 1], observed[2*half_i]});
                    ref_units = fp16_units(
                        {expected_bo[2*half_i + 1], expected_bo[2*half_i]});
                    diff_units = (got_units > ref_units) ?
                                 (got_units - ref_units) :
                                 (ref_units - got_units);
                    if (diff_units > tol_units) over_tolerance =
                        over_tolerance + 1;
                end
            end else begin
                for (index = 0; index < value_bytes; index = index + 1)
                    if (observed[index] !== expected_bo[index]) mismatches =
                        mismatches + 1;
            end
            if (index_en != 0) begin
                for (index = index_offset;
                     index < index_offset + index_bytes; index = index + 1)
                    if (observed[index] !== expected_bo[index]) mismatches =
                        mismatches + 1;
            end
            for (index = 0; index < BO_BYTES; index = index + 1) begin
                if (!in_value_region(index) && !in_index_region(index))
                    if (observed[index] !== expected_bo[index]) mismatches =
                        mismatches + 1;
            end
        end
    endtask

    task automatic capture_bo;
        begin
            for (index = 0; index < BO_WORDS; index = index + 1) begin
                host_read(OUT_BASE + 4*index, value);
                observed[4*index + 0] = value[7:0];
                observed[4*index + 1] = value[15:8];
                observed[4*index + 2] = value[23:16];
                observed[4*index + 3] = value[31:24];
            end
        end
    endtask

    task automatic submit_case;
        begin
            tag = 32'h0000_1000 + page;
            host_write(PAGE_BASE + PAGE_STRIDE*page + 32'h10, CMD_BASE);
            host_write(PAGE_BASE + PAGE_STRIDE*page + 32'h14, cmd_words / 2);
            host_write(PAGE_BASE + PAGE_STRIDE*page + 32'h18, tag);
            host_write(PAGE_BASE + PAGE_STRIDE*page + 32'h0c, 32'd1);
        end
    endtask

    initial begin : TEST
        if (!$value$plusargs("PAGE=%d", page))
            $fatal(1, "missing +PAGE");
        if (!$value$plusargs("CMD_WORDS=%d", cmd_words))
            $fatal(1, "missing +CMD_WORDS");
        if (!$value$plusargs("CRC32=%d", crc32))
            $fatal(1, "missing +CRC32");
        if (!$value$plusargs("DTYPE=%d", dtype))
            $fatal(1, "missing +DTYPE");
        if (!$value$plusargs("TOL_UNITS=%d", tol_units))
            $fatal(1, "missing +TOL_UNITS");
        if (!$value$plusargs("VALUE_BYTES=%d", value_bytes))
            $fatal(1, "missing +VALUE_BYTES");
        if (!$value$plusargs("INDEX_EN=%d", index_en))
            $fatal(1, "missing +INDEX_EN");
        if (!$value$plusargs("INDEX_OFFSET=%d", index_offset))
            $fatal(1, "missing +INDEX_OFFSET");
        if (!$value$plusargs("INDEX_BYTES=%d", index_bytes))
            $fatal(1, "missing +INDEX_BYTES");
        if (!$value$plusargs("CMD_HEX=%s", cmd_hex))
            $fatal(1, "missing +CMD_HEX");
        if (!$value$plusargs("IN_HEX=%s", in_hex))
            $fatal(1, "missing +IN_HEX");
        if (!$value$plusargs("INIT_HEX=%s", init_hex))
            $fatal(1, "missing +INIT_HEX");
        if (!$value$plusargs("EXPECTED_HEX=%s", expected_hex))
            $fatal(1, "missing +EXPECTED_HEX");
        if (page < 0 || page >= N_PAGES)
            $fatal(1, "page %0d out of range", page);
        if (cmd_words > CMD_BYTES_MAX / 4)
            $fatal(1, "command stream too long");

        for (index = 0; index < 80; index = index + 1) @(posedge SYS_CLK);

        if (page == 0) begin
            // Unmapped addresses are explicit SLVERR, never an alias.
            host_write(32'h0001_b000, 32'hdeadbeef, 2'b10);
            host_read(32'h0001_b000, value, 2'b10);
            host_read(32'hffff_ffff, value, 2'b10);
        end

        // Identity binding: the page address alone is not trusted.
        host_expect(PAGE_BASE + PAGE_STRIDE*page + 32'h00,
                    32'h524b5000 + page + 1);
        host_expect(PAGE_BASE + PAGE_STRIDE*page + 32'h28, page);
        host_expect(PAGE_BASE + PAGE_STRIDE*page + 32'h2c, crc32);
        host_expect(PAGE_BASE + PAGE_STRIDE*page + 32'h04, 32'h0001_0000);

        load_hex_bo(IN_BASE);
        load_hex_bo(OUT_BASE);
        load_hex_command;
        for (index = 0; index < BO_BYTES; index = index + 1)
            expected_bo[index] = 8'd0;
        $readmemh(expected_hex, expected_bo);
        submit_case;
        if (page == 0) begin
            // A second page must refuse a submit while this one is active.
            host_write(PAGE_BASE + PAGE_STRIDE*((page + 1) % N_PAGES) +
                       32'h0c, 32'd1, 2'b10);
        end
        wait_result(poll_cycles);

        if (page_irq[page] !== 1'b1)
            $fatal(1, "page %0d completion line did not assert", page);
        value = 0;
        host_read(PAGE_BASE + PAGE_STRIDE*page + 32'h24, value);
        if (value[7:0] != 8'd0)
            $fatal(1, "page %0d engine fault code=%0d", page, value[7:0]);
        host_expect(PAGE_BASE + PAGE_STRIDE*page + 32'h20, 32'd1);
        host_expect(PAGE_BASE + PAGE_STRIDE*page + 32'h1c, tag);
        host_write(PAGE_BASE + PAGE_STRIDE*page + 32'h0c, 32'd2);

        capture_bo;
        compare_bo;
        if (mismatches != 0 || over_tolerance != 0)
            $fatal(1, "page %0d complete-BO comparison failed: byte mismatches=%0d lanes over tolerance=%0d",
                   page, mismatches, over_tolerance);

        if (page == 0) begin
            // Negative control: tamper one captured non-address command field
            // and require that page to fault instead of producing a result.
            load_hex_command;
            cmd_bytes[32] = cmd_bytes[32] ^ 8'h40;
            for (index = 0; index < cmd_words; index = index + 1) begin
                value = {cmd_bytes[4*index + 3], cmd_bytes[4*index + 2],
                         cmd_bytes[4*index + 1], cmd_bytes[4*index + 0]};
                host_write(CMD_BASE + 4*index, value);
            end
            host_write(PAGE_BASE + 32'h10, CMD_BASE);
            host_write(PAGE_BASE + 32'h14, cmd_words / 2);
            host_write(PAGE_BASE + 32'h18, 32'hbad0c0de);
            host_write(PAGE_BASE + 32'h0c, 32'd1);
            wait_result(poll_cycles);
            host_expect(PAGE_BASE + 32'h20, 32'd0);
            status = 0;
            host_read(PAGE_BASE + 32'h24, status);
            if (status[7:0] == 8'd0)
                $fatal(1, "tampered command stream was accepted");
            $display("PASS PPU_CORPUS_IMAGE negative_code=%0d", status[7:0]);
        end

        $display("PASS PPU_CORPUS page=%0d polls=%0d mismatches=%0d over_tolerance=%0d",
                 page, poll_cycles, mismatches, over_tolerance);
        $finish;
    end

    initial begin
        #100_000_000;
        $fatal(1, "pooling corpus bench watchdog expired");
    end
endmodule
