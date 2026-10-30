`timescale 1ns/1ps
module tb_pcie_source_health_invalid #(parameter integer INVALID_CASE=1);
    reg clk;
    wire healthy,alive;
    initial begin clk=0;forever #5 clk=~clk;end
    generate
      if(INVALID_CASE==1) begin : bad_stages
        rk_pcie_source_health #(.SYNC_STAGES(2)) dut(clk,clk,1'b0,1'b0,1'b0,1'b0,healthy,alive);
      end else if(INVALID_CASE==2) begin : bad_divider
        rk_pcie_source_health #(.HEARTBEAT_BITS(1)) dut(clk,clk,1'b0,1'b0,1'b0,1'b0,healthy,alive);
      end else if(INVALID_CASE==3) begin : bad_transitions
        rk_pcie_source_health #(.REQUIRED_TRANSITIONS(1)) dut(clk,clk,1'b0,1'b0,1'b0,1'b0,healthy,alive);
      end else if(INVALID_CASE==4) begin : bad_timeout
        rk_pcie_source_health #(.TIMEOUT_UI_CYCLES(7)) dut(clk,clk,1'b0,1'b0,1'b0,1'b0,healthy,alive);
      end else if(INVALID_CASE==5) begin : bad_guard
        wire ready,failed,seen;
        assign healthy=1'b0;
        assign alive=1'b0;
        rk_transport_epoch_guard #(.FRESH_CYCLES(1)) dut(clk,1'b0,1'b0,ready,failed,seen);
        initial begin #2;if(ready===1'bx || failed===1'bx || seen===1'bx) $display("GUARD_INVALID_OUTPUT_UNKNOWN");end
      end
    endgenerate
    initial begin #1;if(healthy===1'bx || alive===1'bx) $display("INVALID_OUTPUT_UNKNOWN");$display("INVALID_TEST_DID_NOT_FAIL case=%0d",INVALID_CASE);$finish;end
endmodule
