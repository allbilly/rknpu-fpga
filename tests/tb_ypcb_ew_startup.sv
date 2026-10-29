`timescale 1ns/1ps
module tb_ypcb_ew_startup;
    logic SYS_CLK;
    initial SYS_CLK = 0;
    wire [2:0] leds_high, leds_low;
    always #10 SYS_CLK = ~SYS_CLK;
    ypcb_ew_startup_top high_polarity (.SYS_CLK, .led_3bits_tri_o(leds_high));
    ypcb_ew_startup_top #(.LED_ACTIVE_LOW(1)) low_polarity (
        .SYS_CLK, .led_3bits_tri_o(leds_low)
    );
    initial begin
        for (integer i=0; i<64; i=i+1) begin
            @(posedge SYS_CLK); #1;
            if (high_polarity.reset_n !== 0 || low_polarity.reset_n !== 0)
                $fatal(1, "board startup reset released early");
            if (leds_high !== 3'b000 || leds_low !== 3'b111)
                $fatal(1, "unexpected board status during startup reset");
        end
        @(posedge SYS_CLK); #1;
        if (high_polarity.reset_n !== 1 || low_polarity.reset_n !== 1)
            $fatal(1, "board startup reset did not release");
        wait (leds_high[0] === 1'b1 || leds_high[1] === 1'b1);
        @(negedge SYS_CLK);
        if (leds_high !== 3'b001 || leds_low !== 3'b110)
            $fatal(1, "raw SUB(9) board self-test failed: %b %b", leds_high, leds_low);
        repeat (100) begin
            @(negedge SYS_CLK);
            if (leds_high !== 3'b001 || leds_low !== 3'b110)
                $fatal(1, "board result was not sticky");
        end
        $display("PASS YPCB startup profile: no external reset, 64-cycle hold, raw SUB(9), both LED polarities");
        $finish;
    end
    initial begin #100000; $fatal(1, "YPCB startup profile timeout"); end
endmodule
