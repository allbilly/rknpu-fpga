// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// UNSELECTED resource candidate: sixteen independent FP48 contexts, two
// unchanged NVIDIA arithmetic pipelines. All sixteen C32 product kernels are
// upstream and unchanged. No precision, reduction order or output-layout change.
module rk_cacc_fp16_array #(
    parameter int unsigned ATOMIC_K=16,TAG_WIDTH=33
) (
    input wire clk,rst_n,in_valid,
    output wire in_ready,
    input wire [ATOMIC_K*44-1:0] in_groups,
    input wire in_first,in_last,
    input wire [TAG_WIDTH-1:0] in_tag,
    output wire out_valid,
    input wire out_ready,
    output wire [ATOMIC_K*32-1:0] out_values,
    output wire [TAG_WIDTH-1:0] out_tag,
    input wire cancel,
    input wire [7:0] cancel_code,
    output wire busy,error,
    output wire [7:0] error_code
);
    localparam integer CONTEXTS_PER_CORE=8;
    logic active,working,held,fault;
    logic [7:0] saved_code,normalized_cancel;
    logic [ATOMIC_K*44-1:0] groups_hold;
    logic first_hold,last_hold;
    logic [TAG_WIDTH-1:0] saved_tag;
    wire [1:0] unit_fault,partial_valid,final_valid,unit_complete;
    logic legal,disagree;
    wire accept=in_valid&&in_ready;
    wire launch=accept&&legal;
    wire retire=out_valid&&out_ready;

    initial if(ATOMIC_K!=16||TAG_WIDTH==0)
        $fatal(1,"Shared-context candidate requires K16 and a nonzero tag width");
    always @* begin
        case(cancel_code)
            1,2,3,4,5,6,7,8:normalized_cancel=cancel_code;
            default:normalized_cancel=6;
        endcase
        legal=1;
`ifndef SYNTHESIS
        if((^in_groups)===1'bx||(^in_tag)===1'bx||
           (in_first!==1'b0&&in_first!==1'b1)||
           (in_last!==1'b0&&in_last!==1'b1))legal=0;
`endif
        if(in_first!=!active||(active&&in_tag!=saved_tag))legal=0;
        for(integer k=0;k<ATOMIC_K;k=k+1)begin
            if(in_groups[k*44+38+:6]==6'h3f)begin
                if(in_groups[k*44+27+:10]==0)legal=0;
            end else if(in_groups[k*44+35+:3]!=3'b000&&
                        in_groups[k*44+35+:3]!=3'b111)legal=0;
        end
        // Both cores issue the same number of contexts under identical
        // valid/last controls. An incomplete or divergent return is failure.
        disagree=((|partial_valid)&&!(&partial_valid))||
                 ((|final_valid)&&!(&final_valid));
    end
    assign error=rst_n&&(fault||cancel||(|unit_fault)||disagree);
    assign error_code=!rst_n?8'd0:fault?saved_code:cancel?normalized_cancel:
        ((|unit_fault)||disagree)?8'd6:8'd0;
    assign in_ready=rst_n&&!error&&!working&&!held;
    assign out_valid=rst_n&&!error&&held;
    assign out_tag=saved_tag;
    assign busy=rst_n&&!error&&(active||working||held);

    for(genvar u=0;u<2;u=u+1)begin: units
        logic [47:0] partial_bank[CONTEXTS_PER_CORE];
        logic [31:0] final_bank[CONTEXTS_PER_CORE];
        logic [3:0] issued,completed;
        logic local_fault;
        wire [2:0] input_index=issued[2:0];
        wire [2:0] output_index=completed[2:0];
        wire [3:0] kernel_index={input_index,1'b0}+4'(u);
        wire issue=rst_n&&working&&!error&&(issued<4'd8);
        wire [47:0] returned_partial;
        wire [31:0] returned_final;
        wire returned=partial_valid[u]||final_valid[u];
        wire bad_return=!working||(completed>=issued)||
            (partial_valid[u]&&final_valid[u])||
            (final_valid[u]!=last_hold);
        assign unit_fault[u]=local_fault;
        assign unit_complete[u]=(issued==4'd8)&&(completed==4'd8);
        for(genvar slot=0;slot<CONTEXTS_PER_CORE;slot=slot+1)begin: outputs
            assign out_values[(slot*2+u)*32+:32]=final_bank[slot];
        end
        NV_NVDLA_CACC_CALC_fp_48b donor (
            .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),
            .in_data(groups_hold[kernel_index*44+:44]),
            .in_op(partial_bank[input_index]),.in_op_valid(!first_hold),
            .in_sel(last_hold),.in_valid(issue),
            .out_partial_data(returned_partial),.out_partial_valid(partial_valid[u]),
            .out_final_data(returned_final),.out_final_valid(final_valid[u])
        );
        always_ff @(posedge clk or negedge rst_n)begin
            if(!rst_n)begin
                issued<=0;completed<=0;local_fault<=0;
                for(integer slot=0;slot<CONTEXTS_PER_CORE;slot=slot+1)begin
                    partial_bank[slot]<=0;final_bank[slot]<=0;
                end
            end else if(!error)begin
                if(launch)begin issued<=0;completed<=0;end
                if(issue)issued<=issued+1'b1;
                if(returned)begin
                    if(bad_return)local_fault<=1;
                    else begin
                        completed<=completed+1'b1;
                        if(final_valid[u])final_bank[output_index]<=returned_final;
                        else partial_bank[output_index]<=returned_partial;
                    end
                end
                if(retire)begin
                    for(integer slot=0;slot<CONTEXTS_PER_CORE;slot=slot+1)
                        partial_bank[slot]<=0;
                end
            end
        end
    end
    always_ff @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            active<=0;working<=0;held<=0;fault<=0;saved_code<=0;
            groups_hold<=0;first_hold<=0;last_hold<=0;saved_tag<=0;
        end else begin
            if(!fault&&error)begin fault<=1;saved_code<=error_code;end
            if(!error)begin
                if(accept&&!legal)begin fault<=1;saved_code<=6;end
                if(launch)begin
                    groups_hold<=in_groups;first_hold<=in_first;last_hold<=in_last;
                    working<=1;active<=1;
                    if(in_first)saved_tag<=in_tag;
                end
                if(working&&(&unit_complete))begin
                    working<=0;
                    if(last_hold)held<=1;
                end
                if(retire)begin held<=0;active<=0;end
            end
        end
    end
endmodule
