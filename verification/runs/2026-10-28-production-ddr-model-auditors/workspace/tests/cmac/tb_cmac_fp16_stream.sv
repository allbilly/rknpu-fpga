// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_fp16_stream #(
    parameter int unsigned ATOMIC_C=32,ATOMIC_K=16
);
    /* verilator lint_off BLKSEQ */
    localparam integer BITS=ATOMIC_C*16+ATOMIC_K*ATOMIC_C*16+ATOMIC_C+ATOMIC_K*ATOMIC_C+ATOMIC_K*44;
    logic clk,rst_n=0,in_valid=0,in_ready,out_valid,out_ready=0,error;
    logic [ATOMIC_C*16-1:0] in_data=0;
    logic [ATOMIC_K*ATOMIC_C*16-1:0] in_weight=0;
    logic [ATOMIC_C-1:0] in_data_mask=0;
    logic [ATOMIC_K*ATOMIC_C-1:0] in_weight_mask=0;
    logic [34:0] in_tag=0,out_tag;
    logic [ATOMIC_K*44-1:0] out_groups,loaded_expected,queued_expected;
    logic [34:0] queued_tag;
    logic [BITS-1:0] vectors[0:511];
    logic queued=0,accept,retire;
    logic [31:0] rng=32'h35883216;
    integer count,sent=0,received=0,cycles=0,stalls=0,replacements=0,burst=0,max_burst=0;
    string path;
    initial clk=0;
    always #5 clk=~clk;
    rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);
    initial begin
        if(!$value$plusargs("VECTORS=%s",path)||!$value$plusargs("COUNT=%d",count)) $fatal(1,"missing vectors");
        if(count<64||count>512) $fatal(1,"invalid vector count");
        $readmemh(path,vectors,0,count-1);
        repeat(2) @(negedge clk);
        rst_n=1;
        @(posedge clk);#1;
        if(!in_ready||out_valid||error) $fatal(1,"warmup ownership");
        while(received<count) begin
            @(negedge clk);
            // Keep a pending producer frame stable until its handshake.
            if(!in_valid&&sent<count) begin
                if(sent<64||rng[0]||rng[4]) begin
                    {in_data,in_weight,in_data_mask,in_weight_mask,loaded_expected}=vectors[sent];
                    in_tag=35'(sent);in_valid=1;
                end
            end
            // First 64 frames prove a continuous one-frame-per-cycle burst.
            // Later cycles independently stall the consumer and gap the producer.
            out_ready=sent<64 ? 1'b1:(rng[2]||rng[7]);
            rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
            @(posedge clk);
            if(error||out_valid!==queued) $fatal(1,"stream ownership cycle=%0d",cycles);
            if(queued&&(out_groups!==queued_expected||out_tag!==queued_tag))
                $fatal(1,"stream data/tag frame=%0d",received);
            accept=in_valid&&in_ready;retire=out_valid&&out_ready;
            if(out_valid&&!out_ready) stalls=stalls+1;
            if(accept&&retire) replacements=replacements+1;
            if(accept) burst=burst+1;else burst=0;
            if(burst>max_burst) max_burst=burst;
            if(retire) begin queued=0;received=received+1;end
            if(accept) begin
                if(queued) $fatal(1,"accepted with occupied result slot");
                queued=1;queued_expected=loaded_expected;queued_tag=in_tag;sent=sent+1;
            end
            // Change producer valid only after DUT nonblocking assignments.
            #1;if(accept) in_valid=0;
            cycles=cycles+1;
            if(cycles>count*20) $fatal(1,"stream timeout sent=%0d received=%0d",sent,received);
        end
        repeat(4) begin
            @(posedge clk);#1;
            if(out_valid||error||!in_ready) $fatal(1,"duplicate output or failed drain");
        end
        if(sent!=count||queued||max_burst<64||stalls==0||replacements<63) $fatal(1,"insufficient streaming coverage");
        $display("PASS streaming FP16 CMAC C=%0d K=%0d frames=%0d outputs=%0d max_burst=%0d replacements=%0d stalls=%0d cycles=%0d seed=35883216",ATOMIC_C,ATOMIC_K,count,received*ATOMIC_K,max_burst,replacements,stalls,cycles);
        $finish;
    end
    initial begin #1000000;$fatal(1,"stream watchdog");end
    /* verilator lint_on BLKSEQ */
endmodule
