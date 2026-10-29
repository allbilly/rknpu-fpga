// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Test-only pattern leaf. No transport, memory owner or capacity qualification.
// Simulation unknown checks do not model physical metastability.
module rk_ddr_capacity_pattern (
    input  logic [30:0] address,
    input  logic [31:0] seed,
    input  logic        trial,
    output logic        valid,
    output logic [511:0] data
);
    always_comb begin
        valid = address[5:0] == 6'b0;
`ifndef SYNTHESIS
        if ((^address) === 1'bx || (^seed) === 1'bx || (^trial) === 1'bx)
            valid = 1'b0;
`endif
    end
    for (genvar lane = 0; lane < 16; lane++) begin : pattern_lane
        localparam logic [31:0] LANE_SALT = 32'(lane * 32'h9e3779b9);
        assign data[lane*32 +: 32] = {7'b0,address[30:6]} ^ seed ^
                                    LANE_SALT ^ {32{trial}};
    end
endmodule
