`timescale 1ns/1ps
module tb_job_control_equivalence;
    logic clk;
    always #5 clk = ~clk;

    logic rst_n, memory_ready;
    logic [31:0] awaddr, wdata, araddr;
    logic [2:0] awprot, arprot;
    logic [3:0] wstrb;
    logic awvalid, wvalid, bready, arvalid, rready;
    logic start_ready, done, error_in;
    logic [7:0] error_code;
    logic [31:0] completed_tasks;
    logic live_block, dma_busy, job_active;
    wire core_busy = dma_busy || job_active || (live_block && !error_in);
    wire core_write_block = live_block || dma_busy || job_active;

    wire old_awready, old_wready, old_bvalid, old_arready, old_rvalid, old_irq, old_start_valid;
    wire [1:0] old_bresp, old_rresp;
    wire [31:0] old_rdata, old_start_address, old_start_amount;
    wire new_awready, new_wready, new_bvalid, new_arready, new_rvalid, new_irq, new_start_valid;
    wire [1:0] new_bresp, new_rresp;
    wire [31:0] new_rdata, new_start_address, new_start_amount;
    logic compare_enable;

    rk_job_control #(.DEVICE_ID(32'h524b4157)) original (
        .clk, .rst_n, .memory_ready,
        .s_axil_awaddr(awaddr), .s_axil_awprot(awprot), .s_axil_awvalid(awvalid), .s_axil_awready(old_awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid), .s_axil_wready(old_wready),
        .s_axil_bresp(old_bresp), .s_axil_bvalid(old_bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arprot(arprot), .s_axil_arvalid(arvalid), .s_axil_arready(old_arready),
        .s_axil_rdata(old_rdata), .s_axil_rresp(old_rresp), .s_axil_rvalid(old_rvalid), .s_axil_rready(rready),
        .irq(old_irq), .core_start_valid(old_start_valid), .core_start_ready(start_ready),
        .core_start_address(old_start_address), .core_start_amount(old_start_amount),
        .core_busy, .core_done(done), .core_error(error_in), .core_error_code(error_code),
        .core_completed_tasks(completed_tasks)
    );

    rk_job_control_admission #(.DEVICE_ID(32'h524b4157)) candidate (
        .clk, .rst_n, .memory_ready,
        .s_axil_awaddr(awaddr), .s_axil_awprot(awprot), .s_axil_awvalid(awvalid), .s_axil_awready(new_awready),
        .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid), .s_axil_wready(new_wready),
        .s_axil_bresp(new_bresp), .s_axil_bvalid(new_bvalid), .s_axil_bready(bready),
        .s_axil_araddr(araddr), .s_axil_arprot(arprot), .s_axil_arvalid(arvalid), .s_axil_arready(new_arready),
        .s_axil_rdata(new_rdata), .s_axil_rresp(new_rresp), .s_axil_rvalid(new_rvalid), .s_axil_rready(rready),
        .irq(new_irq), .core_start_valid(new_start_valid), .core_start_ready(start_ready),
        .core_start_address(new_start_address), .core_start_amount(new_start_amount),
        .core_busy, .core_done(done), .core_error(error_in), .core_write_block,
        .core_error_code(error_code), .core_completed_tasks(completed_tasks)
    );

    task automatic compare_outputs;
        begin
            if ({old_awready,old_wready,old_bresp,old_bvalid,old_arready,old_rdata,old_rresp,old_rvalid,
                 old_irq,old_start_valid,old_start_address,old_start_amount} !==
                {new_awready,new_wready,new_bresp,new_bvalid,new_arready,new_rdata,new_rresp,new_rvalid,
                 new_irq,new_start_valid,new_start_address,new_start_amount})
                $fatal(1,"single-controller output mismatch at t=%0",$time);
        end
    endtask
    always @(posedge clk) begin #1; if (compare_enable) compare_outputs(); end
    always @(negedge clk) begin #1; if (compare_enable) compare_outputs(); end

    task automatic cycle;
        begin @(posedge clk); #2; compare_outputs(); @(negedge clk); #2; compare_outputs(); end
    endtask

    task automatic send_aw(input logic [31:0] address, input logic [2:0] prot);
        integer guard;
        begin
            @(negedge clk); awaddr=address; awprot=prot; awvalid=1;
            guard=0;
            while (1) begin
                #1; compare_outputs();
                if (old_awready === 1'b1) begin @(posedge clk); #1; compare_outputs(); break; end
                @(posedge clk); #1; compare_outputs(); @(negedge clk); guard=guard+1;
                if (guard>20) $fatal(1,"AW timeout");
            end
            @(negedge clk); awvalid=0; #1; compare_outputs();
        end
    endtask
    task automatic send_w(input logic [31:0] data, input logic [3:0] strobe);
        integer guard;
        begin
            @(negedge clk); wdata=data; wstrb=strobe; wvalid=1;
            guard=0;
            while (1) begin
                #1; compare_outputs();
                if (old_wready === 1'b1) begin @(posedge clk); #1; compare_outputs(); break; end
                @(posedge clk); #1; compare_outputs(); @(negedge clk); guard=guard+1;
                if (guard>20) $fatal(1,"W timeout");
            end
            @(negedge clk); wvalid=0; #1; compare_outputs();
        end
    endtask
    task automatic write_csr(input logic [31:0] address, data,
                             input logic [2:0] prot, input logic [3:0] strobe,
                             input logic aw_first, input integer b_stall,
                             output logic [1:0] response);
        integer guard, n;
        begin
            bready=0;
            if (aw_first) begin send_aw(address,prot); send_w(data,strobe); end
            else begin send_w(data,strobe); send_aw(address,prot); end
            guard=0;
            while (old_bvalid !== 1'b1) begin
                @(posedge clk); #1; compare_outputs(); @(negedge clk); #1; compare_outputs();
                guard=guard+1;
                if (guard>10) $fatal(1,"B response timeout");
            end
            response=old_bresp;
            for (n=0;n<b_stall;n=n+1) begin
                cycle();
                if (old_bvalid !== 1'b1 || old_bresp !== response) $fatal(1,"B channel changed under stall");
            end
            @(negedge clk); bready=1;
            @(posedge clk); #1; compare_outputs();
            @(negedge clk); bready=0; #1; compare_outputs();
        end
    endtask
    task automatic submit_with_start_stalled;
        integer guard,n;
        logic [1:0] response;
        begin
            bready=0;
            send_aw(32'h0c,0); send_w(1,4'hf);
            // The descriptor must see start_ready high on its commit edge.
            guard=0;
            while (old_bvalid !== 1'b1) begin
                @(posedge clk); #1; compare_outputs(); @(negedge clk); #1; compare_outputs();
                guard=guard+1; if (guard>10) $fatal(1,"submit B response timeout");
            end
            // BVALID is now visible and launch_pending is set; lower ready
            // before its following handshake edge to check retained payload.
            start_ready=0;
            response=old_bresp;
            for (n=0;n<2;n=n+1) begin
                cycle();
                if (old_bvalid !== 1'b1 || old_bresp !== response) $fatal(1,"submit B changed under stall");
            end
            if (response !== 2'b00 || old_start_valid !== 1'b1) $fatal(1,"stalled submit did not retain start");
            @(negedge clk); bready=1; @(posedge clk); #1; compare_outputs();
            @(negedge clk); bready=0; #1; compare_outputs();
        end
    endtask
    task automatic read_csr(input logic [31:0] address, input logic [2:0] prot,
                            input integer r_stall, output logic [1:0] response,
                            output logic [31:0] data);
        integer guard,n;
        begin
            @(negedge clk); araddr=address; arprot=prot; arvalid=1;
            guard=0;
            while (old_arready !== 1'b1) begin
                @(posedge clk); #1; compare_outputs(); @(negedge clk); #1;
                guard=guard+1; if (guard>10) $fatal(1,"AR timeout");
            end
            @(posedge clk); #1; compare_outputs();
            @(negedge clk); arvalid=0; #1; compare_outputs();
            guard=0;
            while (old_rvalid !== 1'b1) begin
                @(posedge clk); #1; compare_outputs(); @(negedge clk); #1;
                guard=guard+1; if (guard>10) $fatal(1,"R response timeout");
            end
            response=old_rresp; data=old_rdata;
            for (n=0;n<r_stall;n=n+1) begin
                cycle();
                if (old_rvalid !== 1'b1 || old_rresp !== response || old_rdata !== data)
                    $fatal(1,"R channel changed under stall");
            end
            @(negedge clk); rready=1;
            @(posedge clk); #1; compare_outputs();
            @(negedge clk); rready=0; #1; compare_outputs();
        end
    endtask
    task automatic expect_write(input logic [31:0] address, data,
                               input logic [2:0] prot, input logic [3:0] strobe,
                               input logic aw_first, input logic [1:0] expected);
        logic [1:0] got;
        begin
            write_csr(address,data,prot,strobe,aw_first,2,got);
            if (got !== expected) $fatal(1,"write response mismatch at %08x: got %b expected %b",address,got,expected);
        end
    endtask
    task automatic expect_read(input logic [31:0] address,input logic [2:0] prot,
                               input logic [1:0] expected_resp,input logic [31:0] expected_data);
        logic [1:0] got_resp; logic [31:0] got_data;
        begin
            read_csr(address,prot,2,got_resp,got_data);
            if (got_resp !== expected_resp || got_data !== expected_data)
                $fatal(1,"read mismatch at %08x: got %b/%08x expected %b/%08x",address,got_resp,got_data,expected_resp,expected_data);
        end
    endtask
    task automatic reset_epoch;
        begin
            @(negedge clk); rst_n=0; live_block=0; dma_busy=0; job_active=0; error_in=0; done=0;
            repeat (2) cycle();
            @(negedge clk); rst_n=1; memory_ready=1; start_ready=1;
            @(posedge clk); #1; compare_outputs(); @(negedge clk); #1; compare_outputs();
        end
    endtask
    task automatic legal_descriptor;
        begin
            expect_write(32'h10,32'h10001000,0,4'hf,1,2'b00);
            expect_write(32'h14,32'd35,0,4'hf,0,2'b00);
            expect_write(32'h18,32'hcafe1234,0,4'hf,1,2'b00);
        end
    endtask

    task automatic parent_state_probe(input logic lb, input logic ce,
                                      input logic db, input logic jb);
        logic [1:0] got_response;
        logic [31:0] got_data;
        logic [1:0] expected_response;
        begin
            reset_epoch();
            live_block=lb; error_in=ce; dma_busy=db; job_active=jb;
            if (live_block === 1'b0 && error_in !== 1'b0)
                $fatal(1,"testbench violated parent invariant");
            if (live_block === 1'b0 && error_in === 1'b0 &&
                dma_busy === 1'b0 && job_active === 1'b0)
                expected_response=2'b00;
            else
                expected_response=2'b10;
            expect_write(32'h10,32'h12340000,0,4'hf,1,expected_response);
            read_csr(32'h08,0,0,got_response,got_data);
            if (got_response !== 2'b00 || got_data !== old_rdata)
                $fatal(1,"status read compare failed in parent-state sweep");
        end
    endtask

    integer live_i, err_i, dma_i, job_i;
`ifndef VERILATOR
    logic [1:0] wr;
    logic [31:0] rd;
    logic [3:0] four_state_values [0:3];
`endif
    initial begin
        clk=0;
        rst_n=0; memory_ready=0; awaddr=0; wdata=0; araddr=0; awprot=0; arprot=0;
        wstrb=0; awvalid=0; wvalid=0; bready=0; arvalid=0; rready=0;
        start_ready=0; done=0; error_in=0; error_code=0; completed_tasks=0;
        live_block=0; dma_busy=0; job_active=0; compare_enable=0;
        repeat(3) @(posedge clk);
        @(negedge clk); rst_n=1; memory_ready=1; start_ready=1; wstrb=4'hf; compare_enable=1;
        cycle();
        expect_read(32'h00,0,2'b00,32'h524b4157);
        expect_read(32'h04,0,2'b00,32'h00010000);
        expect_write(32'h00,1,0,4'hf,1,2'b10); // read-only
        expect_write(32'h28,1,0,4'hf,0,2'b11); // unknown CSR
        expect_write(32'h10,1,3'b001,4'hf,1,2'b10); // protected
        expect_write(32'h10,1,0,4'b0011,0,2'b10); // partial strobe
        expect_write(32'h10000010,1,0,4'hf,1,2'b11); // high alias

        // Descriptor register writes remain last-write-wins with split AW/W.
        expect_write(32'h10,32'h10001000,0,4'hf,1,2'b00);
        expect_write(32'h10,32'h20002000,0,4'hf,0,2'b00);
        expect_write(32'h14,32'd35,0,4'hf,1,2'b00);
        expect_write(32'h18,32'hcafe1234,0,4'hf,0,2'b00);
        expect_read(32'h10,0,2'b00,32'h20002000);
        memory_ready=0;
        expect_write(32'h0c,1,0,4'hf,1,2'b10);
        memory_ready=1; start_ready=0;
        expect_write(32'h0c,1,0,4'hf,0,2'b10);
        start_ready=1;
        submit_with_start_stalled();
        if (old_start_valid !== 1'b1 || old_start_address !== 32'h20002000 || old_start_amount !== 35)
            $fatal(1,"accepted start payload not retained");
        start_ready=1;
        cycle();
        if (old_start_valid !== 1'b0) $fatal(1,"ready start did not handshake");

        // Parent-factorization concurrent fault and write: old/candidate must
        // produce the exact same SLVERR and terminal error snapshot.
        dma_busy=1; job_active=1;
        expect_write(32'h14,32'd99,0,4'hf,1,2'b10);
        live_block=1; error_in=1; error_code=8'h66; completed_tasks=32'd1; done=0;
        expect_write(32'h14,32'd99,0,4'hf,0,2'b10);
        dma_busy=0; job_active=0;
        cycle();
        if (old_irq !== 1'b1) $fatal(1,"concurrent fault did not retain error result");
        expect_read(32'h1c,0,2'b00,32'hcafe1234);
        expect_read(32'h20,0,2'b00,32'd1);
        expect_read(32'h24,0,2'b00,32'h66);
        expect_write(32'h0c,2,0,4'hf,1,2'b10);

        // Reset the failed epoch, then prove normal success and that a fault
        // arriving with ACK pending blocks ACK in both implementations.
        reset_epoch();
        legal_descriptor();
        expect_write(32'h0c,1,0,4'hf,0,2'b00);
        cycle();
        dma_busy=1; job_active=1; start_ready=0; cycle();
        dma_busy=0; job_active=0; done=1; completed_tasks=32'd2;
        cycle(); done=0;
        if (old_irq !== 1'b1) $fatal(1,"success result missing");
        expect_read(32'h1c,0,2'b00,32'hcafe1234);
        expect_read(32'h20,0,2'b00,32'd2);
        expect_read(32'h24,0,2'b00,32'd0);
        live_block=1; error_in=1;
        expect_write(32'h0c,2,0,4'hf,1,2'b10);
        live_block=0; error_in=0; start_ready=1;
        expect_write(32'h0c,2,0,4'hf,0,2'b00);
        cycle();

        // Partial reset with only AW accepted discards the partial request.
        send_aw(32'h10,0);
        @(negedge clk); rst_n=0; cycle();
        @(negedge clk); rst_n=1; cycle();
        expect_read(32'h10,0,2'b00,32'd0);

        // Parent invariant: live_block===0 implies core_error===0.
`ifdef VERILATOR
        for (live_i=0;live_i<2;live_i=live_i+1) begin
            for (err_i=0;err_i<2;err_i=err_i+1) begin
                for (dma_i=0;dma_i<2;dma_i=dma_i+1) begin
                    for (job_i=0;job_i<2;job_i=job_i+1) begin
                        if (!(live_i==0 && err_i!=0))
                            parent_state_probe(live_i[0],err_i[0],dma_i[0],job_i[0]);
                    end
                end
            end
        end
        $display("PASS_JOB_CONTROL_CYCLE_EQUIVALENCE four_state=0");
`else
        // Icarus additionally samples adversarial X/Z cases inside invariant.
        four_state_values[0]=4'b0000; four_state_values[1]=4'b0001;
        four_state_values[2]=4'b00xx; four_state_values[3]=4'b00zz;
        for (live_i=0;live_i<4;live_i=live_i+1) begin
            for (err_i=0;err_i<4;err_i=err_i+1) begin
                for (dma_i=0;dma_i<4;dma_i=dma_i+1) begin
                    for (job_i=0;job_i<4;job_i=job_i+1) begin
                        if (live_i==0 && err_i!=0) begin end
                        else begin
                            reset_epoch();
                            live_block=four_state_values[live_i][0]; error_in=four_state_values[err_i][0];
                            dma_busy=four_state_values[dma_i][0]; job_active=four_state_values[job_i][0];
                            if (live_block === 1'b0 && error_in !== 1'b0)
                                $fatal(1,"testbench violated parent invariant");
                            if (live_block === 1'b0 && error_in === 1'b0 &&
                                dma_busy === 1'b0 && job_active === 1'b0)
                                expect_write(32'h10,32'h12340000,0,4'hf,1,2'b00);
                            else
                                expect_write(32'h10,32'h12340000,0,4'hf,1,2'b10);
                            read_csr(32'h08,0,0,wr,rd);
                            if (wr !== 2'b00 || rd !== old_rdata)
                                $fatal(1,"status read compare failed in four-state invariant sweep");
                        end
                    end
                end
            end
        end
        $display("PASS_JOB_CONTROL_CYCLE_EQUIVALENCE four_state=1");
`endif
        $finish;
    end
endmodule
