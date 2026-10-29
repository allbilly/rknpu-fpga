// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Test-only pin adapter for the unchanged nvdlav1 C64 MAC cell.
// No hierarchical forcing, arithmetic replacement, or production interface.
module tb_nvdla_fp16_mac #(
    parameter integer ATOMIC_C=32,ATOMIC_K=16
);
    localparam integer BITS=ATOMIC_C*16+ATOMIC_K*ATOMIC_C*16+ATOMIC_C+ATOMIC_K*ATOMIC_C+ATOMIC_K*44;
    reg clk,rst_n=0;
    reg [1023:0] dat_actv_data,wt_actv_data;
    reg [63:0] dat_actv_nan,wt_actv_nan,dat_pre_mask,wt_sd_mask;
    reg [127:0] dat_actv_nz,wt_actv_nz;
    reg [103:0] dat_actv_pvld=0,wt_actv_pvld=0;
    reg [191:0] dat_pre_exp,wt_sd_exp;
    reg dat_pre_pvld=0,dat_pre_stripe_st=0,dat_pre_stripe_end=0,wt_sd_pvld=0;
    wire [175:0] mac_out_data;
    wire mac_out_nan,mac_out_pvld;
    reg [BITS-1:0] vectors[0:511];
    reg [ATOMIC_C*16-1:0] data;
    reg [ATOMIC_C*ATOMIC_K*16-1:0] weights;
    reg [ATOMIC_C-1:0] dm;
    reg [ATOMIC_C*ATOMIC_K-1:0] wm;
    reg [ATOMIC_K*44-1:0] expected;
    reg [15:0] a,b;
    integer count,outputs=0,seen,latency;
    string path;
    initial clk=0;
    always #5 clk=~clk;
    NV_NVDLA_CMAC_CORE_mac donor(
        .nvdla_core_clk(clk),.nvdla_wg_clk(clk),.nvdla_core_rstn(rst_n),
        .cfg_is_fp16(1'b1),.cfg_is_int16(1'b0),.cfg_is_int8(1'b0),
        .cfg_is_wg(1'b0),.cfg_reg_en(1'b1),
        .dat_actv_data,.dat_actv_nan,.dat_actv_nz,.dat_actv_pvld,
        .dat_pre_exp,.dat_pre_mask,.dat_pre_pvld,.dat_pre_stripe_end,.dat_pre_stripe_st,
        .wt_actv_data,.wt_actv_nan,.wt_actv_nz,.wt_actv_pvld,
        .wt_sd_exp,.wt_sd_mask,.wt_sd_pvld,.mac_out_data,.mac_out_nan,.mac_out_pvld);
    // Matches CORE_active mantissa preparation, including the subnormal
    // factor of two. NaN payload occupies bits [12:3] for MAC_nan.
    function automatic [15:0] prepared(input [15:0] x);
        reg [14:0] mantissa;
        begin
            mantissa=x[14:10]!=0 ? {4'd0,1'b1,x[9:0]} : {4'd0,x[9:0],1'b0};
            prepared={x[15],mantissa<<x[11:10]};
        end
    endfunction
    task automatic tick;@(posedge clk);#1;endtask
    initial begin
        if(ATOMIC_C>64||ATOMIC_C<1) $fatal(1,"invalid source channels");
        if(!$value$plusargs("VECTORS=%s",path)||!$value$plusargs("COUNT=%d",count)) $fatal(1,"missing vectors");
        if(count<1||count>512) $fatal(1,"invalid vector count");
        $readmemh(path,vectors,0,count-1);
        // Drive public operand buses after time zero, while reset and valid=0.
        // This avoids declaration-initializer/event-control ordering in the
        // original explicit-sensitivity unpacking blocks. No internal force.
        @(negedge clk);
        dat_actv_data=0;wt_actv_data=0;dat_actv_nan=0;wt_actv_nan=0;
        dat_actv_nz=0;wt_actv_nz=0;dat_pre_exp=0;wt_sd_exp=0;
        dat_pre_mask=0;wt_sd_mask=0;
        repeat(2) tick();@(negedge clk);rst_n=1;
        repeat(6) tick();
        for(integer frame=0;frame<count;frame=frame+1) begin
            {data,weights,dm,wm,expected}=vectors[frame];
            for(integer kernel=0;kernel<ATOMIC_K;kernel=kernel+1) begin
                @(negedge clk);
                dat_actv_data=0;wt_actv_data=0;dat_actv_nan=0;wt_actv_nan=0;
                dat_actv_nz=0;wt_actv_nz=0;dat_pre_exp=0;wt_sd_exp=0;
                dat_pre_mask=0;wt_sd_mask=0;
                for(integer lane=0;lane<ATOMIC_C;lane=lane+1) begin
                    a=dm[lane] ? data[lane*16+:16]:16'd0;
                    b=wm[kernel*ATOMIC_C+lane] ? weights[(kernel*ATOMIC_C+lane)*16+:16]:16'd0;
                    dat_actv_data[lane*16+:16]=prepared(a);
                    wt_actv_data[lane*16+:16]=prepared(b);
                    dat_actv_nan[lane]=a[14:10]==31&&a[9:0]!=0;
                    wt_actv_nan[lane]=b[14:10]==31&&b[9:0]!=0;
                    dat_actv_nz[lane*2+:2]={2{a[14:0]!=0}};
                    wt_actv_nz[lane*2+:2]={2{b[14:0]!=0}};
                    dat_pre_exp[lane*3+:3]=a[14:12];wt_sd_exp[lane*3+:3]=b[14:12];
                    dat_pre_mask[lane]=a[14:0]!=0;wt_sd_mask[lane]=b[14:0]!=0;
                end
                // CORE_active suppresses numeric products if either operand
                // vector contains NaN; the independent NaN path retains it.
                if(|dat_actv_nan) dat_actv_nz=0;
                if(|wt_actv_nan) wt_actv_nz=0;
                dat_pre_pvld=1;wt_sd_pvld=1;dat_pre_stripe_st=1;dat_pre_stripe_end=1;
                tick();if(mac_out_pvld) $fatal(1,"unexpected pre-stage output");
                @(negedge clk);
                dat_pre_pvld=0;wt_sd_pvld=0;dat_pre_stripe_st=0;dat_pre_stripe_end=0;
                dat_actv_pvld='1;wt_actv_pvld='1;
                if($test$plusargs("DIAG")&&frame==0&&kernel==0) begin
                    #1;$display("DIAG active preedge exp=%h shift=%h row=%h/%h/tag%h nz=%h/%h l0=%h/%h",donor.exp_max,donor.exp_sft_00,
                        donor.res_a_00,donor.res_b_00,donor.res_tag_0,dat_actv_nz,wt_actv_nz,donor.pp_out_l0n00_0,donor.pp_out_l0n00_1);
                end
                tick();if(mac_out_pvld) $fatal(1,"unexpected zero-latency output");
                @(negedge clk);dat_actv_pvld=0;wt_actv_pvld=0;
                seen=0;latency=0;
                repeat(10) begin
                    tick();latency=latency+1;
                    if($test$plusargs("DIAG")&&frame==0&&kernel==0) begin
                        $display("DIAG cycle=%0d mul=%h/%h/tag%h l0=%h/%h l0reg=%h l2=%h/%h l2reg=%h sign=%h l4=%h/%h cfg=%h/%h pvld=%h/%h",latency,
                            donor.res_a_00,donor.res_b_00,donor.res_tag_0,
                            donor.pp_out_l0n00_0,donor.pp_out_l0n00_1,donor.pp_out_l0n00_0_d1,
                            donor.pp_out_l2n0_0,donor.pp_out_l2n0_1,donor.pp_out_l2n0_0_d2,
                            donor.ps_n0b0_d2,donor.pp_out_l4n0_0,donor.pp_out_l4n0_1,
                            donor.cfg_is_fp16_d3,donor.cfg_is_wg_d3,donor.pp_pvld_d1,donor.pp_pvld_d2);
                    end
                    if(mac_out_pvld) begin
                        if(seen!=0||mac_out_data[43:0]!==expected[kernel*44+:44]||
                           mac_out_nan!==((|dat_actv_nan)||(|wt_actv_nan)))
                            $fatal(1,"original MAC mismatch frame=%0d kernel=%0d cycle=%0d got=%h expected=%h nan=%b",frame,kernel,latency,mac_out_data[43:0],expected[kernel*44+:44],mac_out_nan);
                        seen=seen+1;outputs=outputs+1;
                    end
                end
                if(seen!=1) $fatal(1,"missing original MAC output frame=%0d kernel=%0d",frame,kernel);
            end
        end
        $display("PASS original NVDLA FP16 MAC C=%0d K=%0d frames=%0d outputs=%0d native_channels=64",ATOMIC_C,ATOMIC_K,count,outputs);
        $finish;
    end
    initial begin #2000000;$fatal(1,"original MAC watchdog");end
endmodule
