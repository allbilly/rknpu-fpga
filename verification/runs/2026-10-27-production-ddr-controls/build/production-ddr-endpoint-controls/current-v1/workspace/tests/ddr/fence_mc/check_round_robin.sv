// SPDX-License-Identifier: MIT
`timescale 1ps/1ps
module check_round_robin #(parameter integer WIDTH=1)(output logic done);
  /* verilator lint_off BLKSEQ */
  logic clk,rst,disable_grant,upd_last_master;
  logic [WIDTH-1:0] req,current_master;
  wire [WIDTH-1:0] grant_ns,grant_r;
  logic [WIDTH-1:0] expected;
  integer step,last_index,current_index,basis,candidate;
  always #3750 clk=~clk;
  mig_7series_v4_2_round_robin_arb #(.TCQ(100),.WIDTH(WIDTH)) dut(.*);
  initial begin
    clk=0;rst=1;disable_grant=0;upd_last_master=0;req=0;
    current_master=WIDTH'(1<<(WIDTH-1));last_index=WIDTH-1;done=0;expected=0;
    for(step=0;step<128;step=step+1)begin
      @(negedge clk);
      rst=(step%31)==0;disable_grant=(step%7)==3;upd_last_master=(step%3)!=0;
      current_index=step%WIDTH;current_master=WIDTH'(1<<current_index);
      req=WIDTH'((step*13)^(step>>2));
      basis=rst?WIDTH-1:upd_last_master?current_index:last_index;
      expected=0;
      for(integer offset=1;offset<=WIDTH;offset=offset+1)begin
        candidate=(basis+offset)%WIDTH;
        if(candidate<0||candidate>=WIDTH)$fatal(1,"Reference priority index outside width");
        if(!disable_grant && expected=='0 && req[candidate])expected[candidate]=1;
      end
      #101;
      // The original WIDTH1 vector is undriven even if initialized inhibit
      // happens to mask it in an event-driven simulation. Observe, never force.
      if(WIDTH==1 && dut.channel[0].inh_group!=='0)
        $fatal(1,"WIDTH1_UNDRIVEN_INHIBIT_GROUP");
      if(grant_ns!==expected)$fatal(1,"Arbiter combinational grant mismatch width=%0d step=%0d",WIDTH,step);
      @(posedge clk);#101;
      if(grant_r!==expected)$fatal(1,"Arbiter registered grant mismatch width=%0d step=%0d",WIDTH,step);
      last_index=basis;
      $display("TRACE ARBITER width=%0d step=%0d req=%0h reset=%0d disable=%0d update=%0d current=%0h grant=%0h registered=%0h",
        WIDTH,step,req,rst,disable_grant,upd_last_master,current_master,grant_ns,grant_r);
    end
    done=1;
  end
  /* verilator lint_on BLKSEQ */
endmodule
