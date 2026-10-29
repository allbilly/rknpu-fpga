// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Small model control only, not a numerical raw-board or physical FPGA test.
module tb_observed_board_unisim_models;
    reg clk=0;
    always #10 clk=~clk;
    reg ce=1, data=0, preset=0;
    wire q;
    FDPE #(.INIT(1'b0)) ff(.C(clk),.CE(ce),.D(data),.PRE(preset),.Q(q));
    reg [15:0] address=0;
    reg [31:0] memory_input=0;
    reg [3:0] write_enable=0;
    wire [31:0] memory_output;
    RAMB36E1 #(.RAM_MODE("TDP"),.READ_WIDTH_A(18),.WRITE_WIDTH_A(18),
        .READ_WIDTH_B(0),.WRITE_WIDTH_B(0),.DOA_REG(0),.DOB_REG(0),
        .WRITE_MODE_A("WRITE_FIRST"),.SIM_COLLISION_CHECK("ALL")) memory(
        .CLKARDCLK(clk),.CLKBWRCLK(clk),.ENARDEN(1'b1),.ENBWREN(1'b0),
        .REGCEAREGCE(1'b1),.REGCEB(1'b1),.RSTRAMARSTRAM(1'b0),.RSTRAMB(1'b0),
        .RSTREGARSTREG(1'b0),.RSTREGB(1'b0),.CASCADEINA(1'b0),.CASCADEINB(1'b0),
        .INJECTDBITERR(1'b0),.INJECTSBITERR(1'b0),.ADDRARDADDR(address),.ADDRBWRADDR(16'b0),
        .DIADI(memory_input),.DIBDI(32'b0),.DIPADIP(4'b0),.DIPBDIP(4'b0),
        .WEA(write_enable),.WEBWE(8'b0),.DOADO(memory_output));
    reg negative;
    task automatic write_word(input [15:0] index, value);
        @(negedge clk);address=index;memory_input={16'b0,value};write_enable=4'b0011;
        @(posedge clk);#2;
        if(memory_output[15:0]!==value) $fatal(1,"UNISIM BRAM WRITE_FIRST mismatch");
        @(negedge clk);write_enable=0;
    endtask
    task automatic read_word(input [15:0] index, value);
        @(negedge clk);address=index;write_enable=0;
        @(posedge clk);#2;
        if(memory_output[15:0]!==value) $fatal(1,"UNISIM BRAM read mismatch");
    endtask
    initial begin
        negative=$test$plusargs("NEGATIVE");
        #1;
        if(glbl.GSR!==1'b1 || q!==1'b0) $fatal(1,"UNISIM default GSR/INIT mismatch");
        #100;
        if(glbl.GSR!==1'b0 || q!==1'b0) $fatal(1,"UNISIM default GSR release mismatch");
        @(negedge clk);#1;preset=1;
        #1;if(q!==1'b1) $fatal(1,"UNISIM FDPE asynchronous preset mismatch");
        preset=0;data=0;
        @(posedge clk);#1;if(q!==1'b0) $fatal(1,"UNISIM FDPE data mismatch");
        @(negedge clk);ce=0;data=1;
        @(posedge clk);#1;if(q!==1'b0) $fatal(1,"UNISIM FDPE enable mismatch");
        write_word(16'h0000,16'h3588);
        write_word(16'h0010,16'hb5c3);
        read_word(16'h0000,negative ? 16'h3589 : 16'h3588);
        read_word(16'h0010,16'hb5c3);
        write_word(16'h0020,16'hxxab);
        read_word(16'h0020,16'hxxab);
        read_word(16'h0000,16'h3588);
        $display("PASS OBSERVED_BOARD_UNISIM_MODEL_CONTROL default_gsr=100ns fdpe=init,preset,enable bram=write_first,read,unknown,retain; not full board or physical proof");
        $finish;
    end
    initial begin #2000;$fatal(1,"UNISIM model control timeout");end
endmodule
