// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Configuration-lifetime mailbox. Its startup state is clock-local and INIT
// based; no client, MIG, link, PERST or TAP reset can discard an offered frame.
// BSCANE2 selection lives in the physical top, not this transport component.
module rk_retained_jtag_mailbox #(
    parameter int unsigned HOLD_CYCLES = 64
) (
    input wire clk,
    input wire tck, capture, shift, update, sel, tdi,
    output wire tdo,
    output wire power_rst_n,
    output wire req_valid,
    input wire req_ready,
    output wire [603:0] req,
    input wire rsp_valid,
    input wire [511:0] rsp_data,
    input wire [7:0] rsp_status,
    input wire [15:0] rsp_seq
);
    wire offered;
    wire [603:0] offered_frame;
    rk_startup_reset #(.HOLD_CYCLES(HOLD_CYCLES)) startup (
        .clk(clk), .request_reset(1'b0), .rst_n(power_rst_n)
    );
    otpu_jtag_mailbox mailbox (
        .clk(clk), .rst(!power_rst_n),
        .tck(tck), .capture(capture), .shift(shift), .update(update),
        .sel(sel), .tdi(tdi), .tdo(tdo),
        .req_valid(offered), .req_ready(power_rst_n && req_ready),
        .req(offered_frame), .rsp_valid(rsp_valid),
        .rsp_data(rsp_data), .rsp_status(rsp_status), .rsp_seq(rsp_seq)
    );
    assign req_valid = power_rst_n && offered;
    assign req = power_rst_n ? offered_frame : 604'b0;
endmodule
