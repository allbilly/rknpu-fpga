// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Retained-domain link epoch. 'up' must already be synchronized into clk.
// Reset only with the joint backend/frontend epoch, never PCIe link reset.
module rk_transport_epoch_guard #(
    parameter integer FRESH_CYCLES=4
) (
    input wire clk,rst_n,up,
    output wire ready,
    output logic failed,
    output logic seen_up
);
    localparam integer COUNT_BITS=(FRESH_CYCLES>=2 && FRESH_CYCLES<=65536) ?
        $clog2(FRESH_CYCLES+1) : 1;
    logic [COUNT_BITS-1:0] fresh;
    logic armed;
    assign ready=rst_n&&armed&&!failed&&(up===1'b1);
    initial if(FRESH_CYCLES<2 || FRESH_CYCLES>65536)
        $fatal(1,"Invalid transport epoch freshness parameter");
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin fresh<=0;armed<=0;failed<=0;seen_up<=0;end
        else if(!failed)begin
            if(up===1'b1)begin
                seen_up<=1;
                if(!armed)begin
                    if(fresh==COUNT_BITS'(FRESH_CYCLES-1))begin
                        fresh<=COUNT_BITS'(FRESH_CYCLES);armed<=1;
                    end else fresh<=fresh+1'b1;
                end
            end else begin
                fresh<=0;
                // Even a short first up interval could have admitted part of
                // an AXI transaction at the IP/CDC boundary. Never re-arm it.
                if(seen_up)begin failed<=1;armed<=0;end
            end
        end
    end
endmodule
