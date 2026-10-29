`timescale 1ns/1ps
module tb_demo_fault;
    logic clk, rst_n = 0, pass, fail;
    initial clk = 0;
    logic [7:0] error_code;
    always #10 clk = ~clk;
    rk_ew_demo dut (.*);
    task automatic restart;
        begin
            @(negedge clk);
            rst_n = 0;
            repeat (3) @(negedge clk);
            rst_n = 1;
        end
    endtask
    task automatic expect_mismatch;
        begin
            @(posedge clk);
            @(negedge clk);
            if (fail !== 1'b1 || pass !== 1'b0 || error_code !== 8'he1)
                $fatal(1, "bad readback did not latch mismatch: pass=%b fail=%b code=%h", pass, fail, error_code);
            repeat (5) @(negedge clk);
            if (fail !== 1'b1 || error_code !== 8'he1) $fatal(1, "demo fault not sticky");
        end
    endtask
    initial begin
        restart();
        // The first checked ADD is 1+2=3 (4200), not zero.
        wait (dut.done);
        wait (dut.host_rsp_valid && dut.host_rsp_ready && !dut.host_write);
        force dut.host_rdata = 16'h0000;
        expect_mismatch();
        $display("PASS known readback corruption rejected");
        release dut.host_rdata;
`ifdef __ICARUS__
        // A four-state simulator must not silently treat X data as a match.
        restart();
        wait (dut.done);
        wait (dut.host_rsp_valid && dut.host_rsp_ready && !dut.host_write);
        force dut.host_rdata = 16'hxxxx;
        expect_mismatch();
        $display("PASS unknown readback rejected (four-state simulation)");
        release dut.host_rdata;
`endif
        restart();
        wait (pass || fail);
        @(negedge clk);
        if (pass !== 1'b1 || fail !== 1'b0 || error_code !== 8'h00)
            $fatal(1, "demo failed to recover after reset");
        $display("PASS demo readback corruption, sticky mismatch and recovery");
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "demo fault test timeout");
    end
endmodule
