`timescale 1ns/1ps
module tb_cmac_address;
    logic clk, rst_n = 0;
    initial clk = 0;
    always #5 clk = ~clk;
    logic config_valid = 0, config_ready;
    logic [31:0] config_rows = 0, config_input_channels = 0, config_output_channels = 0;
    logic [31:0] config_input_base = 0, config_weight_base = 0, config_output_base = 0;
    logic busy, walk_done, error, pair_valid, pair_ready = 0;
    logic [31:0] input_address, weight_address, output_address;
    logic [31:0] row_index, output_channel, input_channel;
    logic first_product, last_product, last_output;
    logic [31:0] rng = 32'h3588ca01;
    integer checked = 0, rejected = 0, walks = 0;
    rk_cmac_address dut(.*);

    task automatic reset_leaf;
        rst_n = 0; config_valid = 0; pair_ready = 0;
        repeat (3) @(negedge clk);
        if (busy !== 0 || error !== 0 || pair_valid !== 0 || walk_done !== 0)
            $fatal(1, "reset retained state");
        rst_n = 1;
        @(negedge clk);
        if (config_ready !== 1) $fatal(1, "not ready after reset");
    endtask

    task automatic stage(input logic [31:0] m, ai, ao, a, w, d);
        config_rows = m; config_input_channels = ai; config_output_channels = ao;
        config_input_base = a; config_weight_base = w; config_output_base = d;
        config_valid = 1;
        if (config_ready !== 1) $fatal(1, "config unexpectedly blocked");
        @(negedge clk);
        config_valid = 0;
    endtask

    task automatic walk(input integer m, ai, ao, input logic [31:0] a, w, d,
                        input integer stop_after);
        integer count, row_ref, oc_ref, ic_ref, total, last_stalls;
        logic [31:0] a_ref, w_ref, d_ref;
        count = 0; total = m*ai*ao; last_stalls = 0;
        stage(32'(m),32'(ai),32'(ao),a,w,d);
        while (count < total && (stop_after == 0 || count < stop_after)) begin
            row_ref = count / (ai*ao); oc_ref = (count / ai) % ao; ic_ref = count % ai;
            // Independent direct-index oracle, not the RTL's incremental recurrences.
            a_ref = a + 32'(2*(row_ref*ai+ic_ref));
            w_ref = w + 32'(2*((oc_ref/16)*(ai/32)*16*32+(ic_ref/32)*16*32+(oc_ref%16)*32+ic_ref%32));
            d_ref = d + 32'(2*(row_ref*ao*2+oc_ref+(oc_ref/16)*16));
            if (pair_valid !== 1 || busy !== 1 || error !== 0 || config_ready !== 0 || walk_done !== 0)
                $fatal(1, "bad active status at pair %0d", count);
            if (input_address !== a_ref || weight_address !== w_ref || output_address !== d_ref ||
                row_index !== 32'(row_ref) || output_channel !== 32'(oc_ref) || input_channel !== 32'(ic_ref) ||
                first_product !== (ic_ref==0) || last_product !== (ic_ref==ai-1) ||
                last_output !== (row_ref==m-1 && oc_ref==ao-1))
                $fatal(1, "address/tag mismatch pair %0d got %h/%h/%h expected %h/%h/%h",
                       count,input_address,weight_address,output_address,a_ref,w_ref,d_ref);
            rng = rng ^ (rng << 13); rng = rng ^ (rng >> 17); rng = rng ^ (rng << 5);
            pair_ready = (rng[1:0] != 0);
            if (count == total-1 && last_stalls < 3) begin
                pair_ready = 0; last_stalls = last_stalls + 1;
            end
            // Busy config changes cannot replace the captured descriptor or fault it.
            config_valid = 1; config_rows = 0; config_input_base = 32'hffffffff;
            if (pair_ready) begin count = count + 1; checked = checked + 1; end
            @(negedge clk);
        end
        config_valid = 0; pair_ready = 0;
        if (stop_after != 0) begin
            if (walk_done !== 0 || !busy) $fatal(1, "premature partial-walk completion");
            reset_leaf();
        end else begin
            if (walk_done !== 1 || busy !== 0 || error !== 0 || pair_valid !== 0 || config_ready !== 1)
                $fatal(1, "missing final walk completion");
            @(negedge clk);
            if (walk_done !== 0) $fatal(1, "completion is not a pulse");
            walks = walks + 1;
        end
    endtask

    task automatic reject(input logic [31:0] m, ai, ao, a, w, d);
        reset_leaf();
        stage(m,ai,ao,a,w,d);
        if (error !== 1 || busy !== 0 || pair_valid !== 0 || walk_done !== 0 || config_ready !== 0)
            $fatal(1,"invalid configuration admitted: %0d/%0d/%0d %h/%h/%h",m,ai,ao,a,w,d);
        config_rows=1; config_input_channels=32; config_output_channels=32;
        config_input_base=32'h10000000; config_weight_base=32'h20000000; config_output_base=32'h30000000;
        config_valid=1; pair_ready=1;
        repeat (4) @(negedge clk);
        if (error !== 1 || pair_valid !== 0 || config_ready !== 0) $fatal(1,"fault not sticky");
        rejected = rejected + 1;
    endtask

    initial begin
        reset_leaf();
        walk(8,32,32,32'h10010000,32'h10020000,32'h10040000,0);
        walk(2,32,32,32'h10010000,32'h10020000,32'h10040000,0);
        walk(2,64,32,32'h10010000,32'h10020000,32'h10040000,0);
        walk(2,96,32,32'h10010000,32'h10020000,32'h10040000,0);
        walk(1,128,64,32'h10010000,32'h10020000,32'h10040000,0);
        walk(3,96,96,32'h10010000,32'h10020000,32'h10040000,0);
        walk(1,4096,32,32'h10000000,32'h20000000,32'h30000000,0);
        walk(1,32,5632,32'h10000000,32'h20000000,32'h30000000,0);
        // Read-only inputs may alias; output must remain disjoint.
        walk(1,32,32,32'h10010000,32'h10010000,32'h10040000,0);
        // Full mapped output interval may end exactly at 2^32, without wrap.
        walk(1,32,32,32'h10010000,32'h10020000,32'hffffff80,0);
        walk(2,96,32,32'h10010000,32'h10020000,32'h10040000,17);
        walk(2,96,32,32'h10010000,32'h10020000,32'h10040000,0);
        reject(0,32,32,32'h10000000,32'h20000000,32'h30000000);
        reject(2048,32,32,32'h10000000,32'h20000000,32'h30000000);
        reject(1,0,32,32'h10000000,32'h20000000,32'h30000000);
        reject(1,31,32,32'h10000000,32'h20000000,32'h30000000);
        reject(1,33,32,32'h10000000,32'h20000000,32'h30000000);
        reject(1,4128,32,32'h10000000,32'h20000000,32'h30000000);
        reject(2,416,32,32'h10000000,32'h20000000,32'h30000000);
        reject(1,32,0,32'h10000000,32'h20000000,32'h30000000);
        reject(1,32,31,32'h10000000,32'h20000000,32'h30000000);
        reject(1,32,33,32'h10000000,32'h20000000,32'h30000000);
        reject(1,32,16384,32'h10000000,32'h20000000,32'h30000000);
        reject(427,384,32,32'h10000000,32'h20000000,32'h30000000);
        reject(1,384,480,32'h10000000,32'h20000000,32'h30000000);
        reject(1,32,32,32'h10000002,32'h20000000,32'h30000000);
        reject(1,32,32,32'h10000000,32'h20000002,32'h30000000);
        reject(1,32,32,32'h10000000,32'h20000000,32'h30000002);
        reject(1,32,32,32'hfffffff0,32'h20000000,32'h30000000);
        reject(1,32,32,32'h10000000,32'hfffffff0,32'h30000000);
        reject(1,32,32,32'h10000000,32'h20000000,32'hffffff90);
        reject(1,32,32,32'h10000000,32'h20000000,32'h10000000);
        reject(1,32,32,32'h10000000,32'h20000000,32'h20000010);
        reject(32'hffffffff,32'hffffffff,32'hffffffff,0,0,0);
`ifndef VERILATOR
        reject(32'hxxxxxxxx,32,32,32'h10000000,32'h20000000,32'h30000000);
        reject(1,32,32,32'hxxxxxxxx,32'h20000000,32'h30000000);
`endif
        reset_leaf();
        // Maximum input/weight capacity boundaries: admit then cancel after a
        // checked prefix. These are not claims of a full maximum-shape walk.
        walk(426,384,32,32'h10000000,32'h20000000,32'h30000000,35);
        walk(1,352,512,32'h10000000,32'h20000000,32'h30000000,35);
        $display("PASS CMAC address-only leaf: %0d transfers, %0d complete walks, %0d rejected configs; seed=3588ca01",checked,walks,rejected);
        $finish;
    end
    initial begin #10000000; $fatal(1,"CMAC address test timeout"); end
endmodule
