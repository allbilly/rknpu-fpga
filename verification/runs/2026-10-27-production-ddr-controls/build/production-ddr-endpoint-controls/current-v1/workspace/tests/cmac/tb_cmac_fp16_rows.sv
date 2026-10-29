// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_fp16_rows;
    logic clk, rst_n=0, pair_nz=0;
    logic [15:0] op_a=0,op_b=0;
    logic [3:0] exp_sft=0;
    wire [31:0] ref_a,ref_b,res_a,res_b;
    wire [7:0] ref_tag,res_tag;
    integer checked=0,resets=0;
    logic [31:0] random_state=32'h3588f016;
    NV_NVDLA_CMAC_CORE_MAC_mul original (
        .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),
        .cfg_is_fp16(1'b1),.cfg_is_int8(1'b0),.cfg_reg_en(1'b1),
        .op_a_dat(op_a),.op_b_dat(op_b),.op_a_nz({2{pair_nz}}),
        .op_b_nz({2{pair_nz}}),.op_a_pvld(1'b1),.op_b_pvld(1'b1),
        .exp_sft,.res_a(ref_a),.res_b(ref_b),.res_tag(ref_tag));
    rk_cmac_fp16_rows dut(.*);
    initial clk=0;
    always #5 clk=~clk;
    task automatic randomize_operands;
        random_state=random_state^(random_state<<13);
        random_state=random_state^(random_state>>17);
        random_state=random_state^(random_state<<5);
        op_a=random_state[15:0];op_b=random_state[31:16];
    endtask
    task automatic check_rows;
        #1;
        if ({res_a,res_b,res_tag} !== {ref_a,ref_b,ref_tag})
            $fatal(1,"partial-row mismatch a=%h b=%h shift=%h nz=%b got=%h/%h/%h ref=%h/%h/%h",
                op_a,op_b,exp_sft,pair_nz,res_a,res_b,res_tag,ref_a,ref_b,ref_tag);
        checked=checked+1;
    endtask
    task automatic configure;
        rst_n=0;#2;@(negedge clk);rst_n=1;@(negedge clk);
        resets=resets+1;
    endtask
    initial begin
        configure();
        // Sweep every 16-bit signed/magnitude operand, pairing independent
        // deterministic operands and all sixteen alignment codes, nz=0/1.
        for(integer i=0;i<65536;i=i+1) begin
            if(i!=0 && i%16384==0) configure();
            randomize_operands();op_a=16'(i);
            for(integer s=0;s<16;s=s+1) begin
                exp_sft=4'(s);pair_nz=1;check_rows();
                pair_nz=0;check_rows();
            end
        end
        if(checked!=2097152 || resets!=4) $fatal(1,"coverage count");
        $display("PASS fixed FP16 rows comparisons=%0d resets=%0d seed=3588f016; post-configuration only",checked,resets);
        $finish;
    end
endmodule
