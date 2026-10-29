// Declaration-only interface check. NEVER select for synthesis or execute.
`timescale 1ns/1ps
module IBUF(input wire I,output wire O); endmodule
module BUFG(input wire I,output wire O); endmodule
module BSCANE2 #(parameter JTAG_CHAIN=2)(output wire CAPTURE,DRCK,RESET,RUNTEST,SEL,SHIFT,TCK,TDI,TMS,UPDATE,input wire TDO); endmodule
