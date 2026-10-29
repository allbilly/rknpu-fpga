`timescale 1ns/1ps
module tb_shared_bram_regport;
    logic clk,rst_n=0;
    initial clk=0;
    always #5 clk=~clk;
    logic req_valid=0,req_write=0,rsp_ready=0;
    logic [31:0] req_addr=0;
    logic [15:0] req_wdata=0;
    wire req_ready,rsp_valid,rsp_error;
    wire [15:0] rsp_rdata;
    logic host_valid=0,host_write=0,host_rsp_ready=0;
    logic [31:0] host_addr=0;
    logic [15:0] host_wdata=0;
    wire host_ready,host_rsp_valid,host_error,engine_pending,host_pending;
    wire [15:0] host_rdata;
    integer transactions=0;
    rk_shared_bram_regport #(.BYTES(64)) dut(.*);
    task automatic tick;@(posedge clk);#1;endtask
    task automatic reset_all;
        @(negedge clk);rst_n=0;req_valid=0;host_valid=0;rsp_ready=0;host_rsp_ready=0;
        repeat(3)begin tick();if(rsp_valid||host_rsp_valid||req_ready||host_ready) $fatal(1,"reset dominance");end
        @(negedge clk);rst_n=1;tick();
    endtask
    task automatic transfer(input bit host,input bit write_request,input logic [31:0] address,
        input logic [15:0] data,input bit bad,input logic [15:0] expected);
        @(negedge clk);
        if(host)begin host_valid=1;host_write=write_request;host_addr=address;host_wdata=data;end
        else begin req_valid=1;req_write=write_request;req_addr=address;req_wdata=data;end
        if(host ? !host_ready : !req_ready)$fatal(1,"not idle before request");
        tick();
        if(host ? host_rsp_valid : rsp_valid)$fatal(1,"response did not wait for registered RAM execution");
        @(negedge clk);host_valid=0;req_valid=0;
        tick();
        if(host ? !host_rsp_valid : !rsp_valid)$fatal(1,"missing registered response");
        if((host ? host_error : rsp_error)!==bad)$fatal(1,"wrong range response");
        if(!bad&&!write_request&&(host ? host_rdata : rsp_rdata)!==expected)$fatal(1,"wrong RAM data");
        repeat(3)begin
            tick();
            if(host ? (!host_rsp_valid||host_ready) : (!rsp_valid||req_ready))$fatal(1,"response ownership lost under stall");
            if(!bad&&!write_request&&(host ? host_rdata : rsp_rdata)!==expected)$fatal(1,"response changed under stall");
        end
        @(negedge clk);if(host)host_rsp_ready=1;else rsp_ready=1;
        tick();@(negedge clk);host_rsp_ready=0;rsp_ready=0;
        if(host ? host_pending : engine_pending)$fatal(1,"ownership not retired");
        transactions=transactions+1;
    endtask
    initial begin
        reset_all();
        for(integer i=0;i<32;i=i+1)transfer(1,1,32'h10000000+32'(2*i),16'(32'h5200+i),0,0);
        for(integer i=0;i<32;i=i+1)transfer(0,0,32'h10000000+32'(2*i),0,0,16'(32'h5200+i));
        for(integer i=0;i<32;i=i+1)transfer(0,1,32'h10000000+32'(2*i),16'(32'h6a00+i),0,0);
        for(integer i=0;i<32;i=i+1)transfer(1,0,32'h10000000+32'(2*i),0,0,16'(32'h6a00+i));
        transfer(0,1,32'h10000040,16'hffff,1,0);
        transfer(1,1,32'h10000001,16'hffff,1,0);
        transfer(0,0,32'h90000000,0,1,0);
        transfer(1,0,32'h0ffffffe,0,1,0);
`ifndef VERILATOR
        transfer(0,1,32'hxxxxxxxx,16'hffff,1,0);
`endif
        // A write accepted at A executes at B even if global reset removes
        // its response ownership. No rollback or RAM-content reset is promised.
        @(negedge clk);req_valid=1;req_write=1;req_addr=32'h10000000;req_wdata=16'hcafe;
        tick();@(negedge clk);rst_n=0;req_valid=0;tick();tick();
        if(rsp_valid||engine_pending)$fatal(1,"stale response after reset");
        @(negedge clk);rst_n=1;tick();
        transfer(1,0,32'h10000000,0,0,16'hcafe);
        if(transactions!=
`ifdef VERILATOR
           133
`else
           134
`endif
          )$fatal(1,"missing RAM cases");
        $display("PASS shared_registered_bram transactions=%0d stable_stalls reset_commit",transactions);$finish;
    end
    initial begin #1000000;$fatal(1,"RAM bench timeout");end
endmodule
