// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_cmac_product_front;
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic rst_n,cmd_valid,cmd_ready,downstream_busy,busy,address_done,operand_done,product_done,error;
    logic [63:0] cmd_data;
    logic [7:0] error_code;
    logic mem_req_valid,mem_req_ready,mem_rsp_valid,mem_rsp_ready,mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_rsp_rdata;
    logic product_valid,product_ready;
    logic [31:0] product_value,product_output_address,product_row,product_oc,product_ic;
    logic product_first,product_last,product_last_output;
    rk_cmac_product_front #(.TIMEOUT_CYCLES(32)) dut(.*);
    wire [162:0] product_bits={product_value,product_output_address,product_row,
                              product_oc,product_ic,product_first,product_last,product_last_output};
    string root_path,path;
    logic [63:0] commands[0:48];
    logic [15:0] input_mem[0:4095],weight_mem[0:8191];
    logic [31:0] expected_a[0:8191],expected_b[0:8191],expected_product[0:8191];
    logic [130:0] expected_tag[0:8191];
    logic [15:0] expected_input[0:8191],expected_weight[0:8191];
    logic [31:0] rng,held_address;
    logic [15:0] response_data;
    logic [162:0] held_product;
    logic response_error,slave_pending,checking,request_stalled,product_stalled;
    integer rows,ai,ao,total_pairs,requests,products,slave_count,response_delay;
    integer request_wait,response_wait,address_pulses,operand_pulses,product_pulses,final_stalls;
    integer sink_mode,fault_mode,fault_at,total_products,good_runs,fault_runs,reset_runs,x_runs;
    integer blocked_cycles,ownership_checks;
    // Modes: 1 bus fault, 2 request timeout, 3 response timeout, 4 unknown status.
    assign mem_req_ready=rst_n && !slave_pending && rng[2:0]!=0 && !(fault_mode==2 && slave_count+1==fault_at);
    assign mem_rsp_valid=rst_n && slave_pending && response_delay==0 && !(fault_mode==3 && slave_count==fault_at);
    assign mem_rsp_error=response_error;
    // Exactly forty final-product stalls: random ready applies to other
    // products only, so it cannot accidentally insert a forty-first cycle.
    assign product_ready=rst_n && sink_mode!=1 &&
                         (product_last && product_last_output ? final_stalls>=40 : sink_mode==2 || rng[5:3]!=0);
    function automatic logic [15:0] read_half(input logic [31:0] address);
        if (address>=32'h10010000 && address<32'h10010000+32'(rows*ai*2) && address[0]==0)
            return input_mem[(address-32'h10010000)>>1];
        if (address>=32'h10020000 && address<32'h10020000+32'(ao*ai*2) && address[0]==0)
            return weight_mem[(address-32'h10020000)>>1];
        $fatal(1,"unmapped product-front read %h",address);return 0;
    endfunction
    assign mem_rsp_rdata=response_data;
    // Ordinary behavioral RAM process, not a synthesizable always_ff assertion.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            slave_pending<=0;slave_count<=0;response_delay<=0;
            response_data<=0;response_error<=0;rng<=32'h3588ca05;
        end else begin
            rng<=rng*32'd1664525+32'd1013904223;
            if (mem_req_valid && mem_req_ready) begin
                if (slave_pending) $fatal(1,"multiple outstanding reads");
                slave_pending<=1;slave_count<=slave_count+1;response_data<=read_half(mem_req_addr);
                response_delay<=int'({29'b0,rng[8:6]});
                response_error<=fault_mode==1 && slave_count+1==fault_at;
`ifndef VERILATOR
                if (fault_mode==4 && slave_count+1==fault_at) response_error<=1'bx;
`endif
            end
            if (slave_pending) begin
                if (response_delay>0) response_delay<=response_delay-1;
                else if (mem_rsp_valid && mem_rsp_ready) slave_pending<=0;
            end
        end
    end
    task automatic tick;
        logic req_fire,out_fire,last_fire,pre_valid,pre_ready,pre_req,pre_req_ready,pre_rsp_ready,pre_rsp;
        logic [162:0] bits;
        logic [31:0] addr;
        @(posedge clk);
        req_fire=mem_req_valid && mem_req_ready;out_fire=product_valid && product_ready;
        last_fire=out_fire && product_last && product_last_output;
        pre_valid=product_valid;pre_ready=product_ready;bits=product_bits;
        pre_req=mem_req_valid;pre_req_ready=mem_req_ready;addr=mem_req_addr;
        pre_rsp_ready=mem_rsp_ready;pre_rsp=mem_rsp_valid;
        #1;
        if (checking && rst_n) begin
            if (request_stalled && (pre_req!==1 || addr!==held_address)) $fatal(1,"unstable read request");
            if (product_stalled && (pre_valid!==1 || bits!==held_product)) $fatal(1,"unstable product/tag");
            request_stalled=pre_req && !pre_req_ready && !error;
            product_stalled=pre_valid && !pre_ready && !error;
            held_address=addr;held_product=bits;
            if (pre_req && !pre_req_ready) request_wait=request_wait+1;else request_wait=0;
            if (pre_rsp_ready && !pre_rsp) response_wait=response_wait+1;else response_wait=0;
            if (req_fire) begin
                if (requests>=2*total_pairs) $fatal(1,"extra read");
                if (addr !== (requests%2==0 ? expected_a[requests/2] : expected_b[requests/2]))
                    $fatal(1,"read address/order mismatch at %0d",requests);
                if (read_half(addr) !== (requests%2==0 ? expected_input[requests/2] : expected_weight[requests/2]))
                    $fatal(1,"raw lane packing mismatch");
                requests=requests+1;
            end
            if (pre_valid) begin
                if (products>=total_pairs || bits!=={expected_product[products],expected_tag[products]})
                    $fatal(1,"product/tag mismatch at %0d got=%h expected=%h",products,bits,{expected_product[products],expected_tag[products]});
                if (requests<2*(products+1)) $fatal(1,"product before both operand reads");
                if (!pre_ready && expected_tag[products][1:0]==2'b11) final_stalls=final_stalls+1;
            end
            if (out_fire) begin products=products+1;total_products=total_products+1;end
            if (address_done) begin
                address_pulses=address_pulses+1;
                if (operand_done || product_done || !busy) $fatal(1,"address completion too late or ownership lost");
            end
            if (operand_done) begin
                operand_pulses=operand_pulses+1;
                if (requests!=2*total_pairs || product_done || !busy || cmd_ready)
                    $fatal(1,"operand completion lost product pipeline ownership");
            end
            if (product_done!==last_fire) $fatal(1,"early/late product completion");
            if (product_done) product_pulses=product_pulses+1;
            if (!error && requests>0 && products<total_pairs && (!busy || cmd_ready))
                $fatal(1,"command admitted while reader/product pipeline owns task");
            if (!error && operand_pulses==1 && products<total_pairs) ownership_checks=ownership_checks+1;
            if (error && error_code==8 && request_wait!=32 && response_wait!=32)
                $fatal(1,"timeout must be exactly 32 memory-stall cycles");
        end
    endtask
    task automatic reset_all;
        checking=0;
        @(negedge clk);rst_n=0;cmd_valid=0;cmd_data=0;downstream_busy=0;
        repeat(2) tick();
        if (error!==0 || busy!==0 || product_valid!==0 || mem_req_valid!==0 || product_done!==0)
            $fatal(1,"reset did not cancel work");
        requests=0;products=0;request_wait=0;response_wait=0;address_pulses=0;
        operand_pulses=0;product_pulses=0;final_stalls=0;request_stalled=0;product_stalled=0;
        @(negedge clk);rst_n=1;tick();checking=1;
    endtask
    task automatic open_case(input string name,input integer m,input integer n_in,input integer n_out);
        integer fd;
        logic [31:0] a,b,d,r,o,i;
        logic [15:0] av,bv;
        logic [2:0] flags;
        rows=m;ai=n_in;ao=n_out;total_pairs=m*n_in*n_out;
        path={root_path,"/",name,"/commands.hex"};$readmemh(path,commands);
        path={root_path,"/",name,"/input.hex"};$readmemh(path,input_mem,0,rows*ai-1);
        path={root_path,"/",name,"/weight.hex"};$readmemh(path,weight_mem,0,ao*ai-1);
        path={root_path,"/",name,"/products.hex"};$readmemh(path,expected_product,0,total_pairs-1);
        path={root_path,"/",name,"/expected.txt"};fd=$fopen(path,"r");
        if (fd==0) $fatal(1,"missing expected file");
        for (integer j=0;j<total_pairs;j=j+1) begin
            if ($fscanf(fd,"%h %h %h %h %h %h %h %h %h",a,b,d,r,o,i,av,bv,flags)!=9) $fatal(1,"short oracle");
            expected_a[j]=a;expected_b[j]=b;expected_tag[j]={d,r,o,i,flags};
            expected_input[j]=av;expected_weight[j]=bv;
        end
        $fclose(fd);
    endtask
    task automatic submit;
        for (integer w=0;w<49;w=w+1) begin
            @(negedge clk);cmd_valid=1;cmd_data=commands[w];
            if (cmd_ready!==1) $fatal(1,"command blocked at %0d",w);
            tick();
        end
        @(negedge clk);cmd_valid=0;
    endtask
    task automatic finish_good(input logic retain_owner);
        while (!error && product_pulses==0) tick();
        if (error || products!=total_pairs || requests!=2*total_pairs || address_pulses!=1 || operand_pulses!=1 || final_stalls!=40)
            $fatal(1,"stream failure products=%0d requests=%0d code=%0d address=%0d operand=%0d final_stalls=%0d",products,requests,error_code,address_pulses,operand_pulses,final_stalls);
        repeat(4) begin
            tick();
            if (product_valid || mem_req_valid || product_done || busy!==retain_owner || cmd_ready!==!retain_owner)
                $fatal(1,"post-product ownership or extra output");
        end
        @(negedge clk);downstream_busy=0;tick();
        if (busy!==0 || cmd_ready!==1) $fatal(1,"ownership release");
        good_runs=good_runs+1;
    endtask
    task automatic good(input string name,input integer m,input integer n_in,input integer n_out,input logic retain_owner);
        fault_mode=0;fault_at=0;sink_mode=0;reset_all();open_case(name,m,n_in,n_out);submit();
        downstream_busy=retain_owner;finish_good(retain_owner);
    endtask
    task automatic fault(input integer mode,input integer at_request,input logic [7:0] code,input logic fill_pipeline);
        fault_mode=mode;fault_at=at_request;sink_mode=fill_pipeline ? 1 : 0;
        reset_all();open_case("m2_n17_k31",2,32,32);submit();
        while (!error && product_pulses==0) tick();
        if (error!==1 || error_code!==code || product_pulses!=0 || (fill_pipeline && products!=0))
            $fatal(1,"fault expectation mode=%0d at=%0d",mode,at_request);
        if (fill_pipeline && !product_stalled && held_product!=={expected_product[0],expected_tag[0]})
            $fatal(1,"fault did not exercise buffered product");
        checking=0;
        @(negedge clk);sink_mode=2;cmd_valid=1;cmd_data=commands[0];
        repeat(12) begin
            tick();
            if (!error || error_code!==code || product_valid || product_done || cmd_ready || mem_req_valid || mem_rsp_ready)
                $fatal(1,"fault leaked buffered product or admitted work");
        end
        fault_runs=fault_runs+1;
    endtask
    initial begin
        rst_n=0;cmd_valid=0;cmd_data=0;downstream_busy=0;checking=0;
        rows=1;ai=32;ao=32;sink_mode=0;fault_mode=0;fault_at=0;final_stalls=0;
        total_products=0;good_runs=0;fault_runs=0;reset_runs=0;x_runs=0;ownership_checks=0;blocked_cycles=0;
        if (!$value$plusargs("ROOT=%s",root_path)) $fatal(1,"missing ROOT");
        good("m1_n8_k7",8,32,32,0);good("m1_n8_k8",8,32,32,0);good("m1_n8_k9",8,32,32,1);
        good("m2_n17_k31",2,32,32,0);good("m2_n17_k32",2,32,32,1);
        good("m2_n17_k33",2,64,32,0);good("m2_n17_k65",2,96,32,1);
        // No reset between complete command lists; no stale tag/profile reuse.
        checking=0;requests=0;products=0;address_pulses=0;operand_pulses=0;product_pulses=0;final_stalls=0;
        open_case("m2_n17_k31",2,32,32);checking=1;submit();finish_good(0);
        fault(1,1,5,0);fault(1,2,5,0);fault(1,4096,5,0);
        fault(1,7,5,1);fault(1,8,5,1);
        fault(2,1,8,0);fault(2,2,8,0);fault(3,1,8,0);fault(3,2,8,0);
        fault(2,7,8,1);fault(3,8,8,1);
`ifndef VERILATOR
        fault(4,7,5,1);fault(4,8,5,1);x_runs=2;
`endif
        // Public-port reset with 1, 2, 3 buffered products and a blocked fourth
        // operand. No internal forces or hierarchical state writes.
        for (integer count=1;count<=3;count=count+1) begin
            fault_mode=0;fault_at=0;sink_mode=1;reset_all();open_case("m2_n17_k31",2,32,32);submit();
            while (requests<2*count+1 || !product_valid) tick();
            if (count==3) begin
                while (requests<8) tick();
                repeat(80) begin
                    tick();blocked_cycles=blocked_cycles+1;
                    if (error || requests!=8 || cmd_ready || !busy) $fatal(1,"full product path failed to backpressure without timeout");
                end
            end
            if (products!=0 || product_pulses!=0) $fatal(1,"cancelled prefix consumed");
            reset_runs=reset_runs+1;good("m2_n17_k31",2,32,32,0);
        end
        // Also drain the same full condition without reset, checking every tag.
        fault_mode=0;fault_at=0;sink_mode=1;reset_all();open_case("m2_n17_k31",2,32,32);submit();
        while (requests<8 || !product_valid) tick();
        repeat(80) tick();
        if (error || requests!=8 || products!=0) $fatal(1,"full-pipeline drain setup");
        @(negedge clk);sink_mode=0;finish_good(0);
        // Explicit rejection remains at the raw command boundary.
        fault_mode=0;fault_at=0;sink_mode=0;reset_all();open_case("m2_n17_k31",2,32,32);
        @(negedge clk);cmd_valid=1;cmd_data=commands[0]^(64'd1<<16);tick();
        if (!error || error_code!=2 || requests!=0 || product_valid) $fatal(1,"invalid profile reached products");
        good("m2_n17_k31",2,32,32,0);
        @(negedge clk);cmd_valid=1;cmd_data=commands[48];tick();
        if (!error || error_code!=3 || mem_req_valid) $fatal(1,"stale profile accepted");
        if (ownership_checks<40 || blocked_cycles!=80) $fatal(1,"missing ownership/backpressure coverage");
        $display("PASS raw CMAC product front good_runs=%0d fault_runs=%0d reset_cases=%0d x_runs=%0d checked_products=%0d blocked_cycles=%0d seed=3588ca05; no accumulated GEMM",good_runs,fault_runs,reset_runs,x_runs,total_products,blocked_cycles);
        $finish;
    end
    initial begin #30000000;$fatal(1,"product front HDL timeout");end
endmodule
