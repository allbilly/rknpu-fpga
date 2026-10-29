// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Separate EW BRAM profile: no external R28 reset input is consumed.
// Restart this autonomous image by reconfiguration. No JTAG runtime is implied.
module ypcb_ew_startup_top #(
    parameter bit LED_ACTIVE_LOW = 1'b0,
    parameter int unsigned RESET_HOLD_CYCLES = 64
) (
    input wire SYS_CLK,
    output wire [2:0] led_3bits_tri_o
);
    wire reset_n, pass, fail;
    (* MARK_DEBUG="TRUE" *) wire [7:0] unused_error_code;
    logic [25:0] heartbeat;
    initial heartbeat = 0;

    rk_startup_reset #(.HOLD_CYCLES(RESET_HOLD_CYCLES)) startup (
        .clk(SYS_CLK), .request_reset(1'b0), .rst_n(reset_n)
    );
    always_ff @(posedge SYS_CLK) begin
        if (!reset_n) heartbeat <= 0;
        else heartbeat <= heartbeat + 1'b1;
    end
    rk_ew_dma_demo demo (
        .clk(SYS_CLK), .rst_n(reset_n), .pass, .fail,
        .error_code(unused_error_code)
    );
    assign led_3bits_tri_o = {heartbeat[25], fail, pass} ^ {3{LED_ACTIVE_LOW}};
endmodule
