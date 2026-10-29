// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_axil_frame_mailbox;
    logic clk, rst_n=0;
    initial clk=0;
    always #5 clk=~clk;
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
    logic [603:0] expected_req;
    logic [511:0] expected_data;
    logic [639:0] expected_rsp;
    logic [639:0] raw_frame;

    rk_axil_frame_mailbox dut(
        .clk(clk),.rst_n(rst_n),.admission_enable(1'b1),.s_axil_awaddr(awaddr),.s_axil_awprot(awprot),
        .s_axil_awvalid(awvalid),.s_axil_awready(awready),.s_axil_wdata(wdata),
        .s_axil_wstrb(wstrb),.s_axil_wvalid(wvalid),.s_axil_wready(wready),
        .s_axil_bresp(bresp),.s_axil_bvalid(bvalid),.s_axil_bready(bready),
        .s_axil_araddr(araddr),.s_axil_arprot(arprot),.s_axil_arvalid(arvalid),
        .s_axil_arready(arready),.s_axil_rdata(rdata),.s_axil_rresp(rresp),
        .s_axil_rvalid(rvalid),.s_axil_rready(rready),.req_valid(req_valid),
        .req_ready(req_ready),.req(req),.rsp_valid(rsp_valid),.rsp_data(rsp_data),
        .rsp_status(rsp_status),.rsp_seq(rsp_seq),.irq(irq),.protocol_fault(protocol_fault));

    always @(posedge clk) begin
        if(awvalid&&awready)$display("TRACE t=%0t AW %08x",$time,awaddr);
        if(wvalid&&wready)$display("TRACE t=%0t W %08x",$time,wdata);
        if(bvalid&&bready)$display("TRACE t=%0t B %b",$time,bresp);
    end

    task automatic tick; begin @(posedge clk); #1; end endtask
    task automatic check_cond(input logic cond,input string what); begin
        checks=checks+1; if(cond!==1'b1) $fatal(1,"FAIL %s t=%0t",what,$time);
    end endtask
    task automatic reset_dut; begin
        @(negedge clk); rst_n=0; awvalid=0;wvalid=0;bready=0;arvalid=0;rready=0;
        req_ready=0;rsp_valid=0;awprot=0;arprot=0;wstrb=4'hf;tick();tick();
        @(negedge clk); rst_n=1; tick();
        check_cond(!bvalid&&!rvalid&&!req_valid&&!irq&&!protocol_fault,"reset clears visible state");
        check_cond(bresp===0&&rresp===0&&rdata===0&&req===0,"reset outputs known zeros");
    end endtask

    task automatic write_word(input logic [31:0] a,input logic [31:0] d,
                              input logic [2:0] p,input logic [3:0] s,input integer mode,
                              input logic [1:0] want);
        integer n,adelay,wdelay; begin
        awvalid=0;wvalid=0;awaddr=a;wdata=d;awprot=p;wstrb=s;
        if(mode==0)begin adelay=0;wdelay=2;end
        else if(mode==1)begin adelay=2;wdelay=0;end
        else begin adelay=3;wdelay=1;end
        if(mode==1)begin
            repeat(wdelay)@(negedge clk);wvalid=1;while(!wready)@(negedge clk);
            @(posedge clk);#1;wvalid=0;
            repeat(adelay)@(negedge clk);awvalid=1;while(!awready)@(negedge clk);
            @(posedge clk);#1;awvalid=0;
        end else begin
            repeat(adelay)@(negedge clk);awvalid=1;while(!awready)@(negedge clk);
            @(posedge clk);#1;awvalid=0;
            repeat(wdelay)@(negedge clk);wvalid=1;while(!wready)@(negedge clk);
            @(posedge clk);#1;wvalid=0;
        end
        bready=0;
        for(n=0;n<80&&!bvalid;n=n+1)tick();
        check_cond(bvalid,"write response appears"); if(bresp!=want)$fatal(1,"write response code addr=%h want=%b got=%b data=%h mask=%h magic=%h high=%h idle=%b o=%b w=%b h=%b f=%b",a,want,bresp,d,dut.staged,dut.staging[603:572],dut.staging[639:604],dut.idle,dut.offered,dut.waiting,dut.held,dut.failed);
        repeat(2)begin tick();check_cond(bvalid,"BVALID held");check_cond(bresp==want,"BRESP stable");end
        @(negedge clk);bready=1;tick();@(negedge clk);bready=0;
        end endtask

    task automatic read_word(input logic [31:0] a,input logic [2:0] p,
                             input logic want_valid,input logic [1:0] want_resp,
                             input logic [31:0] want_data,input integer hold_cycles);
        integer n; begin
        @(negedge clk);araddr=a;arprot=p;arvalid=1;rready=0;
        do begin @(posedge clk); end while(!arready);
        @(negedge clk);arvalid=0;
        for(n=0;n<80&&!rvalid;n=n+1)tick();
        check_cond(rvalid,"read response appears");check_cond(rresp==want_resp,"read response code");
        if(want_valid&&rdata!==want_data)$fatal(1,"read data mismatch addr=%h got=%h expected=%h resp=%b",a,rdata,want_data,rresp);
        repeat(hold_cycles)begin tick();check_cond(rvalid,"RVALID held");check_cond(rresp==want_resp,"RRESP held");end
        @(negedge clk);rready=1;tick();@(negedge clk);rready=0;
        end endtask

    task automatic stage_frame; integer i,mode; begin
        for(i=0;i<20;i=i+1)begin
            mode=(i%3); write_word(32'h40+4*i,raw_frame[i*32 +:32],0,4'hf,mode,0);
        end
    end endtask
    task automatic start_request; begin
        write_word(32'hc,1,0,4'hf,2,0);
        check_cond(req_valid,"request offered");check_cond(req===expected_req,"exact raw request");
        req_ready=0;repeat(3)begin tick();check_cond(req_valid&&req===expected_req,"request stable stalled");end
        @(negedge clk);req_ready=1;tick();@(negedge clk);req_ready=0;
        check_cond(!req_valid,"one backend handshake consumes request");
    end endtask
    task automatic deliver_response(input logic [15:0] seq,input logic [7:0] status,
                                    input logic [511:0] data); begin
        @(negedge clk);rsp_seq=seq;rsp_status=status;rsp_data=data;rsp_valid=1;tick();
        @(negedge clk);rsp_valid=0;
    end endtask

    integer i;
    initial begin
        $dumpfile("mailbox.vcd");
        $dumpvars(0,tb_axil_frame_mailbox);
        // Deterministic raw little-endian test words, including explicit zero high bits.
        for(i=0;i<20;i=i+1)raw_frame[i*32 +:32]=32'h9e3779b9 ^ (32'h01020304*i);
        raw_frame[603:572]=32'h4f54504a;raw_frame[639:604]=36'd0;
        raw_frame[571:556]=16'h35a7;expected_req=raw_frame[603:0];
        for(i=0;i<16;i=i+1)expected_data[i*32 +:32]=32'hd00d0000+i*32'h01010101;
        expected_rsp={72'd0,32'h4f54504a,16'h35a7,8'd0,expected_data};
        raw_frame[639:604]=36'd0;
        reset_dut();
        // Reset while each AXI-Lite response is held under backpressure.
        @(negedge clk);awaddr=32'h80000020;wdata=0;awvalid=1;
        while(!awready)@(negedge clk);@(posedge clk);#1;awvalid=0;
        @(negedge clk);wvalid=1;while(!wready)@(negedge clk);@(posedge clk);#1;wvalid=0;
        for(i=0;i<20&&!bvalid;i=i+1)tick();check_cond(bvalid&&bresp==3,"DECERR B response held before reset");
        repeat(3)begin tick();check_cond(bvalid&&bresp==3,"B response remains held");end
        reset_dut();
        @(negedge clk);araddr=0;arprot=0;arvalid=1;rready=0;
        while(!arready)@(negedge clk);@(posedge clk);#1;arvalid=0;
        for(i=0;i<20&&!rvalid;i=i+1)tick();check_cond(rvalid&&rdata==32'h524b5046,"R response held before reset");
        repeat(3)begin tick();check_cond(rvalid&&rdata==32'h524b5046,"R response remains held");end
        reset_dut();read_word(0,0,1,0,32'h524b5046,0);
        read_word(0,0,1,0,32'h524b5046,2);read_word(4,0,1,0,32'h00010000,0);
        stage_frame();read_word(16,0,1,0,32'h000fffff,0);
        if(dut.staged!==20'hfffff || dut.staging!==raw_frame)$fatal(1,"stage mismatch mask=%h data=%h expected=%h",dut.staged,dut.staging,raw_frame);
        start_request();
        // Failed early ACK, plus staging/commit blocked while request is outstanding.
        write_word(32'hc,2,0,4'hf,0,2);write_word(32'h40,0,0,4'hf,0,2);
        write_word(32'hc,1,0,4'hf,0,2);
        deliver_response(16'h35a7,0,expected_data);
        check_cond(irq,"response raises irq");
        write_word(32'h40,0,0,4'hf,0,2);write_word(32'hc,1,0,4'hf,0,2);
        // Read each response word once, with the final response held under backpressure.
        for(i=0;i<20;i=i+1)read_word(32'h100+4*i,0,1,0,expected_rsp[i*32 +:32],(i==19)?3:0);
        read_word(20,0,1,0,32'h000fffff,0);
        write_word(32'hc,2,0,4'hf,1,0);
        read_word(16,0,1,0,0,0);check_cond(!irq,"ACK clears response and staging");
        // Duplicate response-word reads cannot substitute for the missing final handshake.
        stage_frame();start_request();
        deliver_response(16'h35a7,0,expected_data);
        for(i=0;i<19;i=i+1)read_word(32'h100+4*i,0,1,0,expected_rsp[i*32 +:32],0);
        read_word(32'h100,0,1,0,expected_rsp[31:0],0);
        write_word(32'hc,2,0,4'hf,0,2);
        read_word(20,0,1,0,32'h07ffff,0);
        read_word(32'h14c,0,1,0,expected_rsp[19*32 +:32],0);
        write_word(32'hc,2,0,4'hf,0,0);
        read_word(16,0,1,0,0,0);
        // Re-stage requirement: partial next request cannot commit.
        write_word(32'h40,raw_frame[31:0],0,4'hf,0,0);
        write_word(32'hc,1,0,4'hf,0,2);
        reset_dut();

        // Address aliases are decoded on full 32-bit address; malformed accesses do not mutate.
        write_word(32'h80000040,32'h12345678,0,4'hf,0,3);
        write_word(32'h42,0,0,4'hf,0,3);read_word(32'h44,0,1,0,0,0);
        read_word(32'h80000000,0,0,3,0,0);read_word(32'h102,0,0,3,0,0);
        read_word(0,1,0,2,0,0);write_word(32'h40,1,1,4'hf,0,2);
        write_word(32'h40,1,0,4'h7,0,2);write_word(32'hc,3,0,4'hf,0,2);
        read_word(16,0,1,0,0,0);
        // Correct setup then corrupt magic/high reserved bits and prove no backend forwarding.
        for(i=0;i<20;i=i+1)write_word(32'h40+4*i,raw_frame[i*32 +:32],0,4'hf,0,0);
        write_word(32'h40+4*17,0,0,4'hf,0,0);write_word(32'hc,1,0,4'hf,0,2);
        check_cond(!req_valid,"invalid frame never forwarded");
        write_word(32'h40+4*17,raw_frame[17*32 +:32],0,4'hf,0,0);
        write_word(32'h40+4*19,32'h00000001,0,4'hf,0,0);write_word(32'hc,1,0,4'hf,0,2);
        reset_dut();

        // Same-edge accept/response is legal; nonzero backend error payload is preserved exactly.
        for(i=0;i<20;i=i+1)write_word(32'h40+4*i,raw_frame[i*32 +:32],0,4'hf,0,0);
        write_word(32'hc,1,0,4'hf,0,0);
        @(negedge clk);req_ready=1;rsp_valid=1;rsp_seq=16'h35a7;rsp_status=8'h2a;rsp_data=512'd0;
        expected_rsp={72'd0,32'h4f54504a,16'h35a7,8'h2a,512'd0};
        tick();@(negedge clk);req_ready=0;rsp_valid=0;
        if(!(irq&&!protocol_fault))$fatal(1,"same-edge response rejected fault=%b code=%h offered=%b waiting=%b held=%b request_seq=%h rsp_seq=%h reqready=%b",protocol_fault,dut.failure_code,dut.offered,dut.waiting,dut.held,dut.request[571:556],rsp_seq,req_ready);
        read_word(32'h100,0,1,0,expected_rsp[31:0],0);
        read_word(32'h140,0,1,0,expected_rsp[16*32 +:32],0);
        // Complete remaining unique response words then ACK.
        for(i=1;i<20;i=i+1)read_word(32'h100+4*i,0,1,0,expected_rsp[i*32 +:32],0);
        write_word(32'hc,2,0,4'hf,0,0);reset_dut();

        // Wrong sequence, unsolicited, duplicate and nonzero error payload are sticky code faults.
        fault_case(1);fault_case(2);fault_case(3);fault_case(4);
`ifndef VERILATOR
        // Four-state policy checks are Icarus-only; Verilator is two-state.
        reset_dut();write_word(32'h40,32'h0,3'b0x0,4'hf,0,2);
        read_word(0,3'b00x,0,2,0,0);
`endif
        $display("PASS frame mailbox checks=%0d",checks);$finish;
    end

    task automatic fault_case(input integer kind); integer n; logic [7:0] code; begin
        reset_dut();
        if(kind!=2)begin
            for(n=0;n<20;n=n+1)write_word(32'h40+4*n,raw_frame[n*32 +:32],0,4'hf,0,0);
            write_word(32'hc,1,0,4'hf,0,0);
            req_ready=1;tick();@(negedge clk);req_ready=0;
        end
        if(kind==1)deliver_response(16'h35a8,0,0);
        if(kind==2)deliver_response(16'h35a7,0,0);
        if(kind==3)begin deliver_response(16'h35a7,0,0);deliver_response(16'h35a7,0,0);end
        if(kind==4)deliver_response(16'h35a7,1,512'h1);
        if(kind==1)code=2;else if(kind==2)code=1;else if(kind==3)code=3;else code=4;
        check_cond(protocol_fault&&irq,"protocol fault sticky");read_word(24,0,1,0,{24'd0,code},0);
        // Fault blocks ACK, staging, commits and new backend request handshakes.
        write_word(32'hc,2,0,4'hf,0,2);write_word(32'h40,0,0,4'hf,0,2);
        write_word(32'hc,1,0,4'hf,0,2);req_ready=1;repeat(3)begin tick();check_cond(!req_valid,"fault blocks phantom request");end
        reset_dut();
        // A response arriving after reset belongs to a stale epoch and faults as unsolicited.
        deliver_response(16'h35a7,0,0);check_cond(protocol_fault,"late old response faults new epoch");
        reset_dut();
    end endtask
endmodule
