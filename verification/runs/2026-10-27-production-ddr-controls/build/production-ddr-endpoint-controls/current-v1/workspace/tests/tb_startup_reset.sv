`timescale 1ns/1ps
module tb_startup_reset;
    logic clk, request_reset;
    initial begin clk=0; request_reset=0; end
    wire rst_short, rst_default;
    always #10 clk = ~clk;
    rk_startup_reset #(.HOLD_CYCLES(3)) short_hold (
        .clk, .request_reset, .rst_n(rst_short)
    );
    rk_startup_reset default_hold (.clk, .request_reset, .rst_n(rst_default));
    task automatic edge_check(input bit want_short, input bit want_default);
        @(posedge clk); #1;
        if (rst_short !== want_short || rst_default !== want_default)
            $fatal(1, "startup reset released at wrong edge: %b %b", rst_short, rst_default);
    endtask
    initial begin
        #1;
        if (rst_short !== 0 || rst_default !== 0) $fatal(1, "reset not initially asserted");
        for (integer edge_index=1; edge_index<=65; edge_index=edge_index+1)
            edge_check(edge_index>3, edge_index>64);
        repeat (80) edge_check(1,1);
        @(negedge clk); #2; request_reset=1;
        #1;
        if (rst_short !== 1 || rst_default !== 1) $fatal(1, "synchronous request changed reset off-edge");
        repeat (4) edge_check(0,0);
        @(negedge clk); request_reset=0;
        for (integer edge_index=1; edge_index<=65; edge_index=edge_index+1)
            edge_check(edge_index>3, edge_index>64);
        // Reassert during a hold; the full interval must restart.
        @(negedge clk); request_reset=1;
        edge_check(0,0);
        @(negedge clk); request_reset=0;
        edge_check(0,0);
        @(negedge clk); request_reset=1;
        edge_check(0,0);
        @(negedge clk); request_reset=0;
        for (integer edge_index=1; edge_index<=65; edge_index=edge_index+1)
            edge_check(edge_index>3, edge_index>64);
        $display("PASS startup reset: initial hold, exact release, synchronous restart, held and repeated requests");
        $finish;
    end
    initial begin #100000; $fatal(1, "startup reset timeout"); end
endmodule
