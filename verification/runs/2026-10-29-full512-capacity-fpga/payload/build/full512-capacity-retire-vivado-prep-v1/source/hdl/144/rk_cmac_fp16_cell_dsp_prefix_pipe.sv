// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Separate timing candidate. Capture the original operand preparation and
// exponent alignment before the unchanged compensated DSP lanes and FP44 sum.
// The register boundary performs no rounding or arithmetic/layout conversion.
module rk_cmac_fp16_cell_dsp_prefix_pipe #(
    parameter int unsigned ATOMIC_C=32
) (
    input wire clk,capture,
    input wire [ATOMIC_C*16-1:0] data_operand,weight,
    input wire [ATOMIC_C*3-1:0] data_exponent,
    input wire [ATOMIC_C-1:0] data_nonzero,weight_mask,
    input wire data_nan,
    input wire [10:0] data_payload,
    output logic [43:0] result,
    output logic invalid
);
    wire [15:0] b[ATOMIC_C];
    wire [14:0] bm[ATOMIC_C];
    wire [3:0] exponent[ATOMIC_C];
    wire [ATOMIC_C-1:0] pair_nz;
    wire [3:0] exponent_tree[1:2*ATOMIC_C-1];
    wire [3:0] maximum=exponent_tree[1];
    logic nan_found;
    logic [10:0] nan_payload;
    logic [15:0] saved_a[ATOMIC_C],saved_b[ATOMIC_C];
    logic [3:0] saved_shift[ATOMIC_C];
    logic [ATOMIC_C-1:0] saved_nz;
    logic [3:0] saved_maximum;
    logic saved_nan;
    logic [10:0] saved_payload;
    wire [31:0] lane_total[ATOMIC_C];
    wire [7:0] row_tag[ATOMIC_C];
    logic [37:0] sum;
    logic [31:0] lane_sum;
    initial if(ATOMIC_C!=8&&ATOMIC_C!=32&&ATOMIC_C!=64)
        $fatal(1,"unsupported atomic C");

    for(genvar i=0;i<ATOMIC_C;i=i+1)begin: lanes
        assign b[i]=weight[i*16+:16];
        assign pair_nz[i]=data_nonzero[i]&&weight_mask[i]&&(b[i][14:0]!=0);
        assign bm[i]={4'd0,(b[i][14:10]!=0),b[i][9:0]} << (b[i][14:10]==0 ? 2'd1:b[i][11:10]);
        assign exponent[i]=pair_nz[i] ? {1'b0,data_exponent[i*3+:3]}+{1'b0,b[i][14:12]}:4'd0;
        assign exponent_tree[ATOMIC_C+i]=exponent[i];
        // Keep the donor operand ordering: weight supplies op_a, data op_b.
        rk_cmac_fp16_lane_dsp_prefix donor(
            .op_a(saved_a[i]),.op_b(saved_b[i]),.pair_nz(saved_nz[i]),
            .exp_sft(saved_shift[i]),.lane_sum(lane_total[i]),.res_tag(row_tag[i]));
    end
    for(genvar node=1;node<ATOMIC_C;node=node+1)begin: exponent_nodes
        assign exponent_tree[node]=(exponent_tree[2*node]>exponent_tree[2*node+1])
            ? exponent_tree[2*node]:exponent_tree[2*node+1];
    end
    always @* begin
        nan_found=0;nan_payload=0;
        // Preserve weight-before-data and lowest-channel donor NaN priority.
        for(integer i=0;i<ATOMIC_C;i=i+1)
            if(!nan_found&&weight_mask[i]&&b[i][14:10]==31&&b[i][9:0]!=0)begin
                nan_found=1;nan_payload={b[i][15],b[i][9:0]};
            end
        if(!nan_found&&data_nan)begin
            nan_found=1;nan_payload=data_payload;
        end
    end
    // Reset invalidates pipeline ownership in the array, so these payload
    // registers need no runtime reset. Every accepted frame overwrites them
    // completely. Configuration INIT values keep native/mapped startup known
    // without adding19200 loads to the engine's asynchronous reset network.
    initial begin
        saved_nz=0;saved_maximum=0;saved_nan=0;saved_payload=0;
        for(integer i=0;i<ATOMIC_C;i=i+1)begin
            saved_a[i]=0;saved_b[i]=0;saved_shift[i]=0;
        end
    end
    always_ff @(posedge clk)begin
        if(capture)begin
            saved_nz<=pair_nz;saved_maximum<=maximum;
            saved_nan<=nan_found;saved_payload<=nan_payload;
            for(integer i=0;i<ATOMIC_C;i=i+1)begin
                saved_a[i]<={b[i][15],bm[i]};
                saved_b[i]<=data_operand[i*16+:16];
                saved_shift[i]<=maximum-exponent[i];
            end
        end
    end
    always @* begin
        sum=0;invalid=0;lane_sum=0;
        // Identical 38-bit integer reduction, with no new rounding boundary.
        for(integer i=0;i<ATOMIC_C;i=i+1)begin
            case(row_tag[i])
                8'hf0,8'h78,8'h3c,8'h1e,8'h0f,8'h07,8'h03,8'h01,8'h00:begin end
                default:invalid=1;
            endcase
            lane_sum=lane_total[i];
            sum=sum+{{6{lane_sum[31]}},lane_sum};
        end
        result=saved_nan ? {6'h3f,saved_payload,27'd0}:{saved_maximum,2'b0,sum};
    end
endmodule
