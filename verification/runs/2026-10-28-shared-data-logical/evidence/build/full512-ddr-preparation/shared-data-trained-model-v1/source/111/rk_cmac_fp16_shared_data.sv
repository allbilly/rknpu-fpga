// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Exact data-side expressions from the original cell, computed once per frame.
// Weight-side preparation and maximum alignment remain per kernel. This is
// combinational integer operand encoding, with no new rounding boundary.
module rk_cmac_fp16_shared_data #(parameter int unsigned ATOMIC_C=32) (
    input wire [ATOMIC_C*16-1:0] data,
    input wire [ATOMIC_C-1:0] mask,
    output wire [ATOMIC_C*16-1:0] operand,
    output wire [ATOMIC_C*3-1:0] exponent,
    output wire [ATOMIC_C-1:0] nonzero,
    output logic nan_found,
    output logic [10:0] nan_payload
);
    for(genvar i=0;i<ATOMIC_C;i=i+1)begin: lanes
        wire [15:0] a=data[i*16+:16];
        wire [14:0] magnitude={4'd0,(a[14:10]!=0),a[9:0]} << (a[14:10]==0 ? 2'd1:a[11:10]);
        assign operand[i*16+:16]={a[15],magnitude};
        assign exponent[i*3+:3]=a[14:12];
        assign nonzero[i]=mask[i]&&(a[14:0]!=0);
    end
    always @* begin
        nan_found=0;nan_payload=0;
        for(integer i=0;i<ATOMIC_C;i=i+1)
            if(!nan_found&&mask[i]&&data[i*16+10+:5]==31&&data[i*16+:10]!=0)begin
                nan_found=1;nan_payload={data[i*16+15],data[i*16+:10]};
            end
    end
endmodule
