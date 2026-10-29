// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Configuration-initialized, registered reset for a continuously running clock.
// This is not a clock-stability detector. request_reset is synchronous to clk.
// An initialized FF delay chain avoids a multi-bit counter transition at startup.
// The output is itself registered; no combinational state decode drives reset.
module rk_startup_reset #(
    parameter int unsigned HOLD_CYCLES = 64
) (
    input wire clk,
    input wire request_reset,
    output logic rst_n
);
    localparam int STAGES = (HOLD_CYCLES < 3 || HOLD_CYCLES > 65535) ? 3 : HOLD_CYCLES;
    (* SHREG_EXTRACT="NO" *) logic [STAGES-1:0] release_pipe;

    initial begin
        rst_n = 1'b0;
        release_pipe = '0;
        if (HOLD_CYCLES < 3 || HOLD_CYCLES > 65535)
            $fatal(1, "HOLD_CYCLES must be between 3 and 65535");
    end

    always_ff @(posedge clk) begin
        if (request_reset) begin
            release_pipe <= '0;
            rst_n <= 1'b0;
        end else begin
            release_pipe <= {release_pipe[STAGES-2:0], 1'b1};
            rst_n <= release_pipe[STAGES-1];
        end
    end
endmodule
