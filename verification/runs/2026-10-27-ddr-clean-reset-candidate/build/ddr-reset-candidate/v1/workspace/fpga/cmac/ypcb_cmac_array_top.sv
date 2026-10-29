// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Candidate 50 MHz YPCB BRAM-only C32/K16 CMAC demo. No PCIe, DDR, flash or fan outputs.
module ypcb_cmac_array_top #(parameter bit LED_ACTIVE_LOW=1'b0) (
    input wire SYS_CLK,SYS_RSTN,
    output wire [2:0] led_3bits_tri_o
);
    (* ASYNC_REG="TRUE" *) reg [1:0] reset_delay;
    (* ASYNC_REG="TRUE" *) reg reset_n;
    reg [25:0] heartbeat;
    wire pass,fail;
    (* MARK_DEBUG="TRUE" *) wire [7:0] unused_error_code;
    initial begin reset_delay=0;reset_n=0;heartbeat=0;end
    always @(posedge SYS_CLK or negedge SYS_RSTN) begin
        if (!SYS_RSTN) begin reset_delay<=0;reset_n<=0;end
        else begin reset_delay<={reset_delay[0],1'b1};reset_n<=reset_delay[1];end
    end
    always @(posedge SYS_CLK or negedge reset_n) begin
        if (!reset_n) heartbeat<=0;
        else heartbeat<=heartbeat+1'b1;
    end
    rk_cmac_array_bram_demo demo(.clk(SYS_CLK),.rst_n(reset_n),.pass,.fail,.error_code(unused_error_code));
    assign led_3bits_tri_o={heartbeat[25],fail,pass}^{3{LED_ACTIVE_LOW}};
endmodule
