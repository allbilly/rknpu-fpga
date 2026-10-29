// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_cacc_fp16_array #(parameter integer ATOMIC_K=1);
    logic clk,rst_n=0,in_valid=0,in_first=0,in_last=0,out_ready=0,cancel=0;
    wire in_ready,out_valid,busy,error;
    logic [511:0] in_data;
    logic [ATOMIC_K*512-1:0] in_weight;
    logic [31:0] in_data_mask;
    logic [ATOMIC_K*32-1:0] in_weight_mask;
    logic [32:0] in_tag=0;
    wire [32:0] out_tag;
    wire [ATOMIC_K*32-1:0] out_values;
    logic [7:0] cancel_code=0;
    wire [7:0] error_code;
    logic [9951:0] cmac_vectors[0:511];
    logic [1250:0] cacc_vectors[0:511];
    logic [8191:0] weights;
    logic [511:0] weight_masks;
    logic [703:0] unused_groups;
    logic [31:0] rng=32'h3588cc16;
    integer count,frames=0,outputs=0,held=0,cancels=0,resets=0;
    string cmac_path,cacc_path;
    initial clk=0;
    always #5 clk=~clk;
    rk_cmac_cacc_fp16_array #(.ATOMIC_K(ATOMIC_K)) dut(.*);
    task automatic tick;@(posedge clk);#1;endtask
    task automatic reset_all;
        @(negedge clk);rst_n=0;in_valid=0;out_ready=0;cancel=1;cancel_code=4;
        in_data=0;in_weight=0;in_data_mask=0;in_weight_mask=0;
        repeat(3) begin tick();if(in_ready||out_valid||busy||error||error_code!==0) $fatal(1,"reset dominance");end
        @(negedge clk);rst_n=1;cancel=0;cancel_code=0;
        repeat(6) begin tick();if(out_valid||busy||error) $fatal(1,"stale pipeline reset");end
        if(!in_ready) $fatal(1,"idle not ready");
    endtask
    task automatic send(input integer index,input logic first,last);
        @(negedge clk);
        {in_data,weights,in_data_mask,weight_masks,unused_groups}=cmac_vectors[index];
        in_weight=weights[ATOMIC_K*512-1:0];in_weight_mask=weight_masks[ATOMIC_K*32-1:0];
        in_first=first;in_last=last;in_tag=cacc_vectors[index][544:512];in_valid=1;
        begin: accepted
            for(integer age=0;age<64;age=age+1) begin
                @(posedge clk);
                if(in_ready) begin #1;disable accepted;end
                #1;if(error) $fatal(1,"unexpected pipeline input fault");
            end
            $fatal(1,"pipeline input timeout");
        end
        @(negedge clk);in_valid=0;
    endtask
    task automatic finish_frame(input integer index,input integer stall);
        begin: final_wait
            for(integer age=0;age<64;age=age+1) begin
                tick();if(error||!busy) $fatal(1,"pipeline final ownership");
                if(out_valid) disable final_wait;
            end
            $fatal(1,"pipeline final timeout");
        end
        repeat(stall+1) begin
            tick();held=held+1;
            if(!out_valid||out_values!==cacc_vectors[index][ATOMIC_K*32-1:0]||out_tag!==cacc_vectors[index][544:512]||!busy||error)
                $fatal(1,"pipeline result frame=%0d got=%h expected=%h",index,out_values,cacc_vectors[index][ATOMIC_K*32-1:0]);
        end
        @(negedge clk);out_ready=1;tick();
        if(out_valid||busy||error) $fatal(1,"pipeline retirement");
        @(negedge clk);out_ready=0;outputs=outputs+ATOMIC_K;
    endtask
    initial begin
        if(ATOMIC_K!=1&&ATOMIC_K!=16) $fatal(1,"unsupported test K");
        if(!$value$plusargs("CMAC=%s",cmac_path)||!$value$plusargs("CACC=%s",cacc_path)||!$value$plusargs("COUNT=%d",count)) $fatal(1,"missing vectors");
        if(count<1||count>512) $fatal(1,"invalid count");
        $readmemh(cmac_path,cmac_vectors,0,count-1);$readmemh(cacc_path,cacc_vectors,0,count-1);
        reset_all();
        for(integer i=0;i<count;i=i+1) begin
            rng=rng*32'd1664525+32'd1013904223;
            repeat(int'(rng[1:0])) tick();
            send(i,cacc_vectors[i][546],cacc_vectors[i][545]);frames=frames+1;
            if(cacc_vectors[i][545]) finish_frame(i,int'(rng[4:2]));
        end
        // Cancel with CMAC ownership, CACC partial ownership, and a held final.
        for(integer phase=0;phase<3;phase=phase+1) begin
            reset_all();send(0,1,phase==2);
            if(phase!=0) repeat(16) tick();
            @(negedge clk);cancel=1;cancel_code=2;tick();
            repeat(16) begin
                @(negedge clk);cancel=0;in_valid=1;out_ready=1;tick();
                if(!error||error_code!==2||in_ready||out_valid||busy) $fatal(1,"pipeline cancel not sticky");
            end
            cancels=cancels+1;
        end
        for(integer age=0;age<10;age=age+1) begin
            reset_all();send(0,1,1);repeat(age) tick();reset_all();resets=resets+1;
            // Original first corpus stream contains exactly one frame.
            if(!cacc_vectors[0][546]||!cacc_vectors[0][545]) $fatal(1,"reset fixture changed");
            send(0,1,1);finish_frame(0,3);
        end
        $display("PASS CMAC CACC FP16 pipeline C=32 K=%0d frames=%0d outputs=%0d resets=%0d cancels=%0d held=%0d seed=3588cc16",ATOMIC_K,frames,outputs,resets,cancels,held);
        $finish;
    end
    initial begin #2000000;$fatal(1,"CMAC CACC pipeline watchdog");end
endmodule
