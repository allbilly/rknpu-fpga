// INTERFACE ELABORATION ONLY: no behavior. NEVER synthesize.
`timescale 1ns/1ps
module rk_startup_reset (
    input wire clk,
    input wire request_reset,
    output wire rst_n
);
endmodule
// INTERFACE ELABORATION ONLY: no behavior. NEVER synthesize.
`timescale 1ns/1ps
module otpu_jtag_mailbox (
    input wire capture,
    input wire clk,
    output wire [603:0] req,
    input wire req_ready,
    output wire req_valid,
    input wire [511:0] rsp_data,
    input wire [15:0] rsp_seq,
    input wire [7:0] rsp_status,
    input wire rsp_valid,
    input wire rst,
    input wire sel,
    input wire shift,
    input wire tck,
    input wire tdi,
    output wire tdo,
    input wire update
);
endmodule
