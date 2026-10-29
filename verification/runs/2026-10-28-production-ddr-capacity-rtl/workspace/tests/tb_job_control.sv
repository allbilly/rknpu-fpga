`timescale 1ns/1ps
module tb_job_control;
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic rst_n=0, memory_ready=1, irq;
    `include "tests/axil_host.svh"
    logic core_start_valid, core_start_ready=1, core_busy=0, core_done=0, core_error=0;
    logic [31:0] core_start_address, core_start_amount, core_completed_tasks=0;
    logic [7:0] core_error_code=0;
    rk_job_control dut(.*);
    integer launches;
    logic [31:0] launched_address, launched_amount;
    logic held_start, held_b, held_r;
    logic [63:0] old_start;
    logic [1:0] old_b;
    logic [33:0] old_r;
    always @(posedge clk) begin
        if (!rst_n) begin
            launches<=0; launched_address<=0; launched_amount<=0;
            held_start<=0; held_b<=0; held_r<=0; old_start<=0; old_b<=0; old_r<=0;
        end else begin
            if (core_start_valid && core_start_ready) begin
                launches<=launches+1; launched_address<=core_start_address; launched_amount<=core_start_amount;
            end
            if (held_start && (!core_start_valid || {core_start_address,core_start_amount} !== old_start))
                $fatal(1,"descriptor changed during launch backpressure");
            if (held_b && (!s_axil_bvalid || s_axil_bresp !== old_b)) $fatal(1,"unstable B");
            if (held_r && (!s_axil_rvalid || {s_axil_rresp,s_axil_rdata} !== old_r)) $fatal(1,"unstable R");
            held_start<=core_start_valid && !core_start_ready; old_start<={core_start_address,core_start_amount};
            held_b<=s_axil_bvalid && !s_axil_bready; old_b<=s_axil_bresp;
            held_r<=s_axil_rvalid && !s_axil_rready; old_r<={s_axil_rresp,s_axil_rdata};
        end
    end
    task automatic reset_all;
        @(negedge clk); rst_n=0; host_idle();
        core_busy=0; core_done=0; core_error=0; core_completed_tasks=0; core_error_code=0;
        core_start_ready=1; memory_ready=1;
        repeat(3) @(negedge clk);
        if (irq || core_start_valid || s_axil_awready || s_axil_wready || s_axil_arready || s_axil_bvalid || s_axil_rvalid)
            $fatal(1,"control traffic during reset");
        rst_n=1;
        host_expect(8,32'h10);
        if (launches!=0) $fatal(1,"stale launch after reset");
    endtask
    task automatic descriptor(input logic [31:0] tag);
        host_write(32'h10,32'h100e0000,0,1);
        host_write(32'h14,35,0,2);
        host_write(32'h18,tag);
    endtask
    task automatic finish_job(input logic fault, input logic [31:0] count, input logic also_done=0);
        @(negedge clk); core_busy=0; core_completed_tasks=count; core_error_code=fault ? 8'd5 : 8'd0;
        core_error=fault; core_done=!fault || also_done;
        @(negedge clk); core_done=0;
        repeat(2) @(negedge clk);
        if (!irq) $fatal(1,"completion event lost");
    endtask
    task automatic open_read(input logic [31:0] addr);
        @(negedge clk); s_axil_araddr=addr; s_axil_arprot=0; s_axil_arvalid=1;
        do @(posedge clk); while (!s_axil_arready);
        @(negedge clk); s_axil_arvalid=0;
        wait(s_axil_rvalid);
    endtask
    logic [31:0] read_only [0:5];
    logic [31:0] invalid_addresses [0:4];
    initial begin
        read_only[0]=0; read_only[1]=4; read_only[2]=8;
        read_only[3]=32'h1c; read_only[4]=32'h20; read_only[5]=32'h24;
        invalid_addresses[0]=32'h28; invalid_addresses[1]=32'h11;
        invalid_addresses[2]=32'h10000010; invalid_addresses[3]=32'hfffffffc; invalid_addresses[4]=1;
        reset_all();
        host_expect(0,32'h524b4557); host_expect(4,32'h00010000);
        host_expect(32'h1c,0); host_expect(32'h20,0); host_expect(32'h24,0);
        host_write(32'h0c,1,2); host_write(32'h0c,2,2);
        host_write(32'h10,32'h100e0000,0,1); host_write(32'h0c,1,2);
        host_write(32'h14,35,0,2); host_write(32'h0c,1,2);
        host_write(32'h18,32'hdeadbeef); host_expect(8,32'h711);
        memory_ready=0; host_expect(8,32'h700); host_write(32'h0c,1,2);
        memory_ready=1;
        core_busy=1; host_write(32'h10,0,2); host_write(32'h0c,1,2); core_busy=0;
        for (integer mask=0; mask<15; mask=mask+1) begin
            host_write(32'h10,32'hbad0bad0,2,mask%3,4'(mask));
            host_expect(32'h10,32'h100e0000);
        end
        for (integer prot=1; prot<8; prot=prot+1) begin
            host_write(32'h14,32'hbad0bad0,2,prot%3,4'hf,3'(prot));
            host_expect(0,0,2,3'(prot));
        end
        host_expect(32'h14,35);
        for (integer i=0; i<6; i=i+1) host_write(read_only[i],32'hffffffff,2,i%3);
        for (integer i=0; i<5; i=i+1) begin
            host_write(invalid_addresses[i],32'hffffffff,3,i%3);
            host_expect(invalid_addresses[i],0,3);
        end
        host_expect(32'h0c,0,2);
        host_write(32'h0c,0,2); host_write(32'h0c,3,2); host_write(32'h0c,4,2); host_write(32'h0c,32'hffffffff,2);
        if (launches!=0 || irq) $fatal(1,"rejected control access launched a job");

        // Read progress while a write is missing either half.
        host_aw(32'h18); repeat(4) @(negedge clk);
        if (s_axil_bvalid) $fatal(1,"B without W");
        host_expect(0,32'h524b4557); host_w(32'habcdef01); host_b();
        host_w(36); repeat(4) @(negedge clk);
        if (s_axil_bvalid) $fatal(1,"B without AW");
        host_expect(0,32'h524b4557); host_aw(32'h14); host_b();
        // Read and write response channels have independent backpressure.
        fork host_aw(32'h10); host_w(32'h100e0010); join
        wait(s_axil_bvalid); host_expect(32'h10,32'h100e0010); host_b();
        open_read(32'h10);
        host_write(32'h10,32'h100e0000);
        if (!s_axil_rvalid || s_axil_rdata!==32'h100e0010) $fatal(1,"read snapshot changed after write");
        s_axil_rready=1; @(negedge clk); s_axil_rready=0;
        descriptor(32'hdeadbeef);

        // Doorbell captures one job even if launch is subsequently stalled.
        fork host_aw(32'h0c); host_w(1); join
        wait(s_axil_bvalid); @(negedge clk); core_start_ready=0; memory_ready=0;
        host_b();
        host_write(32'h10,32'hbad0bad0,2); host_write(32'h14,1,2); host_write(32'h18,1,2);
        host_write(32'h0c,1,2); host_write(32'h0c,2,2);
        if (!core_start_valid || launches!=0) $fatal(1,"pending launch cancelled or duplicated");
        core_start_ready=1; wait(launches==1); @(negedge clk); core_busy=1;
        if (launched_address!=32'h100e0000 || launched_amount!=35) $fatal(1,"descriptor was rewritten");
        finish_job(0,2);
        host_expect(8,32'h704); host_expect(32'h1c,32'hdeadbeef); host_expect(32'h20,2); host_expect(32'h24,0);
        core_completed_tasks=99;
        host_write(32'h10,0,2); host_write(32'h0c,1,2); host_expect(32'h20,2);
        open_read(8);
        host_write(32'h0c,2);
        if (irq || !s_axil_rvalid || s_axil_rdata!==32'h704) $fatal(1,"ACK damaged a pending read snapshot");
        s_axil_rready=1; @(negedge clk); s_axil_rready=0;
        memory_ready=1;
        host_expect(8,32'h10); host_expect(32'h10,0); host_expect(32'h14,0); host_expect(32'h18,0);
        host_write(32'h0c,1,2);

        // A result can arrive before the host consumes the doorbell B response.
        descriptor(32'h2222);
        fork host_aw(32'h0c); host_w(1); join
        wait(launches==2); @(negedge clk); core_busy=1;
        finish_job(0,3);
        if (!s_axil_bvalid) $fatal(1,"doorbell B vanished");
        host_expect(32'h1c,32'h2222); host_expect(32'h20,3); host_b();
        host_write(32'h0c,2);
        if (launches!=2) $fatal(1,"doorbell replayed while B stalled");

        descriptor(32'h3333); host_write(32'h0c,1); core_busy=1;
        finish_job(1,1,1);
        host_expect(8,32'h73c); host_expect(32'h1c,32'h3333); host_expect(32'h20,1); host_expect(32'h24,5);
        host_write(32'h0c,2,2); host_write(32'h0c,1,2); host_write(32'h18,0,2);
        if (!irq || launches!=3) $fatal(1,"fault result cleared without joint reset");

        for (integer phase=0; phase<7; phase=phase+1) begin
            reset_all(); descriptor(32'(phase));
            case (phase)
                0: host_aw(32'h0c);
                1: host_w(1);
                2: begin
                    fork host_aw(32'h0c); host_w(1); join
                    wait(s_axil_bvalid); @(negedge clk); core_start_ready=0;
                end
                3: begin host_write(32'h0c,1); core_busy=1; end
                4: begin fork host_aw(32'h18); host_w(99); join wait(s_axil_bvalid); end
                5: open_read(0);
                6: begin host_write(32'h0c,1); finish_job(0,1); end
                default: $fatal(1,"invalid test phase");
            endcase
            repeat(4) @(negedge clk);
            reset_all(); descriptor(32'h5555); host_write(32'h0c,1);
            finish_job(0,1); host_expect(32'h1c,32'h5555); host_expect(32'h20,1);
            host_write(32'h0c,2);
            if (launches!=1 || irq) $fatal(1,"reset/restart failed");
        end
        $display("PASS job_control independent channels, explicit access errors, descriptor ownership, sticky results/IRQ, launch stalls and seven reset phases");
        $finish;
    end
    initial begin #1000000; $fatal(1,"job control global timeout"); end
endmodule
