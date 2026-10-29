// Common test master: never drives the DUT's internal descriptor interface.
logic [31:0] s_axil_awaddr=0, s_axil_wdata=0, s_axil_araddr=0, s_axil_rdata;
logic [2:0] s_axil_awprot=0, s_axil_arprot=0;
logic [3:0] s_axil_wstrb=0;
logic s_axil_awvalid=0, s_axil_awready, s_axil_wvalid=0, s_axil_wready;
logic s_axil_bvalid, s_axil_bready=0, s_axil_arvalid=0, s_axil_arready;
logic s_axil_rvalid, s_axil_rready=0;
logic [1:0] s_axil_bresp, s_axil_rresp;

task automatic host_aw(input logic [31:0] addr, input logic [2:0] prot=0);
    @(negedge clk); s_axil_awaddr=addr; s_axil_awprot=prot; s_axil_awvalid=1;
    do @(posedge clk); while (!s_axil_awready);
    @(negedge clk); s_axil_awvalid=0;
endtask
task automatic host_w(input logic [31:0] data, input logic [3:0] strobe=4'hf);
    @(negedge clk); s_axil_wdata=data; s_axil_wstrb=strobe; s_axil_wvalid=1;
    do @(posedge clk); while (!s_axil_wready);
    @(negedge clk); s_axil_wvalid=0;
endtask
task automatic host_b(input logic [1:0] expected=0);
    wait(s_axil_bvalid);
    repeat (4) begin
        @(negedge clk);
        if (!s_axil_bvalid || s_axil_bresp !== expected || s_axil_awready || s_axil_wready)
            $fatal(1,"AXI-Lite B/backpressure mismatch got=%0d expected=%0d",s_axil_bresp,expected);
    end
    s_axil_bready=1;
    @(negedge clk); s_axil_bready=0;
    if (s_axil_bvalid) $fatal(1,"duplicate AXI-Lite B response");
endtask
task automatic host_write(input logic [31:0] addr, input logic [31:0] data,
                          input logic [1:0] expected=0, input integer order=0,
                          input logic [3:0] strobe=4'hf, input logic [2:0] prot=0);
    if (order==1) begin host_aw(addr,prot); repeat(3) @(negedge clk); host_w(data,strobe); end
    else if (order==2) begin host_w(data,strobe); repeat(3) @(negedge clk); host_aw(addr,prot); end
    else begin
        fork
            host_aw(addr,prot);
            host_w(data,strobe);
        join
    end
    host_b(expected);
endtask
task automatic host_read(input logic [31:0] addr, output logic [31:0] data,
                         input logic [1:0] expected=0, input logic [2:0] prot=0);
    @(negedge clk); s_axil_araddr=addr; s_axil_arprot=prot; s_axil_arvalid=1;
    do @(posedge clk); while (!s_axil_arready);
    @(negedge clk); s_axil_arvalid=0;
    wait(s_axil_rvalid); data=s_axil_rdata;
    repeat (4) begin
        @(negedge clk);
        if (!s_axil_rvalid || s_axil_rdata !== data || s_axil_rresp !== expected || s_axil_arready)
            $fatal(1,"AXI-Lite R/backpressure mismatch @%08h got=%0d expected=%0d",addr,s_axil_rresp,expected);
    end
    s_axil_rready=1;
    @(negedge clk); s_axil_rready=0;
    if (s_axil_rvalid) $fatal(1,"duplicate AXI-Lite R response");
endtask
task automatic host_expect(input logic [31:0] addr, input logic [31:0] expected,
                           input logic [1:0] response=0, input logic [2:0] prot=0);
    logic [31:0] data;
    host_read(addr,data,response,prot);
    if (data !== expected) $fatal(1,"AXI-Lite register @%08h got=%08h expected=%08h",addr,data,expected);
endtask
task automatic host_idle;
    s_axil_awvalid=0; s_axil_wvalid=0; s_axil_arvalid=0; s_axil_bready=0; s_axil_rready=0;
endtask
