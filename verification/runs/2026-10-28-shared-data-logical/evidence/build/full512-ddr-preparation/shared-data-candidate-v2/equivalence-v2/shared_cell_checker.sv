`timescale 1ns/1ps
module shared_cell_checker #(parameter integer C=8) (
    input wire clk, input wire run_start, input wire enable,
    input integer random_first, random_count, output reg done
);
    reg capture;
    reg [C*16-1:0] data, weight;
    reg [C-1:0] data_mask, weight_mask;
    wire [C*16-1:0] shared_data_operand;
    wire [C*3-1:0] shared_data_exponent;
    wire [C-1:0] shared_data_nonzero;
    wire shared_data_nan;
    wire [10:0] shared_data_payload;
    wire [43:0] ref_result,candidate_result;
    wire ref_invalid,candidate_invalid;
    reg [31:0] rng;
    reg [31:0] random_word;
    reg [4:0] finite_exp;
    integer exp_tmp;
    reg [43:0] held_result;
    reg held_invalid;
    integer lane,frame,directed_count,raw_count,finite_count,skip_frame,draw;
    reg [31:0] rng_start,rng_end;

    ref_cell #(.ATOMIC_C(C)) reference (
        .clk(clk),.capture(capture),.data(data),.weight(weight),
        .data_mask(data_mask),.weight_mask(weight_mask),
        .result(ref_result),.invalid(ref_invalid));
    rk_cmac_fp16_shared_data #(.ATOMIC_C(C)) shared_data (
        .data(data),.mask(data_mask),.operand(shared_data_operand),
        .exponent(shared_data_exponent),.nonzero(shared_data_nonzero),
        .nan_found(shared_data_nan),.nan_payload(shared_data_payload));
    rk_cmac_fp16_cell_dsp_prefix_pipe #(.ATOMIC_C(C)) candidate (
        .clk(clk),.capture(capture),.data_operand(shared_data_operand),
        .data_exponent(shared_data_exponent),.data_nonzero(shared_data_nonzero),
        .data_nan(shared_data_nan),.data_payload(shared_data_payload),
        .weight(weight),.weight_mask(weight_mask),
        .result(candidate_result),.invalid(candidate_invalid));

    function automatic [31:0] xorshift32(input [31:0] value);
        reg [31:0] x;
        begin
            x=value;
            x=x^(x<<13);x=x^(x>>17);x=x^(x<<5);
            xorshift32=x;
        end
    endfunction
    task automatic require_equal(input integer sample_id);
        begin
            if ((^ref_result)===1'bx || (^candidate_result)===1'bx ||
                ref_invalid===1'bx || candidate_invalid===1'bx)
                $fatal(1,"UNKNOWN C=%0d sample=%0d ref=%h/%b candidate=%h/%b",C,sample_id,ref_result,ref_invalid,candidate_result,candidate_invalid);
            if (ref_result !== candidate_result || ref_invalid !== candidate_invalid)
                $fatal(1,"MISMATCH C=%0d sample=%0d ref=%h/%b candidate=%h/%b",C,sample_id,ref_result,ref_invalid,candidate_result,candidate_invalid);
        end
    endtask
    task automatic clear_inputs;
        begin data='0;weight='0;data_mask={C{1'b1}};weight_mask={C{1'b1}};end
    endtask
    task automatic put_data(input integer index,input [15:0] value);
        begin data[index*16 +: 16]=value;end
    endtask
    task automatic put_weight(input integer index,input [15:0] value);
        begin weight[index*16 +: 16]=value;end
    endtask
    task automatic advance_skipped_frames(input integer count);
        begin
            for(skip_frame=0;skip_frame<count;skip_frame=skip_frame+1)
                for(lane=0;lane<C;lane=lane+1)
                    for(draw=0;draw<6;draw=draw+1)rng=xorshift32(rng);
        end
    endtask
    // Capture once, compare after NBA, then churn every input/mask with
    // capture low. Churn draws exactly three RNG words per lane.
    task automatic capture_and_churn(input integer sample_id,
                                     input logic expect_nan,
                                     input [10:0] expected_payload,
                                     input logic expect_non_nan);
        begin
            @(negedge clk);capture=1'b1;
            @(posedge clk);#1;require_equal(sample_id);
            if(expect_nan && candidate_result !== {6'h3f,expected_payload,27'd0})
                $fatal(1,"NAN_PRIORITY C=%0d sample=%0d expected_payload=%h got=%h",C,sample_id,expected_payload,candidate_result);
            if(expect_non_nan && candidate_result[43:38]===6'h3f)
                $fatal(1,"MASKED_NAN_PROPAGATED C=%0d sample=%0d result=%h",C,sample_id,candidate_result);
            held_result=ref_result;held_invalid=ref_invalid;
            capture=1'b0;
            for(integer n=0;n<C;n=n+1)begin
                rng=xorshift32(rng);data[n*16+:16]=rng[15:0];
                rng=xorshift32(rng);weight[n*16+:16]=rng[15:0];
                rng=xorshift32(rng);data_mask[n]=rng[0];weight_mask[n]=rng[9];
            end
            @(posedge clk);#1;require_equal(sample_id);
            if(ref_result !== held_result || candidate_result !== held_result ||
               ref_invalid !== held_invalid || candidate_invalid !== held_invalid)
                $fatal(1,"CAPTURE0_NOT_HELD C=%0d sample=%0d held=%h ref=%h candidate=%h",C,sample_id,held_result,ref_result,candidate_result);
        end
    endtask

    initial begin
        done=0;capture=0;clear_inputs();rng=32'h3588da7a;
        directed_count=0;raw_count=0;finite_count=0;rng_start=0;rng_end=0;
        wait(run_start);
        if(!enable)begin done=1;end else begin
            // Signed zero and both zero-sign combinations.
            clear_inputs();put_data(0,16'h0000);put_weight(0,16'h8000);
            put_data(1,16'h8000);put_weight(1,16'h0000);
            capture_and_churn(1,1'b0,11'd0,1'b0);directed_count=directed_count+1;
            // Minimum and maximum subnormals with both signs.
            clear_inputs();put_data(0,16'h0001);put_weight(0,16'h03ff);
            put_data(1,16'h8001);put_weight(1,16'h83ff);
            capture_and_churn(2,1'b0,11'd0,1'b0);directed_count=directed_count+1;
            // Subnormal/normal boundary and finite extremes.
            clear_inputs();put_data(0,16'h0400);put_weight(0,16'h7bff);
            put_data(1,16'h03ff);put_weight(1,16'h0400);
            put_data(2,16'hfbff);put_weight(2,16'h7bff);
            capture_and_churn(3,1'b0,11'd0,1'b0);directed_count=directed_count+1;
            // Positive/negative infinity and finite partner lanes.
            clear_inputs();put_data(0,16'h7c00);put_weight(0,16'h3c00);
            put_data(1,16'hfc00);put_weight(1,16'hbc00);
            capture_and_churn(4,1'b0,11'd0,1'b0);directed_count=directed_count+1;
            // Lowest enabled weight qNaN wins over later weight and data NaNs.
            clear_inputs();put_data(0,16'h7e33);put_weight(1,16'h7e11);put_weight(3,16'hfe22);
            capture_and_churn(5,1'b1,11'h211,1'b0);directed_count=directed_count+1;
            // Weight sNaN sign/payload and weight-before-data priority.
            clear_inputs();put_data(0,16'hfe55);put_weight(0,16'hfc05);put_weight(2,16'h7c03);
            capture_and_churn(6,1'b1,11'h405,1'b0);directed_count=directed_count+1;
            // Data NaN must survive when the corresponding weight is masked off.
            clear_inputs();put_data(2,16'hfe55);put_weight(2,16'h7e99);weight_mask[2]=0;
            capture_and_churn(7,1'b1,11'h655,1'b0);directed_count=directed_count+1;
            // Masked data and weight NaNs are ignored; a finite lane remains.
            clear_inputs();put_data(0,16'h7e31);data_mask[0]=0;
            put_weight(1,16'hfe77);weight_mask[1]=0;
            put_data(2,16'h3c00);put_weight(2,16'h4000);
            capture_and_churn(8,1'b0,11'd0,1'b1);directed_count=directed_count+1;

            // Directed churn consumes 3*C xorshift draws per case. Advance
            // skipped global frames by 3*C generation + 3*C churn draws.
            advance_skipped_frames(random_first);
            rng_start=rng;
            for(frame=random_first;frame<random_first+random_count;frame=frame+1)begin
                clear_inputs();
                for(lane=0;lane<C;lane=lane+1)begin
                    rng=xorshift32(rng);random_word=rng;
                    if((frame%4)==0)data[lane*16+:16]=random_word[15:0];
                    else begin
                        exp_tmp={27'd0,random_word[4:0]};exp_tmp=exp_tmp%32'd31;
                        finite_exp=exp_tmp[4:0];data[lane*16+:16]={random_word[31],finite_exp,random_word[9:0]};
                    end
                    rng=xorshift32(rng);random_word=rng;
                    if((frame%4)==0)weight[lane*16+:16]=random_word[15:0];
                    else begin
                        exp_tmp={27'd0,random_word[4:0]};exp_tmp=exp_tmp%32'd31;
                        finite_exp=exp_tmp[4:0];weight[lane*16+:16]={random_word[31],finite_exp,random_word[9:0]};
                    end
                    rng=xorshift32(rng);data_mask[lane]=rng[0];weight_mask[lane]=rng[9];
                end
                capture_and_churn(100+frame,1'b0,11'd0,1'b0);
                if((frame%4)==0)raw_count=raw_count+1;else finite_count=finite_count+1;
            end
            rng_end=rng;
            $display("PASS shared_cell_equivalence C=%0d directed=%0d first=%0d count=%0d full_raw=%0d finite_exp=%0d seed=0x3588da7a rng_start=%08x rng_end=%08x capture0_churn=checked",
                     C,directed_count,random_first,random_count,raw_count,finite_count,rng_start,rng_end);
            done=1;
        end
    end
endmodule
