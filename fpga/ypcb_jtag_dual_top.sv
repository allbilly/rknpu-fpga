// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Pin-free host-drivable image: the USER2 JTAG mailbox drives the dual-endpoint
// AXI4-Lite slave.
//
// The dual-endpoint image itself cannot become a bitstream because its 32-bit
// AXI slave is a top-level port with no board pins (`NSTD-1`/`UCIO-1`). This top
// removes that blocker without changing the endpoint RTL: the only package pins
// are the audited clock and the three LEDs, which the board files do define.
//
// Topology:
//
//   BSCANE2 (USER2) -> otpu_jtag_mailbox -> rk_jtag_axil_bridge -> AXI4-Lite
//                                                                     |
//                                            ypcb_dual_endpoint_top <--
//
// The mailbox frame opcodes are the frozen OpenTPU ones:
//   1 register read, 2 register write, 3 64-byte read, 4 64-byte write.
// The adapter maps opcodes 3/4 onto 16 consecutive 32-bit AXI beats, so a host
// loads BOs and reads results through the same memory window the simulation
// replay already proves. No new arithmetic, layout or address translation is
// introduced: the words the host writes are the words the engines read.
//
// LEDs: LED0 = conv completion/fault, LED1 = pooling completion/fault,
//       LED2 = heartbeat. Polarity is the explicit LED_ACTIVE_LOW parameter.
module ypcb_jtag_dual_top #(
    parameter bit LED_ACTIVE_LOW = 1'b0,
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned BRIDGE_TIMEOUT_CYCLES = 65536
) (
    input  wire SYS_CLK,
    output wire [2:0] led_3bits_tri_o
);
    wire clk_ib, clk, reset_n;
    wire tck, capture, shift, update, sel, tdi, tdo;

    // The audited board has a single-ended 50 MHz oscillator; route it through
    // IBUF/BUFG exactly like the other images in this repository.
    IBUF u_ibuf50 (.I(SYS_CLK), .O(clk_ib));
    BUFG u_bufg50 (.I(clk_ib), .O(clk));
    rk_startup_reset #(.HOLD_CYCLES(64)) startup (
        .clk(clk), .request_reset(1'b0), .rst_n(reset_n)
    );

    wire req_valid, req_ready, rsp_valid;
    wire conv_irq, pool_irq, gemm_irq;
    wire [603:0] req;
    wire [511:0] rsp_data;
    wire [7:0] rsp_status;
    wire [15:0] rsp_seq;
    wire fault;

    (* DONT_TOUCH = "TRUE" *) BSCANE2 #(.JTAG_CHAIN(2)) u_bscan (
        .TCK(tck), .DRCK(), .CAPTURE(capture), .SHIFT(shift), .UPDATE(update),
        .SEL(sel), .TDI(tdi), .TDO(tdo), .RESET(), .RUNTEST(), .TMS()
    );
    // The preserved hierarchy is part of fpga/host/mailbox_cdc.tcl's exact
    // scope: the CDC constraints address u_mailbox/held_reg* and the
    // synchronizer chains by name.
    (* KEEP_HIERARCHY = "TRUE" *) otpu_jtag_mailbox u_mailbox (
        .clk, .rst(!reset_n), .tck, .capture, .shift, .update, .sel, .tdi,
        .tdo,
        .req_valid, .req_ready, .req,
        .rsp_valid, .rsp_data, .rsp_status, .rsp_seq
    );

    wire [31:0] s_axil_awaddr, s_axil_wdata, s_axil_araddr, s_axil_rdata;
    wire [2:0] s_axil_awprot, s_axil_arprot;
    wire [3:0] s_axil_wstrb;
    wire [1:0] s_axil_bresp, s_axil_rresp;
    wire s_axil_awvalid, s_axil_awready, s_axil_wvalid, s_axil_wready;
    wire s_axil_bvalid, s_axil_bready, s_axil_arvalid, s_axil_arready;
    wire s_axil_rvalid, s_axil_rready;

    rk_jtag_axil_bridge #(.TIMEOUT_CYCLES(BRIDGE_TIMEOUT_CYCLES)) bridge (
        .clk, .rst_n(reset_n),
        .req_valid, .req_ready, .req,
        .rsp_valid, .rsp_data, .rsp_status, .rsp_seq, .fault,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready
    );

    // The mailbox adapter supplies the host transaction; the endpoint top's own
    // startup reset must not run a second release, so its RESET_HOLD_CYCLES is
    // kept at the minimum and the top-level reset is the authoritative one.
    ypcb_dual_endpoint_top #(
        .LED_ACTIVE_LOW(LED_ACTIVE_LOW),
        .RESET_HOLD_CYCLES(64),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) image (
        .SYS_CLK(clk),
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready,
        .conv_irq, .pool_irq, .gemm_irq,
        .led_3bits_tri_o()
    );

    // LED0 = conv completion or fault, LED1 = pooling completion or fault,
    // LED2 = heartbeat. `fault` from the adapter is included because a
    // quarantined bridge must be visible without a host.
    logic [25:0] heartbeat;
    initial heartbeat = 0;
    always_ff @(posedge clk) begin
        if (!reset_n) heartbeat <= 26'd0;
        else heartbeat <= heartbeat + 1'b1;
    end

    assign led_3bits_tri_o = {heartbeat[25],
                               pool_irq | gemm_irq | fault,
                               conv_irq | fault}
                             ^ {3{LED_ACTIVE_LOW}};
endmodule
