// SPDX-License-Identifier: MIT
`timescale 1ps/1ps
// Source-level FI_XOR leaf contract only. No MIG controller, memory, ECC
// encoder/decoder, PHY, retirement, or hardware is instantiated here.
module tb_mig_fi_xor;
    logic clk = 1'b0;
    always #5 clk = ~clk;
    logic [575:0] wrdata_in;
    wire [575:0] wrdata_out;
    logic wrdata_en;
    logic [8:0] fi_xor_we;
    logic [71:0] fi_xor_wrdata;
    // Deliberately not connected to the DUT: the leaf has no reset port.
    logic mock_reset;
    logic [71:0] model_mask;
    integer scenarios;

    mig_7series_v4_2_fi_xor #(.DQ_WIDTH(72), .DQS_WIDTH(9), .nCK_PER_CLK(4)) dut (
        .clk(clk), .wrdata_in(wrdata_in), .wrdata_out(wrdata_out),
        .wrdata_en(wrdata_en), .fi_xor_we(fi_xor_we), .fi_xor_wrdata(fi_xor_wrdata)
    );

    function automatic logic [575:0] seeded_vector(input logic [31:0] seed);
        logic [31:0] state;
        logic [575:0] value;
        begin
            state = seed;
            for (integer word_index = 0; word_index < 18; word_index = word_index + 1) begin
                state = state ^ (state << 13);
                state = state ^ (state >> 17);
                state = state ^ (state << 5);
                value[word_index*32 +: 32] = state;
            end
            seeded_vector = value;
        end
    endfunction

    function automatic logic [71:0] lane_payload;
        logic [71:0] value;
        begin
            for (integer lane_index = 0; lane_index < 9; lane_index = lane_index + 1)
                value[lane_index*8 +: 8] = 8'(8'h31 + 8'(lane_index*8'h17));
            lane_payload = value;
        end
    endfunction

    task automatic tick;
        begin @(posedge clk); #1; end
    endtask

    task automatic check_vector(input logic [575:0] value, input logic [31:0] tag);
        logic [575:0] expected;
        begin
            wrdata_in = value;
            expected = value;
            expected[71:0] = value[71:0] ^ model_mask;
            #1;
            if (wrdata_out !== expected)
                $fatal(1, "FI_XOR mismatch tag=%h mask=%h low=%h high_match=%b",
                       tag, model_mask, wrdata_out[71:0],
                       wrdata_out[575:72] === value[575:72]);
            if (wrdata_out[575:72] !== value[575:72])
                $fatal(1, "FI_XOR modified upper seven 72-bit words tag=%h", tag);
            scenarios = scenarios + 1;
        end
    endtask

    task automatic arm_bytes(input logic [8:0] lanes, input logic [71:0] payload);
        begin
            @(negedge clk);
            wrdata_en = 1'b0;
            fi_xor_we = lanes;
            fi_xor_wrdata = payload;
            tick();
            for (integer lane_index = 0; lane_index < 9; lane_index = lane_index + 1)
                if (lanes[lane_index])
                    model_mask[lane_index*8 +: 8] = payload[lane_index*8 +: 8];
            @(negedge clk);
            fi_xor_we = '0;
            fi_xor_wrdata = '0;
            wrdata_in = seeded_vector(32'h00003588 ^ {23'b0,lanes});
            check_vector(wrdata_in, {23'b0,lanes});
        end
    endtask

    task automatic clear_with_write(input logic [8:0] concurrent_arm);
        begin
            @(negedge clk);
            wrdata_en = 1'b1;
            fi_xor_we = concurrent_arm;
            fi_xor_wrdata = lane_payload();
            tick();
            model_mask = '0;
            @(negedge clk);
            wrdata_en = 1'b0;
            fi_xor_we = '0;
            fi_xor_wrdata = '0;
            check_vector('0, 32'hc1ea0001);
            check_vector('1, 32'hc1ea0002);
            check_vector(seeded_vector(32'h00003588), 32'h00003588);
        end
    endtask

    initial begin
        wrdata_in = '0;
        wrdata_en = 1'b0;
        fi_xor_we = '0;
        fi_xor_wrdata = '0;
        mock_reset = 1'b0;
        model_mask = '0;
        scenarios = 0;
        tick();
        check_vector('0, 32'h00000000);
        check_vector('1, 32'hffffffff);
        check_vector(seeded_vector(32'h00003588), 32'h00003588);

        // Arm each byte lane independently and prove it persists without a write.
        for (integer lane_index = 0; lane_index < 9; lane_index = lane_index + 1)
            arm_bytes(9'(1 << lane_index), lane_payload());
        repeat (5) begin
            tick();
            check_vector(seeded_vector(32'h00003588 ^ scenarios), scenarios);
        end

        // An unrelated mock reset is not a DUT input and cannot clear an armed mask.
        @(negedge clk); mock_reset = 1'b1; tick();
        if (mock_reset !== 1'b1) $fatal(1, "Mock reset stimulus did not assert");
        check_vector(seeded_vector(32'h0000cafe), 32'h0000cafe);
        @(negedge clk); mock_reset = 1'b0; tick();
        if (mock_reset !== 1'b0) $fatal(1, "Mock reset stimulus did not deassert");
        check_vector(seeded_vector(32'h0000beef), 32'h0000beef);

        // Merge low32, high32, then ECC8 arms exactly as nine byte enables.
        arm_bytes(9'b000001111, lane_payload());
        arm_bytes(9'b011110000, lane_payload());
        arm_bytes(9'b100000000, lane_payload());
        check_vector('1, 32'hc1ea0010);
        repeat (3) begin tick(); check_vector(seeded_vector(32'h3588 + scenarios), scenarios); end

        // An explicit all-byte zero-arm disarms every stored XOR mask.
        arm_bytes(9'b111111111, '0);
        if (model_mask !== '0) $fatal(1, "Model did not clear all byte masks");
        check_vector(seeded_vector(32'h0000f00d), 32'h0000f00d);

        // Arm all lanes, then a write clears in one cycle; following writes stay clean.
        arm_bytes(9'b111111111, lane_payload());
        clear_with_write('0);
        @(negedge clk); wrdata_en = 1'b1; fi_xor_we = 9'b111111111; fi_xor_wrdata = '1; tick();
        model_mask = '0;
        @(negedge clk); wrdata_en = 1'b0; fi_xor_we = '0; fi_xor_wrdata = '0;
        check_vector(seeded_vector(32'h12345678), 32'h12345678);

        // Simultaneous write-enable and arm obeys the source's clear-first priority.
        @(negedge clk); wrdata_en = 1'b1; fi_xor_we = 9'b111111111; fi_xor_wrdata = lane_payload(); tick();
        model_mask = '0;
        @(negedge clk); wrdata_en = 1'b0; fi_xor_we = '0; fi_xor_wrdata = '0;
        check_vector(seeded_vector(32'h87654321), 32'h87654321);
        repeat (4) begin tick(); check_vector(seeded_vector(32'h00003588 ^ scenarios), scenarios); end

        if (scenarios < 30) $fatal(1, "Insufficient FI_XOR assertions: %0d", scenarios);
        $display("PASS fi_xor_leaf seed=00003588 scenarios=%0d byte_lanes=9 low72_only=1 write_clear=1", scenarios);
        $finish;
    end
endmodule
