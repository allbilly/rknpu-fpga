// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_array_startup #(parameter bit LED_ACTIVE_LOW=1'b0);
    // Verification-only clock/counters use ordered blocking assignments.
    // No warning in a DUT or donor file is disabled here.
    /* verilator lint_off BLKSEQ */
    logic clk, clock_running;
    wire [2:0] leds;
    initial begin clk=0;clock_running=1;end
    always begin #10;if (clock_running) clk=~clk;end
    ypcb_cmac_array_startup_top #(.LED_ACTIVE_LOW(LED_ACTIVE_LOW)) dut (
        .SYS_CLK(clk), .led_3bits_tri_o(leds)
    );
    logic [47:0] outputs[0:63];
    logic [47:0] operands[0:6527];
    integer mode, initializations, checks, command_reads, operand_reads, writes, acks, frames, cycles;
    integer successes, faults, input_edges;
    time previous_edge;
    string outcome;

    always @(posedge clk) begin
        if (input_edges!=0 && $time-previous_edge!=64'd20) $fatal(1,"input clock is not 50 MHz");
        previous_edge=$time;input_edges=input_edges+1;
    end
    always @(posedge clk or negedge dut.reset_n) begin
        if (!dut.reset_n) begin
            initializations=0;checks=0;command_reads=0;operand_reads=0;
            writes=0;acks=0;frames=0;cycles=0;
        end else begin
            cycles=cycles+1;
            if (dut.demo.host_valid&&dut.demo.core_busy) $fatal(1,"host/engine ownership collision");
            if (dut.demo.host_valid&&dut.demo.host_ready) begin
                if (dut.demo.host_write) begin
                    if (initializations>=4096 || dut.demo.index!==12'(initializations)) $fatal(1,"initialization order");
                    initializations=initializations+1;
                end else begin
                    if (checks>=4096 || dut.demo.index!==12'(checks)) $fatal(1,"readback order");
                    checks=checks+1;
                end
            end
            if (dut.demo.mem_req_valid&&dut.demo.mem_req_ready) begin
                if (initializations!=4096) $fatal(1,"engine began before full BRAM initialization");
                if (dut.demo.mem_req_write) begin
                    if (writes>=64 || {dut.demo.mem_req_addr,dut.demo.mem_req_wdata}!==outputs[writes])
                        $fatal(1,"numerical/address mismatch output=%0d",writes);
                    writes=writes+1;
                end else if (dut.demo.mem_req_addr>=32'h100e0000) begin
                    if (command_reads>=196 || dut.demo.mem_req_addr!==32'h100e0000+32'(command_reads*2))
                        $fatal(1,"command read order");
                    command_reads=command_reads+1;
                end else begin
                    if (command_reads!=196 || operand_reads>=6528) $fatal(1,"operand read count/ownership");
                    if (dut.demo.mem_req_addr!==operands[operand_reads][47:16]) $fatal(1,"operand packing/order");
                    operand_reads=operand_reads+1;
                end
            end
            if (dut.demo.engine.core.datapath.in_valid&&dut.demo.engine.core.datapath.in_ready) begin
                if (frames>=12) $fatal(1,"extra accepted C32/K16 frame");
                frames=frames+1;
            end
            if (dut.demo.unused_ack) begin
                acks=acks+1;
                if (acks>writes) $fatal(1,"output acknowledgment without its write");
            end
            if (dut.demo.pass&&dut.demo.fail) $fatal(1,"simultaneous pass and fail");
        end
    end

    task automatic success;
        wait(dut.demo.pass||dut.demo.fail);@(negedge clk);
        if (dut.demo.pass!==1 || dut.demo.fail!==0 || dut.demo.error_code!==0 ||
            leds!==(LED_ACTIVE_LOW ? 3'b110 : 3'b001)) $fatal(1,"startup board failed code=%h",dut.demo.error_code);
        if (initializations!=4096 || checks!=4096 || command_reads!=196 || operand_reads!=6528 ||
            writes!=64 || acks!=64 || frames!=12)
            $fatal(1,"incomplete full board coverage init=%0d checks=%0d cmd=%0d reads=%0d writes=%0d acks=%0d frames=%0d",
                   initializations,checks,command_reads,operand_reads,writes,acks,frames);
        repeat(20) begin
            @(negedge clk);
            if (dut.demo.pass!==1 || dut.demo.fail!==0 || dut.demo.host_valid || dut.demo.mem_req_valid)
                $fatal(1,"successful result is not sticky/quiescent");
        end
        successes=successes+1;outcome="success";
    endtask
    task automatic failure(input logic [7:0] expected_code);
        wait(dut.demo.pass||dut.demo.fail);@(negedge clk);
        if (dut.demo.fail!==1 || dut.demo.pass!==0 || dut.demo.error_code!==expected_code ||
            leds!==(LED_ACTIVE_LOW ? 3'b101 : 3'b010)) $fatal(1,"wrong fault code=%h expected=%h",dut.demo.error_code,expected_code);
        repeat(20) begin
            @(negedge clk);
            if (dut.demo.fail!==1 || dut.demo.pass!==0 || dut.demo.host_valid || dut.demo.mem_req_valid)
                $fatal(1,"fault result is not sticky/quiescent");
        end
        faults=faults+1;outcome="fault";
    endtask
    task automatic abort_configuration_model;
        integer saved_init,saved_checks,saved_commands,saved_operands,saved_writes,saved_acks,saved_frames,saved_cycles;
        @(negedge clk);
        if (dut.demo.pass!==0 || dut.demo.fail!==0 || dut.demo.core_done!==0 || dut.demo.error_code!==0)
            $fatal(1,"abort reached a completed/faulted board");
        if (initializations!=4096) $fatal(1,"abort occurred before complete initialization");
        case (mode)
            10: if (command_reads<20 || command_reads>=196 || operand_reads!=0 || writes!=0 || acks!=0 || frames!=0 || checks!=0)
                    $fatal(1,"fetch abort did not stop in the requested partial phase");
            11: if (command_reads!=196 || frames!=1 || checks!=0 || writes!=0 || acks!=0)
                    $fatal(1,"frame abort did not follow exactly one accepted partial-reduction frame");
            12: if (checks<20 || checks>=4096 || command_reads!=196 || operand_reads!=6528 || writes!=64 || acks!=64 || frames!=12)
                    $fatal(1,"readback abort did not stop before the complete RAM check");
            default:$fatal(1,"invalid abort phase");
        endcase
        // Stop only the test clock/process. This neither drives reset nor
        // claims physical reconfiguration or runtime fault recovery. The runner
        // must perform MODE=0 in a fresh process using this same compiled image.
        saved_init=initializations;saved_checks=checks;saved_commands=command_reads;saved_operands=operand_reads;
        saved_writes=writes;saved_acks=acks;saved_frames=frames;saved_cycles=cycles;
        clock_running=0;
        #40;
        if (clk!==0 || initializations!=saved_init || checks!=saved_checks || command_reads!=saved_commands ||
            operand_reads!=saved_operands || writes!=saved_writes || acks!=saved_acks || frames!=saved_frames || cycles!=saved_cycles ||
            dut.demo.pass!==0 || dut.demo.fail!==0) $fatal(1,"configuration-model clock stop did not preserve the partial state");
        outcome="abort";
    endtask

    initial begin
        input_edges=0;previous_edge=0;successes=0;faults=0;outcome="unset";
        initializations=0;checks=0;command_reads=0;operand_reads=0;writes=0;acks=0;frames=0;cycles=0;
        if (!$value$plusargs("MODE=%d",mode)) $fatal(1,"missing mode");
        if ($bits(dut.demo.engine.core.frame_data)!=512 || $bits(dut.demo.engine.core.frame_weight)!=8192 ||
            $bits(dut.demo.engine.core.frame_data_mask)!=32 || $bits(dut.demo.engine.core.frame_weight_mask)!=512 ||
            dut.demo.engine.core.datapath.arithmetic.ATOMIC_C!=32 || dut.demo.engine.core.datapath.arithmetic.ATOMIC_K!=16)
            $fatal(1,"full C32/K16 frame geometry was changed");
        $readmemh("tests/cmac/array_data/writes.hex",outputs,0,63);
        $readmemh("tests/cmac/array_data/reads.hex",operands,0,6527);
        #1;
        if (dut.reset_n!==0) $fatal(1,"startup reset not initially asserted");
        for (integer edge_index=1;edge_index<=64;edge_index=edge_index+1) begin
            @(posedge clk);#1;
            if (dut.reset_n!==0 || leds!==(LED_ACTIVE_LOW ? 3'b111 : 3'b000) ||
                dut.demo.host_valid!==0 || dut.demo.host_rsp_valid!==0 || dut.demo.host_rsp_ready!==0 ||
                dut.demo.mem_req_valid!==0 || dut.demo.mem_rsp_ready!==0 || dut.demo.core_busy!==0 ||
                dut.demo.engine.start_valid!==0 || initializations!=0 || command_reads!=0 || operand_reads!=0 || writes!=0 || frames!=0)
                $fatal(1,"early reset release or activity during the 64-edge hold");
        end
        @(posedge clk);#1;
        if (dut.reset_n!==1 || input_edges!=65) $fatal(1,"startup reset did not release on edge65");
        case (mode)
            0:success();
            1:begin
                wait(dut.demo.mem_rsp_valid);@(negedge clk);force dut.demo.mem_rsp_error=1'b1;
                failure(8'd5);release dut.demo.mem_rsp_error;
            end
            2:begin
                wait(dut.demo.state==8&&dut.demo.index==0);@(negedge clk);force dut.demo.host_rdata=16'hffff;
                failure(8'hfd);release dut.demo.host_rdata;
            end
            3:begin
                wait(operand_reads>=20);@(negedge clk);force dut.demo.watchdog=20'hfffff;
                failure(8'hfe);release dut.demo.watchdog;
            end
`ifdef __ICARUS__
            4:begin
                wait(dut.demo.state==8&&dut.demo.index==0);@(negedge clk);force dut.demo.host_rdata=16'hxxxx;
                failure(8'hfd);release dut.demo.host_rdata;
            end
`endif
            10:begin wait(command_reads>=20);abort_configuration_model();end
            11:begin wait(frames>=1);abort_configuration_model();end
            12:begin wait(checks>=20);abort_configuration_model();end
            default:$fatal(1,"unsupported startup mode");
        endcase
        if ((mode==0 && (successes!=1 || faults!=0)) ||
            (mode>=1 && mode<=4 && (successes!=0 || faults!=1)) ||
            (mode>=10 && (successes!=0 || faults!=0 || clock_running))) $fatal(1,"mode outcome coverage mismatch");
        $display("PASS full512_startup mode=%0d polarity=%0d outcome=%s error=%02h hold=64 release=65 init=%0d checks=%0d cmd_reads=%0d operand_reads=%0d writes=%0d acks=%0d frames=%0d cycles=%0d; configuration model only",
                 mode,LED_ACTIVE_LOW,outcome,dut.demo.error_code,initializations,checks,command_reads,operand_reads,writes,acks,frames,cycles);
        $finish;
    end
    initial begin #60000000;$fatal(1,"full C32/K16 startup simulation timeout");end
    /* verilator lint_on BLKSEQ */
endmodule
