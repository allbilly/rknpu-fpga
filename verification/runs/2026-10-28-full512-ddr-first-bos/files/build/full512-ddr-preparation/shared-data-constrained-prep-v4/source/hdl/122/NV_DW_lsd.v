// ================================================================
// NVDLA Open Source Project
// Copyright(c) 2016 - 2017 NVIDIA Corporation. Licensed under the
// NVDLA Open Hardware License; see the donor distribution LICENSE.
// ================================================================
// Derived from hw/vmod/vlibs/NV_DW_lsd.v at 8e06b1b9d85aab65b40d43d08eec5ea4681ff715.
// Compatibility change: statically bounded loop, explicit sizing. The original
// loop exits at its first transition or at i==0. This version visits the same
// indices and freezes after that same point. Used only at widths 36 and 44.
`timescale 1ns/1ps
module NV_DW_lsd (a, dec, enc);
    parameter a_width=8;
    parameter b_width=a_width-1;
    localparam enc_width=((a_width>16)?((a_width>64)?((a_width>128)?8:7):((a_width>32)?6:5)):((a_width>4)?((a_width>8)?4:3):((a_width>2)?2:1)));
    input [a_width-1:0] a;
    output [a_width-1:0] dec;
    output [enc_width-1:0] enc;
    initial begin
        if (a_width<2 || a_width>256 || b_width!=a_width-1) $fatal(1,"unsupported leading-sign-detector parameters");
    end
    function [enc_width-1:0] DWF_lsd_enc(input [a_width-1:0] value);
        reg done;
        reg [enc_width-1:0] result;
        begin
            done=0;result=enc_width'(a_width-1);
            for (integer i=a_width-2;i>=0;i=i-1) begin
                if (!done && value[i+1]!=value[i]) begin
                    result=enc_width'(a_width-i-2);done=1;
                end
            end
            DWF_lsd_enc=result;
        end
    endfunction
    assign enc=DWF_lsd_enc(a);
    assign dec={{(a_width-1){1'b0}},1'b1} << (b_width-int'(enc));
endmodule
