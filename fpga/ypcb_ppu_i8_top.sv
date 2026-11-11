// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// YPCB_00338_1P1 BRAM-only board image containing the first captured pooling
// RTL in this repository: the frozen signed-INT8 C16 H2 W2 maximum task runs
// autonomously at power-on, and the result is held on the LEDs.
//
// Board I/O is exactly the audited clock and LED pins (see fpga/ypcb.xdc semantics,
// repeated here without the external R28 reset because this image restarts
// only by reconfiguration).
//
// This is a bring-up image, not the conv/pool framework, not DDR execution and
// not a qualification result. It deliberately contains no PCIe, MIG or host
// driver: AXI-Lite/BRAM transport only.
module ypcb_ppu_i8_top #(
    parameter bit LED_ACTIVE_LOW = 1'b0,
    parameter int unsigned RESET_HOLD_CYCLES = 64,
    parameter int unsigned TIMEOUT_CYCLES = 2048,
    parameter int unsigned WATCHDOG_CYCLES = 1_000_000
) (
    input  wire SYS_CLK,
    output wire [2:0] led_3bits_tri_o
);
    wire reset_n;
    logic [25:0] heartbeat;
    initial heartbeat = 0;

    rk_startup_reset #(.HOLD_CYCLES(RESET_HOLD_CYCLES)) startup (
        .clk(SYS_CLK), .request_reset(1'b0), .rst_n(reset_n)
    );

    always_ff @(posedge SYS_CLK) begin
        if (!reset_n) heartbeat <= 26'd0;
        else heartbeat <= heartbeat + 1'b1;
    end

    wire pass, fail;
    // Kept for in-system debug visibility; the LEDs carry pass/fail only.
    /* verilator lint_off UNUSEDSIGNAL */
    (* MARK_DEBUG="TRUE" *) wire [7:0] error_code;
    /* verilator lint_on UNUSEDSIGNAL */

    rk_ppu_pool_self_test #(
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES),
        .WATCHDOG_CYCLES(WATCHDOG_CYCLES)
    ) self_test (
        .clk(SYS_CLK), .rst_n(reset_n),
        .pass, .fail, .error_code
    );

    // pass -> LED0 only, fail -> LED1 only, heartbeat on LED2. The captured task
    // is short, so the heartbeat continues to blink after a result is latched.
    assign led_3bits_tri_o = {heartbeat[25], fail, pass} ^ {3{LED_ACTIVE_LOW}};
endmodule
