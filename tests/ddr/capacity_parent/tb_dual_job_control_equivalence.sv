`timescale 1ns/1ps
module tb_dual_job_control_equivalence;
    logic clk;
    always #5 clk=~clk;

    logic rst_n,memory_ready;
    logic [31:0] awaddr,wdata,araddr;
    logic [2:0] awprot,arprot;
    logic [3:0] wstrb;
    logic awvalid,wvalid,bready,arvalid,rready;
    logic ew_start_ready,cmac_start_ready,done,error_in;
    logic [7:0] error_code;
    logic [31:0] completed_tasks;
    logic live_block,dma_busy,job_active;
    wire core_busy=dma_busy||job_active||(live_block&&!error_in);
    wire core_write_block=live_block||dma_busy||job_active;

    wire old_awready,old_wready,old_bvalid,old_arready,old_rvalid,old_irq,old_sched_fault,old_owned,old_owner_cmac;
    wire old_start_valid,old_start_cmac;
    wire [1:0] old_bresp,old_rresp;
    wire [31:0] old_rdata,old_start_address,old_start_amount;
    wire new_awready,new_wready,new_bvalid,new_arready,new_rvalid,new_irq,new_sched_fault,new_owned,new_owner_cmac;
    wire new_start_valid,new_start_cmac;
    wire [1:0] new_bresp,new_rresp;
    wire [31:0] new_rdata,new_start_address,new_start_amount;
    logic compare_enable;

    rk_dual_job_control original (
        .clk,.rst_n,.memory_ready,
        .s_axil_awaddr(awaddr),.s_axil_wdata(wdata),.s_axil_araddr(araddr),
        .s_axil_awprot(awprot),.s_axil_arprot(arprot),.s_axil_wstrb(wstrb),
        .s_axil_awvalid(awvalid),.s_axil_wvalid(wvalid),.s_axil_bready(bready),
        .s_axil_arvalid(arvalid),.s_axil_rready(rready),
        .s_axil_awready(old_awready),.s_axil_wready(old_wready),.s_axil_bvalid(old_bvalid),
        .s_axil_arready(old_arready),.s_axil_rvalid(old_rvalid),.s_axil_bresp(old_bresp),
        .s_axil_rresp(old_rresp),.s_axil_rdata(old_rdata),.irq(old_irq),
        .scheduler_fault(old_sched_fault),.control_owned(old_owned),.control_owner_cmac(old_owner_cmac),
        .core_start_valid(old_start_valid),.core_start_cmac(old_start_cmac),
        .core_start_address(old_start_address),.core_start_amount(old_start_amount),
        .core_ew_start_ready(ew_start_ready),.core_cmac_start_ready(cmac_start_ready),
        .core_busy,.core_done(done),.core_error(error_in),.core_error_code(error_code),
        .core_completed_tasks(completed_tasks)
    );

    rk_dual_job_control_admission candidate (
        .clk,.rst_n,.memory_ready,
        .s_axil_awaddr(awaddr),.s_axil_wdata(wdata),.s_axil_araddr(araddr),
        .s_axil_awprot(awprot),.s_axil_arprot(arprot),.s_axil_wstrb(wstrb),
        .s_axil_awvalid(awvalid),.s_axil_wvalid(wvalid),.s_axil_bready(bready),
        .s_axil_arvalid(arvalid),.s_axil_rready(rready),
        .s_axil_awready(new_awready),.s_axil_wready(new_wready),.s_axil_bvalid(new_bvalid),
        .s_axil_arready(new_arready),.s_axil_rvalid(new_rvalid),.s_axil_bresp(new_bresp),
        .s_axil_rresp(new_rresp),.s_axil_rdata(new_rdata),.irq(new_irq),
        .scheduler_fault(new_sched_fault),.control_owned(new_owned),.control_owner_cmac(new_owner_cmac),
        .core_start_valid(new_start_valid),.core_start_cmac(new_start_cmac),
        .core_start_address(new_start_address),.core_start_amount(new_start_amount),
        .core_ew_start_ready(ew_start_ready),.core_cmac_start_ready(cmac_start_ready),
        .core_busy,.core_done(done),.core_error(error_in),.core_write_block,
        .core_error_code(error_code),.core_completed_tasks(completed_tasks)
    );

    task automatic compare_outputs;
        begin
            if ({old_awready,old_wready,old_bresp,old_bvalid,old_arready,old_rdata,old_rresp,old_rvalid,
                 old_irq,old_sched_fault,old_owned,old_owner_cmac,old_start_valid,old_start_cmac,
                 old_start_address,old_start_amount} !==
                {new_awready,new_wready,new_bresp,new_bvalid,new_arready,new_rdata,new_rresp,new_rvalid,
                 new_irq,new_sched_fault,new_owned,new_owner_cmac,new_start_valid,new_start_cmac,
                 new_start_address,new_start_amount})
                $fatal(1,"dual-controller output mismatch at t=%0",$time);
        end
    endtask
    always @(posedge clk) begin #1; if (compare_enable) compare_outputs(); end
    always @(negedge clk) begin #1; if (compare_enable) compare_outputs(); end
    task automatic cycle;
        begin @(posedge clk); #2; compare_outputs(); @(negedge clk); #2; compare_outputs(); end
    endtask

    task automatic send_aw(input logic [31:0] address,input logic [2:0] prot);
        integer guard;
        begin
            @(negedge clk); awaddr=address; awprot=prot; awvalid=1; guard=0;
            while (1) begin
                #1; compare_outputs();
                if (old_awready === 1'b1) begin @(posedge clk); #1; compare_outputs(); break; end
                @(posedge clk); #1; compare_outputs(); @(negedge clk); guard=guard+1;
                if (guard>20) $fatal(1,"dual AW timeout");
            end
            @(negedge clk); awvalid=0; #1; compare_outputs();
        end
    endtask
    task automatic send_w(input logic [31:0] data,input logic [3:0] strobe);
        integer guard;
        begin
            @(negedge clk); wdata=data; wstrb=strobe; wvalid=1; guard=0;
            while (1) begin
                #1; compare_outputs();
                if (old_wready === 1'b1) begin @(posedge clk); #1; compare_outputs(); break; end
                @(posedge clk); #1; compare_outputs(); @(negedge clk); guard=guard+1;
                if (guard>20) $fatal(1,"dual W timeout");
            end
            @(negedge clk); wvalid=0; #1; compare_outputs();
        end
    endtask
    task automatic write_csr(input logic [31:0] address,data,
                             input logic [2:0] prot,input logic [3:0] strobe,
                             input logic aw_first,input integer b_stall,
                             output logic [1:0] response);
        integer guard,n;
        begin
            bready=0;
            if (aw_first) begin send_aw(address,prot); send_w(data,strobe); end
            else begin
                // This raw AXI-Lite parent decodes W using the held AWADDR;
                // legal W-before-AW acceptance still presents the address.
                @(negedge clk); awaddr=address; awprot=prot; awvalid=0; #1; compare_outputs();
                send_w(data,strobe); send_aw(address,prot);
            end
            guard=0;
            while (old_bvalid !== 1'b1) begin
                @(posedge clk); #1; compare_outputs(); @(negedge clk); #1; compare_outputs();
                guard=guard+1; if (guard>10) $fatal(1,"dual B response timeout");
            end
            response=old_bresp;
            for (n=0;n<b_stall;n=n+1) begin
                cycle();
                if (old_bvalid !== 1'b1 || old_bresp !== response) $fatal(1,"dual B changed under stall");
            end
            @(negedge clk); bready=1; @(posedge clk); #1; compare_outputs();
            @(negedge clk); bready=0; #1; compare_outputs();
        end
    endtask
    task automatic read_csr(input logic [31:0] address,input logic [2:0] prot,
                            input integer r_stall,output logic [1:0] response,
                            output logic [31:0] data);
        integer guard,n;
        begin
            @(negedge clk); araddr=address; arprot=prot; arvalid=1; guard=0;
            while (old_arready !== 1'b1) begin
                @(posedge clk); #1; compare_outputs(); @(negedge clk); #1;
                guard=guard+1; if (guard>10) $fatal(1,"dual AR timeout");
            end
            @(posedge clk); #1; compare_outputs(); @(negedge clk); arvalid=0; #1; compare_outputs();
            guard=0;
            while (old_rvalid !== 1'b1) begin
                @(posedge clk); #1; compare_outputs(); @(negedge clk); #1;
                guard=guard+1; if (guard>10) $fatal(1,"dual R timeout");
            end
            response=old_rresp; data=old_rdata;
            for (n=0;n<r_stall;n=n+1) begin
                cycle();
                if (old_rvalid !== 1'b1 || old_rresp !== response || old_rdata !== data)
                    $fatal(1,"dual R changed under stall");
            end
            @(negedge clk); rready=1; @(posedge clk); #1; compare_outputs();
            @(negedge clk); rready=0; #1; compare_outputs();
        end
    endtask
    task automatic expect_write(input logic [31:0] address,data,
                                input logic [2:0] prot,input logic [3:0] strobe,
                                input logic aw_first,input logic [1:0] expected);
        logic [1:0] got;
        begin
            write_csr(address,data,prot,strobe,aw_first,2,got);
            if (got !== expected) $fatal(1,"dual write response mismatch at %08x: %b expected %b",address,got,expected);
        end
    endtask
    task automatic expect_read(input logic [31:0] address,input logic [2:0] prot,
                               input logic [1:0] expected_resp,input logic [31:0] expected_data);
        logic [1:0] got_resp; logic [31:0] got_data;
        begin
            read_csr(address,prot,2,got_resp,got_data);
            if (got_resp !== expected_resp || got_data !== expected_data)
                $fatal(1,"dual read mismatch at %08x: %b/%08x expected %b/%08x",address,got_resp,got_data,expected_resp,expected_data);
        end
    endtask
    task automatic reset_pair;
        begin
            @(negedge clk); rst_n=0; live_block=0; dma_busy=0; job_active=0; error_in=0; done=0;
            repeat (2) cycle();
            @(negedge clk); rst_n=1; memory_ready=1; ew_start_ready=1; cmac_start_ready=1;
            @(posedge clk); #1; compare_outputs(); @(negedge clk); #1; compare_outputs();
        end
    endtask
    task automatic stage_ew;
        begin
            expect_write(32'h10,32'h10001000,0,4'hf,1,2'b00);
            expect_write(32'h10,32'h20002000,0,4'hf,0,2'b00);
            expect_write(32'h14,32'd35,0,4'hf,1,2'b00);
            expect_write(32'h18,32'hcafe1234,0,4'hf,0,2'b00);
        end
    endtask
    task automatic stage_cmac;
        begin
            expect_write(32'h110,32'h30003000,0,4'hf,0,2'b00);
            expect_write(32'h114,32'd45,0,4'hf,1,2'b00);
            expect_write(32'h118,32'hface5678,0,4'hf,0,2'b00);
        end
    endtask
    task automatic finish_job(input logic cmac,input logic [31:0] tag,
                              input logic [31:0] tasks,input logic [31:0] amount);
        logic [1:0] peer_resp; logic [31:0] peer_data,base,peer,expected_peer_status;
        begin
            base=cmac ? 32'h100 : 32'h0;
            peer=cmac ? 32'h0 : 32'h100;
            expected_peer_status=cmac ? 32'h00000040 : 32'h00000740;
            expect_write(base+12,1,0,4'hf,1,2'b00);
            if (old_owned !== 1'b1 || old_owner_cmac !== cmac)
                $fatal(1,"global owner selected wrong bank");
            expect_write(peer+16,32'h77770000,0,4'hf,0,2'b10);
            expect_write(peer+12,1,0,4'hf,1,2'b10);
            expect_write(peer+12,2,0,4'hf,0,2'b10);
            read_csr(peer+8,0,2,peer_resp,peer_data);
            if (peer_resp !== 2'b00 || peer_data !== expected_peer_status || old_owned !== 1'b1 || old_owner_cmac !== cmac)
                $fatal(1,"peer status or ownership changed while job owned");
            dma_busy=1; job_active=1; done=0; cycle();
            dma_busy=0; job_active=0; done=1; completed_tasks=tasks;
            cycle(); done=0; cycle();
            if (old_irq !== 1'b1 || old_owned !== 1'b1) $fatal(1,"owner/result did not remain through completion");
            expect_read(base+16,0,2'b00,cmac ? 32'h30003000 : 32'h20002000);
            expect_read(base+20,0,2'b00,amount);
            expect_read(base+24,0,2'b00,cmac ? 32'hface5678 : 32'hcafe1234);
            expect_read(base+28,0,2'b00,tag);
            expect_read(base+32,0,2'b00,tasks);
            expect_read(base+36,0,2'b00,32'h0);
            if (old_owned !== 1'b1) $fatal(1,"owner released before ACK");
            expect_write(base+12,2,0,4'hf,0,2'b00);
            cycle(); cycle();
            if (old_owned !== 1'b0 || old_irq !== 1'b0) $fatal(1,"successful ACK did not release global owner/result");
        end
    endtask

    logic [1:0] read_resp; logic [31:0] read_data;
    integer i;
    initial begin
        clk=0; rst_n=0; memory_ready=0; awaddr=0; wdata=0; araddr=0;
        awprot=0; arprot=0; wstrb=0; awvalid=0; wvalid=0; bready=0;
        arvalid=0; rready=0; ew_start_ready=0; cmac_start_ready=0; done=0;
        error_in=0; error_code=0; completed_tasks=0; live_block=0; dma_busy=0; job_active=0; compare_enable=0;
        repeat (3) @(posedge clk);
        @(negedge clk); rst_n=1; memory_ready=1; ew_start_ready=1; cmac_start_ready=1; wstrb=4'hf; compare_enable=1;
        cycle();
        expect_read(0,0,2'b00,32'h524b4144); expect_read(4,0,2'b00,32'h10000);
        expect_read(32'h100,0,2'b00,32'h524b4344); expect_read(32'h104,0,2'b00,32'h10000);
        expect_write(32'h28,1,0,4'hf,1,2'b11); // Unknown/unsupported EW address forwarded, never truncated.
        expect_write(32'h20000010,1,0,4'hf,0,2'b11); // High address alias.
        expect_write(32'h110,1,3'b001,4'hf,1,2'b10); // Protection error.
        expect_write(32'h110,1,0,4'b0011,0,2'b10); // Partial strobe.
        stage_ew(); stage_cmac();
        expect_read(32'h10,0,2'b00,32'h20002000);
        expect_read(32'h110,0,2'b00,32'h30003000);
        // Invalid read-side protected/unknown cases preserve original responses.
        expect_read(32'h08,3'b001,2'b10,0);
        expect_read(32'h20000008,0,2'b11,0);

        // Own EW globally; opposite-bank writes/SUBMIT/wrong ACK cannot replace it.
        finish_job(1'b0,32'hcafe1234,32'd3,32'd35);
        read_csr(32'h108,0,2,read_resp,read_data);
        if (read_resp !== 2'b00 || read_data !== 32'h00000711 || old_owned !== 1'b0)
            $fatal(1,"peer did not return idle status after ACK");
        // CMAC remains staged, then receives the same global owner after EW ACK.
        finish_job(1'b1,32'hface5678,32'd1,32'd45);

        // A new source epoch clears partial AW/R ownership and both bank states.
        stage_ew();
        expect_write(32'h0c,1,0,4'hf,0,2'b00);
        if (old_owned !== 1'b1) $fatal(1,"EW owner was not accepted before reset control");
        @(negedge clk); rst_n=0; cycle();
        @(negedge clk); rst_n=1; memory_ready=1; cycle();
        if (old_owned !== 1'b0 || old_irq !== 1'b0 || old_sched_fault !== 1'b0)
            $fatal(1,"joint control reset did not clear both-bank owner");

        // Parent invariant four-state probes are run in Icarus. Verilator is
        // two-state and runs the same bounded 0/1 subset in the source peer.
`ifndef VERILATOR
        for (i=0;i<4;i=i+1) begin
            reset_pair();
            case (i)
                0: begin live_block=1'b1; error_in=1'b0; dma_busy=1'b0; job_active=1'b0; end
                1: begin live_block=1'b1; error_in=1'bx; dma_busy=1'b0; job_active=1'b0; end
                2: begin live_block=1'bx; error_in=1'bz; dma_busy=1'b0; job_active=1'b0; end
                3: begin live_block=1'bz; error_in=1'b1; dma_busy=1'b0; job_active=1'b0; end
            endcase
            if (live_block === 1'b0 && error_in !== 1'b0) $fatal(1,"dual test violated parent invariant");
            expect_write(32'h10,32'h11110000,0,4'hf,1,2'b10);
            read_csr(32'h08,0,0,read_resp,read_data);
            if (read_resp !== 2'b00 || read_data !== old_rdata) $fatal(1,"dual invariant status read failed");
        end
`else
        for (i=0;i<4;i=i+1) begin
            reset_pair();
            live_block=i[0]; error_in=i[1]; dma_busy=1'b0; job_active=1'b0;
            if (live_block === 1'b0 && error_in !== 1'b0) begin end
            else begin
                expect_write(32'h10,32'h11110000,0,4'hf,1,
                    (live_block===1'b0 && error_in===1'b0) ? 2'b00 : 2'b10);
                read_csr(32'h08,0,0,read_resp,read_data);
                if (read_resp !== 2'b00 || read_data !== old_rdata) $fatal(1,"dual invariant status read failed");
            end
        end
`endif
        $display("PASS_DUAL_JOB_CONTROL_CYCLE_EQUIVALENCE");
        $finish;
    end
endmodule
