`timescale 1ns/1ps
module tb_host_axi_netlist;
    tb_host_axi testbench();
    initial begin
        force testbench.clk=1'b0;
        // Drive external reset after time zero while the clock is held. The
        // mapped feedback cone can otherwise retain X from static-input model
        // startup. Preserve default Xilinx GSR and the bench's normal reset.
        // No DUT state or primitive model is forced or modified.
        #1;
        testbench.s_axil_araddr='x;
        testbench.rst_n='x;
        #1;
        testbench.rst_n=0;
        #198;
        release testbench.clk;
    end
endmodule
