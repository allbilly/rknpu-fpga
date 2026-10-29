// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Candidate direct-convolution NVDLA group: 64 FP16 pairs, one reused Booth
// lane. This internal interface is not a raw command decoder or an RK proof.
module rk_nvdla_cmac_group #(parameter int unsigned TAG_WIDTH=35) (
    input logic clk,rst_n,in_valid,
    output logic in_ready,
    input logic [1023:0] in_data,in_weight,
    input logic [TAG_WIDTH-1:0] in_tag,
    output logic out_valid,
    input logic out_ready,
    output logic [43:0] out_group,
    output logic [TAG_WIDTH-1:0] out_tag,
    input logic cancel,
    input logic [7:0] cancel_code,
    output logic busy,error,
    output logic [7:0] error_code
);
    typedef enum logic [1:0] {IDLE,SCAN,MAC,HOLD} state_t;
    state_t state;
    logic [1023:0] data_q,weight_q;
    logic [5:0] lane;
    logic [3:0] max_block,block_exp,gap;
    logic [15:0] data_half,weight_half,data_prepared,weight_prepared;
    logic [14:0] data_mant,weight_mant;
    logic pair_nonzero,data_nan,weight_nan,data_nan_seen,weight_nan_seen;
    logic [10:0] data_nan_payload,weight_nan_payload;
    logic [37:0] sum,next_sum;
    logic [31:0] row_a,row_b,compensation,lane_sum;
    logic [7:0] row_tag,saved_code,cancel_normalized;
    logic fault,legal_input,legal_row;
    initial begin if (TAG_WIDTH==0) $fatal(1,"TAG_WIDTH must be positive");end
    assign data_half=data_q[{lane,4'b0}+:16];
    assign weight_half=weight_q[{lane,4'b0}+:16];
    assign pair_nonzero=(data_half[14:0]!=0)&&(weight_half[14:0]!=0);
    assign block_exp=pair_nonzero ? {1'b0,data_half[14:12]}+{1'b0,weight_half[14:12]} : 4'd0;
    assign gap=max_block-block_exp;
    assign data_mant={4'd0,(data_half[14:10]!=0),data_half[9:0]} <<
                     (data_half[14:10]==0 ? 2'd1 : data_half[11:10]);
    assign weight_mant={4'd0,(weight_half[14:10]!=0),weight_half[9:0]} <<
                       (weight_half[14:10]==0 ? 2'd1 : weight_half[11:10]);
    assign data_prepared={data_half[15],data_mant};
    assign weight_prepared={weight_half[15],weight_mant};
    assign data_nan=(data_half[14:10]==31)&&(data_half[9:0]!=0);
    assign weight_nan=(weight_half[14:10]==31)&&(weight_half[9:0]!=0);
    // Preserve the donor's separate CSA-row alignment. Compensation is the
    // per-lane equivalent of its direct-convolution sign-tag reduction.
    NV_NVDLA_CMAC_CORE_MAC_mul donor(
        .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),
        .cfg_is_fp16(1'b1),.cfg_is_int8(1'b0),.cfg_reg_en(1'b1),.exp_sft(gap),
        .op_a_dat(weight_prepared),.op_a_nz({2{pair_nonzero}}),.op_a_pvld(1'b1),
        .op_b_dat(data_prepared),.op_b_nz({2{pair_nonzero}}),.op_b_pvld(1'b1),
        .res_a(row_a),.res_b(row_b),.res_tag(row_tag));
    always @* begin
        legal_row=1;
        case (row_tag)
            8'hf0:compensation=32'haaab0000;
            8'h78:compensation=32'hfaaab000;
            8'h3c:compensation=32'hffaaab00;
            8'h1e:compensation=32'hfffaaab0;
            8'h0f:compensation=32'hffffaaab;
            8'h07:compensation=32'hfffffaab;
            8'h03:compensation=32'hffffffab;
            8'h01:compensation=32'hfffffffb;
            8'h00:compensation=0;
            default:begin compensation=0;legal_row=0;end
        endcase
        case (cancel_code)
            1,2,3,4,5,6,7,8:cancel_normalized=cancel_code;
            default:cancel_normalized=6;
        endcase
        legal_input=1;
`ifndef SYNTHESIS
        if ((^{in_data,in_weight,in_tag})===1'bx) legal_input=0;
`endif
    end
    assign lane_sum=row_a+row_b+compensation;
    assign next_sum=sum+{{6{lane_sum[31]}},lane_sum};
    assign error=rst_n&&(fault||cancel);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? cancel_normalized : 8'd0;
    assign in_ready=rst_n&&!error&&(state==IDLE);
    assign out_valid=rst_n&&!error&&(state==HOLD);
    assign busy=rst_n&&!error&&(state!=IDLE);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE;data_q<=0;weight_q<=0;lane<=0;max_block<=0;sum<=0;
            data_nan_seen<=0;weight_nan_seen<=0;data_nan_payload<=0;weight_nan_payload<=0;
            out_group<=0;out_tag<=0;fault<=0;saved_code<=0;
        end else begin
            if (!fault&&cancel) begin fault<=1;saved_code<=cancel_normalized;end
            if (!error) begin
                case (state)
                    IDLE:if (in_valid) begin
                        if (!legal_input) begin fault<=1;saved_code<=6;end
                        else begin
                            data_q<=in_data;weight_q<=in_weight;out_tag<=in_tag;
                            lane<=0;max_block<=0;sum<=0;data_nan_seen<=0;weight_nan_seen<=0;state<=SCAN;
                        end
                    end
                    SCAN:begin
                        if (block_exp>max_block) max_block<=block_exp;
                        if (data_nan&&!data_nan_seen) begin data_nan_seen<=1;data_nan_payload<={data_half[15],data_half[9:0]};end
                        if (weight_nan&&!weight_nan_seen) begin weight_nan_seen<=1;weight_nan_payload<={weight_half[15],weight_half[9:0]};end
                        if (lane==63) begin lane<=0;state<=MAC;end
                        else lane<=lane+1'b1;
                    end
                    MAC:begin
                        if (!legal_row) begin fault<=1;saved_code<=6;end
                        else begin
                            sum<=next_sum;
                            if (lane==63) begin
                                if (weight_nan_seen) out_group<={6'h3f,weight_nan_payload,27'd0};
                                else if (data_nan_seen) out_group<={6'h3f,data_nan_payload,27'd0};
                                else out_group<={max_block,2'b0,next_sum};
                                state<=HOLD;
                            end else lane<=lane+1'b1;
                        end
                    end
                    HOLD:if (out_ready) state<=IDLE;
                    default:begin fault<=1;saved_code<=6;end
                endcase
            end
        end
    end
endmodule
