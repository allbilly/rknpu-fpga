// SPDX-License-Identifier: MIT
`timescale 1ps/1ps
// Actual archived/derived arbiter checks, without force or internal overrides.
module tb_round_robin_width #(parameter bit INCLUDE_WIDTH_ONE=1);
  wire d1,d2,d3,d4;
  if(INCLUDE_WIDTH_ONE)begin: one
    check_round_robin #(.WIDTH(1)) w1(.done(d1));
  end else begin: no_one
    assign d1=1'b1;
  end
  check_round_robin #(.WIDTH(2)) w2(.done(d2));
  check_round_robin #(.WIDTH(3)) w3(.done(d3));
  check_round_robin #(.WIDTH(4)) w4(.done(d4));
  initial begin
    wait(d1&&d2&&d3&&d4);
    $display("PASS round_robin_width widths=%0d cases_per_width=128 scope=actual_arbiter_only",INCLUDE_WIDTH_ONE?4:3);
    $finish;
  end
  initial begin #2000000;$fatal(1,"Arbiter control watchdog");end
endmodule
