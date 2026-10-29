`timescale 1ns/1ps
module tb_ew;
    localparam logic [31:0] BASE=32'h10000000;
    localparam integer WORDS=524288;
    logic clk;
    initial clk=0;
    always #5 clk=~clk;
    logic rst_n=0,cmd_valid=0,cmd_ready,busy,done,error;
    logic [63:0] cmd_data=0;
    logic [7:0] error_code;
    logic mem_req_valid,mem_req_ready,mem_req_write,mem_rsp_valid,mem_rsp_ready,mem_rsp_error;
    logic [31:0] mem_req_addr;
    logic [15:0] mem_req_wdata,mem_rsp_rdata;
    logic [15:0] memory [0:WORDS-1];
    `include "tests/memory_check.svh"
    integer expected_checks;
    logic [63:0] commands [0:1023];
    logic pending, pending_write;
    logic [31:0] pending_addr;
    logic [15:0] pending_data;
    logic [31:0] lfsr;
    integer delay_count,cycles,completed,transactions;
    integer ncmd, expected_error, expected_done, bus_error_at=0,drop_reply=0;
    integer stall_request=0, expected_transactions;
    logic held;
    logic [48:0] held_request;
    string prefix;
    rk_ew_core #(.TIMEOUT_CYCLES(128)) dut(.*);
    assign mem_req_ready = rst_n && stall_request==0 && !pending && !mem_rsp_valid && (lfsr[0] || lfsr[3]);
    always @(posedge clk) begin
        if (!rst_n) begin
            pending<=0; mem_rsp_valid<=0; mem_rsp_error<=0;
            mem_rsp_rdata<=0; delay_count<=0;
            transactions<=0; cycles<=0; completed<=0; held<=0;
            lfsr<=32'h35881234;
        end else begin
            cycles<=cycles+1;
            lfsr<={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
            if (cycles>2000000) $fatal(1,"global timeout");
            if (done) completed<=completed+1;
            if (done && error) $fatal(1,"done and error both asserted");
            if ((mem_req_valid || mem_rsp_ready) && !busy) $fatal(1,"memory activity outside busy");
            if (held && !error && (!mem_req_valid ||
                {mem_req_write,mem_req_addr,mem_req_wdata} !== held_request))
                $fatal(1,"memory request changed under backpressure");
            held<=mem_req_valid && !mem_req_ready;
            held_request<={mem_req_write,mem_req_addr,mem_req_wdata};
            if (mem_rsp_valid && mem_rsp_ready) mem_rsp_valid<=0;
            if (mem_req_valid && mem_req_ready) begin
                pending<=1; pending_write<=mem_req_write;
                pending_addr<=mem_req_addr; pending_data<=mem_req_wdata;
                delay_count<=int'(lfsr[6:4]); transactions<=transactions+1;
            end
            if (pending && drop_reply==0) begin
                if (delay_count!=0) delay_count<=delay_count-1;
                else begin
                    pending<=0; mem_rsp_valid<=1;
                    if ((bus_error_at!=0 && transactions==bus_error_at) ||
                        pending_addr<BASE || ((pending_addr-BASE)>>1)>=WORDS || pending_addr[0]) begin
                        mem_rsp_error<=1; mem_rsp_rdata<=0;
                    end else begin
                        mem_rsp_error<=0;
                        if (pending_write) begin
                            memory[(pending_addr-BASE)>>1]<=pending_data;
                            mem_rsp_rdata<=0;
                        end else mem_rsp_rdata<=memory[(pending_addr-BASE)>>1];
                    end
                end
            end
        end
    end
    initial begin
        if (!$value$plusargs("NCHECKS=%d",expected_checks)) $fatal(1,"missing NCHECKS");
        if (!$value$plusargs("CASE=%s",prefix)) $fatal(1,"missing CASE");
        if (!$value$plusargs("NCMD=%d",ncmd)) $fatal(1,"missing NCMD");
        if (!$value$plusargs("ECODE=%d",expected_error)) expected_error=0;
        if (!$value$plusargs("NDONE=%d",expected_done)) expected_done=1;
        if (!$value$plusargs("BUS_ERROR_AT=%d",bus_error_at)) bus_error_at=0;
        if (!$value$plusargs("DROP=%d",drop_reply)) drop_reply=0;
        if (!$value$plusargs("STALL_REQUEST=%d",stall_request)) stall_request=0;
        if (!$value$plusargs("NTRANS=%d",expected_transactions)) $fatal(1,"missing NTRANS");
        if (ncmd<1 || ncmd>1024) $fatal(1,"invalid NCMD");
        $readmemh({prefix,"/commands.hex"},commands,0,ncmd-1);
        $readmemh({prefix,"/input.hex"},memory);
        repeat(4) @(negedge clk);
        rst_n=1;
        for(integer i=0;i<ncmd && !error;i=i+1) begin
            @(negedge clk);
            cmd_valid=1; cmd_data=commands[i];
            do @(posedge clk); while(!cmd_ready && !error);
            @(negedge clk);
            cmd_valid=0;
        end
        wait(error || completed==expected_done && expected_error==0);
        repeat(3) @(negedge clk);
        if (expected_error!=0) begin
            if (!error || int'(error_code)!=expected_error) $fatal(1,"wrong error: got %0d wanted %0d",error_code,expected_error);
            if (cmd_ready) $fatal(1,"fault must stop command acceptance until reset");
        end else if (error) $fatal(1,"unexpected error %0d",error_code);
        if (completed!=expected_done) $fatal(1,"completion count %0d wanted %0d",completed,expected_done);
        if (transactions!=expected_transactions)
            $fatal(1,"transaction count %0d wanted %0d",transactions,expected_transactions);
        verify_memory({prefix,"/check.txt"},"",expected_checks,expected_error!=0);
        $display("PASS %s cycles=%0d transactions=%0d completed=%0d expected_error=%0d",prefix,cycles,transactions,completed,expected_error);
        $finish;
    end
endmodule
