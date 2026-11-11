// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Cheap mailbox->AXI scaffold bench for the Image-A top `ypcb_merged_top`.
//
// The bench drives the frozen OpenTPU USER2 mailbox frame format through the
// reviewed `rk_jtag_axil_bridge` into the Image-A address decode, and checks the
// S1 scaffolding only: page identities (runtime conv page + GEMM page), scratch
// isolation, the shared 64 KiB window, the `memory_ready` status line, explicit
// SLVERR holes, and a negative control for an unwritten page. It is NOT a
// family replay: the page slaves are `merged_page_stub` placeholders by design.
// Image B (pooling + EW) has its own separate top and no bench yet.
//
// Simulation-only glue: `tests/merged/merged_primitive_stubs.sv` provides the
// Xilinx IBUF/BUFG/BSCANE2 models; this bench forces the BSCANE2 user pins with
// its own TCK/DR signals (tests/host/mailbox_scan.svh, the shared mailbox driver
// also used by tests/tb_ypcb_jtag_dual.sv). Nothing here claims a physical TAP.
//
// Run (from the repo root):
//   iverilog -g2012 -o /tmp/merged.vvp -s tb_ypcb_merged_top \
//       tests/merged/merged_primitive_stubs.sv \
//       $(python3 -c "import tools.merged.vivado_merged_image as t; \
//            print(' '.join(n for n in t.load_spec()['sources']))") \
//       tests/tb_ypcb_merged_top.sv
//   vvp /tmp/merged.vvp
module tb_ypcb_merged_top #(
    // One downstream-error address per run: a SLVERR quarantines the reviewed
    // bridge by design, so only one error transaction can be exercised in a
    // session. The wrapper test runs indices 0..3 (one bench run each).
    parameter integer HOLE_INDEX = 0
);
    localparam logic [31:0] PAGE_RKCV = 32'h0001_0000;
    localparam logic [31:0] PAGE_RKCM = 32'h0001_1000;
    localparam logic [31:0] ID_RKCV = 32'h524b_4356;
    localparam logic [31:0] ID_RKCM = 32'h524b_434d;

    logic clk = 0;
    always #10 clk = ~clk;

    wire [2:0] leds;

    ypcb_merged_top #(.LED_ACTIVE_LOW(1'b0)) dut (
        .SYS_CLK(clk),
        .led_3bits_tri_o(leds)
    );

    // Simulation-only: drive the BSCANE2 user pins from the local scan driver.
    logic tck = 0, capture = 0, shift = 0, update = 0, sel = 0, tdi = 0;
    wire tdo = dut.u_bscan.TDO;
    initial begin
        force dut.u_bscan.TCK = tck;
        force dut.u_bscan.CAPTURE = capture;
        force dut.u_bscan.SHIFT = shift;
        force dut.u_bscan.UPDATE = update;
        force dut.u_bscan.SEL = sel;
        force dut.u_bscan.TDI = tdi;
    end

    `include "host/mailbox_scan.svh"

    logic [15:0] sequence_q = 16'h0;
    integer frames = 0;
    integer checks = 0;
    logic [31:0] value;
    logic [511:0] frame_data, readback;

    // One mailbox frame, one transaction; poll for the matching sequence.
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
                $fatal(1, "MERGED_SCAFFOLD frame %0d op=%0d status=%02x expected=%02x",
                       sequence_q, opcode, received[519:512], status_expected);
            result = received[511:0];
            frames = frames + 1;
            checks = checks + 1;
        end
    endtask

    task automatic write_word(input logic [31:0] address, input logic [31:0] data,
                              input logic [7:0] status_expected = 0);
        logic [511:0] unused;
        command(8'd2, address, {480'h0, data}, 4'hf, unused, status_expected);
    endtask

    task automatic read_word(input logic [31:0] address, output logic [31:0] data,
                             input logic [7:0] status_expected = 0);
        logic [511:0] value512;
        command(8'd1, address, 512'h0, 4'hf, value512, status_expected);
        data = value512[31:0];
    endtask

    task automatic write_block(input logic [31:0] address, input logic [511:0] data,
                               input logic [7:0] status_expected = 0);
        logic [511:0] unused;
        command(8'd4, address, data, 4'hf, unused, status_expected);
    endtask

    task automatic read_block(input logic [31:0] address, output logic [511:0] data,
                              input logic [7:0] status_expected = 0);
        command(8'd3, address, 512'h0, 4'hf, data, status_expected);
    endtask

    task automatic expect_word(input logic [31:0] address, input logic [31:0] expected,
                               input string label);
        read_word(address, value);
        if (value !== expected)
            $fatal(1, "MERGED_SCAFFOLD %s: address=%08x got=%08x expected=%08x",
                   label, address, value, expected);
        checks = checks + 1;
    endtask

    task automatic expect_block(input logic [31:0] address, input logic [511:0] expected,
                                input string label);
        read_block(address, readback);
        if (readback !== expected)
            $fatal(1, "MERGED_SCAFFOLD %s: block at %08x differs (got %0128x expected %0128x)",
                   label, address, readback, expected);
        checks = checks + 1;
    endtask

    integer i;
    logic [511:0] pattern_a, pattern_b;

    initial begin : TEST
        // The top's startup reset releases after 64 SYS_CLK cycles; leave margin
        // before the first JTAG frame so the mailbox backend is out of reset.
        repeat (200) @(posedge clk);

        // ---- 1. page-presence: every Image-A page answers with its identity ---
        expect_word(PAGE_RKCV, ID_RKCV, "runtime conv page identity");
        expect_word(PAGE_RKCV + 32'h4, 32'h0001_0000, "runtime conv page ABI version");
        expect_word(PAGE_RKCM, ID_RKCM, "GEMM page identity");

        // ---- 2. arbitration status line: host window idle -> memory_ready=1 ---
        // STATUS bit4 is the page's memory_ready mirror (rk_job_control layout).
        read_word(PAGE_RKCV + 32'h8, value);
        if (value[4] !== 1'b1)
            $fatal(1, "MERGED_SCAFFOLD runtime page memory_ready idle=%b status=%08x",
                   value[4], value);
        checks = checks + 1;

        // ---- 3. register round-trip + page isolation ----------------------
        // S2 attached the real CMAC GEMM page, so 0x04 is its read-only
        // ABI_VERSION (the retired stub answered a writable scratch word here).
        expect_word(PAGE_RKCM + 32'h4, 32'h0001_0000, "GEMM ABI version");
        // Its JOB_TAG register (0x18) is the writable round-trip control.
        write_word(PAGE_RKCM + 32'h18, 32'h1111_2222);
        expect_word(PAGE_RKCM + 32'h18, 32'h1111_2222, "GEMM JOB_TAG round-trip");
        // The runtime page's START_ADDRESS register must be writable and readable
        // (the real wrapper and the ABI-reference model share this layout).
        write_word(PAGE_RKCV + 32'h10, 32'h0000_0100);
        expect_word(PAGE_RKCV + 32'h10, 32'h0000_0100, "runtime page START_ADDRESS round-trip");
        // Read-only identity registers ignore writes and never alias another page.
        write_word(PAGE_RKCV + 32'h4, 32'hdead_beef);
        expect_word(PAGE_RKCV + 32'h4, 32'h0001_0000, "ABI register stays read-only");
        expect_word(PAGE_RKCM + 32'h18, 32'h1111_2222, "GEMM page register not aliased");

        // ---- 4. shared 64 KiB window: first and last 64-byte line ------------
        pattern_a = 512'h0123_4567_89ab_cdef_fedc_ba98_7654_3210_dead_beef_0bad_f00d_1357_9bdf_2468_ace0;
        pattern_b = 512'hfeed_face_cafe_babe_0011_2233_4455_6677_8899_aabb_ccdd_eeff_10_20_30_40;
        write_block(32'h0000_0000, pattern_a);
        expect_block(32'h0000_0000, pattern_a, "window first line");
        write_block(32'h0000_FFC0, pattern_b);
        expect_block(32'h0000_FFC0, pattern_b, "window last line");
        write_word(32'h0000_FFF8, 32'hCAFE_BABE);
        expect_word(32'h0000_FFF8, 32'hCAFE_BABE, "window last word");

        // ---- 5. explicit SLVERR hole (never a silent alias) ------------------
        // The reviewed bridge quarantines on a downstream AXI error (it returns
        // exactly one status-7 response, then refuses further requests). That is
        // the documented behaviour, not a scaffold bug; so exactly one hole is
        // exercised per session and the quarantine itself is checked.
        case (HOLE_INDEX)
            0: read_word(32'h0001_2000, value, 8'd7);        // page gap (Image B space)
            1: read_word(32'h0002_0000, value, 8'd7);        // pooled/EW space in Image A
            2: read_word(32'h1000_1000, value, 8'd7);        // EW aperture lives in Image B
            3: write_word(32'h000F_FFFC, 32'h0, 8'd7);       // low page space hole
            default: $fatal(1, "MERGED_SCAFFOLD invalid HOLE_INDEX %0d", HOLE_INDEX);
        endcase

        // ---- 6. the bridge is quarantined: a new sequence gets no response ---
        sequence_q = sequence_q + 1;
        scan_frame({36'b0, 32'h4f54504a, sequence_q, 8'd1, 4'hf,
                    32'h0001_0000, 512'h0}, readback);
        if (readback[567:536] === 32'h4f54504a &&
            readback[535:520] === sequence_q)
            $fatal(1, "MERGED_SCAFFOLD bridge recovered instead of staying quarantined");
        // The top's fault LED output must be active after the downstream error.
        // (LED polarity 0: fault is LED1 for pooling/GEMM/EW scenarios and the
        // conv LED for the conv interrupt; the bridge fault is ORed into both.)
        if (leds[0] !== 1'b1 && leds[1] !== 1'b1)
            $fatal(1, "MERGED_SCAFFOLD bridge fault not visible on the LEDs");

        $display("PASS YPCB_MERGED_SCAFFOLD image_a=1 hole=%0d frames=%0d checks=%0d",
                 HOLE_INDEX, frames, checks);
        $finish;
    end

    // Fallback watchdog. The real page made this bench much slower: a full run
    // is ~6 s of SIMULATED time (each mailbox frame is 640 JTAG scan cycles at
    // ~167 ns and the bench issues ~19 frames per hole), which takes 1-2 min of
    // wall time. `timescale 1ns/1ps` means the delay below is in ns, so it must
    // be well above 6 s simulated; the earlier #10_000_000 (= 10 ms) fired
    // before the first section and ended the run silently.
    initial begin
        #30_000_000;   // 30 ms simulated: ~5x the observed 6.2 ms full run
        $fatal(1, "MERGED_SCAFFOLD timeout after %0d checks", checks);
    end
endmodule
