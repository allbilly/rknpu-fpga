// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Board-image testbench: the autonomous pooling self-test must reach PASS from
// reset release exactly as it will on the FPGA, with both LED polarities.
module tb_ypcb_ppu_i8;
    logic SYS_CLK;
    initial SYS_CLK = 0;
    always #10 SYS_CLK = ~SYS_CLK;

    wire [2:0] leds_high, leds_low;

    ypcb_ppu_i8_top high_polarity (
        .SYS_CLK, .led_3bits_tri_o(leds_high)
    );
    ypcb_ppu_i8_top #(.LED_ACTIVE_LOW(1)) low_polarity (
        .SYS_CLK, .led_3bits_tri_o(leds_low)
    );

    integer cycles;

    initial begin : TEST
        // Reset is configuration-initialized, so both instances start in hold.
        for (cycles = 0; cycles < 64; cycles = cycles + 1) begin
            @(posedge SYS_CLK); #1;
            if (high_polarity.reset_n !== 1'b0 || low_polarity.reset_n !== 1'b0)
                $fatal(1, "startup reset released before 64 held edges");
        end
        @(posedge SYS_CLK); #1;
        if (high_polarity.reset_n !== 1'b1 || low_polarity.reset_n !== 1'b1)
            $fatal(1, "startup reset did not release");

        // Wait for a terminal result; the watchdog inside the self-test also
        // bounds this, so a hang is an explicit failure rather than a timeout.
        cycles = 0;
        while (high_polarity.self_test.pass !== 1'b1 &&
               high_polarity.self_test.fail !== 1'b1 && cycles < 3_000_000) begin
            @(negedge SYS_CLK);
            cycles = cycles + 1;
        end
        if (cycles == 3_000_000) $fatal(1, "board image produced no result");

        if (high_polarity.self_test.fail !== 1'b0)
            $fatal(1, "board self-test FAILED code=%02x",
                   high_polarity.self_test.error_code);
        if (high_polarity.self_test.pass !== 1'b1)
            $fatal(1, "board self-test did not reach PASS");

        @(negedge SYS_CLK);
        if (low_polarity.self_test.pass !== 1'b1 ||
            low_polarity.self_test.fail !== 1'b0)
            $fatal(1, "second polarity instance did not pass");

        // pass=LED0, heartbeat=LED2; fail must stay dark in both polarities.
        if (leds_high[1] !== 1'b0 || leds_low[1] !== 1'b1 ||
            leds_high[0] !== 1'b1 || leds_low[0] !== 1'b0)
            $fatal(1, "LED result pattern differs high=%b low=%b", leds_high, leds_low);

        // The captured result must stay latched across heartbeat edges.
        repeat (200) begin
            @(negedge SYS_CLK);
            if (high_polarity.self_test.pass !== 1'b1 ||
                high_polarity.self_test.fail !== 1'b0)
                $fatal(1, "board result was not sticky");
        end
        $display("PASS YPCB PPU INT8 image: 64-cycle hold, captured C16 H2W2 max whole-BO, both LED polarities");
        $finish;
    end

    initial begin
        #40_000_000;
        $fatal(1, "YPCB PPU image timeout");
    end
endmodule
