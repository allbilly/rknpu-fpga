// Separate startup candidate with registered BRAM controls; no prior image approval.
// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Separate full C32/K16 BRAM profile. Select the qualified DSP-prefix sources
// and generated join in the profile manifest; this wrapper changes no math.
// Startup/reconfiguration only: no external reset input or runtime reset opcode.
module ypcb_cmac_array_regmem_top #(
    parameter bit LED_ACTIVE_LOW = 1'b0,
    parameter int unsigned RESET_HOLD_CYCLES = 64
) (
    input wire SYS_CLK,
    output wire [2:0] led_3bits_tri_o
);
    wire reset_n, pass, fail;
    (* MARK_DEBUG="TRUE" *) wire [7:0] unused_error_code;
    reg [25:0] heartbeat;
    initial heartbeat = 0;

    rk_startup_reset #(.HOLD_CYCLES(RESET_HOLD_CYCLES)) startup (
        .clk(SYS_CLK), .request_reset(1'b0), .rst_n(reset_n)
    );
    always @(posedge SYS_CLK) begin
        if (!reset_n) heartbeat <= 0;
        else heartbeat <= heartbeat + 1'b1;
    end
    rk_cmac_array_bram_demo_regmem demo (
        .clk(SYS_CLK), .rst_n(reset_n), .pass, .fail,
        .error_code(unused_error_code)
    );
    assign led_3bits_tri_o = {heartbeat[25], fail, pass} ^ {3{LED_ACTIVE_LOW}};
endmodule
