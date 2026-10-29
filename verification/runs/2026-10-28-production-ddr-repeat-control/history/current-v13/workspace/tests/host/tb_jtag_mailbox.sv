`timescale 1ns/1ps
module tb_jtag_mailbox;
    logic clk;
    initial clk=0;
    always #10 clk=~clk;
    logic rst=1,tck=0,capture=0,shift=0,update=0,sel=0,tdi=0;
    wire tdo;
    logic req_valid,req_ready=0,rsp_valid=0;
    logic [603:0] req;
    logic [511:0] rsp_data=0;
    logic [7:0] rsp_status=0;
    logic [15:0] rsp_seq=0;
    otpu_jtag_mailbox dut(.*);
    `include "tests/host/mailbox_scan.svh"
    logic [639:0] frame,received;
    logic [603:0] expected;
    logic [511:0] payload;
    logic [15:0] seq;
    logic [31:0] random_state;
    integer accepted;
    initial begin
        accepted=0;random_state=32'h3588c640;
        repeat(8) @(negedge clk);rst=0;
        scan_frame(0,received);
        if (received!=={72'b0,32'h4f54504a,16'b0,8'b0,512'b0}) $fatal(1,"initial mailbox response wrong");
        for(integer n=0;n<8;n=n+1) begin
            for(integer i=0;i<16;i=i+1) begin
                random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
                payload[32*i +:32]=random_state;
            end
            seq=n==0 ? 16'hffff : 16'(n);
            expected={32'h4f54504a,seq,8'd4,4'hf,32'h10000040,payload};
            frame={36'b0,expected};scan_frame(frame,received);
            repeat(8) @(negedge clk);
            if (!req_valid || req!==expected) $fatal(1,"CDC request mismatch");
            // Polling while SYS is stalled must neither overwrite nor duplicate it.
            scan_frame(0,received);
            if (!req_valid || req!==expected) $fatal(1,"request changed under backpressure");
            req_ready=1;@(negedge clk);req_ready=0;accepted=accepted+1;
            if (req_valid) $fatal(1,"request was not consumed");
            rsp_data=~payload;rsp_status=8'(n);rsp_seq=seq;rsp_valid=1;
            @(negedge clk);rsp_valid=0;
            // First capture may be the old completion: toggle sync needs TCK edges.
            scan_frame(0,received);scan_frame(0,received);
            if (received!=={72'b0,32'h4f54504a,seq,8'(n),~payload}) $fatal(1,"CDC response mismatch");
            repeat(5) @(negedge clk);
            if (req_valid) $fatal(1,"poll created a request");
        end
        // Wrong magic and opcode-zero polls are discarded, per the donor ABI.
        frame=0;frame[603:572]=32'hdeadbeef;frame[555:548]=1;scan_frame(frame,received);
        frame=0;frame[603:572]=32'h4f54504a;scan_frame(frame,received);
        repeat(8) @(negedge clk);if(req_valid) $fatal(1,"invalid poll dispatched");
        // Runtime SYS reset is not TAP reinitialization: retained completion is observable.
        rst=1;repeat(5) @(negedge clk);rst=0;scan_frame(0,received);
        if (req_valid || received[535:520]!==16'd7 || received[567:536]!==32'h4f54504a) $fatal(1,"reset retention contract changed");
        if (accepted!=8) $fatal(1,"wrong coverage");
        $display("PASS jtag_mailbox 8 asynchronous 604-bit requests and 568-bit responses; seed=3588c640, stalls, polls, sequence wrap, reset retention");
        $finish;
    end
    initial begin #10000000;$fatal(1,"mailbox test timeout");end
endmodule
