`timescale 1ns/1ps
module tb_jtag_dual_bram;
    logic clk,rst_n=0,req_valid=0;
    initial clk=0;
    always #10 clk=~clk;
    logic [603:0] req=0;
    wire req_ready,rsp_valid,irq,fault;
    wire [511:0] rsp_data;
    wire [7:0] rsp_status;
    wire [15:0] rsp_seq;
    wire [31:0] cmac_rearm_count;
    logic [15:0] sequence_id=0;
    logic [511:0] value,data;
    logic [31:0] address;
    integer commands=0,accepted_writes,local_reset_edges;
    integer mode,lines,ew_lines,repeat_lines,ew_amount,fd,rc;
    string directory;
    rk_jtag_dual_bram #(.TIMEOUT_CYCLES(256),.MAX_TASKS(4)) dut(.*);
    always @(posedge clk)begin
        if(!rst_n)begin accepted_writes<=0;local_reset_edges<=0;end
        else begin
            if(dut.mem_req_valid&&dut.mem_req_ready&&dut.mem_req_write)accepted_writes<=accepted_writes+1;
            if(!dut.cm_engine.child_rst_n)begin
                if(dut.engine_pending||dut.mem_req_valid||dut.mem_rsp_valid||!dut.owner_valid||!dut.owner_cmac||dut.ew_busy)
                    $fatal(1,"local reset crossed live/shared ownership");
                local_reset_edges<=local_reset_edges+1;
            end
        end
    end
    task automatic command(input logic [7:0] opcode,input logic [31:0] offset,
        input logic [511:0] payload,output logic [511:0] result,input logic [7:0] status=0);
        @(negedge clk);sequence_id=sequence_id+1'b1;
        if(!req_ready)$fatal(1,"private frame interface not idle");
        req={32'h4f54504a,sequence_id,opcode,4'hf,offset,payload};req_valid=1;
        @(negedge clk);req_valid=0;
        begin: await_reply
            for(integer age=0;age<1000;age=age+1)begin
                if(rsp_valid)disable await_reply;
                @(negedge clk);
            end
            $fatal(1,"frame response timeout");
        end
        if(rsp_status!==status||rsp_seq!==sequence_id)$fatal(1,"frame response status/sequence offset=%h actual=%h expected=%h",offset,rsp_status,status);
        if(status!=0&&rsp_data!==0)$fatal(1,"error response data not zero");
        result=rsp_data;commands=commands+1;@(negedge clk);
    endtask
    task automatic reg_write(input logic [31:0] offset,input logic [31:0] payload,input logic [7:0] status=0);
        command(2,offset,{480'b0,payload},value,status);
    endtask
    task automatic expect_reg(input logic [31:0] offset,input logic [31:0] expected);
        command(1,offset,0,value);
        if(value!=={480'b0,expected})$fatal(1,"register mismatch offset=%h actual=%h expected=%h",offset,value,expected);
    endtask
    task automatic reset_all;
        @(negedge clk);rst_n=0;req_valid=0;repeat(5)@(negedge clk);
        rst_n=1;repeat(5)@(negedge clk);
        if(irq||fault||cmac_rearm_count!=0)$fatal(1,"global reset status");
        expect_reg(0,32'h524b4557);expect_reg(4,32'h00010000);
        expect_reg(32'h100,32'h524b434d);expect_reg(32'h104,32'h00010000);
    endtask
    task automatic upload(input string file,input integer count);
        fd=$fopen(file,"r");if(fd==0)$fatal(1,"missing upload");
        for(integer i=0;i<count;i=i+1)begin
            rc=$fscanf(fd,"%h %h\n",address,data);if(rc!=2)$fatal(1,"short upload");
            command(4,address,data,value);
        end
        rc=$fscanf(fd,"%h %h\n",address,data);if(rc==2)$fatal(1,"extra upload");$fclose(fd);
    endtask
    task automatic check_memory(input string file);
        fd=$fopen(file,"r");if(fd==0)$fatal(1,"missing expected memory");
        for(integer i=0;i<lines;i=i+1)begin
            rc=$fscanf(fd,"%h %h\n",address,data);if(rc!=2)$fatal(1,"short readback expectation");
            command(3,address,0,value);
            if(value!==data)$fatal(1,"joined memory mismatch address=%h",address);
        end
        rc=$fscanf(fd,"%h %h\n",address,data);if(rc==2)$fatal(1,"extra expected memory");$fclose(fd);
    endtask
    task automatic stage(input logic [31:0] base,input logic [31:0] amount,input logic [31:0] tag,
                         input logic [31:0] start=32'h100e0000);
        reg_write(base+32'h10,start);reg_write(base+32'h14,amount);reg_write(base+32'h18,tag);
    endtask
    task automatic result(input logic [31:0] base,input logic [31:0] tag,input logic [31:0] tasks,input logic [7:0] code);
        begin: await_result
            for(integer age=0;age<20000;age=age+1)begin
                command(1,base+8,0,value);
                if(value[2])disable await_result;
            end
            $fatal(1,"joined job result timeout");
        end
        if(!irq||value[1]||value[6]||value[3]!== (code!=0)||value[5]!== (code!=0))$fatal(1,"inconsistent job status");
        expect_reg(base+32'h1c,tag);expect_reg(base+32'h20,tasks);expect_reg(base+32'h24,{24'b0,code});
    endtask
    initial begin
        if(!$value$plusargs("DIRECTORY=%s",directory)||!$value$plusargs("MODE=%d",mode)||
           !$value$plusargs("LINES=%d",lines)||!$value$plusargs("EW_LINES=%d",ew_lines)||
           !$value$plusargs("REPEAT_LINES=%d",repeat_lines)||!$value$plusargs("EW_AMOUNT=%d",ew_amount))$fatal(1,"missing joined metadata");
        if(mode<0||mode>4||lines!=1408||ew_lines<1||repeat_lines<1)$fatal(1,"bad joined test profile");
        reset_all();
        // Exact window decode: full-width high addresses never alias either ID.
        command(1,32'h200,0,value,3);command(1,32'h10000,0,value,3);
        command(2,32'h180,0,value,3);command(2,32'h100,0,value,2);
        if(mode!=2&&mode!=3)upload({directory,"/initial.txt"},lines);
        if(mode==1)begin
            command(3,32'h100e0000,0,value);value[63:48]=16'hffff;
            command(4,32'h100e0000,value,data);
        end
        stage(32'h100,mode==2 ? 44 : 45,32'habc00001,mode==3 ? 32'h10100000 : 32'h100e0000);
        reg_write(32'h10c,1);
        if(mode==4)begin
            // Interrupt during command fetch; RAM/input contents survive the
            // global ownership reset and the restarted job must fetch afresh.
            begin: await_read
                for(integer age=0;age<100;age=age+1)begin
                    @(posedge clk);if(dut.mem_req_valid&&dut.mem_req_ready)disable await_read;
                end
                $fatal(1,"no command fetch to interrupt");
            end
            reset_all();stage(32'h100,45,32'habc00001);reg_write(32'h10c,1);
        end
        if(mode>=1&&mode<=3)begin
            result(32'h100,32'habc00001,0,mode==1 ? 8'd1 : mode==2 ? 8'd7 : 8'd5);
            if(!fault||accepted_writes!=0||cmac_rearm_count!=0||local_reset_edges!=0)$fatal(1,"failed CMAC was rearmed or wrote data");
            reg_write(32'h10c,2,2);reg_write(32'h0c,1,2);
            command(3,32'h10010000,0,value,2);
            repeat(10)@(negedge clk);if(!fault||!irq)$fatal(1,"CMAC fault was not sticky");
            $display("PASS dual_raw_jobs mode=%0d expected_fault rearm=0 writes=0",mode);$finish;
        end
        // Admission is blocked from accepted doorbell through result ACK.
        command(3,32'h10010000,0,value,2);
        stage(0,32'(ew_amount),32'habc00002);reg_write(32'h0c,1,2);
        result(32'h100,32'habc00001,1,0);
        if(fault||cmac_rearm_count!=1||local_reset_edges!=2||accepted_writes!=32)$fatal(1,"CMAC standalone rearm/count failure");
        reg_write(32'h0c,1,2);reg_write(32'h0c,2,2);
        check_memory({directory,"/cmac_expected.txt"});reg_write(32'h10c,2);
        upload({directory,"/ew_delta.txt"},ew_lines);reg_write(32'h0c,1);
        result(0,32'habc00002,2,0);
        if(cmac_rearm_count!=1||local_reset_edges!=2||accepted_writes!=64)$fatal(1,"EW phase changed CMAC ownership/data count");
        check_memory({directory,"/ew_expected.txt"});reg_write(32'h0c,2);
        upload({directory,"/repeat_delta.txt"},repeat_lines);
        stage(32'h100,45,32'habc00003);reg_write(32'h10c,1);result(32'h100,32'habc00003,1,0);
        if(fault||cmac_rearm_count!=2||local_reset_edges!=4||accepted_writes!=96)$fatal(1,"CMAC-EW-CMAC rearm/count failure");
        check_memory({directory,"/repeat_expected.txt"});reg_write(32'h10c,2);
        repeat(5)@(negedge clk);if(irq||fault||dut.owner_valid)$fatal(1,"owner not released after final ACK");
        $display("PASS dual_raw_jobs mode=%0d cmac_jobs=2 ew_tasks=2 rearm=2 writes=96 checked_lines=%0d",mode,3*lines);$finish;
    end
    initial begin #100000000;$fatal(1,"joined wall-cycle watchdog");end
endmodule
