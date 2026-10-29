// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_array_bram_demo;
    // Verification-only clock and ordered scoreboard calculations intentionally
    // use blocking assignments. No DUT warning is suppressed by this region.
    /* verilator lint_off BLKSEQ */
    logic clk,reset_n=0;
    wire [2:0] leds;
    initial clk=0;
    always #10 clk=~clk; // Functional simulation at the intended 50 MHz input.
    ypcb_cmac_array_top dut(.SYS_CLK(clk),.SYS_RSTN(reset_n),.led_3bits_tri_o(leds));
    logic [47:0] outputs[0:63];
    logic [47:0] operands[0:6527];
    integer mode,initializations,checks,command_reads,operand_reads,writes,acks,cycles;
    integer successful_runs,reset_runs,fault_runs;
    always @(posedge clk or negedge dut.reset_n) begin
        if (!dut.reset_n) begin
            initializations=0;checks=0;command_reads=0;operand_reads=0;writes=0;acks=0;cycles=0;
        end else begin
            cycles=cycles+1;
            if (dut.demo.host_valid&&dut.demo.core_busy) $fatal(1,"host/engine ownership collision");
            if (dut.demo.host_valid&&dut.demo.host_ready) begin
                if (dut.demo.host_write) begin
                    if (initializations>=4096||dut.demo.index!==12'(initializations)) $fatal(1,"initialization order");
                    initializations=initializations+1;
                end else begin
                    if (checks>=4096||dut.demo.index!==12'(checks)) $fatal(1,"readback order");
                    checks=checks+1;
                end
            end
            if (dut.demo.mem_req_valid&&dut.demo.mem_req_ready) begin
                if (initializations!=4096) $fatal(1,"engine began before full BRAM initialization");
                if (dut.demo.mem_req_write) begin
                    if (writes>=64||{dut.demo.mem_req_addr,dut.demo.mem_req_wdata}!==outputs[writes])
                        $fatal(1,"board demo numerical/address mismatch output=%0d",writes);
                    writes=writes+1;
                end else if (dut.demo.mem_req_addr>=32'h100e0000) begin
                    if (command_reads>=196||dut.demo.mem_req_addr!==32'h100e0000+32'(command_reads*2)) $fatal(1,"command read order");
                    command_reads=command_reads+1;
                end else begin
                    if (command_reads!=196||operand_reads>=6528) $fatal(1,"operand read count/ownership");
                    if (dut.demo.mem_req_addr!==operands[operand_reads][47:16]) $fatal(1,"operand read packing/order");
                    operand_reads=operand_reads+1;
                end
            end
            if (dut.demo.unused_ack) acks=acks+1;
            if (dut.demo.pass&&dut.demo.fail) $fatal(1,"simultaneous pass and fail");
        end
    end
    task automatic reset_board;
        @(negedge clk);#2;reset_n=0;
        #1;
        if (dut.reset_n!==0||leds!==0||dut.demo.mem_req_valid||dut.demo.host_valid)
            $fatal(1,"asynchronous reset did not quiesce board before next clock");
        repeat(5) @(negedge clk);
        if (leds!==0||dut.demo.pass||dut.demo.fail) $fatal(1,"board reset indicators");
        #2;reset_n=1;
        #1;if (dut.reset_n!==0) $fatal(1,"reset released asynchronously");
        repeat(2) begin
            @(posedge clk);#1;
            if (dut.reset_n!==0) $fatal(1,"reset synchronizer released early");
        end
        @(posedge clk);#1;
        if (dut.reset_n!==1) $fatal(1,"reset synchronizer failed three-edge release");
        @(negedge clk);
    endtask
    task automatic success;
        wait(dut.demo.pass||dut.demo.fail);@(negedge clk);
        if (dut.demo.fail||dut.demo.error_code!=0||leds[1:0]!==2'b01) $fatal(1,"board demo failed code=%h",dut.demo.error_code);
        if (initializations!=4096||checks!=4096||command_reads!=196||operand_reads!=6528||writes!=64||acks!=64)
            $fatal(1,"incomplete board self-test init=%0d check=%0d cmd=%0d operand=%0d writes=%0d acks=%0d",initializations,checks,command_reads,operand_reads,writes,acks);
        repeat(20) begin
            @(negedge clk);
            if (!dut.demo.pass||dut.demo.fail||dut.demo.host_valid||dut.demo.mem_req_valid) $fatal(1,"pass not sticky/quiescent");
        end
        successful_runs=successful_runs+1;
    endtask
    task automatic failure(input logic [7:0] code);
        wait(dut.demo.pass||dut.demo.fail);@(negedge clk);
        if (!dut.demo.fail||dut.demo.pass||dut.demo.error_code!==code||leds[1:0]!==2'b10) $fatal(1,"wrong board failure code=%h expected=%h",dut.demo.error_code,code);
        repeat(20) begin
            @(negedge clk);
            if (!dut.demo.fail||dut.demo.pass||dut.demo.host_valid||dut.demo.mem_req_valid) $fatal(1,"failure not sticky/quiescent");
        end
        fault_runs=fault_runs+1;
    endtask
    initial begin
        successful_runs=0;reset_runs=0;fault_runs=0;
        if (!$value$plusargs("MODE=%d",mode)) $fatal(1,"missing mode");
        $readmemh("tests/cmac/array_data/writes.hex",outputs);
        $readmemh("tests/cmac/array_data/reads.hex",operands);
        reset_board();
        case (mode)
            0:success();
            1:begin
                wait(dut.demo.mem_rsp_valid);@(negedge clk);
                force dut.demo.mem_rsp_error=1'b1;
                failure(5);release dut.demo.mem_rsp_error;
            end
            2:begin
                wait(dut.demo.state==8&&dut.demo.index==0);@(negedge clk);
                force dut.demo.host_rdata=16'hffff;
                failure(8'hfd);release dut.demo.host_rdata;
            end
            3:begin
                wait(command_reads>=20);reset_board();reset_runs=reset_runs+1;success();
            end
            4:begin
                wait(dut.demo.engine.core.frame_valid&&dut.demo.engine.core.frame_ready);
                @(posedge clk);
                reset_board();reset_runs=reset_runs+1;success();
            end
            5:begin
                wait(checks>=20);reset_board();reset_runs=reset_runs+1;success();
            end
            6:begin success();reset_board();reset_runs=reset_runs+1;success();end
            8:begin
                wait(operand_reads>=20);@(negedge clk);
                force dut.demo.watchdog=20'hfffff;
                failure(8'hfe);release dut.demo.watchdog;
            end
`ifndef VERILATOR
            7:begin
                wait(dut.demo.state==8&&dut.demo.index==0);@(negedge clk);
                force dut.demo.host_rdata=16'hxxxx;
                failure(8'hfd);release dut.demo.host_rdata;
            end
`endif
            default:$fatal(1,"unsupported test mode");
        endcase
        $display("PASS C32 K16 BRAM board RTL mode=%0d success=%0d resets=%0d faults=%0d init=%0d check=%0d cmd_reads=%0d operand_reads=%0d writes=%0d acks=%0d cycles=%0d; no physical FPGA test",mode,successful_runs,reset_runs,fault_runs,initializations,checks,command_reads,operand_reads,writes,acks,cycles);
        $finish;
    end
    initial begin #60000000;$fatal(1,"board demo simulation timeout");end
    /* verilator lint_on BLKSEQ */
endmodule
