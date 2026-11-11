`timescale 1ns/1ps
// Full-BO replay for the captured integer elementwise streams.
//
// The 64 KiB device window at BASE holds the exact 4096-byte input BO images
// (a, b), a zeroed 4096-byte output BO and the captured regcmd BO with the
// worker's value32 address patches already applied. The TB loads the window
// image, runs the new rk_ew_int_dma path (int decoder + int engine), then dumps
// the 4096-byte output BO for the Python masked comparison against
// expected.bin/expected.mask.bin.
//
// Plusargs: STIM=<hex image> NCMD=<regcmd qwords> ECODE=<expected error code>
//           NDONE=<expected done 0/1> OUTFILE=<output BO words> NAME=<case>
module tb_ew_int;
    localparam logic [31:0] BASE = 32'h10000000;
    localparam integer WORDS = 16384;          // 32 KiB device window
    localparam logic [31:0] OUT_OFF = 32'h0000_2400;
    localparam integer OUT_WORDS = 2048;       // 4096-byte output BO

    logic clk;
    initial clk = 1'b0;
    always #5 clk = ~clk;

    logic rst_n = 1'b0;
    logic start_valid = 1'b0, start_ready;
    logic [31:0] start_address = 32'd0, start_amount = 32'd0;
    logic busy, done, task_done, error;
    logic [31:0] completed_tasks;
    integer task_done_count;
    logic [7:0] error_code;
    logic mem_req_valid, mem_req_ready, mem_req_write;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata, mem_rsp_rdata;
    logic mem_rsp_valid, mem_rsp_ready, mem_rsp_error;

    logic [15:0] memory [0:WORDS-1];
    logic [31:0] pending_addr;
    logic pending, pending_write;
    logic [15:0] pending_data;
    integer ncmd, expected_error, expected_done, cycles, wait_cycles;
    integer transactions, outstanding, max_outstanding;
    string stim_path, out_path, case_name;
    integer fd, i;
    logic done_seen;

    rk_ew_int_dma dut (
        .clk(clk), .rst_n(rst_n),
        .start_valid(start_valid), .start_ready(start_ready),
        .start_address(start_address), .start_amount(start_amount),
        .busy(busy), .done(done), .task_done(task_done), .error(error),
        .completed_tasks(completed_tasks), .error_code(error_code),
        .mem_req_valid(mem_req_valid), .mem_req_ready(mem_req_ready),
        .mem_req_write(mem_req_write), .mem_req_addr(mem_req_addr),
        .mem_req_wdata(mem_req_wdata),
        .mem_rsp_valid(mem_rsp_valid), .mem_rsp_ready(mem_rsp_ready),
        .mem_rsp_rdata(mem_rsp_rdata), .mem_rsp_error(mem_rsp_error)
    );

    // Deterministic single-cycle-latency memory with range checking.
    assign mem_req_ready = rst_n && !pending && !mem_rsp_valid;
    always @(posedge clk) begin
        if (!rst_n) begin
            pending <= 1'b0;
            pending_write <= 1'b0;
            pending_addr <= 32'd0;
            pending_data <= 16'd0;
            mem_rsp_valid <= 1'b0;
            mem_rsp_error <= 1'b0;
            mem_rsp_rdata <= 16'd0;
            transactions <= 0;
            outstanding <= 0;
            max_outstanding <= 0;
            cycles <= 0;
            wait_cycles <= 0;
            done_seen <= 1'b0;
            task_done_count <= 0;
        end else begin
            cycles <= cycles + 1;
            if (cycles > 2000000) $fatal(1, "global timeout");
            if (done) done_seen <= 1'b1;
            if (task_done) task_done_count <= task_done_count + 1;
            if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid <= 1'b0;
            if (mem_req_valid && mem_req_ready) begin
                pending <= 1'b1;
                pending_write <= mem_req_write;
                pending_addr <= mem_req_addr;
                pending_data <= mem_req_wdata;
                transactions <= transactions + 1;
                outstanding <= outstanding + 1;
                if (outstanding + 1 > max_outstanding)
                    max_outstanding <= outstanding + 1;
                if (outstanding + 1 > 1) $fatal(1, "more than one outstanding transaction");
            end
            if (pending) begin
                pending <= 1'b0;
                outstanding <= outstanding - 1;
                mem_rsp_valid <= 1'b1;
                if (pending_addr < BASE || pending_addr[0] ||
                    ((pending_addr - BASE) >> 1) >= WORDS) begin
                    mem_rsp_error <= 1'b1;
                    mem_rsp_rdata <= 16'd0;
                    $display("MEMERR at %0t addr=%08h write=%0d", $time,
                             pending_addr, pending_write);
                end else begin
                    mem_rsp_error <= 1'b0;
                    if (pending_write) begin
                        memory[(pending_addr - BASE) >> 1] <= pending_data;
                        mem_rsp_rdata <= 16'd0;
                    end else begin
                        mem_rsp_rdata <= memory[(pending_addr - BASE) >> 1];
                    end
                end
            end
        end
    end

    initial begin
        if (!$value$plusargs("STIM=%s", stim_path)) $fatal(1, "missing STIM");
        if (!$value$plusargs("NCMD=%d", ncmd)) $fatal(1, "missing NCMD");
        if (!$value$plusargs("ECODE=%d", expected_error)) expected_error = 0;
        if (!$value$plusargs("NDONE=%d", expected_done)) expected_done = 1;
        if (!$value$plusargs("OUTFILE=%s", out_path)) $fatal(1, "missing OUTFILE");
        if (!$value$plusargs("NAME=%s", case_name)) case_name = "case";
        if (ncmd < 4 || ncmd > 8192) $fatal(1, "invalid NCMD");
        $readmemh(stim_path, memory);
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        start_address = BASE;
        start_amount = ncmd;
        start_valid = 1'b1;
        @(posedge clk);
        while (!start_ready) @(posedge clk);
        @(negedge clk);
        start_valid = 1'b0;
        wait_cycles = 0;
        while (!done && !error) begin
            @(posedge clk);
            wait_cycles = wait_cycles + 1;
            if (wait_cycles > 500000) $fatal(1, "engine timeout");
        end
        repeat (4) @(negedge clk);
        if (expected_error != 0) begin
            if (!error) $fatal(1, "expected error %0d, none raised", expected_error);
            if (int'(error_code) != expected_error)
                $fatal(1, "wrong error code %0d wanted %0d", error_code, expected_error);
            if (done_seen) $fatal(1, "error case must not raise done");
            $display("PASS %s error_code=%0d transactions=%0d cycles=%0d",
                     case_name, error_code, transactions, cycles);
        end else begin
            if (error) $fatal(1, "unexpected error %0d", error_code);
            if (!done_seen) $fatal(1, "missing done");
            if (completed_tasks != 32'd1)
                $fatal(1, "completed_tasks=%0d wanted 1", completed_tasks);
            if (busy) $fatal(1, "busy must be low after done");
            if (expected_done != 1) $fatal(1, "success case requires NDONE=1");
            if (task_done_count != 1)
                $fatal(1, "task_done pulses %0d wanted 1", task_done_count);
            fd = $fopen(out_path, "w");
            if (fd == 0) $fatal(1, "cannot open OUTFILE");
            for (i = 0; i < OUT_WORDS; i = i + 1)
                $fdisplay(fd, "%04x", memory[(OUT_OFF >> 1) + i]);
            $fclose(fd);
            $display("PASS %s done=1 transactions=%0d max_outstanding=%0d cycles=%0d",
                     case_name, transactions, max_outstanding, cycles);
        end
        $finish;
    end
endmodule
