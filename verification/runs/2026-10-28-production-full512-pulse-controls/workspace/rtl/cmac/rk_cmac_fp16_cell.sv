// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Parallel FP16 dot-product cell. NVIDIA nvdlav1 partial-row arithmetic;
// ATOMIC_C changes the group, not the format of the FP44 output to CACC.
module rk_cmac_fp16_cell #(parameter int unsigned ATOMIC_C=32) (
    input wire clk,rst_n,
    input wire [ATOMIC_C*16-1:0] data,weight,
    input wire [ATOMIC_C-1:0] data_mask,weight_mask,
    output logic [43:0] result,
    output logic invalid
);
    wire [15:0] a[ATOMIC_C],b[ATOMIC_C];
    wire [3:0] exponent[ATOMIC_C];
    wire [31:0] row_a[ATOMIC_C],row_b[ATOMIC_C];
    wire [7:0] row_tag[ATOMIC_C];
    logic [3:0] maximum;
    logic [37:0] sum;
    logic [31:0] compensation,lane_sum;
    logic nan_found;
    logic [10:0] nan_payload;
    initial if (ATOMIC_C!=8&&ATOMIC_C!=32&&ATOMIC_C!=64) $fatal(1,"unsupported atomic C");
    for(genvar i=0;i<ATOMIC_C;i=i+1) begin: lanes
        wire pair_nz=data_mask[i]&&weight_mask[i]&&(a[i][14:0]!=0)&&(b[i][14:0]!=0);
        wire [14:0] am={4'd0,(a[i][14:10]!=0),a[i][9:0]} << (a[i][14:10]==0 ? 2'd1:a[i][11:10]);
        wire [14:0] bm={4'd0,(b[i][14:10]!=0),b[i][9:0]} << (b[i][14:10]==0 ? 2'd1:b[i][11:10]);
        assign a[i]=data[i*16+:16];
        assign b[i]=weight[i*16+:16];
        assign exponent[i]=pair_nz ? {1'b0,a[i][14:12]}+{1'b0,b[i][14:12]}:4'd0;
        NV_NVDLA_CMAC_CORE_MAC_mul donor(
            .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),.cfg_is_fp16(1'b1),
            .cfg_is_int8(1'b0),.cfg_reg_en(1'b1),.exp_sft(maximum-exponent[i]),
            .op_a_dat({b[i][15],bm}),.op_a_nz({2{pair_nz}}),.op_a_pvld(1'b1),
            .op_b_dat({a[i][15],am}),.op_b_nz({2{pair_nz}}),.op_b_pvld(1'b1),
            .res_a(row_a[i]),.res_b(row_b[i]),.res_tag(row_tag[i]));
    end
    always @* begin
        maximum=0;
        for(integer i=0;i<ATOMIC_C;i=i+1) if(exponent[i]>maximum) maximum=exponent[i];
    end
    always @* begin
        sum=0;invalid=0;compensation=0;lane_sum=0;nan_found=0;nan_payload=0;
        // Preserve the donor's weight-before-data, lowest-channel NaN priority.
        for(integer i=0;i<ATOMIC_C;i=i+1)
            if(!nan_found&&weight_mask[i]&&b[i][14:10]==31&&b[i][9:0]!=0) begin
                nan_found=1;nan_payload={b[i][15],b[i][9:0]};
            end
        for(integer i=0;i<ATOMIC_C;i=i+1)
            if(!nan_found&&data_mask[i]&&a[i][14:10]==31&&a[i][9:0]!=0) begin
                nan_found=1;nan_payload={a[i][15],a[i][9:0]};
            end
        for(integer i=0;i<ATOMIC_C;i=i+1) begin
            case(row_tag[i])
                8'hf0:compensation=32'haaab0000;
                8'h78:compensation=32'hfaaab000;
                8'h3c:compensation=32'hffaaab00;
                8'h1e:compensation=32'hfffaaab0;
                8'h0f:compensation=32'hffffaaab;
                8'h07:compensation=32'hfffffaab;
                8'h03:compensation=32'hffffffab;
                8'h01:compensation=32'hfffffffb;
                8'h00:compensation=0;
                default:begin compensation=0;invalid=1;end
            endcase
            lane_sum=row_a[i]+row_b[i]+compensation;
            sum=sum+{{6{lane_sum[31]}},lane_sum};
        end
        result=nan_found ? {6'h3f,nan_payload,27'd0}:{maximum,2'b0,sum};
    end
endmodule
