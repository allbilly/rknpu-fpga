`timescale 1ns/1ps
module tb_job_control_netlist;
    tb_job_control testbench();
    initial begin
        force testbench.clk=1'b0;
        // An idle address is unspecified until the host drives ARVALID. Give
        // the event-sensitive UNISIM LUTs a post-time-zero input transition;
        // declaration-initialized static inputs otherwise never evaluate in
        // Icarus. No DUT state/model or expected result is forced or changed.
        #1; testbench.s_axil_araddr='x;
        #199;
        release testbench.clk;
    end
endmodule
