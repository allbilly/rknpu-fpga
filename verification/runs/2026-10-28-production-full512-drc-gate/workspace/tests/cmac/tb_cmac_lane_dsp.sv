// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_lane_dsp;
    reg [15:0] op_a = 0, op_b = 0;
    reg [3:0] exp_sft = 0;
    reg pair_nz = 0;
    wire [31:0] reference_lane, actual_lane;
    wire [7:0] reference_tag, actual_tag;
    wire [39:0] difference;
    wire mismatch;
    integer comparisons = 0;
    integer samples = 4096;
    reg [31:0] random_state = 32'h3588d501;
    cmac_lane_dsp_miter dut(.*);
    function automatic [31:0] next_random(input [31:0] prior);
        reg [31:0] value;
        begin
            value = prior ^ (prior << 13);
            value = value ^ (value >> 17);
            next_random = value ^ (value << 5);
        end
    endfunction
    function automatic [15:0] directed(input integer index);
        begin
            case(index)
                0: directed = 16'h0000; 1: directed = 16'h8000;
                2: directed = 16'h0001; 3: directed = 16'h8001;
                4: directed = 16'h7fff; 5: directed = 16'hffff;
                6: directed = 16'h4000; 7: directed = 16'hc000;
                8: directed = 16'h5555; 9: directed = 16'haaaa;
                10: directed = 16'h03ff; default: directed = 16'h07ff;
            endcase
        end
    endfunction
    task automatic check;
        reg [31:0] compared;
        begin
            #1;
`ifdef RK_LANE_DSP_NEGATIVE
            compared = actual_lane ^ 32'h00000001;
`else
            compared = actual_lane;
`endif
            if(reference_lane !== compared || reference_tag !== actual_tag)
                $fatal(1, "LANE_DSP_MISMATCH a=%h b=%h shift=%h nz=%b expected=%h actual=%h tag=%h/%h",
                    op_a, op_b, exp_sft, pair_nz, reference_lane, compared, reference_tag, actual_tag);
            comparisons = comparisons + 1;
        end
    endtask
    initial begin
        if($value$plusargs("SAMPLES=%d", samples)) begin end
        if(samples < 1 || samples > 65536) $fatal(1, "invalid sample count");
        for(integer a = 0; a < 12; a = a + 1)
            for(integer b = 0; b < 12; b = b + 1)
                for(integer s = 0; s < 16; s = s + 1)
                    for(integer nz = 0; nz < 2; nz = nz + 1) begin
                        op_a = directed(a); op_b = directed(b);
                        exp_sft = s[3:0]; pair_nz = nz[0]; check();
                    end
        for(integer sample = 0; sample < samples; sample = sample + 1) begin
            random_state = next_random(random_state); op_a = random_state[15:0];
            random_state = next_random(random_state); op_b = random_state[15:0];
            for(integer s = 0; s < 16; s = s + 1)
                for(integer nz = 0; nz < 2; nz = nz + 1) begin
                    exp_sft = s[3:0]; pair_nz = nz[0]; check();
                end
        end
        if(comparisons != 4608 + 32 * samples) $fatal(1, "comparison count");
        $display("PASS LANE_DSP_BINARY_FIXTURES comparisons=%0d seed=3588d501 samples=%0d", comparisons, samples);
        $finish;
    end
    initial begin #3000000; $fatal(1, "LANE_DSP_WATCHDOG"); end
endmodule
