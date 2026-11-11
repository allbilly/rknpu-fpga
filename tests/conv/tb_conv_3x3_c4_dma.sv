// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_conv_3x3_c4_dma #(
    parameter integer PROFILE = 0
);
    localparam integer STRIDE2 = PROFILE == 1;
    localparam integer PAD1 = PROFILE == 2;
    localparam integer INPUT_H = (STRIDE2 || PAD1) ? 11 : 9;
    localparam integer INPUT_W = (STRIDE2 || PAD1) ? 11 : 9;
    localparam integer OUTPUT_H = PAD1 ? 9 : STRIDE2 ? 5 : 7;
    localparam integer OUTPUT_W = PAD1 ? 9 : STRIDE2 ? 5 : 7;
    localparam integer INPUT_PIXELS = INPUT_H * INPUT_W;
    localparam integer OUTPUT_PIXELS = OUTPUT_H * OUTPUT_W;
    localparam integer INPUT_HALFWORDS = INPUT_PIXELS * 16;
    localparam integer OUTPUT_HALFWORDS = PAD1 ? 2688 : STRIDE2 ? 896 : 1664;
    localparam integer INPUT_READS = INPUT_PIXELS * 4;
    localparam integer TOTAL_READS = 216 + 576 + INPUT_READS;
    localparam integer TOTAL_WRITES = OUTPUT_PIXELS * 8;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic start_valid = 1'b0;
    logic [31:0] start_address = 0;
    logic [31:0] start_amount = 54;
    wire start_ready, busy, done, acknowledged, frame_done, error;
    wire [7:0] error_code;
    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready, mem_rsp_valid;
    logic [15:0] mem_rsp_rdata;
    logic mem_rsp_error;

    logic [63:0] commands [0:53];
    logic [15:0] input_memory [0:INPUT_HALFWORDS-1];
    logic [15:0] weight_memory [0:575];
    logic [15:0] expected [0:OUTPUT_PIXELS*4-1];
    logic [15:0] device_output [0:OUTPUT_HALFWORDS-1];
    logic [15:0] output_memory [0:OUTPUT_HALFWORDS-1];
    logic [15:0] initial_output [0:OUTPUT_HALFWORDS-1];
    logic pending, pending_write, pending_error;
    logic [31:0] pending_address;
    logic [15:0] pending_data;
    logic [7:0] delay_left;
    logic [31:0] rng;
    integer mode, jobs, command_reads, weight_reads, input_reads, write_requests;
    integer read_responses, write_responses, acknowledgments, frame_acks, done_count;
    integer age, index_value;
    string fixture;

    always #5 clk = ~clk;

    rk_conv_3x3_c4_dma #(.PROFILE(PROFILE), .TIMEOUT_CYCLES(16)) dut (
        .clk, .rst_n, .start_valid, .start_ready, .start_address, .start_amount,
        .busy, .done, .acknowledged, .frame_done, .error, .error_code,
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata, .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata,
        .mem_rsp_error
    );

    always @* begin
        mem_req_ready = rst_n && !pending && rng[2:0] != 0;
        mem_rsp_valid = rst_n && pending && delay_left == 0 && mode != 5;
        mem_rsp_rdata = pending_data;
        mem_rsp_error = pending_error;
    end

    function automatic logic [15:0] model_read(input logic [31:0] address);
        integer idx;
        integer halfword;
        begin
            if (address >= start_address &&
                {1'b0, address} < ({1'b0, start_address} + 33'd432) && !address[0]) begin
                halfword = (address - start_address) >> 1;
                model_read = commands[halfword / 4][(halfword % 4) * 16 +: 16];
            end else if (address >= 32'h00002000 && address < 32'h00002480 && !address[0]) begin
                idx = (address - 32'h00002000) >> 1;
                model_read = weight_memory[idx];
            end else if (address >= 32'h00001000 &&
                         address < 32'h00001000 + INPUT_PIXELS*16 && !address[0]) begin
                idx = (address - 32'h00001000) >> 1;
                model_read = input_memory[idx];
            end else begin
                $fatal(1, "unexpected descriptor convolution read %08x", address);
                model_read = 16'd0;
            end
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin : memory_model
        integer atom, lane;
        if (!rst_n) begin
            pending <= 0;
            pending_write <= 0;
            pending_error <= 0;
            pending_address <= 0;
            pending_data <= 0;
            delay_left <= 0;
            rng <= 32'h3c4c9a31;
            command_reads = 0;
            weight_reads = 0;
            input_reads = 0;
            write_requests = 0;
            read_responses = 0;
            write_responses = 0;
        end else begin
            rng <= rng * 32'd1664525 + 32'd1013904223;
            if (mem_req_valid && mem_req_ready) begin
                if (pending || mem_req_addr[0])
                    $fatal(1, "overlapping or unaligned DMA memory request");
                pending <= 1;
                pending_write <= mem_req_write;
                pending_address <= mem_req_addr;
                pending_data <= mem_req_wdata;
                pending_error <= mode == 4 && !mem_req_write && command_reads == 0;
                delay_left <= {5'b0, rng[5:3]} + 8'd1;
                if (mem_req_write) begin
                    atom = write_requests / 8;
                    lane = write_requests % 8;
                    if (atom >= OUTPUT_PIXELS ||
                        mem_req_addr !== 32'h00003000 + 32'(write_requests) * 32'd2)
                        $fatal(1, "unexpected output write #%0d at %08x",
                               write_requests, mem_req_addr);
                    if (lane < 4 && mem_req_wdata !== expected[lane*OUTPUT_PIXELS + atom])
                        $fatal(1, "output mismatch atom=%0d lane=%0d got=%04x expected=%04x",
                               atom, lane, mem_req_wdata, expected[lane*OUTPUT_PIXELS + atom]);
                    if (lane >= 4 && mem_req_wdata !== 16'h0000)
                        $fatal(1, "padded output lane nonzero atom=%0d lane=%0d", atom, lane);
                    write_requests = write_requests + 1;
                end else if (command_reads < 216) begin
                    if (mem_req_addr !== start_address + 32'(command_reads)*32'd2)
                        $fatal(1, "command BO fetch reordered read=%0d addr=%08x",
                               command_reads, mem_req_addr);
                    command_reads = command_reads + 1;
                    pending_data <= model_read(mem_req_addr);
                end else if (weight_reads < 576) begin
                    if (mem_req_addr !== 32'h00002000 + 32'(weight_reads)*32'd2)
                        $fatal(1, "weight read reordered read=%0d addr=%08x",
                               weight_reads, mem_req_addr);
                    weight_reads = weight_reads + 1;
                    pending_data <= model_read(mem_req_addr);
                end else begin
                    index_value = input_reads;
                    if (index_value >= INPUT_READS ||
                        mem_req_addr !== 32'h00001000 +
                            32'(index_value/4)*32'd16 + 32'(index_value%4)*32'd2)
                        $fatal(1, "input read reordered read=%0d addr=%08x",
                               input_reads, mem_req_addr);
                    input_reads = input_reads + 1;
                    pending_data <= model_read(mem_req_addr);
                end
            end
            if (pending) begin
                if (delay_left != 0) delay_left <= delay_left - 1'b1;
                else if (mem_rsp_valid && mem_rsp_ready) begin
                    pending <= 0;
                    if (pending_write) begin
                        write_responses = write_responses + 1;
                        if (!pending_error) begin
                            index_value = (pending_address - 32'h00003000) >> 1;
                            output_memory[index_value] <= pending_data;
                        end
                    end else read_responses = read_responses + 1;
                end
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin : event_counts
        if (!rst_n) begin
            acknowledgments = 0;
            frame_acks = 0;
            done_count = 0;
        end else begin
            if (acknowledged) acknowledgments = acknowledgments + 1;
            if (frame_done) frame_acks = frame_acks + 1;
            if (done) done_count = done_count + 1;
        end
    end

    task automatic tick;
        begin @(posedge clk); #2; end
    endtask

    task automatic reset_all;
        begin
            @(negedge clk);
            rst_n = 0;
            start_valid = 0;
            repeat (3) tick();
            for (integer i = 0; i < OUTPUT_HALFWORDS; i = i + 1) begin
                initial_output[i] = 16'h5aa5 ^ 16'(i * 29);
                output_memory[i] = initial_output[i];
            end
            @(negedge clk);
            rst_n = 1;
            repeat (3) tick();
            if (!start_ready || error || busy)
                $fatal(1, "DMA reset release failed");
        end
    endtask

    task automatic start_job;
        begin
            @(negedge clk);
            start_address = mode == 2 ? 32'hfffffee0 :
                            mode == 3 ? 32'h00001000 : 32'h00008000;
            start_amount = mode == 1 ? 32'd53 : 32'd54;
            start_valid = 1;
            if (!start_ready) $fatal(1, "descriptor start unexpectedly stalled");
            tick();
            @(negedge clk);
            start_valid = 0;
        end
    endtask

    task automatic expect_error(input logic [7:0] code, input integer timeout_cycles);
        begin
            for (age = 0; age < timeout_cycles && !error; age = age + 1) tick();
            if (!error || error_code !== code || busy || done || mem_req_valid || mem_rsp_ready)
                $fatal(1, "DMA error expected=%0d actual=%0d busy=%b", code, error_code, busy);
            repeat (4) begin
                tick();
                if (!error || error_code !== code || busy || done || mem_req_valid)
                    $fatal(1, "DMA failure was not sticky");
            end
        end
    endtask

    task automatic verify_success;
        begin
            for (age = 0; age < 300000 && !done && !error; age = age + 1) tick();
            if (error || !done) $fatal(1, "DMA convolution failed code=%0d", error_code);
            repeat (8) tick();
            if (busy || done || command_reads != 216 || weight_reads != 576 ||
                input_reads != INPUT_READS || read_responses != TOTAL_READS ||
                write_requests != TOTAL_WRITES || write_responses != TOTAL_WRITES ||
                acknowledgments != TOTAL_WRITES || frame_acks != OUTPUT_PIXELS ||
                done_count != jobs) begin
                $fatal(1, "DMA traffic mismatch job=%0d cmd=%0d weights=%0d input=%0d reads=%0d writes=%0d ack=%0d frames=%0d done=%0d",
                       jobs, command_reads, weight_reads, input_reads, read_responses,
                       write_requests, acknowledgments, frame_acks, done_count);
            end
            for (integer atom = 0; atom < OUTPUT_PIXELS; atom = atom + 1)
                for (integer channel = 0; channel < 4; channel = channel + 1) begin
                    if (output_memory[atom*8+channel] !== expected[channel*OUTPUT_PIXELS+atom])
                        $fatal(1, "output memory mismatch atom=%0d channel=%0d", atom, channel);
                    if (device_output[atom*8+channel] !== expected[channel*OUTPUT_PIXELS+atom])
                        $fatal(1, "device output mismatch atom=%0d channel=%0d", atom, channel);
                end
            for (integer i = TOTAL_WRITES; i < OUTPUT_HALFWORDS; i = i + 1)
                if (output_memory[i] !== initial_output[i])
                    $fatal(1, "output BO tail modified halfword=%0d", i);
            if (!start_ready) $fatal(1, "rearmed descriptor wrapper did not advertise start");
            // A second descriptor must run from the same exact raw profile after
            // the owned core reset pulse and must not touch the BO gaps.
            @(negedge clk);
            start_valid = 1'b1;
            tick();
            @(negedge clk);
            start_valid = 1'b0;
            command_reads = 0;
            weight_reads = 0;
            input_reads = 0;
            write_requests = 0;
            read_responses = 0;
            write_responses = 0;
            jobs = jobs + 1;
            for (age = 0; age < 300000 && !done && !error; age = age + 1) tick();
            if (error || !done) $fatal(1, "second DMA convolution failed code=%0d", error_code);
            repeat (8) tick();
            if (busy || done || command_reads != 216 || weight_reads != 576 ||
                input_reads != INPUT_READS || read_responses != TOTAL_READS ||
                write_requests != TOTAL_WRITES || write_responses != TOTAL_WRITES ||
                acknowledgments != TOTAL_WRITES*jobs || frame_acks != OUTPUT_PIXELS*jobs ||
                done_count != jobs) begin
                $fatal(1, "second DMA traffic mismatch job=%0d cmd=%0d weights=%0d input=%0d reads=%0d writes=%0d ack=%0d frames=%0d done=%0d",
                       jobs, command_reads, weight_reads, input_reads, read_responses,
                       write_requests, acknowledgments, frame_acks, done_count);
            end
            for (integer atom = 0; atom < OUTPUT_PIXELS; atom = atom + 1)
                for (integer channel = 0; channel < 4; channel = channel + 1) begin
                    if (output_memory[atom*8+channel] !== expected[channel*OUTPUT_PIXELS+atom])
                        $fatal(1, "second output memory mismatch atom=%0d channel=%0d", atom, channel);
                    if (device_output[atom*8+channel] !== expected[channel*OUTPUT_PIXELS+atom])
                        $fatal(1, "second device output mismatch atom=%0d channel=%0d", atom, channel);
                end
            for (integer i = TOTAL_WRITES; i < OUTPUT_HALFWORDS; i = i + 1)
                if (output_memory[i] !== initial_output[i])
                    $fatal(1, "second output BO tail modified halfword=%0d", i);
        end
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s", fixture) || !$value$plusargs("MODE=%d", mode))
            $fatal(1, "missing DMA test arguments");
        if (mode < 0 || mode > 6) $fatal(1, "unsupported DMA test mode");
        jobs = 0;
        $readmemh({fixture, "/commands.hex"}, commands);
        $readmemh({fixture, "/input.hex"}, input_memory);
        $readmemh({fixture, "/weight.hex"}, weight_memory);
        $readmemh({fixture, "/expected.hex"}, expected);
        $readmemh({fixture, "/device.hex"}, device_output);
        reset_all();
        if (mode == 6) commands[7] = commands[7] ^ (64'h1 << 16);
        start_job();
        jobs = 1;
        case (mode)
            0: verify_success();
            1,2: begin
                expect_error(7, 8);
                if (command_reads || write_requests) $fatal(1, "bad descriptor touched memory");
            end
            3: begin
                expect_error(4, 10000);
                if (command_reads != 216 || weight_reads || input_reads || write_requests)
                    $fatal(1, "overlap rejection touched operand/output BO");
            end
            4: begin
                expect_error(5, 10000);
                if (command_reads != 1 || weight_reads || input_reads || write_requests)
                    $fatal(1, "command read error traffic mismatch");
            end
            5: begin
                expect_error(8, 10000);
                if (command_reads != 1 || weight_reads || input_reads || write_requests)
                    $fatal(1, "command read timeout traffic mismatch");
            end
            6: begin
                expect_error(2, 10000);
                if (command_reads != 32 || weight_reads || input_reads || write_requests)
                    $fatal(1, "bad raw command traffic mismatch");
            end
        endcase
        $display("PASS CONV_3X3_DMA profile=%0d mode=%0d command_reads=%0d reads=%0d writes=%0d",
                 PROFILE, mode, command_reads, read_responses, write_requests);
        $finish;
    end

    initial begin
        #20000000;
        $fatal(1, "DMA testbench watchdog");
    end
endmodule
