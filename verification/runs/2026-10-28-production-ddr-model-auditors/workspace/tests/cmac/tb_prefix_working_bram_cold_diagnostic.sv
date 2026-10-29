// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Read-only observation of unchanged models/wrappers. Not an acceptance bench.
module tb_prefix_working_bram_cold_diagnostic;
    reg clk=0;
    always #10 clk=~clk;
    reg host_enable=0,core_enable=0,host_we=0,core_we=0;
    reg [11:0] host_index=0,core_index=0;
    reg [15:0] host_wdata=0,core_wdata=0;
    wire [15:0] h_m,h_z,h_o,c_m,c_z,c_o;
    actual_working_bram_mapped mapped(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(h_m),.core_rdata(c_m));
    actual_working_bram_zero zero_encoded(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(h_z),.core_rdata(c_z));
    actual_working_bram_one counterfactual_one(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(h_o),.core_rdata(c_o));
    task automatic observe(input string phase);
        $display("TRACE phase=%s t=%0t GSR=%b host=%04h/%04h/%04h core=%04h/%04h/%04h",phase,$time,glbl.GSR,h_m,h_z,h_o,c_m,c_z,c_o);
        $display("INTERNAL cell=0 phase=%s INIT_A=%09b INIT_00=%08b mem0=%08b mem1=%08b mem4095=%08b parity0=%b buf=%08b out=%08b mux=%08b DOA=%08b parity_out=%b parity_mux=%b DOPA=%b wire=%08b port=%08b",phase,
            mapped.actual_0.INIT_A[8:0],mapped.actual_0.INIT_00[7:0],
            mapped.actual_0.gen_tdp.INT_RAMB_TDP.mem[0],mapped.actual_0.gen_tdp.INT_RAMB_TDP.mem[1],mapped.actual_0.gen_tdp.INT_RAMB_TDP.mem[4095],mapped.actual_0.gen_tdp.INT_RAMB_TDP.memp[0],
            mapped.actual_0.gen_tdp.INT_RAMB_TDP.doa_buf[7:0],mapped.actual_0.gen_tdp.INT_RAMB_TDP.doa_out[7:0],mapped.actual_0.gen_tdp.INT_RAMB_TDP.doa_out_mux[7:0],mapped.actual_0.gen_tdp.INT_RAMB_TDP.DOA[7:0],
            mapped.actual_0.gen_tdp.INT_RAMB_TDP.dopa_out[0],mapped.actual_0.gen_tdp.INT_RAMB_TDP.dopa_out_mux[0],mapped.actual_0.gen_tdp.INT_RAMB_TDP.DOPA[0],mapped.actual_0.doado_wire[7:0],mapped.actual_0.DOADO[7:0]);
        $display("INTERNAL cell=1 phase=%s INIT_A=%09b INIT_00=%08b mem0=%08b mem1=%08b mem4095=%08b parity0=%b buf=%08b out=%08b mux=%08b DOA=%08b parity_out=%b parity_mux=%b DOPA=%b wire=%08b port=%08b",phase,
            mapped.actual_1.INIT_A[8:0],mapped.actual_1.INIT_00[7:0],
            mapped.actual_1.gen_tdp.INT_RAMB_TDP.mem[0],mapped.actual_1.gen_tdp.INT_RAMB_TDP.mem[1],mapped.actual_1.gen_tdp.INT_RAMB_TDP.mem[4095],mapped.actual_1.gen_tdp.INT_RAMB_TDP.memp[0],
            mapped.actual_1.gen_tdp.INT_RAMB_TDP.doa_buf[7:0],mapped.actual_1.gen_tdp.INT_RAMB_TDP.doa_out[7:0],mapped.actual_1.gen_tdp.INT_RAMB_TDP.doa_out_mux[7:0],mapped.actual_1.gen_tdp.INT_RAMB_TDP.DOA[7:0],
            mapped.actual_1.gen_tdp.INT_RAMB_TDP.dopa_out[0],mapped.actual_1.gen_tdp.INT_RAMB_TDP.dopa_out_mux[0],mapped.actual_1.gen_tdp.INT_RAMB_TDP.DOPA[0],mapped.actual_1.doado_wire[7:0],mapped.actual_1.DOADO[7:0]);
    endtask
    initial begin
        #1;
        if(glbl.GSR!==1'b1) $fatal(1,"diagnostic default GSR assertion missing");
        observe("gsr_asserted");
        wait(glbl.GSR===1'b0);#1;observe("gsr_released");
        @(posedge clk);#2;observe("disabled_after_gsr");
        @(negedge clk);host_enable=1;host_index=0;
        @(posedge clk);#2;observe("cold_read_0");
        @(negedge clk);host_index=1;
        @(posedge clk);#2;observe("cold_read_1");
        @(negedge clk);host_index=4095;
        @(posedge clk);#2;observe("cold_read_4095");
        @(negedge clk);host_index=0;host_we=1;host_wdata=16'h3bb5;
        @(posedge clk);#2;observe("host_write_0_read_first");
        @(negedge clk);host_enable=0;host_we=0;core_enable=1;core_index=0;
        @(posedge clk);#2;observe("core_read_written_0");
        @(negedge clk);core_we=1;core_wdata=16'h9eef;
        @(posedge clk);#2;observe("core_write_0_read_first");
        @(negedge clk);core_enable=0;core_we=0;host_enable=1;
        @(posedge clk);#2;observe("host_read_core_written_0");
        $display("OBSERVATION_ONLY unchanged actual working BRAM cold trace; no overwrite, startup or hardware acceptance");
        $finish;
    end
    initial begin #1000;$fatal(1,"diagnostic simulation timeout");end
endmodule
