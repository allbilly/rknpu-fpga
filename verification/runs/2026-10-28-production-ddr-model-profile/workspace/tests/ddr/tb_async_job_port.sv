// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_async_job_port #(parameter integer DUT_STAGES=3);
    logic s_clk,d_clk,s_run,d_run,s_rst_n,d_rst_n,s_admission_enable;
    logic s_start_valid,s_result_ready,d_allow_start,force_result,invalid_status,local_failure;
    logic [31:0] s_start_address,s_start_amount;
    wire s_start_ready,s_result_valid,s_result_error,s_protocol_fault;
    wire [7:0] s_result_code;
    wire [31:0] s_result_tasks;
    wire d_start_valid,d_result_ready,d_protocol_fault;
    wire [31:0] d_start_address,d_start_amount;
    logic model_pending,model_valid,model_error;
    logic [7:0] model_code;
    logic [31:0] model_tasks,random_s,random_d;
    logic [3:0] delay_left;
    wire d_start_ready=d_rst_n&&d_allow_start&&random_d[0];
    wire d_result_valid=force_result||model_valid;
    wire d_result_error=force_result?1'b0:model_error;
    wire [7:0] d_result_code=force_result?8'b0:model_code;
    wire [31:0] d_result_tasks=force_result?32'hdeadbeef:model_tasks;
    rk_async_job_port #(.SYNC_STAGES(DUT_STAGES)) dut(.*);
    initial begin s_clk=0;d_clk=0;s_run=1;d_run=1;end
    always begin #3.75;if(s_run)s_clk=~s_clk;end
    always begin #10;if(d_run)d_clk=~d_clk;end
    function automatic logic [7:0] code_for(input logic[3:0] status_bits);
        code_for=status_bits[0]?({5'b0,status_bits[3:1]}+8'd1):8'b0;
    endfunction
    integer source_count,destination_count,result_count,total_good;
    logic [63:0] expected_descriptor,held_descriptor;
    logic [40:0] expected_result,held_result;
    logic s_stalled,d_stalled;

    always @(posedge s_clk or negedge s_rst_n) begin
        if(!s_rst_n)begin
            random_s<=32'h3588cdc2;source_count<=0;result_count<=0;
            expected_descriptor<=0;expected_result<=0;s_stalled<=0;held_result<=0;
        end else begin
            random_s<={random_s[30:0],random_s[31]^random_s[21]^random_s[1]^random_s[0]};
            if(s_start_valid&&s_start_ready)begin
                source_count<=source_count+1;expected_descriptor<={s_start_address,s_start_amount};
                if(local_failure)expected_result<={1'b1,8'd5,32'b0};
                else if(invalid_status)expected_result<={1'b1,8'd5,s_start_address^s_start_amount};
                else expected_result<={s_start_address[7],code_for(s_start_address[10:7]),s_start_address^s_start_amount};
            end
            if(s_stalled&&(!s_result_valid||{s_result_error,s_result_code,s_result_tasks}!==held_result))
                $fatal(1,"Held source result changed under backpressure");
            s_stalled<=s_result_valid&&!s_result_ready;
            held_result<={s_result_error,s_result_code,s_result_tasks};
            if(s_result_valid&&s_result_ready)begin
                if(result_count>=source_count||{s_result_error,s_result_code,s_result_tasks}!==expected_result)
                    $fatal(1,"Unexpected/incorrect source result");
                result_count<=result_count+1;
            end
        end
    end
    always @(posedge d_clk or negedge d_rst_n)begin
        if(!d_rst_n)begin
            random_d<=32'h7532bb02;destination_count<=0;
            model_pending<=0;model_valid<=0;model_error<=0;model_code<=0;model_tasks<=0;delay_left<=0;
            d_stalled<=0;held_descriptor<=0;
        end else begin
            random_d<={random_d[30:0],random_d[31]^random_d[21]^random_d[1]^random_d[0]};
            if(d_stalled&&(!d_start_valid||{d_start_address,d_start_amount}!==held_descriptor))
                $fatal(1,"Offered core start withdrawn/changed under backpressure");
            d_stalled<=d_start_valid&&!d_start_ready;held_descriptor<={d_start_address,d_start_amount};
            if(d_start_valid&&d_start_ready)begin
                if(model_pending||model_valid||{d_start_address,d_start_amount}!==expected_descriptor)
                    $fatal(1,"Core descriptor changed/duplicated");
                destination_count<=destination_count+1;model_pending<=1;
                model_error<=invalid_status?1'b0:d_start_address[7];
                model_code<=invalid_status?8'd7:code_for(d_start_address[10:7]);
                model_tasks<=d_start_address^d_start_amount;delay_left<={1'b0,random_d[3:1]};
            end
            if(model_pending)begin
                if(delay_left==0)begin model_pending<=0;model_valid<=1;end
                else delay_left<=delay_left-1'b1;
            end
            if(model_valid&&d_result_ready)model_valid<=0;
        end
    end
    task automatic reset_epoch;
        s_admission_enable=0;s_start_valid=0;force_result=0;invalid_status=0;local_failure=0;
        s_rst_n=0;d_rst_n=0;s_result_ready=1;d_allow_start=1;
        repeat(5)@(negedge s_clk);
        s_rst_n=1;@(negedge d_clk);d_rst_n=1;
        repeat(8)@(negedge s_clk);s_admission_enable=1;
    endtask
    task automatic send(input logic[31:0] address,input logic[31:0] amount);
        integer guard;
        @(negedge s_clk);guard=0;
        while(!s_start_ready)begin
            @(negedge s_clk);guard=guard+1;if(guard>5000)$fatal(1,"Descriptor admission timeout");
        end
        s_start_valid=1;s_start_address=address;s_start_amount=amount;
        @(posedge s_clk);if(!s_start_ready)$fatal(1,"Descriptor admission vanished before handshake");
        @(negedge s_clk);s_start_valid=0;
    endtask
    task automatic finish_one;
        integer guard;
        guard=0;
        while(result_count!=source_count)begin
            @(negedge s_clk);guard=guard+1;if(guard>5000)$fatal(1,"Source result timeout");
        end
        total_good=total_good+1;
    endtask
    integer mode,prior;
    initial begin
        s_rst_n=0;d_rst_n=0;s_admission_enable=0;s_start_valid=0;s_start_address=0;s_start_amount=0;
        s_result_ready=1;d_allow_start=1;force_result=0;invalid_status=0;local_failure=0;total_good=0;
        if(!$value$plusargs("MODE=%d",mode))mode=0;
        reset_epoch();
        if(mode==0)begin
            repeat(256)begin
                s_result_ready=0;send(random_s,{random_s[15:0],random_s[31:16]});
                wait(s_result_valid);repeat(12)@(negedge s_clk);
                s_result_ready=1;finish_one();
            end
            if(source_count!=256||destination_count!=256||result_count!=256||s_protocol_fault||d_protocol_fault)
                $fatal(1,"Normal job inventory/fault mismatch");
        end else if(mode==1)begin
            d_allow_start=0;send(32'hf1230002,32'h8000002d);wait(d_start_valid);
            @(negedge d_clk);d_run=0;s_admission_enable=0;
            repeat(80)@(negedge s_clk);
            if(s_result_valid||s_start_ready||result_count!=0)$fatal(1,"Stopped core fabricated completion");
            d_run=1;d_allow_start=1;finish_one();s_admission_enable=1;
            send(32'h81230040,32'hffff0023);@(negedge s_clk);s_run=0;
            repeat(100)@(negedge d_clk);
            if(s_start_ready||source_count!=2||destination_count!=2)$fatal(1,"Stopped controller lost ownership");
            s_run=1;finish_one();
            d_allow_start=0;send(32'h10000010,32'hfffffff0);wait(d_start_valid);
            reset_epoch();repeat(50)@(negedge s_clk);
            if(s_result_valid||source_count!=0||destination_count!=0||result_count!=0)
                $fatal(1,"Old joint-reset epoch escaped");
            send(32'hfedc0020,32'h00010000);finish_one();
        end else if(mode==2)begin
            // Early reply before the descriptor crosses must not launch work.
            local_failure=1;send(32'h10000040,32'hffffffff);force_result=1;
            repeat(3)@(negedge d_clk);force_result=0;finish_one();
            repeat(12)@(negedge s_clk);
            if(destination_count!=0||!s_protocol_fault||!d_protocol_fault||s_start_ready)
                $fatal(1,"Early result silently accepted as a core job");
            // An already offered start survives a later protocol fault.
            reset_epoch();d_allow_start=0;send(32'h10000040,32'h8000002d);wait(d_start_valid);
            @(negedge d_clk);force_result=1;repeat(3)@(negedge d_clk);force_result=0;
            repeat(12)@(negedge s_clk);
            if(!d_start_valid||s_result_valid||!s_protocol_fault)$fatal(1,"Fault canceled offered core start");
            d_allow_start=1;finish_one();
            // Held results do not change; the outer owner must also use fault.
            reset_epoch();s_result_ready=0;send(32'h10000040,32'h20);wait(s_result_valid);
            @(negedge d_clk);force_result=1;repeat(3)@(negedge d_clk);force_result=0;
            repeat(12)@(negedge s_clk);prior=result_count;
            if(!s_protocol_fault||!s_result_valid||s_result_error||s_result_code!=0||s_start_ready)
                $fatal(1,"Held result or later fault visibility changed");
            s_result_ready=1;finish_one();
            if(result_count!=prior+1)$fatal(1,"Held result did not complete exactly once");
            // An inconsistent error/code payload is an explicit protocol fault.
            reset_epoch();invalid_status=1;send(32'hf0000040,32'h89abcdef);finish_one();
            repeat(12)@(negedge s_clk);
            if(!s_protocol_fault||!d_protocol_fault||s_start_ready)$fatal(1,"Invalid result flags silently ignored");
        end else $fatal(1,"Unknown job crossing test mode");
        $display("PASS async_job_port mode=%0d completed=%0d seed=3588cdc2 source_only_no_physical_CDC",mode,total_good);
        $finish;
    end
    initial begin #20000000;$fatal(1,"Job crossing watchdog");end
endmodule
