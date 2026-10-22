// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_array_datapath;
    logic clk,rst_n=0,in_valid=0,in_first=0,in_last=0,in_last_frame=0,cancel=0;
    wire in_ready,busy,acknowledged,frame_done,done,error;
    logic [511:0] in_data,in_weight_mask;
    logic [8191:0] in_weight;
    logic [31:0] in_data_mask,in_output_address=0;
    logic [7:0] cancel_code=0;
    wire [7:0] error_code;
    wire mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready;
    logic mem_rsp_error=0;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic [9951:0] cmac_vectors[0:511];
    logic [1250:0] cacc_vectors[0:511];
    logic [767:0] output_vectors[0:63];
    logic [703:0] unused_groups;
    logic [15:0] memory[0:2047];
    logic pending=0,inject_error=0;
    logic [31:0] rng=32'h3588cd16;
    integer delay_left=0,requests=0,responses=0,acks=0,completed_frames=0,jobs=0;
    integer count,output_count,stream_count,limit,streams,accepted=0;
    string cmac_path,cacc_path,output_path;
    initial clk=0;
    always #5 clk=~clk;
    assign mem_req_ready=rst_n&&!pending&&rng[1:0]!=0;
    assign mem_rsp_valid=rst_n&&pending&&delay_left==0;
    rk_cmac_array_datapath #(.TIMEOUT_CYCLES(64)) dut(.*);
    always @(posedge clk or negedge rst_n) begin: slave
        logic response_fire,expect_ack,expect_frame,expect_done;
        integer frame,lane;
        if(!rst_n) begin
            pending<=0;mem_rsp_error<=0;delay_left<=0;requests<=0;responses<=0;acks<=0;completed_frames<=0;jobs<=0;rng<=32'h3588cd16;
            for(integer i=0;i<2048;i=i+1) memory[i]<=16'ha55a;
        end else begin
            rng<=rng*32'd1664525+32'd1013904223;
            response_fire=mem_rsp_valid&&mem_rsp_ready;
            expect_ack=response_fire&&!mem_rsp_error;
            expect_frame=expect_ack&&(responses%16==15);
            expect_done=expect_frame&&(responses==streams*16-1);
            if(mem_req_valid&&mem_req_ready) begin
                frame=requests/16;lane=requests%16;
                if(pending||!mem_req_write||frame>=streams||mem_req_addr!==32'h10040000+32'(frame*64+lane*2)||mem_req_wdata!==output_vectors[frame][lane*16+:16])
                    $fatal(1,"datapath write mismatch index=%0d addr=%h data=%h expected=%h",requests,mem_req_addr,mem_req_wdata,output_vectors[frame][lane*16+:16]);
                memory[frame*32+lane]<=mem_req_wdata;
                pending<=1;requests<=requests+1;delay_left<=lane==15 ? 23 : int'(rng[4:2])+1;
                mem_rsp_error<=inject_error&&requests==15;
            end
            if(pending) begin
                if(delay_left>0) delay_left<=delay_left-1;
                else if(response_fire) begin pending<=0;responses<=responses+1;end
            end
            if(expect_ack) acks<=acks+1;
            if(expect_frame) completed_frames<=completed_frames+1;
            if(expect_done) jobs<=jobs+1;
            #1;
            if(acknowledged!==expect_ack||frame_done!==expect_frame||done!==expect_done) $fatal(1,"datapath ack/frame/job timing");
        end
    end
    task automatic tick;@(posedge clk);#1;endtask
    task automatic reset_all;
        @(negedge clk);rst_n=0;in_valid=0;in_data=0;in_weight=0;in_data_mask=0;in_weight_mask=0;
        repeat(3) begin tick();if(error||busy||in_ready||mem_req_valid||mem_rsp_ready||done) $fatal(1,"datapath reset");end
        @(negedge clk);rst_n=1;repeat(6) tick();if(!in_ready||busy||error) $fatal(1,"datapath reset release");
    endtask
    task automatic send(input integer index,stream,input logic final_frame);
        @(negedge clk);
        {in_data,in_weight,in_data_mask,in_weight_mask,unused_groups}=cmac_vectors[index];
        in_first=cacc_vectors[index][546];in_last=cacc_vectors[index][545];
        in_output_address=32'h10040000+32'(stream*64);in_last_frame=final_frame;in_valid=1;
        begin: accepted_frame
            for(integer age=0;age<4096;age=age+1) begin
                @(posedge clk);if(in_ready) begin #1;disable accepted_frame;end
                #1;if(error) $fatal(1,"datapath fault waiting input");
            end
            $fatal(1,"datapath input timeout");
        end
        accepted=accepted+1;@(negedge clk);in_valid=0;
    endtask
    initial begin
        if(!$value$plusargs("CMAC=%s",cmac_path)||!$value$plusargs("CACC=%s",cacc_path)||!$value$plusargs("OUTPUT=%s",output_path)||
           !$value$plusargs("COUNT=%d",count)||!$value$plusargs("OUTPUT_COUNT=%d",output_count)||!$value$plusargs("LIMIT=%d",limit)||!$value$plusargs("STREAMS=%d",stream_count)) $fatal(1,"missing vectors");
        if(count<1||count>512||output_count<1||output_count>64||limit<1||limit>count||stream_count<1||stream_count>output_count) $fatal(1,"invalid corpus dimensions");
        $readmemh(cmac_path,cmac_vectors,0,count-1);$readmemh(cacc_path,cacc_vectors,0,count-1);$readmemh(output_path,output_vectors,0,output_count-1);
        streams=stream_count;reset_all();
        begin: produce
            integer stream;
            stream=0;
            for(integer index=0;index<limit;index=index+1) begin
                send(index,stream,stream==streams-1);
                if(cacc_vectors[index][545]) stream=stream+1;
            end
            if(stream!=streams) $fatal(1,"limit cuts a reduction");
        end
        // A new job must not enter after the final reduction was accepted and
        // before its final output write is acknowledged.
        @(negedge clk);in_valid=1;
        begin: wait_done
            for(integer age=0;age<8192;age=age+1) begin
                tick();if(error||in_ready) $fatal(1,"closure/ownership before done");
                if(done) disable wait_done;
            end
            $fatal(1,"datapath completion timeout");
        end
        @(negedge clk);in_valid=0;tick();
        if(busy||error||!in_ready||requests!=streams*16||acks!=requests||responses!=requests||completed_frames!=streams||jobs!=1) $fatal(1,"datapath drain/counts");
        for(integer i=0;i<2048;i=i+1) begin
            if(i/32<streams&&i%32<16) begin
                if(memory[i]!==output_vectors[i/32][(i%32)*16+:16]) $fatal(1,"final memory value");
            end else if(memory[i]!==16'ha55a) $fatal(1,"output gap changed");
        end
        $display("PASS datapath normal C=32 K=16 operand_frames=%0d output_frames=%0d writes=%0d seed=3588cd16",accepted,streams,requests);
        // Failed final write may already have committed but must never complete.
        inject_error=1;streams=1;reset_all();send(0,0,1);
        begin: wait_error
            for(integer age=0;age<8192;age=age+1) begin tick();if(error) disable wait_error;end
            $fatal(1,"missing final-write error");
        end
        if(error_code!==5||requests!=16||acks!=15||completed_frames!=0||jobs!=0||done||frame_done) $fatal(1,"final failure counts");
        repeat(16) begin tick();if(!error||in_ready||mem_req_valid||mem_rsp_ready||busy||done) $fatal(1,"datapath fault not sticky");end
        $display("PASS datapath final-write fault code=5 requests=16 acknowledgments=15 completions=0");
        $finish;
    end
    initial begin #5000000;$fatal(1,"datapath watchdog");end
endmodule
