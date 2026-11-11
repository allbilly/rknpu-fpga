// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Board-image testbench: the autonomous conv self-test must reach PASS from
// reset release exactly as it will on the FPGA, with both LED polarities.
module tb_ypcb_conv_i8_top;
    logic SYS_CLK;
    initial SYS_CLK = 0;
    always #10 SYS_CLK = ~SYS_CLK;

    wire [2:0] leds_high, leds_low;

    ypcb_conv_simple_top high_polarity (
        .SYS_CLK, .led_3bits_tri_o(leds_high)
    );
    ypcb_conv_simple_top #(.LED_ACTIVE_LOW(1)) low_polarity (
        .SYS_CLK, .led_3bits_tri_o(leds_low)
    );

    integer cycles;

    initial begin : TEST
        // Configuration-initialized reset: both instances start in hold.
        for (cycles = 0; cycles < 64; cycles = cycles + 1) begin
            @(posedge SYS_CLK); #1;
            if (high_polarity.reset_n !== 1'b0 || low_polarity.reset_n !== 1'b0)
                $fatal(1, "startup reset released before 64 held edges");
        end
        @(posedge SYS_CLK); #1;
        if (high_polarity.reset_n !== 1'b1 || low_polarity.reset_n !== 1'b1)
            $fatal(1, "startup reset did not release");

        cycles = 0;
        while (high_polarity.self_test.pass !== 1'b1 &&
               high_polarity.self_test.fail !== 1'b1 && cycles < 8_000_000) begin
            @(negedge SYS_CLK);
            cycles = cycles + 1;
        end
        if (cycles == 8_000_000) $fatal(1, "board image produced no result");

        if (high_polarity.self_test.fail !== 1'b0)
            $fatal(1, "board conv self-test FAILED code=%02x",
                   high_polarity.self_test.error_code);
        if (high_polarity.self_test.pass !== 1'b1)
            $fatal(1, "board conv self-test did not reach PASS");

        @(negedge SYS_CLK);
        if (low_polarity.self_test.pass !== 1'b1 ||
            low_polarity.self_test.fail !== 1'b0)
            $fatal(1, "second polarity instance did not pass");

        if (leds_high[1] !== 1'b0 || leds_low[1] !== 1'b1 ||
            leds_high[0] !== 1'b1 || leds_low[0] !== 1'b0)
            $fatal(1, "LED result pattern differs high=%b low=%b", leds_high, leds_low);

        repeat (200) begin
            @(negedge SYS_CLK);
            if (high_polarity.self_test.pass !== 1'b1 ||
                high_polarity.self_test.fail !== 1'b0)
                $fatal(1, "board result was not sticky");
        end
        $display("PASS YPCB conv image: 64-cycle hold, captured C4 k3x3 OC16 whole-BO, both LED polarities");
        $finish;
    end

    initial begin
        #200_000_000;
        $fatal(1, "YPCB conv image timeout");
    end
endmodule
