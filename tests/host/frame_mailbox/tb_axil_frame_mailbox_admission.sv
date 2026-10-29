`timescale 1ns/1ps
module tb_axil_frame_mailbox_admission;
    logic clk,rst_n;
    initial begin clk=0; forever #5 clk=~clk; end
    logic admission_enable;
    logic [31:0] awaddr=0,wdata=0,araddr=0;
    logic [2:0] awprot=0,arprot=0;
    logic awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
    logic [3:0] wstrb=4'hf;
    wire awready,wready,bvalid,arready,rvalid,req_valid,irq,protocol_fault;
    wire [1:0] bresp,rresp;
    wire [31:0] rdata;
    wire [603:0] req;
    logic req_ready=0,rsp_valid=0;
    logic [511:0] rsp_data=0;
    logic [7:0] rsp_status=0;
    logic [15:0] rsp_seq=0;
    integer checks=0;

    rk_axil_frame_mailbox dut(
        .clk,.rst_n,.admission_enable,.s_axil_awaddr(awaddr),.s_axil_awprot(awprot),
        .s_axil_awvalid(awvalid),.s_axil_awready(awready),.s_axil_wdata(wdata),
        .s_axil_wstrb(wstrb),.s_axil_wvalid(wvalid),.s_axil_wready(wready),
        .s_axil_bresp(bresp),.s_axil_bvalid(bvalid),.s_axil_bready(bready),
        .s_axil_araddr(araddr),.s_axil_arprot(arprot),.s_axil_arvalid(arvalid),
        .s_axil_arready(arready),.s_axil_rdata(rdata),.s_axil_rresp(rresp),
        .s_axil_rvalid(rvalid),.s_axil_rready(rready),.req_valid(req_valid),
        .req_ready(req_ready),.req(req),.rsp_valid(rsp_valid),.rsp_data(rsp_data),
        .rsp_status(rsp_status),.rsp_seq(rsp_seq),.irq,.protocol_fault);

    task automatic ck(input logic c,input string msg);
        begin checks=checks+1;if(c!==1'b1)$fatal(1,"FAIL %s t=%0t",msg,$time);end
    endtask
    task automatic tick; begin @(posedge clk);#1;end endtask
    task automatic reset_all;
        begin
            @(negedge clk);rst_n=0;admission_enable=0;awvalid=0;wvalid=0;bready=0;
            arvalid=0;rready=0;req_ready=0;rsp_valid=0;awprot=0;arprot=0;wstrb=4'hf;
            repeat(2)tick();@(negedge clk);rst_n=1;tick();
            ck(!bvalid&&!rvalid&&!req_valid&&!irq&&!protocol_fault,"joint reset clears admission test state");
            ck(dut.staged===20'd0&&!dut.aw_pending&&!dut.w_pending,"joint reset clears halves and staged mask");
        end
    endtask
    task automatic send_aw(input logic [31:0] a);
        integer n;
        begin
            @(negedge clk);awaddr=a;awvalid=1;n=0;
            while(!awready&&n<20)begin @(negedge clk);n++;end
            ck(awready,"AW channel accepts independently of admission");
            @(posedge clk);#1;@(negedge clk);awvalid=0;
        end
    endtask
    task automatic send_w(input logic [31:0] d);
        integer n;
        begin
            @(negedge clk);wdata=d;wvalid=1;n=0;
            while(!wready&&n<20)begin @(negedge clk);n++;end
            ck(wready,"W channel accepts independently of admission");
            @(posedge clk);#1;@(negedge clk);wvalid=0;
        end
    endtask
    task automatic get_b(input logic [1:0] expected,input integer hold_cycles);
        integer n;
        begin
            n=0;while(!bvalid&&n<20)begin tick();n++;end
            ck(bvalid&&bresp===expected,"B response code");
            repeat(hold_cycles)begin tick();ck(bvalid&&bresp===expected,"held B stable");end
        end
    endtask
    task automatic consume_b;
        begin @(negedge clk);bready=1;tick();@(negedge clk);bready=0;end
    endtask
    task automatic axwrite(input logic [31:0] a,input logic [31:0] d,input logic [1:0] expected);
        begin
            send_aw(a);send_w(d);get_b(expected,0);consume_b();
        end
    endtask
    task automatic axread(input logic [31:0] a,input logic [1:0] expected_resp,input logic [31:0] expected_data,input integer held);
        integer n;
        begin
            @(negedge clk);araddr=a;arvalid=1;rready=0;n=0;
            while(!arready&&n<20)begin @(negedge clk);n++;end
            ck(arready,"AR remains accepted while admission is disabled");
            @(posedge clk);#1;@(negedge clk);arvalid=0;
            n=0;while(!rvalid&&n<20)begin tick();n++;end
            if(!(rvalid&&rresp===expected_resp&&rdata===expected_data))
                $display("RDBG addr=%h valid=%b resp=%b data=%h wantresp=%b wantdata=%h admission=%b",a,rvalid,rresp,rdata,expected_resp,expected_data,admission_enable);
            ck(rvalid&&rresp===expected_resp&&rdata===expected_data,"R response code and data");
            repeat(held)begin tick();ck(rvalid&&rresp===expected_resp&&rdata===expected_data,"held R stable");end
            @(negedge clk);rready=1;tick();@(negedge clk);rready=0;
        end
    endtask
    task automatic test_aw_only_startup_then_up;
        begin
            reset_all();
            send_aw(32'h40);
            ck(dut.aw_pending&&!dut.aw_allowed,"startup AW half is marked disqualified");
            admission_enable=1;send_w(32'h11223344);get_b(2,1);consume_b();
            ck(dut.staged===20'd0&&!dut.aw_pending&&!dut.w_pending&&!req_valid,
               "AW accepted before first up cannot be paired into staging");
            axwrite(32'h40,32'h55667788,0);
            ck(dut.staged===20'h00001&&dut.staging[31:0]===32'h55667788,
               "fresh healthy write succeeds after rejected AW half was cleared");
        end
    endtask
    task automatic test_w_only_startup_then_up;
        begin
            reset_all();
            send_w(32'hA1B2C3D4);
            ck(dut.w_pending&&!dut.w_allowed,"startup W half is marked disqualified");
            admission_enable=1;send_aw(32'h40);get_b(2,1);consume_b();
            ck(dut.staged===20'd0&&!dut.aw_pending&&!dut.w_pending&&!req_valid,
               "W accepted before first up cannot be paired into staging");
            axwrite(32'h44,32'h01020304,0);
            ck(dut.staged===20'h00002&&dut.staging[63:32]===32'h01020304,
               "fresh healthy write succeeds after rejected W half was cleared");
        end
    endtask
    task automatic test_live_admission_drop_before_write_fire(input logic aw_first);
        begin
            reset_all();admission_enable=1;
            if(aw_first)begin send_aw(32'h40);send_w(32'h89abcdef);end
            else begin send_w(32'h76543210);send_aw(32'h40);end
            ck(dut.aw_pending&&dut.w_pending&&dut.aw_allowed&&dut.w_allowed,
               "both healthy halves accepted before write fire");
            admission_enable=0;
            // A/W have been accepted, but write_fire has not reached the next
            // active edge. Live admission loss must return SLVERR without commit.
            get_b(2,1);consume_b();
            ck(dut.staged===20'd0&&!dut.aw_pending&&!dut.w_pending&&!req_valid,
               "live admission loss rejects accepted halves without staging");
            admission_enable=1;axwrite(32'h48,32'hcafef00d,0);
            ck(dut.staged===20'h00004&&dut.staging[95:64]===32'hcafef00d,
               "clean transaction succeeds after rejected halves drain");
        end
    endtask
    task automatic test_reads_and_held_responses;
        logic [31:0] saved_data;
        begin
            reset_all();admission_enable=1;
            send_aw(32'h40);send_w(32'h1234abcd);get_b(0,0);
            admission_enable=0;
            repeat(3)begin tick();ck(bvalid&&bresp===0,"held successful B survives admission drop");end
            consume_b();
            ck(dut.staged===20'h00001&&dut.staging[31:0]===32'h1234abcd,
               "healthy write committed before held B");
            axread(32'h40,2,0,3);
            admission_enable=1;axread(32'h40,0,32'h1234abcd,0);
            @(negedge clk);araddr=0;arvalid=1;rready=0;
            while(!arready)@(negedge clk);@(posedge clk);#1;@(negedge clk);arvalid=0;
            while(!rvalid)tick();
            saved_data=rdata;ck(rvalid&&rresp===0&&saved_data===32'h524b5046,"healthy R response ready to hold");
            admission_enable=0;repeat(3)begin tick();ck(rvalid&&rresp===0&&rdata===saved_data,"held successful R survives admission drop");end
            @(negedge clk);rready=1;tick();@(negedge clk);rready=0;
        end
    endtask
`ifndef VERILATOR
    task automatic test_unknown_admission;
        begin
            reset_all();admission_enable=1'bx;
            send_aw(32'h40);send_w(32'hfacefeed);get_b(2,0);consume_b();
            ck(dut.staged===20'd0&&!req_valid,"unknown admission rejects write without effects");
            axread(0,2,0,0);
            admission_enable=1;axwrite(32'h40,32'h0badf00d,0);
            ck(dut.staged===20'h00001&&dut.staging[31:0]===32'h0badf00d,
               "known-high admission recovers only for a new write");
        end
    endtask
`endif
    initial begin
        clk=0;rst_n=1;admission_enable=0;
        reset_all();
        test_aw_only_startup_then_up();
        test_w_only_startup_then_up();
        test_live_admission_drop_before_write_fire(1);
        test_live_admission_drop_before_write_fire(0);
        test_reads_and_held_responses();
        ck(!req_valid&&req===604'd0,"admission rejection never creates a backend frame");
`ifndef VERILATOR
        test_unknown_admission();
`endif
        $display("PASS frame mailbox admission checks=%0d four_state=%0d",
`ifdef VERILATOR
                 checks,0);
`else
                 checks,1);
`endif
        $finish;
    end
    initial begin #1000000;$fatal(1,"GLOBAL_ADMISSION_TEST_TIMEOUT");end
endmodule
