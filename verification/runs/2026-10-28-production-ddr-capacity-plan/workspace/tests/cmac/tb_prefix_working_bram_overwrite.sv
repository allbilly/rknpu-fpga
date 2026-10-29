// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unit qualification of the two actual RAMB36E1 configurations, not board startup.
module tb_prefix_working_bram_overwrite;
    reg clk=0;
    always #10 clk=~clk;
    reg host_enable=0,core_enable=0,host_we=0,core_we=0;
    reg [11:0] host_index=0,core_index=0;
    reg [15:0] host_wdata=0,core_wdata=0;
    wire [15:0] h_m,h_z,h_o,c_m,c_z,c_o;
    reg [31:0] rom [0:4095];
    integer i,negative,probes,writes,reads,old_reads,retention;
    reg [15:0] wanted;
    actual_working_bram_mapped mapped(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(h_m),.core_rdata(c_m));
    actual_working_bram_zero zero_encoded(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(h_z),.core_rdata(c_z));
    actual_working_bram_one counterfactual_one(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(h_o),.core_rdata(c_o));
    function automatic [15:0] changed(input integer index);
        changed=rom[index][15:0]^16'ha55a^16'(index);
    endfunction
    task automatic check_known(input string phase,input integer index,
                               input [15:0] a,b,c,expected);
        if(a!==expected||b!==expected||c!==expected)
            $fatal(1,"working BRAM mismatch phase=%s index=%0d got=%04h/%04h/%04h expected=%04h",phase,index,a,b,c,expected);
    endtask
    task automatic check_cold(input integer index,input [15:0] a,b,c);
        if(a!==16'hxxxx||b!==16'h0000||c!==16'hffff)
            $fatal(1,"working BRAM cold-state mismatch index=%0d got=%04h/%04h/%04h",index,a,b,c);
    endtask
    task automatic host_write_word(input integer index,input [15:0] value,input integer cold);
        @(negedge clk);host_enable=1;core_enable=0;host_we=1;core_we=0;
        host_index=12'(index);host_wdata=value;
        @(posedge clk);#2;
        if(cold) check_cold(index,h_m,h_z,h_o);
        else check_known("host_reinit_read_first",index,h_m,h_z,h_o,changed(index));
        writes=writes+1;old_reads=old_reads+1;
    endtask
    task automatic core_write_word(input integer index,input [15:0] value);
        @(negedge clk);host_enable=0;core_enable=1;host_we=0;core_we=1;
        core_index=12'(index);core_wdata=value;
        @(posedge clk);#2;
        check_known("core_write_read_first",index,c_m,c_z,c_o,rom[index][15:0]);
        writes=writes+1;old_reads=old_reads+1;
    endtask
    task automatic core_read_word(input string phase,input integer index,input [15:0] value);
        @(negedge clk);host_enable=0;core_enable=1;host_we=0;core_we=0;core_index=12'(index);
        @(posedge clk);#2;
        check_known(phase,index,c_m,c_z,c_o,value);reads=reads+1;
    endtask
    task automatic host_read_word(input integer index,input [15:0] value);
        @(negedge clk);host_enable=1;core_enable=0;host_we=0;core_we=0;host_index=12'(index);
        @(posedge clk);#2;
        check_known("host_after_core_write",index,h_m,h_z,h_o,value);reads=reads+1;
    endtask
    initial begin
        probes=0;writes=0;reads=0;old_reads=0;retention=0;negative=0;
        if($value$plusargs("NEGATIVE=%d",negative)) begin end
        $readmemh("@ROM_PATH@",rom);
        #1;if(glbl.GSR!==1'b1) $fatal(1,"working BRAM default GSR assertion missing");
        wait(glbl.GSR===1'b0);#1;
        // Observe every consumed startup bit before overwriting it. This is
        // a test-only read, not a legal initialization/data use in the board.
        for(i=0;i<4096;i=i+1) begin
            @(negedge clk);host_enable=1;core_enable=0;host_we=0;core_we=0;host_index=12'(i);
            @(posedge clk);#2;check_cold(i,h_m,h_z,h_o);probes=probes+1;
        end
        for(i=0;i<4096;i=i+1) host_write_word(i,rom[i][15:0],1);
        for(i=0;i<4096;i=i+1) begin
            wanted=rom[i][15:0]^((negative&&i==0)?16'h1:16'h0);
            core_read_word("core_after_host_init",i,wanted);
        end
        for(i=0;i<4096;i=i+1) core_write_word(i,changed(i));
        for(i=0;i<4096;i=i+1) host_read_word(i,changed(i));
        // Both ports read concurrently at different addresses; no undefined
        // same-address cross-port write/read collision is manufactured.
        for(i=0;i<4096;i=i+1) begin
            @(negedge clk);host_enable=1;core_enable=1;host_we=0;core_we=0;
            host_index=12'(i);core_index=12'(4095-i);
            @(posedge clk);#2;
            check_known("parallel_host_read",i,h_m,h_z,h_o,changed(i));
            check_known("parallel_core_read",4095-i,c_m,c_z,c_o,changed(4095-i));reads=reads+2;
        end
        // Actual memory reset and output-register-enable pins remain tied
        // low. Disabled ports must retain their last observed data.
        @(negedge clk);host_enable=0;core_enable=0;host_we=0;core_we=0;
        repeat(17) begin
            @(posedge clk);#2;
            check_known("disabled_host_retention",4095,h_m,h_z,h_o,changed(4095));
            check_known("disabled_core_retention",0,c_m,c_z,c_o,changed(0));retention=retention+2;
        end
        for(i=0;i<4096;i=i+1) host_write_word(i,rom[i][15:0],0);
        for(i=0;i<4096;i=i+1) core_read_word("core_after_reinit",i,rom[i][15:0]);
        if(probes!=4096||writes!=12288||reads!=20480||old_reads!=12288||retention!=34)
            $fatal(1,"incomplete working BRAM overwrite corpus");
        $display("PASS actual working BRAM overwrite configurations=2 variants=3 default_gsr=100ns cold_words=%0d writes=%0d reads=%0d read_first=%0d retention=%0d; not board startup or physical acceptance",probes,writes,reads,old_reads,retention);
        $finish;
    end
    initial begin #1000000;$fatal(1,"working BRAM overwrite simulation timeout");end
endmodule
