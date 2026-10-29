`timescale 1ns/1ps
module tb_startup_funcsim;
  reg SYS_CLK=0;
  wire [2:0] led;
  ypcb_ew_startup_top dut(.SYS_CLK(SYS_CLK),.led_3bits_tri_o(led));
  always #10 SYS_CLK=~SYS_CLK;
  integer cycle;
  initial begin
    // Standard vendor glbl retains GSR for the first100ns; no forced removal.
    repeat(12) @(negedge SYS_CLK);
    if (led[1:0] !== 2'b00) $fatal(1,"Unexpected result during startup hold");
    for(cycle=0;cycle<50000;cycle=cycle+1) begin
      @(negedge SYS_CLK);
      if(led[1:0] === 2'b01) begin
        $display("PASS actual Vivado routed functional netlist startup SUB9 scoreboard, cycle=%0d",cycle);
        $finish;
      end
      if(led[1:0] !== 2'b00) $fatal(1,"Fail/unknown result in routed functional netlist: %b",led);
    end
    $fatal(1,"Routed functional netlist timeout");
  end
endmodule
