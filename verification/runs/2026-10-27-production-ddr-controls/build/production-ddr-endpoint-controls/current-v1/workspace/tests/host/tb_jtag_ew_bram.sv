`timescale 1ns/1ps
module tb_jtag_ew_bram #(
    parameter bit THROUGH_MAILBOX=0
);
    logic clk;
    initial clk=0;
    always #10 clk=~clk;
    logic rst_n=0,req_valid,req_ready,rsp_valid,irq,fault;
    logic [603:0] req;
    logic [511:0] rsp_data;
    logic [7:0] rsp_status;
    logic [15:0] rsp_seq;
    logic direct_valid=0;
    logic [603:0] direct_req=0;
    logic mailbox_valid;
    logic [603:0] mailbox_req;
    logic tck=0,capture=0,shift=0,update=0,sel=0,tdi=0;
    wire tdo;
    assign req_valid=THROUGH_MAILBOX ? mailbox_valid : direct_valid;
    assign req=THROUGH_MAILBOX ? mailbox_req : direct_req;
    rk_jtag_ew_bram #(.TIMEOUT_CYCLES(128),.MAX_TASKS(4)) dut(.*);
    otpu_jtag_mailbox mailbox (
        .clk,.rst(!rst_n),.tck,.capture,.shift,.update,.sel,.tdi,.tdo,
        .req_valid(mailbox_valid),.req_ready(THROUGH_MAILBOX && req_ready),.req(mailbox_req),
        .rsp_valid,.rsp_data,.rsp_status,.rsp_seq
    );
    `include "tests/host/mailbox_scan.svh"
    logic [15:0] sequence_id=16'hfffe;
    integer commands=0;
    // No hierarchical RAM reads/writes: uploads and checks use the public frames.
    task automatic command(input logic [7:0] op,input logic [31:0] address,
        input logic [511:0] data,output logic [511:0] result,
        input logic [7:0] status=0,input logic [3:0] strobes=15);
        logic [639:0] packet,received;
        integer polls;
        sequence_id=sequence_id==16'hffff ? 16'd1 : sequence_id+1;
        packet={36'b0,32'h4f54504a,sequence_id,op,strobes,address,data};
        if (THROUGH_MAILBOX) begin
            scan_frame(packet,received);polls=0;
            while ((received[567:536]!==32'h4f54504a || received[535:520]!==sequence_id) && polls<6) begin
                scan_frame(0,received);polls=polls+1;
            end
            if (received[639:568]!==0 || received[567:536]!==32'h4f54504a ||
                received[535:520]!==sequence_id || received[519:512]!==status)
                $fatal(1,"mailbox response mismatch seq %h status %h expected %h",received[535:520],received[519:512],status);
            result=received[511:0];
        end else begin
            if (!req_ready) $fatal(1,"endpoint unexpectedly refused request");
            direct_req=packet[603:0];direct_valid=1;
            @(negedge clk);direct_valid=0;polls=0;
            while (!rsp_valid && polls<1000) begin @(negedge clk);polls=polls+1;end
            if (!rsp_valid || rsp_seq!==sequence_id || rsp_status!==status)
                $fatal(1,"frame response mismatch seq %h status %h expected %h",rsp_seq,rsp_status,status);
            result=rsp_data;
            @(negedge clk);
        end
        if (status!=0 && result!==0) $fatal(1,"error leaked nonzero data");
        commands=commands+1;
    endtask
    logic [511:0] value,expected_line,upload_line;
    logic [31:0] start_address,start_amount,tag,address;
    integer expected_tasks,upload_count,check_count,fd,rc,observed,jobs,negative_mode,reset_partial;
    integer accepted_writes;
    always @(posedge clk) begin
        if (!rst_n) accepted_writes<=0;
        else if (dut.mem_req_valid && dut.mem_req_ready && dut.mem_req_write) accepted_writes<=accepted_writes+1;
    end
    string prefix,output_path;
    task automatic reset_all;
        @(negedge clk);rst_n=0;direct_valid=0;
        repeat(5) @(negedge clk);rst_n=1;repeat(5) @(negedge clk);
        if (fault || irq) $fatal(1,"joint reset did not clear status");
    endtask
    task automatic expect_reg(input logic [31:0] off,input logic [31:0] data);
        command(1,off,0,value);
        if (value!=={480'b0,data}) $fatal(1,"register %h mismatch %h !=%h",off,value,data);
    endtask
    task automatic check_memory(input string checks,input string observed_path);
        fd=$fopen(checks,"r");observed=$fopen(observed_path,"w");
        if (fd==0 || observed==0) $fatal(1,"cannot open readback files");
        for(integer i=0;i<upload_count;i=i+1) begin
            rc=$fscanf(fd,"%h %h\n",address,expected_line);if(rc!=2) $fatal(1,"short expected file");
            command(3,address,0,value);
            if (value!==expected_line) $fatal(1,"memory mismatch at %h actual %h expected %h",address,value,expected_line);
            $fdisplay(observed,"%08h %0128h",address,value);
        end
        rc=$fscanf(fd,"%h %h\n",address,expected_line);if(rc==2) $fatal(1,"extra expected line");
        $fclose(fd);$fclose(observed);
    endtask
    initial begin
        if (!$value$plusargs("CASE=%s",prefix) || !$value$plusargs("OUTPUT=%s",output_path) ||
            !$value$plusargs("START=%h",start_address) || !$value$plusargs("AMOUNT=%d",start_amount) ||
            !$value$plusargs("NTASKS=%d",expected_tasks) || !$value$plusargs("NLINES=%d",upload_count)) $fatal(1,"missing case metadata");
        if (!$value$plusargs("JOBS=%d",jobs)) jobs=1;
        if (!$value$plusargs("NEGATIVE=%d",negative_mode)) negative_mode=0;
        if (!$value$plusargs("RESET_PARTIAL=%d",reset_partial)) reset_partial=0;
        reset_all();expect_reg(0,32'h524b4557);expect_reg(4,32'h00010000);
        command(1,32'h80000000,0,value,3);command(2,0,0,value,2);
        command(2,32'h18,0,value,2,4'h7);
        command(3,32'h90000000,0,value,6);command(3,32'h10000002,0,value,4);
        fd=$fopen({prefix,"/upload.txt"},"r");if (fd==0) $fatal(1,"cannot open upload");
        for(integer i=0;i<upload_count;i=i+1) begin
            rc=$fscanf(fd,"%h %h\n",address,upload_line);if(rc!=2) $fatal(1,"short upload");
            command(4,address,upload_line,value);
        end
        rc=$fscanf(fd,"%h %h\n",address,upload_line);if(rc==2) $fatal(1,"extra upload line");$fclose(fd);
        if (negative_mode==1) begin
            command(3,start_address & 32'hffffffc0,0,value);
            value[8*(start_address[5:0]+6) +:16]=16'hffff;
            command(4,start_address & 32'hffffffc0,value,upload_line);
        end
        if (reset_partial!=0) begin
            if (THROUGH_MAILBOX) $fatal(1,"partial reset driver requires SYS frame interface");
            command(2,32'h10,{480'b0,start_address},value);
            command(2,32'h14,{480'b0,start_amount},value);
            command(2,32'h18,512'h17,value);
            command(2,32'h0c,512'd1,value);
            wait(accepted_writes==17);
            @(negedge clk);rst_n=0;direct_valid=0;
            repeat(5) @(negedge clk);rst_n=1;repeat(5) @(negedge clk);
            expect_reg(8,32'h10);
            check_memory({prefix,"/partial.txt"},{output_path,".partial"});
            // Re-execute with original BOs still resident; reset never rolls back RAM.
        end
        for(integer job=0;job<jobs;job=job+1) begin
            tag=32'h35880000+32'(job);
            command(2,32'h10,{480'b0,start_address},value);
            command(2,32'h14,{480'b0,start_amount},value);
            command(2,32'h18,{480'b0,tag},value);
            command(2,32'h0c,512'd1,value);
            if (!THROUGH_MAILBOX) begin
                // Before the raw DMA can finish, RAM ownership must reject traffic.
                command(3,32'h10040000,0,value,2);
                command(4,32'h10040000,0,value,2);
            end
            value=0;check_count=0;
            while (!value[2] && check_count<10000) begin
                command(1,8,0,value);check_count=check_count+1;
            end
            if (!value[2] || value[1] || value[3]!=(negative_mode!=0) || !irq) $fatal(1,"bad job result %h",value);
            expect_reg(32'h1c,tag);expect_reg(32'h20,negative_mode==0 ? 32'(expected_tasks) : 32'b0);
            expect_reg(32'h24,negative_mode==0 ? 32'b0 : 32'd1);
            if (negative_mode!=0) begin
                if (!fault) $fatal(1,"raw unknown register did not fault endpoint");
                command(2,32'h0c,512'd2,value,2);
                command(3,32'h10040000,0,value,2);
                reset_all();expect_reg(8,32'h10);
            end else begin
                if (fault) $fatal(1,"successful job faulted");
                command(2,32'h10,0,value,2);command(2,32'h0c,512'd1,value,2);
                // Readback is legal while the successful completion remains pending.
                check_memory({prefix,"/expected.txt"},output_path);
                command(2,32'h0c,512'd2,value);expect_reg(8,32'h10);
                if (irq) $fatal(1,"ACK did not clear IRQ");
            end
        end
        $display("PASS jtag_ew_bram %s mailbox=%0d jobs=%0d negative=%0d reset_partial=%0d lines=%0d commands=%0d",prefix,THROUGH_MAILBOX,jobs,negative_mode,reset_partial,upload_count,commands);
        $finish;
    end
    initial begin #3000000000;$fatal(1,"host BRAM global timeout");end
endmodule
