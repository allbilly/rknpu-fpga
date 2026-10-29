// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// YPCB_00338_1P1 BRAM-only bring-up top. Board source identifies a 50 MHz
// single-ended clock. No DDR3, PCIe, flash or fan-control outputs are instantiated.
// LED electrical polarity is intentionally configurable, not assumed verified.
module ypcb_top #(
    parameter bit LED_ACTIVE_LOW = 1'b0
) (
    input wire SYS_CLK,
    input wire SYS_RSTN,
    output wire [2:0] led_3bits_tri_o
);
    (* ASYNC_REG="TRUE" *) reg [2:0] reset_pipe;
    reg [25:0] heartbeat;
    wire pass,fail;
    (* MARK_DEBUG="TRUE" *) wire [7:0] unused_error_code;
    initial begin
        reset_pipe = 0;
        heartbeat = 0;
    end
    // Asynchronous assertion, synchronous deassertion to the only clock domain.
    always @(posedge SYS_CLK or negedge SYS_RSTN) begin
        if (!SYS_RSTN) reset_pipe<=0;
        else reset_pipe<={reset_pipe[1:0],1'b1};
    end
    always @(posedge SYS_CLK) begin
        if (!reset_pipe[2]) heartbeat<=0;
        else heartbeat<=heartbeat+1;
    end
    rk_ew_dma_demo demo(.clk(SYS_CLK),.rst_n(reset_pipe[2]),.pass(pass),.fail(fail),.error_code(unused_error_code));
    wire [2:0] indicators={heartbeat[25],fail,pass};
    assign led_3bits_tri_o=indicators ^ {3{LED_ACTIVE_LOW}};
endmodule
