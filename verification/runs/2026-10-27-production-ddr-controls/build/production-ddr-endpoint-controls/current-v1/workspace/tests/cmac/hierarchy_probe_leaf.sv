// SPDX-License-Identifier: MIT
module hierarchy_probe_leaf #(parameter int unsigned WIDTH=32) (
    input wire clk, rst_n,
    input wire [WIDTH-1:0] data,
    output logic [WIDTH-1:0] result
);
    /* verilator hier_block */
    always_ff @(posedge clk or negedge rst_n)
        if (!rst_n) result <= 0;
        else result <= data + WIDTH'(1);
endmodule
