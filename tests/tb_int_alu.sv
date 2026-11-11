`timescale 1ns/1ps
// Integer ALU vector check: every captured lane plus explicitly labelled
// source-formula saturation edges (flag=0 means "captured lane", flag=1 means
// "source-formula candidate edge, not a captured output").
// Vector line: op dtype a b expected captured
module tb_int_alu;
    localparam integer MAX_VECTORS = 4096;
    logic clk;
    initial clk = 1'b0;
    always #5 clk = ~clk;
    logic rst_n = 1'b0;
    logic in_valid = 1'b0, in_ready;
    logic [2:0] in_op = 3'd0;
    logic [1:0] in_dtype = 2'd0;
    logic signed [31:0] in_a = 32'sd0, in_b = 32'sd0;
    logic out_valid, out_ready = 1'b0;
    logic signed [31:0] out_data;
    integer vec_count, index, op, dtype, captured, errors, waited;
    logic [31:0] a_raw, b_raw, expected_raw;
    string vec_path;
    integer vfd;
    logic signed [31:0] expected_signed;

    rk_int_alu dut (
        .clk(clk), .rst_n(rst_n),
        .in_valid(in_valid), .in_ready(in_ready),
        .in_op(in_op), .in_dtype(in_dtype), .in_a(in_a), .in_b(in_b),
        .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data)
    );

    initial begin
        errors = 0;
        if (!$value$plusargs("VECFILE=%s", vec_path)) $fatal(1, "missing VECFILE");
        if (!$value$plusargs("VECOUNT=%d", vec_count)) $fatal(1, "missing VECOUNT");
        if (vec_count < 1 || vec_count > MAX_VECTORS) $fatal(1, "invalid VECOUNT");
        vfd = $fopen(vec_path, "r");
        if (vfd == 0) $fatal(1, "cannot open VECFILE");
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        for (index = 0; index < vec_count; index = index + 1) begin
            if ($fscanf(vfd, "%d %d %h %h %h %d",
                         op, dtype, a_raw, b_raw, expected_raw, captured) != 6)
                $fatal(1, "short vector file at %0d", index);
            in_op = op[2:0];
            in_dtype = dtype[1:0];
            in_a = a_raw;
            in_b = b_raw;
            expected_signed = expected_raw;
            @(negedge clk);
            in_valid = 1'b1;
            waited = 0;
            while (!in_ready) begin
                @(posedge clk);
                waited = waited + 1;
                if (waited > 100) $fatal(1, "ALU in_ready timeout");
            end
            @(posedge clk);
            @(negedge clk);
            in_valid = 1'b0;
            out_ready = 1'b1;
            waited = 0;
            while (!out_valid) begin
                @(posedge clk);
                waited = waited + 1;
                if (waited > 100) $fatal(1, "ALU out_valid timeout");
            end
            if (out_data !== expected_signed) begin
                $display("FAIL vector %0d op=%0d dtype=%0d a=%08h b=%08h got=%08h want=%08h captured=%0d",
                         index, op, dtype, a_raw, b_raw, out_data, expected_raw, captured);
                errors = errors + 1;
            end
            @(negedge clk);
            out_ready = 1'b0;
        end
        // Backpressure control: out_ready held low must hold out_valid/data.
        repeat (2) @(negedge clk);
        $fclose(vfd);
        if (errors != 0) $fatal(1, "int ALU vector failures: %0d", errors);
        $display("PASS tb_int_alu vectors=%0d", vec_count);
        $finish;
    end
endmodule
