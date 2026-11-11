// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Whole-BO replay of one frozen `conv-simple` capture through
// rk_conv_simple_core: raw descriptor, parameterised spatial front, donor
// CMAC/CACC arithmetic, FP16 output atom writer.
//
// The memory model is the only behavioural component. Every write is checked
// against the captured device bytes as it happens, and the complete output BO
// is compared at the end; untouched bytes must keep their initial value.
module tb_conv_simple #(
    parameter int unsigned PROFILE = 0,
    parameter int unsigned INPUT_H = 8,
    parameter int unsigned INPUT_W = 8,
    parameter int unsigned KH = 3,
    parameter int unsigned KW = 3,
    parameter int unsigned INPUT_CHANNELS = 4,
    parameter int unsigned KERNELS = 8,
    parameter int unsigned C1_BLOCKS = 2,
    parameter int unsigned ALIGN_C = 8,
    parameter int unsigned PACK_C2 = 4,
    parameter int unsigned CHUNK_LANES = 16,
    parameter int unsigned WEIGHT_HALFWORDS = 1152,
    parameter int unsigned INPUT_HALFWORDS = 256,
    parameter int unsigned OUTPUT_BYTES = 1152,
    parameter int unsigned MODE = 0,
    parameter int unsigned TIMEOUT_CYCLES = 4096,
    // BO placement comes from the capture itself: the 5x5 and C16 cases put
    // the output above the weight BO so the three ranges stay disjoint.
    parameter int unsigned INPUT_BASE = 32'h00001000,
    parameter int unsigned WEIGHT_BASE = 32'h00002000,
    parameter int unsigned OUTPUT_BASE = 32'h00003000
);
    localparam int unsigned OUTPUT_H = INPUT_H - KH + 1;
    localparam int unsigned OUTPUT_W = INPUT_W - KW + 1;
    localparam int unsigned OUTPUT_PIXELS = OUTPUT_H * OUTPUT_W;
    localparam int unsigned TOTAL_ATOMS = OUTPUT_PIXELS * C1_BLOCKS;
    localparam int unsigned OUTPUT_HALFWORDS = OUTPUT_BYTES / 2;
    localparam int unsigned LANES_PER_PLANE =
        (INPUT_CHANNELS < PACK_C2) ? INPUT_CHANNELS : PACK_C2;
    localparam int unsigned PLANES =
        (INPUT_CHANNELS + PACK_C2 - 1) / PACK_C2;
    localparam int unsigned INPUT_PIXELS = INPUT_H * INPUT_W;
    localparam int unsigned INPUT_READS = INPUT_PIXELS * INPUT_CHANNELS;
    localparam int unsigned TOTAL_READS = WEIGHT_HALFWORDS + INPUT_READS;
    localparam int unsigned TOTAL_WRITES = TOTAL_ATOMS * 8;
    localparam int unsigned TOTAL_FRAMES = TOTAL_ATOMS * (KH * KW);


    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic cmd_valid = 1'b0, cmd_last = 1'b0;
    logic [63:0] cmd_data = 64'd0;
    wire cmd_ready, busy, acknowledged, frame_done, done, error;
    wire [7:0] error_code;
    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready, mem_rsp_valid, mem_rsp_error;
    logic [15:0] mem_rsp_rdata;

    logic [63:0] commands [0:51];
    logic [15:0] input_memory [0:INPUT_HALFWORDS-1];
    logic [15:0] weight_memory [0:WEIGHT_HALFWORDS-1];
    logic [15:0] expected [0:OUTPUT_HALFWORDS-1];
    logic [15:0] output_memory [0:OUTPUT_HALFWORDS-1];
    logic [15:0] initial_output [0:OUTPUT_HALFWORDS-1];

    // Observation nets for the core's published operand placement; the bench
    // does not drive them, it only checks the wrapper-facing contract.
    wire [31:0] config_input_base, config_weight_base, config_output_base;
    wire [31:0] input_bytes, weight_bytes, output_bytes;
    logic pending, pending_write, pending_error;
    logic [31:0] pending_address;
    logic [15:0] pending_data;
    logic [7:0] delay_left;
    logic [31:0] rng = 32'h3c4c9a31;
    integer mode, command_count, read_requests, read_responses;
    integer weight_reads, input_reads, write_requests, write_responses;
    integer acknowledgments, frame_acks, observed_frames, done_count, age, index_value;
    string fixture;

    always #5 clk = ~clk;

    initial if (PROFILE > 2) $fatal(1, "unknown conv-simple profile");

    rk_conv_simple_core #(
        .PROFILE(PROFILE), .INPUT_H(INPUT_H), .INPUT_W(INPUT_W), .KH(KH), .KW(KW),
        .INPUT_CHANNELS(INPUT_CHANNELS), .KERNELS(KERNELS),
        .C1_BLOCKS(C1_BLOCKS), .ALIGN_C(ALIGN_C), .PACK_C2(PACK_C2),
        .CHUNK_LANES(CHUNK_LANES), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) dut (.*);

    always @* begin
        mem_req_ready = rst_n && !pending && (rng[2:0] != 2'b00) &&
                         !(mode == 9 && read_requests == 0);
        mem_rsp_valid = rst_n && pending && delay_left == 0 &&
                        !(mode == 11 && pending_write);
        mem_rsp_rdata = pending_data;
        mem_rsp_error = pending_error;
    end

    always @(posedge clk or negedge rst_n) begin : memory_model
        integer atom, lane;
        if (!rst_n) begin
            pending <= 1'b0;
            pending_write <= 1'b0;
            pending_error <= 1'b0;
            pending_address <= 32'd0;
            pending_data <= 16'd0;
            delay_left <= 0;
            command_count = 0;
            read_requests = 0;
            read_responses = 0;
            weight_reads = 0;
            input_reads = 0;
            write_requests = 0;
            write_responses = 0;
        end else begin
            rng <= rng * 32'd1664525 + 32'd1013904223;
            if (mem_req_valid && mem_req_ready) begin
                if (pending || mem_req_addr[0])
                    $fatal(1, "overlapping or unaligned memory request");
                pending <= 1'b1;
                pending_write <= mem_req_write;
                pending_address <= mem_req_addr;
                pending_data <= mem_req_wdata;
                pending_error <=
                    (mode == 8 && !mem_req_write && read_requests == 0) ||
                    (mode == 10 && mem_req_write && write_requests == 0);
                delay_left <= {5'b0, rng[5:3]} + 8'd1;

                if (mem_req_write) begin
                    atom = write_requests / 8;
                    lane = write_requests % 8;
                    if (write_requests >= TOTAL_WRITES ||
                        mem_req_addr !== OUTPUT_BASE + 32'(atom) * 32'd16 +
                                        32'(lane) * 32'd2)
                        $fatal(1, "unexpected output write #%0d address=%08x",
                               write_requests, mem_req_addr);
                    if (mem_req_wdata !== expected[atom * 8 + lane])
                        $fatal(1, "output mismatch atom=%0d lane=%0d got=%04x expected=%04x",
                               atom, lane, mem_req_wdata, expected[atom * 8 + lane]);
                    write_requests = write_requests + 1;
                end else begin
                    if (command_count != 52)
                        $fatal(1, "operand read before all raw command words were accepted");
                    if (read_requests < WEIGHT_HALFWORDS) begin
                        index_value = read_requests;
                        if (mem_req_addr !== WEIGHT_BASE + 32'(index_value) * 32'd2)
                            $fatal(1, "weight order #%0d address=%08x",
                                   read_requests, mem_req_addr);
                        pending_data <= weight_memory[index_value];
                        weight_reads = weight_reads + 1;
                    end else begin
                        index_value = read_requests - WEIGHT_HALFWORDS;
                        if (index_value >= INPUT_READS)
                            $fatal(1, "input read beyond the packed BO");
                        // Plane-major order: pixel, then C1 plane, then lanes.
                        if (mem_req_addr !== INPUT_BASE +
                            32'(index_value % INPUT_CHANNELS / LANES_PER_PLANE) *
                                (INPUT_PIXELS * INPUT_CHANNELS / PLANES * 2) +
                            32'(index_value / INPUT_CHANNELS) *
                                (LANES_PER_PLANE * 2) +
                            32'(index_value % INPUT_CHANNELS % LANES_PER_PLANE) * 32'd2)
                            $fatal(1, "packed input order #%0d address=%08x",
                                   read_requests, mem_req_addr);
                        pending_data <= input_memory[
                            (index_value % INPUT_CHANNELS / LANES_PER_PLANE) *
                            (INPUT_PIXELS * LANES_PER_PLANE) +
                            (index_value / INPUT_CHANNELS) * LANES_PER_PLANE +
                            (index_value % INPUT_CHANNELS % LANES_PER_PLANE)];
                        input_reads = input_reads + 1;
                    end
                    read_requests = read_requests + 1;
                end
            end

            if (pending) begin
                if (delay_left != 0) delay_left <= delay_left - 1'b1;
                else if (mem_rsp_valid && mem_rsp_ready) begin
                    pending <= 1'b0;
                    if (pending_write) begin
                        write_responses = write_responses + 1;
                        if (!pending_error)
                            output_memory[(pending_address - OUTPUT_BASE) >> 1]
                                <= pending_data;
                    end else read_responses = read_responses + 1;
                end
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin : bus_stability
        logic stalled_request, held_write, stalled_response, held_error;
        logic [31:0] held_address;
        logic [15:0] held_data, held_response_data;
        if (!rst_n) begin
            stalled_request = 1'b0;
            held_write = 1'b0;
            stalled_response = 1'b0;
            held_error = 1'b0;
        end else begin
            if (stalled_request && !error &&
                (!mem_req_valid || mem_req_write !== held_write ||
                 mem_req_addr !== held_address || mem_req_wdata !== held_data))
                $fatal(1, "memory request changed while stalled");
            stalled_request = mem_req_valid && !mem_req_ready;
            if (mem_req_valid && !mem_req_ready) begin
                held_write = mem_req_write;
                held_address = mem_req_addr;
                held_data = mem_req_wdata;
            end
            if (stalled_response && !error &&
                (!mem_rsp_valid || mem_rsp_rdata !== held_response_data ||
                 mem_rsp_error !== held_error))
                $fatal(1, "memory response changed while stalled");
            stalled_response = mem_rsp_valid && !mem_rsp_ready;
            if (mem_rsp_valid && !mem_rsp_ready) begin
                held_response_data = mem_rsp_rdata;
                held_error = mem_rsp_error;
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin : frame_observer
        integer atom, tap;
        if (!rst_n) begin
            acknowledgments = 0;
            frame_acks = 0;
            observed_frames = 0;
            done_count = 0;
        end else begin
            // `acknowledged` is one halfword write; `frame_done` is one
            // completed output atom. They are different counters.
            if (acknowledged) acknowledgments = acknowledgments + 1;
            if (frame_done) frame_acks = frame_acks + 1;
            if (done) done_count = done_count + 1;
            if (dut.frame_valid && dut.frame_ready) begin
                atom = observed_frames / (KH * KW);
                tap = observed_frames % (KH * KW);
                if (observed_frames >= TOTAL_FRAMES ||
                    dut.frame_output_address !== OUTPUT_BASE + 32'(atom) * 32'd16 ||
                    dut.frame_first !== (tap == 0) ||
                    dut.frame_last !== (tap == KH*KW-1) ||
                    dut.frame_last_output !== (atom == TOTAL_ATOMS-1))
                    $fatal(1, "frame metadata mismatch frame=%0d atom=%0d addr=%08x exp=%08x first=%b last=%b last_out=%b frames=%0d",
                           observed_frames, atom, dut.frame_output_address,
                           OUTPUT_BASE + 32'(atom) * 32'd16, dut.frame_first,
                           dut.frame_last, dut.frame_last_output, TOTAL_FRAMES);
                observed_frames = observed_frames + 1;
            end
        end
    end

    task automatic tick;
        begin @(posedge clk); #2; end
    endtask

    task automatic reset_all;
        begin
            @(negedge clk);
            rst_n = 1'b0;
            cmd_valid = 1'b0;
            cmd_last = 1'b0;
            cmd_data = 64'd0;
            repeat (3) tick();
            for (integer i = 0; i < OUTPUT_HALFWORDS; i = i + 1) begin
                initial_output[i] = 16'ha5a5 ^ 16'(i * 17);
                output_memory[i] = initial_output[i];
            end
            @(negedge clk);
            rst_n = 1'b1;
            repeat (3) tick();
            if (!cmd_ready || error || busy)
                $fatal(1, "reset release contract failed");
        end
    endtask

    task automatic send_task;
        logic [63:0] word;
        logic last_word;
        begin
            command_count = 0;
            for (integer i = 0; i < 52; i = i + 1) begin
                word = commands[i];
                last_word = (i == 50);
                case (mode)
                    1: if (i == 7) word = word ^ (64'h1 << 16);
                    2: if (i == 5) word = word ^ (64'h1 << 48);
                    3: if (i == 50) last_word = 1'b0;
                    4: if (i == 51) word = word ^ (64'h1 << 16);
                    5: if (i == 18) word[19:16] = 4'h1;
                    6: if (i == 24) word[47:16] = 32'h00001000;
                    7: if (i == 32) word[47:16] = 32'h00002000;  // weight BO
                    default: begin end
                endcase
                @(negedge clk);
                cmd_data = word;
                cmd_last = last_word;
                cmd_valid = 1'b1;
                if (!cmd_ready) $fatal(1, "raw word stalled at index=%0d", i);
                tick();
                command_count = command_count + 1;
                if (error) begin
                    @(negedge clk);
                    cmd_valid = 1'b0;
                    cmd_last = 1'b0;
                    disable send_task;
                end
            end
            @(negedge clk);
            cmd_valid = 1'b0;
            cmd_last = 1'b0;
        end
    endtask

    task automatic expect_profile_error(input logic [7:0] wanted);
        begin
            if (!error || error_code !== wanted || busy || done ||
                mem_req_valid || mem_rsp_ready)
                $fatal(1, "profile error=%b code=%0d expected=%0d word=%0d last_data=%064x",
                       error, error_code, wanted, dut.profile.state,
                       cmd_data);
            repeat (8) begin
                tick();
                if (!error || error_code !== wanted || busy || cmd_ready || mem_req_valid)
                    $fatal(1, "profile rejection not sticky");
            end
            if (read_requests != 0 || write_requests != 0)
                $fatal(1, "invalid raw stream touched operand/output memory");
        end
    endtask

    task automatic check_valid_output;
        begin
            for (age = 0; age < 400000; age = age + 1) begin
                tick();
                if (error)
                    $fatal(1, "valid replay failed code=%0d reads=%0d writes=%0d frames=%0d",
                           error_code, read_requests, write_requests, observed_frames);
                if (done) disable check_valid_output;
            end
            $fatal(1, "conv-simple watchdog");
        end
    endtask

    task automatic verify_valid_case;
        begin
            check_valid_output();
            repeat (8) tick();
            if (error || busy || done || command_count != 52 ||
                read_requests != TOTAL_READS || read_responses != TOTAL_READS ||
                weight_reads != WEIGHT_HALFWORDS || input_reads != INPUT_READS ||
                write_requests != TOTAL_WRITES || write_responses != TOTAL_WRITES ||
                acknowledgments != TOTAL_WRITES || frame_acks != TOTAL_ATOMS ||
                done_count != 1 || observed_frames != TOTAL_FRAMES)
                $fatal(1, "traffic mismatch cmd=%0d r=%0d/%0d w=%0d/%0d ack=%0d atoms=%0d frames=%0d",
                       command_count, read_requests, read_responses, write_requests,
                       write_responses, acknowledgments, frame_acks, observed_frames);
            for (integer i = 0; i < OUTPUT_HALFWORDS; i = i + 1)
                if (output_memory[i] !== expected[i])
                    $fatal(1, "complete output BO mismatch halfword=%0d got=%04x expected=%04x",
                           i, output_memory[i], expected[i]);
        end
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s", fixture) || !$value$plusargs("MODE=%d", mode))
            $fatal(1, "missing test arguments");
        if (mode < 0 || mode > 12) $fatal(1, "unsupported mode");
        $readmemh({fixture, "/commands.hex"}, commands);
        // The commands.hex is written already relocated by the runner, so the
        // bases it carries are authoritative; the localparams only describe
        // the same placement for the memory model's bounds checks.
        $readmemh({fixture, "/input.hex"}, input_memory);
        $readmemh({fixture, "/weight.hex"}, weight_memory);
        $readmemh({fixture, "/expected.hex"}, expected);
        reset_all();
        send_task();
        case (mode)
            0: verify_valid_case();
            1: expect_profile_error(8'd2);   // unmodelled register value
            2: expect_profile_error(8'd1);   // wrong target/offset
            3: expect_profile_error(8'd3);   // P C trigger missing
            4: expect_profile_error(8'd2);   // nonzero padding word
            5: expect_profile_error(8'd2);   // address not 16-byte aligned
            6, 7: expect_profile_error(8'd4);  // input/weight and weight/output overlap
            8, 9, 10, 11: begin
                for (age = 0; age < 400000 && !error; age = age + 1) tick();
                if (!error || error_code !== ((mode == 8 || mode == 10) ? 8'd5 : 8'd8) || done)
                    $fatal(1, "memory fault mismatch mode=%0d code=%0d", mode, error_code);
                // Mode 8 faults an error response; mode 9 withholds readiness,
                // so its first request is issued but never accepted.
                if (mode == 8 && read_requests != 1)
                    $fatal(1, "first-read fault traffic r=%0d", read_requests);
                if (mode == 9 && read_requests > 0)
                    $fatal(1, "stalled first request traffic r=%0d", read_requests);
                if (mode == 10 && (read_requests != TOTAL_READS ||
                                   write_requests != 1 || write_responses != 1))
                    $fatal(1, "write error traffic r=%0d w=%0d wrsp=%0d",
                           read_requests, write_requests, write_responses);
                // Mode 11 withholds the response to the first write, so the
                // request is issued but never acknowledged.
                if (mode == 11 && (read_requests != TOTAL_READS ||
                                   write_requests > 1 || write_responses != 0))
                    $fatal(1, "write timeout traffic r=%0d w=%0d wrsp=%0d",
                           read_requests, write_requests, write_responses);
            end
            12: begin
                verify_valid_case();
                @(negedge clk);
                cmd_data = commands[0];
                cmd_last = 1'b0;
                cmd_valid = 1'b1;
                while (!cmd_ready) tick();
                tick();
                @(negedge clk);
                cmd_valid = 1'b0;
                if (!error || error_code !== 8'd7 || busy || mem_req_valid)
                    $fatal(1, "extra raw word was not rejected with code 7");
            end
            default: $fatal(1, "unexpected mode");
        endcase
        $display("PASS CONV_SIMPLE profile=%0d mode=%0d commands=%0d reads=%0d writes=%0d frames=%0d output_bytes=%0d",
                 PROFILE, mode, command_count, read_requests, write_requests,
                 observed_frames, OUTPUT_BYTES);
        $finish;
    end

    initial begin
        #40000000;
        $fatal(1, "conv-simple testbench watchdog");
    end
endmodule
