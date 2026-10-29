// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Separate USER2-controlled raw-command EW BRAM endpoint. No DDR or PCIe.
// LED0 is pending completion IRQ, LED1 fault, LED2 heartbeat; no pass LED.
module ypcb_jtag_ew_top #(parameter bit LED_ACTIVE_LOW = 1'b0) (
    input wire SYS_CLK,
    output wire [2:0] led_3bits_tri_o
);
    wire clk_ib, clk, rst_n;
    wire tck, capture, shift, update, sel, tdi, tdo;
    wire req_valid, req_ready, rsp_valid, irq, fault;
    wire [603:0] req;
    wire [511:0] rsp_data;
    wire [7:0] rsp_status;
    wire [15:0] rsp_seq;
    logic [25:0] heartbeat;
    initial heartbeat = 0;

    IBUF u_ibuf50 (.I(SYS_CLK), .O(clk_ib));
    BUFG u_bufg50 (.I(clk_ib), .O(clk));
    rk_startup_reset startup (.clk, .request_reset(1'b0), .rst_n);
    (* DONT_TOUCH = "TRUE" *) BSCANE2 #(.JTAG_CHAIN(2)) u_bscan (
        .TCK(tck), .DRCK(), .CAPTURE(capture), .SHIFT(shift), .UPDATE(update),
        .SEL(sel), .TDI(tdi), .TDO(tdo), .RESET(), .RUNTEST(), .TMS()
    );
    // The preserved name/hierarchy is part of mailbox_cdc.tcl's exact scope.
    (* KEEP_HIERARCHY = "TRUE" *) otpu_jtag_mailbox u_mailbox (
        .clk, .rst(!rst_n), .tck, .capture, .shift, .update, .sel, .tdi, .tdo,
        .req_valid, .req_ready, .req, .rsp_valid, .rsp_data, .rsp_status, .rsp_seq
    );
    rk_jtag_ew_bram #(.BYTES(1048576), .BASE(32'h10000000), .TIMEOUT_CYCLES(65536)) endpoint (
        .clk, .rst_n, .req_valid, .req_ready, .req,
        .rsp_valid, .rsp_data, .rsp_status, .rsp_seq, .irq, .fault
    );
    always_ff @(posedge clk) begin
        if (!rst_n) heartbeat <= 0;
        else heartbeat <= heartbeat + 1'b1;
    end
    assign led_3bits_tri_o = {heartbeat[25], fault, irq} ^ {3{LED_ACTIVE_LOW}};
endmodule
