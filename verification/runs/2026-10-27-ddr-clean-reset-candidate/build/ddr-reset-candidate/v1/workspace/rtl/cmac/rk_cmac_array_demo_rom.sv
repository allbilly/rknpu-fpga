// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module rk_cmac_array_demo_rom (
    input logic clk,
    input logic [11:0] index,
    output logic [15:0] initial_value,expected_value
);
    (* rom_style="block" *) logic [31:0] contents [0:4095];
    logic [31:0] value;
    initial $readmemh("tests/cmac/array_data/board_rom.hex",contents);
    always @(posedge clk) value<=contents[index];
    assign initial_value=value[15:0];
    assign expected_value=value[31:16];
endmodule
