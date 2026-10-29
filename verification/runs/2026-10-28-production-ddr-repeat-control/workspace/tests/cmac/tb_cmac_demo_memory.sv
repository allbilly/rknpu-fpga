// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_demo_memory;
    /* verilator lint_off BLKSEQ */
    logic clk,rst_n=0;
    initial clk=0;
    always #5 clk=~clk;
    logic req_valid=0,req_ready,req_write=0,rsp_valid,rsp_ready=0,rsp_error;
    logic [31:0] req_addr=0;
    logic [15:0] req_wdata=0,rsp_rdata;
    logic host_valid=0,host_ready,host_write=0,host_rsp_valid,host_rsp_ready=0;
    logic [11:0] host_index=0;
    logic [15:0] host_wdata=0,host_rdata;
    rk_cmac_demo_memory dut(.*);
    integer transactions=0,errors=0;
    function automatic logic [31:0] device_address(input integer i);
        if (i<224) return 32'h10010000+32'(2*i);
        if (i<3328) return 32'h10020000+32'(2*(i-224));
        if (i<3488) return 32'h10040000+32'(2*(i-3328));
        return 32'h100e0000+32'(2*(i-3488));
    endfunction
    task automatic host_access(input bit wr,input integer i,input logic [15:0] value);
        @(negedge clk);host_valid=1;host_write=wr;host_index=12'(i);host_wdata=value;
        do @(posedge clk);while(!host_ready);
        @(negedge clk);host_valid=0;
        wait(host_rsp_valid);
        repeat(2) begin
            @(negedge clk);
            if (!host_rsp_valid||host_ready||(!wr&&host_rdata!==value)) $fatal(1,"host held response index=%0d",i);
        end
        host_rsp_ready=1;@(negedge clk);host_rsp_ready=0;
    endtask
    task automatic core_access(input bit wr,input logic [31:0] address,input logic [15:0] value,input bit err);
        @(negedge clk);req_valid=1;req_write=wr;req_addr=address;req_wdata=value;
        do @(posedge clk);while(!req_ready);
        @(negedge clk);req_valid=0;
        wait(rsp_valid);
        repeat(3) begin
            @(negedge clk);
            if (!rsp_valid||req_ready||rsp_error!==err||(!wr&&!err&&rsp_rdata!==value))
                $fatal(1,"core held response address=%h read=%h expected=%h error=%b expected_error=%b",address,rsp_rdata,value,rsp_error,err);
        end
        rsp_ready=1;@(negedge clk);rsp_ready=0;
        transactions=transactions+1;if(err) errors=errors+1;
    endtask
    initial begin
        repeat(3) @(negedge clk);rst_n=1;
        for(integer i=0;i<4096;i=i+1) host_access(1,i,16'(i)^16'h3c5a);
        // Every mapped halfword, including guards, must map uniquely.
        for(integer i=0;i<3712;i=i+1) core_access(0,device_address(i),16'(i)^16'h3c5a,0);
        for(integer w=0;w<4;w=w+1) begin
            case(w)
                0:begin core_access(1,32'h1000fffe,16'hffff,1);core_access(1,32'h100101c0,16'hffff,1);end
                1:begin core_access(1,32'h1001fffe,16'hffff,1);core_access(1,32'h10021840,16'hffff,1);end
                2:begin core_access(1,32'h1003fffe,16'hffff,1);core_access(1,32'h10040140,16'hffff,1);end
                3:begin core_access(1,32'h100dfffe,16'hffff,1);core_access(1,32'h100e01c0,16'hffff,1);end
            endcase
        end
        for(integer i=0;i<3712;i=i+1) begin
            core_access(1,device_address(i)|32'd1,16'hffff,1);
            core_access(1,device_address(i),16'(i)^16'h5aa5,0);
        end
        // Reset cancels response ownership, not an already accepted RAM write.
        @(negedge clk);req_valid=1;req_write=1;req_addr=32'h10010000;req_wdata=16'h1234;
        do @(posedge clk);while(!req_ready);
        @(negedge clk);req_valid=0;#1;rst_n=0;#1;
        if(rsp_valid||host_rsp_valid||req_ready||host_ready) $fatal(1,"reset left memory ownership active");
        repeat(3) @(negedge clk);rst_n=1;
        host_access(0,0,16'h1234);
        for(integer i=1;i<4096;i=i+1) host_access(0,i,16'(i)^(i<3712?16'h5aa5:16'h3c5a));
        if(transactions!=11144||errors!=3720) $fatal(1,"incomplete memory coverage");
        $display("PASS CMAC demo memory mapped_halfwords=3712 flat_halfwords=4096 transactions=%0d rejected=%0d reset_pending_write=1",transactions,errors);
        $finish;
    end
    initial begin #3000000;$fatal(1,"memory test timeout");end
    /* verilator lint_on BLKSEQ */
endmodule
