`timescale 1ns/1ps
module tb_dma_demo;
    logic clk, rst_n=0, pass, fail;
    logic [7:0] error_code;
    integer requests, writes, tasks, jobs, host_writes, host_reads;
    initial clk=0;
    always #10 clk=~clk;
    rk_ew_dma_demo dut(.*);
    always @(posedge clk) begin
        if (!rst_n) begin requests<=0; writes<=0; tasks<=0; jobs<=0; host_writes<=0; host_reads<=0; end
        else begin
            if (dut.mem_req_valid && dut.mem_req_ready) begin
                requests<=requests+1;
                if (dut.mem_req_write) writes<=writes+1;
            end
            if (dut.unused_task_done) tasks<=tasks+1;
            if (dut.done) jobs<=jobs+1;
            if (dut.host_valid && dut.host_ready) begin
                if (dut.busy) $fatal(1,"host/accelerator overlap");
                if (dut.host_write) host_writes<=host_writes+1;
                else host_reads<=host_reads+1;
            end
            if (pass && (dut.busy || fail || jobs!=1 || tasks!=2)) $fatal(1,"premature pass");
        end
    end
    task automatic restart;
        @(negedge clk); rst_n=0;
        repeat(3) @(negedge clk);
        rst_n=1;
    endtask
    task automatic expect_pass;
        wait(pass || fail);
        @(negedge clk);
        if (pass!==1'b1 || fail!==1'b0 || error_code!==0 || requests!=324 || writes!=32 ||
            tasks!=2 || jobs!=1 || host_writes!=336 || host_reads!=336)
            $fatal(1,"DMA demo counts/error req=%0d wr=%0d tasks=%0d jobs=%0d init=%0d check=%0d code=%h",
                   requests,writes,tasks,jobs,host_writes,host_reads,error_code);
    endtask
    task automatic expect_error(input logic [7:0] code);
        // A memory error first latches in DMA, then reaches the demo controller.
        repeat(3) @(negedge clk);
        if (fail!==1'b1 || pass!==1'b0 || error_code!==code)
            $fatal(1,"wrong injected error got %h wanted %h",error_code,code);
        repeat(4) @(negedge clk);
        if (fail!==1'b1 || error_code!==code) $fatal(1,"fault not sticky");
    endtask
    initial begin
        restart(); expect_pass();
        $display("PASS DMA board workload: verbatim SUB(9), two tasks, 324 requests, 336 memory checks");
        restart();
        wait(dut.mem_req_valid && dut.mem_req_ready);
        restart(); expect_pass();
        $display("PASS DMA demo reset during command fetch and restart");
        restart();
        wait(requests==141);
        restart(); expect_pass();
        $display("PASS DMA demo reset during data execution and restart");
        restart();
        wait(dut.host_rsp_valid && dut.host_rsp_ready);
        force dut.host_error=1'b1;
        expect_error(8'he2); release dut.host_error;
        $display("PASS DMA demo initialization bus error");
        restart();
        wait(dut.mem_rsp_valid && dut.mem_rsp_ready);
        force dut.mem_rsp_error=1'b1;
        expect_error(8'd5); release dut.mem_rsp_error;
        $display("PASS DMA demo command bus error");
        restart();
        wait(dut.done);
        force dut.completed_tasks=32'd1;
        expect_error(8'he4); release dut.completed_tasks;
        $display("PASS DMA demo completion-count mismatch");
        restart();
        wait(dut.done);
        wait(dut.host_rsp_valid && dut.host_rsp_ready && !dut.host_write);
        force dut.host_rdata=16'h0000;
        expect_error(8'he1); release dut.host_rdata;
        $display("PASS DMA demo known readback corruption");
`ifdef __ICARUS__
        restart();
        wait(dut.done);
        wait(dut.host_rsp_valid && dut.host_rsp_ready && !dut.host_write);
        force dut.host_rdata=16'hxxxx;
        expect_error(8'he1); release dut.host_rdata;
        $display("PASS DMA demo unknown readback corruption");
`endif
        restart();
        force dut.watchdog=32'd1000000;
        expect_error(8'he3); release dut.watchdog;
        restart(); expect_pass();
        $display("PASS DMA demo watchdog and fault recovery");
        $finish;
    end
    initial begin
        #1000000;
        $fatal(1,"DMA demo test timeout");
    end
endmodule
