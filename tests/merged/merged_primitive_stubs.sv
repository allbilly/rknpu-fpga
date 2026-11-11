// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// SIMULATION-ONLY Xilinx primitive models for the merged-image scaffold bench.
//
// `ypcb_merged_top` (like the adopted pin-free tops) instantiates IBUF/BUFG and
// a single BSCANE2. Vivado supplies those primitives; Icarus does not. This file
// is compiled only by `tests/merged/test_merged_scaffold_bench.py` and by manual
// Icarus runs -- it is never part of a synthesis source list.
//
// The BSCANE2 model leaves the JTAG user pins tied low so the testbench can
// `force` them from its own TCK/DR-signal driver (see tests/tb_ypcb_merged_top.sv
// and tests/host/mailbox_scan.svh). TDO is passed through unchanged to the
// user-logic input. There is no TAP model, no IDCODE/DR behaviour and no
// hardware claim: this is a scaffold bench, not the physical USER2 chain.

// Port directions match the real primitive: the user-logic pins TCK/TDI/TMS/
// DRCK/SEL/CAPTURE/SHIFT/UPDATE/RESET/RUNTEST are primitive outputs, and TDO is
// the primitive input driven by the user logic. The bench forces the five DR
// pins it drives (TCK/CAPTURE/SHIFT/UPDATE/SEL/TDI) and reads TDO through the
// hierarchy; a synthesis build uses the real unisim primitive instead.
module BSCANE2 #(parameter integer JTAG_CHAIN = 1) (
    output wire TCK,
    output wire DRCK,
    output wire TDI,
    output wire TMS,
    output wire SEL,
    output wire CAPTURE,
    output wire SHIFT,
    output wire UPDATE,
    output wire RESET,
    output wire RUNTEST,
    input  wire TDO
);
    assign TCK = 1'b0;
    assign DRCK = 1'b0;
    assign TDI = 1'b0;
    assign TMS = 1'b0;
    assign SEL = 1'b0;
    assign CAPTURE = 1'b0;
    assign SHIFT = 1'b0;
    assign UPDATE = 1'b0;
    assign RESET = 1'b0;
    assign RUNTEST = 1'b0;
endmodule

module IBUF (input wire I, output wire O);
    assign O = I;
endmodule

module BUFG (input wire I, output wire O);
    assign O = I;
endmodule
