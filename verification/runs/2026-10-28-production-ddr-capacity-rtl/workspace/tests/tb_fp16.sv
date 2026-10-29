`timescale 1ns/1ps
module tb_fp16;
    logic clk;
    initial clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, in_valid = 0, in_ready, out_valid, out_ready;
    logic [1:0] in_op = 0;
    logic [15:0] in_a = 0, in_b = 0, out_data;
    logic [63:0] vectors [0:65535];
    logic [31:0] lfsr;
    integer count, received, cycles;
    logic stalled;
    logic [15:0] held_data;
    string vector_file;
    initial begin
        out_ready = 0; lfsr = 32'h12345678;
        received = 0; cycles = 0; stalled = 0;
    end
    rk_fp16_alu dut (.*);
    always @(negedge clk) begin
        lfsr <= {lfsr[30:0], lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
        out_ready <= rst_n && (lfsr[0] || lfsr[5]);
    end
    always @(posedge clk) begin
        if (rst_n) begin
            cycles <= cycles + 1;
            if (cycles > 1000000) $fatal(1,"ALU timeout");
            if (stalled && (!out_valid || out_data !== held_data)) $fatal(1,"ALU output changed under backpressure");
            stalled <= out_valid && !out_ready;
            held_data <= out_data;
            if (out_valid && out_ready) begin
                if (received >= count || out_data !== vectors[received][15:0])
                    $fatal(1,"ALU vector %0d: got %04h expected %04h",received,out_data,vectors[received][15:0]);
                received <= received + 1;
            end
        end
    end
    initial begin
        if (!$value$plusargs("VECTORS=%s",vector_file)) $fatal(1,"missing +VECTORS");
        if (!$value$plusargs("COUNT=%d",count)) $fatal(1,"missing +COUNT");
        if (count < 1 || count > 65536) $fatal(1,"bad COUNT");
        $readmemh(vector_file,vectors,0,count-1);
        repeat(4) @(negedge clk);
        rst_n = 1;
        for (integer i=0; i<count; i=i+1) begin
            @(negedge clk);
            in_valid=1; in_op=vectors[i][49:48]; in_a=vectors[i][47:32]; in_b=vectors[i][31:16];
            do @(posedge clk); while (!in_ready);
        end
        @(negedge clk);
        in_valid=0;
        wait(received==count);
        @(negedge clk);
        $display("PASS ALU: %0d vectors, %0d cycles",received,cycles);
        $finish;
    end
endmodule
