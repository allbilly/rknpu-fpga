`timescale 1ns/1ps
module tb_ypcb;
    logic SYS_CLK, SYS_RSTN = 1;
    initial SYS_CLK = 0;
    wire [2:0] leds_high, leds_low;
    always #10 SYS_CLK = ~SYS_CLK;
    ypcb_top high_polarity(.SYS_CLK(SYS_CLK), .SYS_RSTN(SYS_RSTN), .led_3bits_tri_o(leds_high));
    ypcb_top #(.LED_ACTIVE_LOW(1)) low_polarity(
        .SYS_CLK(SYS_CLK), .SYS_RSTN(SYS_RSTN), .led_3bits_tri_o(leds_low));
    task automatic check_pass;
        begin
            wait (leds_high[0] === 1'b1 || leds_high[1] === 1'b1);
            @(negedge SYS_CLK);
            if (leds_high !== 3'b001 || leds_low !== 3'b110)
                $fatal(1, "board LED result high=%b low=%b", leds_high, leds_low);
        end
    endtask
    initial begin
        // FPGA register initialization must start the demo even without a button press.
        check_pass();
        // A sub-cycle reset pulse asynchronously reaches both synchronizers.
        #2 SYS_RSTN = 0;
        #1;
        if (high_polarity.reset_pipe !== 3'b000 || low_polarity.reset_pipe !== 3'b000)
            $fatal(1, "reset did not assert asynchronously");
        #2 SYS_RSTN = 1;
        repeat (2) begin
            @(posedge SYS_CLK);
            #1;
            if (high_polarity.reset_pipe[2] !== 1'b0) $fatal(1, "reset released too early");
        end
        @(posedge SYS_CLK);
        #1;
        if (high_polarity.reset_pipe !== 3'b111) $fatal(1, "reset failed to release");
        check_pass();
        $display("PASS YPCB top: startup, asynchronous reset, synchronized release, both LED polarities");
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "YPCB top timeout");
    end
endmodule
