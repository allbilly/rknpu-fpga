// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_conv_array_core;
    logic clk=0, rst_n=0, cmd_valid=0, cmd_last=0;
    logic [63:0] cmd_data=0;
    wire cmd_ready, busy, acknowledged, frame_done, done, error;
    wire [7:0] error_code;
    wire mem_req_valid, mem_req_ready, mem_req_write, mem_rsp_valid, mem_rsp_ready, mem_rsp_error;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata, mem_rsp_rdata;
    logic [63:0] commands[0:53];
    logic [15:0] input_memory[0:399], weight_memory[0:127];
    logic [15:0] output_memory[0:799], captured_output[0:799], expected[0:199];
    logic pending, pending_write, pending_error;
    logic [31:0] pending_address;
    logic [15:0] pending_data;
    logic [7:0] delay_left;
    logic [31:0] rng;
    logic request_stalled, request_hold_write;
    logic [31:0] request_hold_address;
    logic [15:0] request_hold_data;
    logic response_stalled, response_hold_error;
    logic [15:0] response_hold_data;
    integer mode, report_mode, command_count, read_requests, read_responses;
    integer weight_reads, input_reads, write_requests, write_responses;
    integer acknowledgments, frame_acks, done_count, observed_frames;
    integer age, index_value;
    string fixture;

    always #5 clk=~clk;

    rk_conv_array_core #(.TIMEOUT_CYCLES(32)) dut(.*);

    assign mem_req_ready = rst_n && !pending && rng[2:0] != 0 &&
                           !(mode>=23 && mode<=25) && mode!=30;
    assign mem_rsp_valid = rst_n && pending && delay_left == 0 &&
                           mode!=10 && mode!=29 && !(mode==28 && pending_write);
    assign mem_rsp_rdata = pending_data;
    assign mem_rsp_error = pending_error;

    // Assert the master/adapter ready-valid stability contract under stalls.
    // Fault cancellation may withdraw the current transaction.
    always @(posedge clk or negedge rst_n) begin : bus_stability_checks
        if (!rst_n) begin
            request_stalled<=0; request_hold_write<=0;
            request_hold_address<=0; request_hold_data<=0;
            response_stalled<=0; response_hold_error<=0; response_hold_data<=0;
        end else begin
            if (request_stalled && !error &&
                (!mem_req_valid || mem_req_write!==request_hold_write ||
                 mem_req_addr!==request_hold_address || mem_req_wdata!==request_hold_data))
                $fatal(1,"memory request changed while backpressured");
            request_stalled<=mem_req_valid && !mem_req_ready;
            if (mem_req_valid && !mem_req_ready) begin
                request_hold_write<=mem_req_write;
                request_hold_address<=mem_req_addr;
                request_hold_data<=mem_req_wdata;
            end

            if (response_stalled && !error &&
                (!mem_rsp_valid || mem_rsp_rdata!==response_hold_data ||
                 mem_rsp_error!==response_hold_error))
                $fatal(1,"memory response changed while backpressured");
            response_stalled<=mem_rsp_valid && !mem_rsp_ready;
            if (mem_rsp_valid && !mem_rsp_ready) begin
                response_hold_data<=mem_rsp_rdata;
                response_hold_error<=mem_rsp_error;
            end
        end
    end

    function automatic logic [15:0] model_read(input logic [31:0] address);
        integer idx;
        begin
            if (address >= 32'h00002000 && address < 32'h00002100 && !address[0]) begin
                idx=(address-32'h00002000)>>1;
                model_read=weight_memory[idx];
            end else if (address >= 32'h00001000 && address < 32'h00001320 && !address[0]) begin
                idx=(address-32'h00001000)>>1;
                model_read=input_memory[idx];
            end else begin
                $fatal(1,"unexpected read address %08x",address);
                model_read=0;
            end
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin : memory_model
        if (!rst_n) begin
            pending<=0; pending_write<=0; pending_error<=0;
            pending_address<=0; pending_data<=0; delay_left<=0;
            rng<=32'hc08c8a25;
            read_requests=0; read_responses=0; weight_reads=0; input_reads=0;
            write_requests=0; write_responses=0;
        end else begin
            rng<=rng*32'd1664525+32'd1013904223;
            if (mem_req_valid && mem_req_ready) begin
                if (pending || mem_req_addr[0]) $fatal(1,"overlapping or unaligned memory request");
                pending<=1;
                pending_write<=mem_req_write;
                pending_address<=mem_req_addr;
                pending_data<=mem_req_wdata;
                pending_error<=(mode==9 && read_requests==0 && !mem_req_write) ||
                               (mode==27 && write_requests==0 && mem_req_write);
                 delay_left<={5'b0,rng[5:3]}+8'd1;
                if (mem_req_write) begin
                    if (command_count!=54 || write_requests>=200 ||
                        mem_req_addr!==32'h00003000+32'(write_requests/8)*32'd16+
                                       32'(write_requests%8)*32'd2)
                        $fatal(1,"unexpected conv output address #%0d: %08x",write_requests,mem_req_addr);
                    if (mem_req_wdata!==captured_output[write_requests])
                        $fatal(1,"captured output lane mismatch #%0d got=%04x expected=%04x",
                               write_requests,mem_req_wdata,captured_output[write_requests]);
                    write_requests=write_requests+1;
                end else begin
                    if (read_requests<64) begin
                        index_value=(read_requests/8)*32+(read_requests%8)*2;
                        if (mem_req_addr!==32'h00002000+32'(index_value))
                            $fatal(1,"weight read order #%0d got=%08x",read_requests,mem_req_addr);
                        weight_reads=weight_reads+1;
                    end else begin
                        index_value=read_requests-64;
                        if (index_value>=200 || mem_req_addr!==32'h00001000+
                            32'(index_value/8)*32'd16+32'(index_value%8)*32'd2)
                            $fatal(1,"input read order #%0d got=%08x",read_requests,mem_req_addr);
                        input_reads=input_reads+1;
                    end
                    pending_data<=model_read(mem_req_addr);
                    read_requests=read_requests+1;
                end
            end
            if (pending) begin
                if (delay_left!=0) delay_left<=delay_left-1'b1;
                else if (mem_rsp_valid && mem_rsp_ready) begin
                    pending<=0;
                    if (pending_write) begin
                        write_responses=write_responses+1;
                        if (!pending_error) begin
                            index_value=(pending_address-32'h00003000)>>1;
                            output_memory[index_value]<=pending_data;
                        end
                    end else begin
                        read_responses=read_responses+1;
                    end
                end
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin : stream_observer
        integer atom, lane, kernel, channel, slot;
        if (!rst_n) begin
            acknowledgments=0; frame_acks=0; done_count=0; observed_frames=0;
        end else begin
            if (acknowledged) acknowledgments=acknowledgments+1;
            if (frame_done) frame_acks=frame_acks+1;
            if (done) done_count=done_count+1;
            if (dut.frame_valid && dut.frame_ready) begin
                atom=observed_frames;
                if (atom>=25) $fatal(1,"extra convolution frame");
                if (dut.frame_output_address!==32'h00003000+32'(atom)*32'd16 ||
                    dut.frame_first!==1'b1 || dut.frame_last!==1'b1 ||
                    dut.frame_last_output!==(atom==24) || dut.frame_data_mask!==32'h000000ff)
                    $fatal(1,"frame metadata mismatch at atom %0d",atom);
                for (lane=0;lane<32;lane=lane+1) begin
                    if (lane<8) begin
                        if (dut.frame_data[lane*16+:16]!==input_memory[atom*8+lane])
                            $fatal(1,"input frame lane mismatch atom=%0d lane=%0d",atom,lane);
                    end else if (dut.frame_data[lane*16+:16]!==16'h0000)
                        $fatal(1,"input padding lane nonzero atom=%0d lane=%0d",atom,lane);
                end
                for (kernel=0;kernel<16;kernel=kernel+1) begin
                    for (channel=0;channel<32;channel=channel+1) begin
                        slot=kernel*32+channel;
                        if (kernel<8 && channel<8) begin
                            if (dut.frame_weight[slot*16+:16]!==weight_memory[kernel*16+channel])
                                $fatal(1,"weight frame kernel=%0d channel=%0d",kernel,channel);
                        end else if (dut.frame_weight[slot*16+:16]!==16'h0000)
                            $fatal(1,"weight IC/OC padding nonzero k=%0d c=%0d",kernel,channel);
                    end
                    if (dut.frame_weight_mask[kernel*32+:32]!==
                        (kernel<8 ? 32'h000000ff : 32'h00000000))
                        $fatal(1,"weight mask mismatch for kernel %0d",kernel);
                end
                observed_frames=observed_frames+1;
            end
        end
    end

    task automatic tick;
        begin @(posedge clk); #2; end
    endtask

    task automatic reset_all;
        begin
            @(negedge clk); rst_n=0; cmd_valid=0; cmd_last=0; cmd_data=0;
            repeat (3) tick();
            if (busy || error || done || mem_req_valid || mem_rsp_ready || cmd_ready)
                $fatal(1,"reset dominance failure");
            for (integer i=0;i<800;i=i+1) output_memory[i]=captured_output[i];
            @(negedge clk); rst_n=1; repeat (3) tick();
            if (!cmd_ready || error || busy) $fatal(1,"reset release failure");
        end
    endtask

    task automatic send_task;
        logic [63:0] word;
        logic last_word;
        begin
            command_count=0;
            for (integer i=0;i<54;i=i+1) begin
                word=commands[i];
                last_word=(i==53);
                case (mode)
                    1: if (i==7) word=word^(64'h1<<16);             // bad geometry value
                    2: if (i==5) word=word^(64'h1<<48);             // unknown register target
                    3: if (i==52) last_word=1'b1;                   // early task boundary
                    4: if (i==53) word=word^(64'h1<<16);             // bad terminal tail
                    5: if (i==21) word=(word&~(64'hffffffff<<16))|(64'h1001<<16);
                    6: if (i==27) word=(word&~(64'hffffffff<<16))|(64'h1000<<16);
                    7: if (i==8) word=word^(64'h1<<16);              // unsupported channel shape
                    8: if (i==53) last_word=1'b0;                   // missing final boundary
                    11: if (i==21) word[47]=1'bx;                    // X input base
                    12: if (i==21) word[47]=1'bz;                    // Z input base
                    13: if (i==27) word[47]=1'bx;                    // X weight base
                    14: if (i==27) word[47]=1'bz;                    // Z weight base
                    15: if (i==35) word[47]=1'bx;                    // X output base
                    16: if (i==35) word[47]=1'bz;                    // Z output base
                    17: if (i==21) word[47:16]=32'hfffffd00;         // input endpoint overflow
                    18: if (i==27) word[47:16]=32'hffffff10;         // weight endpoint overflow
                    19: if (i==35) word[47:16]=32'hfffffa00;         // output endpoint overflow
                    20: if (i==27) word[47:16]=32'h00001100;         // input/weight overlap
                    21: if (i==35) word[47:16]=32'h00001100;         // input/output overlap
                    22: if (i==27) word[47:16]=32'h00003000;         // weight/output overlap
                    23: if (i==21) word[47:16]=32'hfffffce0;         // input ends at 2^32
                    24: if (i==27) word[47:16]=32'hffffff00;         // weight ends at 2^32
                    25: if (i==35) word[47:16]=32'hfffff9c0;         // output ends at 2^32
                    default: begin end
                endcase
                @(negedge clk); cmd_data=word; cmd_last=last_word; cmd_valid=1;
                if (!cmd_ready) $fatal(1,"raw word stalled at index %0d",i);
                tick();
                command_count=command_count+1;
                if (error) begin
                    @(negedge clk); cmd_valid=0; cmd_last=0;
                    disable send_task;
                end
            end
            @(negedge clk); cmd_valid=0; cmd_last=0;
        end
    endtask

    task automatic expect_profile_error(input logic [7:0] wanted);
        begin
            if (!error || error_code!==wanted || busy || done || mem_req_valid || mem_rsp_ready)
                $fatal(1,"profile rejection got error=%b code=%0d expected=%0d",error,error_code,wanted);
            repeat (8) begin
                tick();
                if (!error || error_code!==wanted || busy || cmd_ready || mem_req_valid || done)
                    $fatal(1,"profile error not sticky");
            end
            if (read_requests!=0 || write_requests!=0)
                $fatal(1,"invalid profile touched operand/output BO");
        end
    endtask

    task automatic run_valid_case;
        begin : await_done
            for (age=0;age<200000;age=age+1) begin
                tick();
                if (error) $fatal(1,"valid replay failed code=%0d reads=%0d writes=%0d",error_code,read_requests,write_requests);
                if (done) disable await_done;
            end
            $fatal(1,"convolution replay watchdog");
            end
        repeat (8) tick();
        if (error || busy || done || !cmd_ready || command_count!=54 ||
            read_requests!=264 || read_responses!=264 || weight_reads!=64 ||
            input_reads!=200 || write_requests!=200 || write_responses!=200 ||
            acknowledgments!=200 || frame_acks!=25 || done_count!=1 || observed_frames!=25)
            $fatal(1,"transaction count mismatch cmd=%0d r=%0d/%0d w=%0d/%0d ack=%0d frame=%0d done=%0d atoms=%0d",
                command_count,read_requests,read_responses,write_requests,write_responses,
                acknowledgments,frame_acks,done_count,observed_frames);
        for (integer atom=0;atom<25;atom=atom+1)
            for (integer lane=0;lane<8;lane=lane+1)
                if (output_memory[atom*8+lane]!==expected[lane*25+atom])
                    $fatal(1,"NCHW oracle mismatch atom=%0d lane=%0d",atom,lane);
        // Whole 1600-byte BO comparison: plane 0 is the captured result. The
        // capture does not define planes 1..3; seed those bytes from the raw
        // captured BO and require the engine to leave every one untouched.
        for (integer i=0;i<800;i=i+1)
            if (output_memory[i]!==captured_output[i])
                $fatal(1,"whole output BO mismatch halfword=%0d got=%04x expected=%04x",
                       i,output_memory[i],captured_output[i]);
    endtask

    task automatic expect_boundary_endpoint_valid;
        begin
            repeat (6) tick();
            if (error || !busy || !mem_req_valid || mem_req_ready ||
                read_requests!=0 || write_requests!=0)
                $fatal(1,"exclusive 2^32 endpoint rejected or request escaped mode=%0d",mode);
            case (mode)
                23: if (dut.input_base!==32'hfffffce0 ||
                        dut.weight_base!==32'h00002000 || dut.output_base!==32'h00003000)
                        $fatal(1,"input endpoint bases mismatch");
                24: if (dut.input_base!==32'h00001000 ||
                        dut.weight_base!==32'hffffff00 || dut.output_base!==32'h00003000)
                        $fatal(1,"weight endpoint bases mismatch");
                25: if (dut.input_base!==32'h00001000 ||
                        dut.weight_base!==32'h00002000 || dut.output_base!==32'hfffff9c0)
                        $fatal(1,"output endpoint bases mismatch");
                default: $fatal(1,"bad endpoint mode");
            endcase
        end
    endtask

    task automatic send_extra_qword;
        begin
            @(negedge clk); cmd_data=commands[0]; cmd_last=0; cmd_valid=1;
            while (!cmd_ready) tick();
            tick();
            command_count=command_count+1;
            @(negedge clk); cmd_valid=0; cmd_last=0;
        end
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s",fixture) || !$value$plusargs("MODE=%d",mode))
            $fatal(1,"missing test arguments");
        if (mode<0 || mode>30 || mode==26) $fatal(1,"unsupported test mode");
        report_mode=mode;
        $readmemh({fixture,"/commands.hex"},commands);
        $readmemh({fixture,"/input.hex"},input_memory);
        $readmemh({fixture,"/weight.hex"},weight_memory);
        $readmemh({fixture,"/output.hex"},captured_output);
        $readmemh({fixture,"/expected.hex"},expected);
        reset_all();
        send_task();
        case (mode)
            0: run_valid_case();
            1,7: expect_profile_error(2);
            2: expect_profile_error(1);
            3,4,8: expect_profile_error(3);
            5,6,11,12,13,14,15,16,17,18,19,20,21,22: expect_profile_error(4);
            23,24,25: expect_boundary_endpoint_valid();
            9,10,27,28,29: begin
                for (age=0;age<1000 && !error;age=age+1) tick();
                if (!error || error_code!==((mode==9 || mode==27) ? 8'd5 : 8'd8) || done)
                    $fatal(1,"memory fault test mismatch mode=%0d code=%0d",mode,error_code);
                case (mode)
                    9: if (read_requests!=1 || write_requests!=0)
                           $fatal(1,"first-read error coverage mismatch");
                    10,29: if (read_requests!=1 || write_requests!=0)
                               $fatal(1,"first-read timeout coverage mismatch");
                    27: if (read_requests<72 || read_requests>264 ||
                            write_requests!=1 || write_responses!=1)
                            $fatal(1,"write-response error coverage mismatch r=%0d w=%0d wrsp=%0d err=%b code=%0d",
                                   read_requests,write_requests,write_responses,error,error_code);
                    28: if (read_requests<72 || read_requests>264 ||
                            write_requests!=1 || write_responses!=0)
                            $fatal(1,"write-response timeout coverage mismatch r=%0d w=%0d wrsp=%0d err=%b code=%0d",
                                   read_requests,write_requests,write_responses,error,error_code);
                    default: $fatal(1,"bad memory fault mode");
                endcase
                repeat (8) begin tick(); if (!error || busy || mem_req_valid || done) $fatal(1,"memory fault escaped"); end
                if (mode==29) begin
                    // Reset core and memory adapter together after a stale
                    // timed-out response, then replay the same raw task.
                    mode=0;
                    reset_all();
                    send_task();
                    run_valid_case();
                end
            end
            30: begin
                send_extra_qword();
                expect_profile_error(7);
                if (command_count!=55) $fatal(1,"extra QWORD count mismatch");
            end
            default: $fatal(1,"unexpected mode");
        endcase
        $display("PASS CONV_C8_H5_W5_OC8 mode=%0d seed=%08x commands=%0d reads=%0d writes=%0d",report_mode,32'hc08c8a25,command_count,read_requests,write_requests);
        $finish;
    end

    initial begin #10000000; $fatal(1,"testbench watchdog"); end
endmodule
