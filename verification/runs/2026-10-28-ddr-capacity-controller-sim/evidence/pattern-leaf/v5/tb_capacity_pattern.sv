`timescale 1ns/1ps
module tb_capacity_pattern;
    logic [30:0] address;
    logic [31:0] seed;
    logic trial;
    logic valid;
    logic [511:0] data;
    string vector_path;
    integer fd, scanned, count;
    integer trial_i, valid_i;
    logic [511:0] expected_data;
    logic [30:0] expected_address;
    logic [31:0] expected_seed;
    logic expected_trial;
    logic expected_valid;

    rk_ddr_capacity_pattern dut(.*);

    task automatic fail(input string message);
        $display("FAIL_CAPACITY_PATTERN %s", message);
        $fatal(1);
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vector_path))
            fail("missing VECTORS path");
        fd = $fopen(vector_path, "r");
        if (fd == 0) fail("cannot open vectors");
        count = 0;
        while (!$feof(fd)) begin
            scanned = $fscanf(fd, "%h %h %d %d %h\n",
                expected_address, expected_seed, trial_i, valid_i, expected_data);
            if (scanned == -1) begin
                // EOF after the last complete row.
            end else if (scanned != 5) begin
                fail("malformed/truncated vector row");
            end else begin
                address = expected_address;
                seed = expected_seed;
                if ((trial_i != 0 && trial_i != 1) || (valid_i != 0 && valid_i != 1))
                    fail("vector trial/valid field is not exactly 0 or 1");
                expected_trial = (trial_i == 1);
                trial = expected_trial;
                expected_valid = (valid_i == 1);
                #1;
                if (valid !== expected_valid)
                    fail($sformatf("valid mismatch row=%0d address=%08x trial=%0d got=%b expected=%b",
                                   count, address, trial, valid, expected_valid));
                if (data !== expected_data)
                    fail($sformatf("data mismatch row=%0d address=%08x seed=%08x trial=%0d got=%h expected=%h",
                                   count, address, seed, trial, data, expected_data));
                count = count + 1;
            end
        end
        $fclose(fd);
        if (count != 4162) fail($sformatf("wrong vector count=%0d", count));

        // Known unaligned addresses are rejected while preserving the data function.
        address = 31'h00000001; seed = 32'h3588c350; trial = 1'b0; #1;
        if (valid !== 1'b0) fail("unaligned address 1 was valid");
        address = 31'h7fffffff; seed = 32'hffffffff; trial = 1'b1; #1;
        if (valid !== 1'b0) fail("unaligned max address was valid");

`ifndef VERILATOR
        address = {25'h0, 6'bx00000}; seed = 32'h0; trial = 1'b0; #1;
        if (valid !== 1'b0) fail("X address was not rejected");
        address = 31'h0; seed = 32'hxxxxxxxx; trial = 1'b0; #1;
        if (valid !== 1'b0) fail("X seed was not rejected");
        address = 31'h0; seed = 32'h0; trial = 1'bx; #1;
        if (valid !== 1'b0) fail("X trial was not rejected");
        address = 31'h0; seed = 32'h0; trial = 1'bz; #1;
        if (valid !== 1'b0) fail("Z trial was not rejected");
`endif
        $display("PASS_CAPACITY_PATTERN rows=%0d aligned_unaligned_and_four_state_checks=PASS", count);
        $finish;
    end
endmodule
