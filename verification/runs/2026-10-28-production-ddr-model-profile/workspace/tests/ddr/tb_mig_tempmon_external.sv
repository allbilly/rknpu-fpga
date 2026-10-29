`timescale 1ps/1ps
module tb_mig_tempmon_external;
  logic clk;
  logic xadc_clk;
  logic rst;
  logic [11:0] device_temp_i;
  wire [11:0] device_temp;

  logic [31:0] seed;
  logic [11:0] transient_value [0:5];
  logic seen_bits [0:11];
  logic [11:0] stable_a;
  logic [11:0] stable_b;
  logic [11:0] stable_c;
  integer idx;
  integer gap;
  integer i;
  integer j;

  mig_7series_v4_2_tempmon #(
    .TCQ(100),
    .TEMP_MON_CONTROL("EXTERNAL")
  ) dut (
    .clk(clk),
    .xadc_clk(xadc_clk),
    .rst(rst),
    .device_temp_i(device_temp_i),
    .device_temp(device_temp)
  );

  initial begin
    forever #3750 clk = ~clk;
  end

  task automatic advance_cycles(input integer count);
    integer k;
    begin
      for (k=0;k<count;k=k+1) begin
        @(posedge clk);
        #200;
      end
    end
  endtask

  task automatic expect_sample(input logic [11:0] expected, input integer phase);
    begin
      if (device_temp !== expected)
        $fatal(1,"TEMP_MON phase=%0d expected=%03x observed=%03x",phase,expected,device_temp);
    end
  endtask

  initial begin
    clk = 1'b0;
    xadc_clk = 1'b0; // EXTERNAL branch has no XADC dependency.
    rst = 1'b1;
    device_temp_i = 12'h000;
    seed = 32'h74c3a29d;
    stable_a = 12'h155;
    stable_b = 12'h6a5;
    stable_c = 12'habc;
    transient_value[0] = 12'h7ff;
    transient_value[1] = 12'h800;
    transient_value[2] = 12'h123;
    transient_value[3] = 12'hffe;
    transient_value[4] = 12'h480;
    transient_value[5] = 12'h001;
    for (i=0;i<12;i=i+1) seen_bits[i] = 1'b0;

    // Establish a valid initial output only through the observable filter.
    advance_cycles(4);
    @(negedge clk);
    rst = 1'b0;
    device_temp_i = stable_a;
    advance_cycles(40);
    expect_sample(stable_a,1);

    // Multi-bit transitions are each held only 1 or 2 source cycles. None may
    // reach the output, including the 0x7ff -> 0x800 carry boundary.
    for (i=0;i<6;i=i+1) begin
      seed = seed * 32'd1664525 + 32'd1013904223;
      gap = seed[0] ? 1 : 2;
      @(negedge clk);
      device_temp_i = transient_value[i];
      advance_cycles(gap);
      expect_sample(stable_a,2+i);
    end
    @(negedge clk);
    device_temp_i = stable_b;
    advance_cycles(15);
    expect_sample(stable_a,8);
    advance_cycles(25);
    expect_sample(stable_b,9);

    // Stagger distinct input bits near rising edges using a fixed LCG seed.
    // Every interim vector is observable only at the input; the output must
    // retain the previous stable sample while no vector reaches 15 cycles.
    for (i=0;i<12;i=i+1) begin
      seed = seed * 32'd1664525 + 32'd1013904223;
      idx = seed % 12;
      while (seen_bits[idx]) idx = (idx+1) % 12;
      seen_bits[idx] = 1'b1;
      seed = seed * 32'd1664525 + 32'd1013904223;
      gap = seed[2] ? 1 : 2;
      @(posedge clk);
      #25;
      device_temp_i[idx] = ~device_temp_i[idx];
      advance_cycles(gap);
      expect_sample(stable_b,10+i);
    end
    @(negedge clk);
    device_temp_i = stable_c;
    advance_cycles(15);
    expect_sample(stable_b,22);
    advance_cycles(25);
    expect_sample(stable_c,23);

    // The output register is not reset to zero. While reset is asserted, the
    // sampled input changes; after release, only a new stable value may publish.
    @(posedge clk);
    #25;
    rst = 1'b1;
    for (j=0;j<8;j=j+1) begin
      seed = seed * 32'd1664525 + 32'd1013904223;
      @(posedge clk);
      #25;
      device_temp_i = seed[11:0];
      #200;
      expect_sample(stable_c,24+j);
    end
    @(negedge clk);
    rst = 1'b0;
    device_temp_i = 12'h39a;
    advance_cycles(15);
    expect_sample(stable_c,32);
    advance_cycles(25);
    expect_sample(12'h39a,33);

    $display("PASS_TEMP_MON_EXTERNAL_FILTER seed=%08x stable15_hold=1 reset_retains_output=1",seed);
    $finish;
  end
endmodule
