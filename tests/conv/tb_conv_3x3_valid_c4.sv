// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_conv_3x3_valid_c4 #(
    parameter bit STRIDE2 = 1'b0,
    parameter bit PAD1 = 1'b0,
    parameter bit GROUPED_C2 = 1'b0,
    parameter bit SPLIT_OC = 1'b0,
    parameter bit DEPTHWISE = 1'b0
);
    // Real input channels in the packed C2 planes versus real output channels
    // in the 8-lane output atom. They are different quantities.
    localparam integer REAL_CHANNELS = DEPTHWISE ? 3 : SPLIT_OC ? 16 : GROUPED_C2 ? 2 : 4;
    localparam integer OUTPUT_CHANNELS = DEPTHWISE ? 3 : SPLIT_OC ? 8 : 4;
    localparam integer KERNELS = DEPTHWISE ? 3 : SPLIT_OC ? 8 : 4;
    // Depthwise packs 8 lanes per tap position; the others use align_C=16.
    // Depthwise uses [ky][kx][c2_out]; the other profiles use
    // [ky][kx][KERNELS][align_C]. c2_out equals ALIGN_C in both cases.
    localparam integer ALIGN_C = DEPTHWISE ? 8 : 16;
    localparam integer WEIGHT_LANES = DEPTHWISE ? ALIGN_C : KERNELS * ALIGN_C;
    localparam integer WEIGHT_HALFWORDS = 9 * WEIGHT_LANES;
    localparam integer INPUT_H = DEPTHWISE ? 11 : (STRIDE2 || PAD1) ? 11 : GROUPED_C2 ? 5 : 9;
    localparam integer INPUT_W = DEPTHWISE ? 28 : (STRIDE2 || PAD1) ? 11 : GROUPED_C2 ? 5 : 9;
    localparam integer OUTPUT_H = DEPTHWISE ? 9 : PAD1 ? 9 : STRIDE2 ? 5 : GROUPED_C2 ? 3 : 7;
    localparam integer OUTPUT_W = DEPTHWISE ? 26 : PAD1 ? 9 : STRIDE2 ? 5 : GROUPED_C2 ? 3 : 7;
    localparam integer STRIDE = STRIDE2 ? 2 : 1;
    localparam integer INPUT_PIXELS = INPUT_H * INPUT_W;
    localparam integer OUTPUT_PIXELS = OUTPUT_H * OUTPUT_W;
    // Two packed C1 planes of 8 lanes cover up to sixteen real channels.
    localparam integer PLANE_HALFWORDS = INPUT_PIXELS * 8;
    localparam integer PLANES = DEPTHWISE ? 1 : SPLIT_OC ? 2 : 2;
    // Real lanes carried by one packed C1 plane: min(REAL_C, PACK_C2).
    localparam integer LANES_PER_PLANE = REAL_CHANNELS < 8 ? REAL_CHANNELS : 8;
    localparam integer INPUT_MEMORY_HALFWORDS = PLANE_HALFWORDS * PLANES;
    localparam integer OUTPUT_MEMORY_HALFWORDS = DEPTHWISE ? 7552 :
                                                  GROUPED_C2 ? 384 : PAD1 ? 2688 : STRIDE2 ? 896 : 1664;
    localparam integer EXPECTED_HALFWORDS = OUTPUT_PIXELS * OUTPUT_CHANNELS;
    localparam integer INPUT_READS = INPUT_PIXELS * REAL_CHANNELS;
    localparam integer TOTAL_READS = WEIGHT_HALFWORDS + INPUT_READS;
    localparam integer TOTAL_WRITES = OUTPUT_PIXELS * 8;
    localparam integer TOTAL_FRAMES = OUTPUT_PIXELS * 9;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic cmd_valid = 1'b0;
    logic cmd_last = 1'b0;
    logic [63:0] cmd_data = 64'd0;
    wire cmd_ready, busy, acknowledged, frame_done, done, error;
    wire [7:0] error_code;
    wire mem_req_valid, mem_req_write, mem_rsp_ready;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    logic mem_req_ready;
    logic mem_rsp_valid;
    logic [15:0] mem_rsp_rdata;
    logic mem_rsp_error;

    logic [63:0] commands [0:53];
    logic [15:0] input_memory [0:INPUT_MEMORY_HALFWORDS-1];
    logic [15:0] weight_memory [0:WEIGHT_HALFWORDS-1];
    logic [15:0] expected [0:EXPECTED_HALFWORDS-1];
    logic [15:0] device_output [0:OUTPUT_MEMORY_HALFWORDS-1];
    logic [15:0] output_memory [0:OUTPUT_MEMORY_HALFWORDS-1];
    logic [15:0] initial_output [0:OUTPUT_MEMORY_HALFWORDS-1];
    logic pending, pending_write, pending_error;
    logic [31:0] pending_address;
    logic [15:0] pending_data;
    logic [7:0] delay_left;
    logic [31:0] rng;
    integer mode, command_count, read_requests, read_responses;
    integer weight_reads, input_reads, write_requests, write_responses;
    integer acknowledgments, frame_acks, done_count, observed_frames;
    integer age, index_value;
    string fixture;

    always #5 clk = ~clk;
`ifdef CONV_STRIDE2
    initial if (!STRIDE2 || PAD1 || GROUPED_C2 || SPLIT_OC || DEPTHWISE) $fatal(1, "stride-2 wrapper requires stride-2 fixture geometry");
    rk_conv_3x3_stride2_c4_core #(.TIMEOUT_CYCLES(32)) dut (.*);
`elsif CONV_PAD1
    initial if (!PAD1 || STRIDE2 || GROUPED_C2 || SPLIT_OC || DEPTHWISE) $fatal(1, "pad-1 wrapper requires explicit-zero-frame geometry");
    rk_conv_3x3_pad1_zero_frame_c4_core #(.TIMEOUT_CYCLES(32)) dut (.*);
`elsif CONV_GROUPED
    initial if (!GROUPED_C2 || STRIDE2 || PAD1 || SPLIT_OC || DEPTHWISE) $fatal(1, "grouped wrapper requires grouped C2 fixture geometry");
    rk_conv_3x3_grouped_c2_core #(.TIMEOUT_CYCLES(32)) dut (.*);
`elsif CONV_DEPTHWISE
    initial if (!DEPTHWISE || STRIDE2 || PAD1 || GROUPED_C2 || SPLIT_OC)
        $fatal(1, "depthwise wrapper requires C3/OC3 fixture geometry");
    rk_conv_3x3_depthwise_c3_core #(.TIMEOUT_CYCLES(32)) dut (.*);
`elsif CONV_SPLITOC
    initial if (!SPLIT_OC || STRIDE2 || PAD1 || GROUPED_C2 || DEPTHWISE) $fatal(1, "split-OC wrapper requires C16/OC8 fixture geometry");
    rk_conv_3x3_splitoc_c16_core #(.TIMEOUT_CYCLES(32)) dut (.*);
`else
    initial if (STRIDE2 || PAD1 || GROUPED_C2 || SPLIT_OC || DEPTHWISE) $fatal(1, "valid wrapper requires valid fixture geometry");
    rk_conv_3x3_valid_c4_core #(.TIMEOUT_CYCLES(32)) dut (.*);
`endif

    localparam logic [31:0] WEIGHT_BASE = DEPTHWISE ? 32'h00003000 : 32'h00002000;
    localparam logic [31:0] OUTPUT_BASE = DEPTHWISE ? 32'h00004000 : 32'h00003000;

    always @* begin
        mem_req_ready = rst_n && !pending && (rng[2:0] != 0);
        mem_rsp_valid = rst_n && pending && delay_left == 0 &&
                        !(mode == 9) && !(mode == 11 && pending_write);
        mem_rsp_rdata = pending_data;
        mem_rsp_error = pending_error;
    end

    function automatic logic [15:0] model_read(input logic [31:0] address);
        integer idx;
        begin
            if (address >= WEIGHT_BASE &&
                address < WEIGHT_BASE + WEIGHT_HALFWORDS*2 && !address[0]) begin
                idx = (address - WEIGHT_BASE) >> 1;
                model_read = weight_memory[idx];
            end else if (address >= 32'h00001000 &&
                         address < 32'h00001000 + INPUT_MEMORY_HALFWORDS*2 && !address[0]) begin
                idx = (address - 32'h00001000) >> 1;
                model_read = input_memory[idx];
            end else begin
                $fatal(1, "unexpected conv memory read %08x", address);
                model_read = 16'd0;
            end
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin : memory_model
        integer atom, lane;
        if (!rst_n) begin
            pending <= 1'b0;
            pending_write <= 1'b0;
            pending_error <= 1'b0;
            pending_address <= 32'd0;
            pending_data <= 16'd0;
            delay_left <= 0;
            rng <= 32'h3c4c9a31;
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
                    if (command_count != 54 || atom >= OUTPUT_PIXELS ||
                        mem_req_addr !== OUTPUT_BASE + 32'(atom) * 32'd16 +
                                        32'(lane) * 32'd2)
                        $fatal(1, "unexpected spatial output write #%0d address=%08x",
                               write_requests, mem_req_addr);
                    if (lane < OUTPUT_CHANNELS && mem_req_wdata !== expected[lane * OUTPUT_PIXELS + atom])
                        $fatal(1, "defined output mismatch atom=%0d lane=%0d got=%04x expected=%04x",
                               atom, lane, mem_req_wdata, expected[lane * OUTPUT_PIXELS + atom]);
                    if (lane >= OUTPUT_CHANNELS && mem_req_wdata !== 16'h0000)
                        $fatal(1, "padded OC lane nonzero atom=%0d lane=%0d", atom, lane);
                    write_requests = write_requests + 1;
                end else begin
                    if (command_count != 54)
                        $fatal(1, "operand read before all raw command words were accepted");
                    if (read_requests < WEIGHT_HALFWORDS) begin
                        index_value = read_requests;
                        if (mem_req_addr !== WEIGHT_BASE + 32'(index_value) * 32'd2)
                            $fatal(1, "kh-major weight order #%0d address=%08x",
                                   read_requests, mem_req_addr);
                        weight_reads = weight_reads + 1;
                    end else begin
                        index_value = read_requests - WEIGHT_HALFWORDS;
                        // Plane-major inner traversal: pixel, then C1 plane,
                        // then the real lanes of that plane.
                        if (index_value >= INPUT_READS ||
                            mem_req_addr !== 32'h00001000 +
                                32'(index_value % REAL_CHANNELS / LANES_PER_PLANE) *
                                    PLANE_HALFWORDS * 2 +
                                32'(index_value / REAL_CHANNELS) * 32'd16 +
                                32'(index_value % REAL_CHANNELS % LANES_PER_PLANE) * 32'd2)
                            $fatal(1, "packed C input order #%0d address=%08x",
                                   read_requests, mem_req_addr);
                        input_reads = input_reads + 1;
                    end
                    pending_data <= model_read(mem_req_addr);
                    read_requests = read_requests + 1;
                end
            end

            if (pending) begin
                if (delay_left != 0) delay_left <= delay_left - 1'b1;
                else if (mem_rsp_valid && mem_rsp_ready) begin
                    pending <= 1'b0;
                    if (pending_write) begin
                        write_responses = write_responses + 1;
                        if (!pending_error) begin
                            index_value = (pending_address - OUTPUT_BASE) >> 1;
                            output_memory[index_value] <= pending_data;
                        end
                    end else read_responses = read_responses + 1;
                end
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin : bus_stability
        logic stalled_request;
        logic held_write;
        logic [31:0] held_address;
        logic [15:0] held_data;
        logic stalled_response;
        logic held_error;
        logic [15:0] held_response_data;
        if (!rst_n) begin
            stalled_request = 1'b0;
            held_write = 1'b0;
            held_address = 0;
            held_data = 0;
            stalled_response = 1'b0;
            held_error = 1'b0;
            held_response_data = 0;
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
        integer atom, tap, tap_y, tap_x, input_pixel, kernel, channel, slot;
        if (!rst_n) begin
            acknowledgments = 0;
            frame_acks = 0;
            done_count = 0;
            observed_frames = 0;
        end else begin
            if (acknowledged) acknowledgments = acknowledgments + 1;
            if (frame_done) frame_acks = frame_acks + 1;
            if (done) done_count = done_count + 1;
            if (dut.frame_valid && dut.frame_ready) begin
                atom = observed_frames / 9;
                tap = observed_frames % 9;
                tap_y = tap / 3;
                tap_x = tap % 3;
                input_pixel = (atom / OUTPUT_W * STRIDE + tap_y) * INPUT_W +
                              atom % OUTPUT_W * STRIDE + tap_x;
                if (observed_frames >= TOTAL_FRAMES ||
                    dut.frame_output_address !== OUTPUT_BASE + 32'(atom) * 32'd16 ||
                    dut.frame_first !== (tap == 0) || dut.frame_last !== (tap == 8) ||
                    dut.frame_last_output !== (atom == OUTPUT_PIXELS-1) ||
                    dut.frame_data_mask !== ((32'd1 << REAL_CHANNELS) - 32'd1))
                    $fatal(1, "spatial frame metadata mismatch frame=%0d", observed_frames);
                for (channel = 0; channel < 32; channel = channel + 1) begin
                    if (channel < REAL_CHANNELS) begin
                        if (dut.frame_data[channel*16 +: 16] !==
                            input_memory[channel / 8 * PLANE_HALFWORDS +
                                         input_pixel*8 + channel % 8])
                            $fatal(1, "window data mismatch atom=%0d tap=%0d lane=%0d",
                                   atom, tap, channel);
                    end else if (dut.frame_data[channel*16 +: 16] !== 16'h0000)
                        $fatal(1, "unmodeled input lane nonzero channel=%0d", channel);
                end
                for (kernel = 0; kernel < 16; kernel = kernel + 1) begin
                    for (channel = 0; channel < 32; channel = channel + 1) begin
                        slot = kernel * 32 + channel;
                        if (kernel < KERNELS && channel < REAL_CHANNELS) begin
                            if (DEPTHWISE && channel != kernel) begin
                                if (dut.frame_weight[slot*16 +: 16] !== 16'h0000)
                                    $fatal(1, "depthwise off-diagonal weight nonzero k=%0d ic=%0d",
                                           kernel, channel);
                            end else if (dut.frame_weight[slot*16 +: 16] !==
                                weight_memory[tap*WEIGHT_LANES +
                                              (DEPTHWISE ? kernel :
                                               kernel*ALIGN_C + channel)])
                                $fatal(1, "kh-major weight mismatch tap=%0d OC=%0d IC=%0d",
                                       tap, kernel, channel);
                        end else if (dut.frame_weight[slot*16 +: 16] !== 16'h0000)
                            $fatal(1, "unmodeled weight nonzero kernel=%0d channel=%0d",
                                   kernel, channel);
                    end
                    if (dut.frame_weight_mask[kernel*32 +: 32] !==
                        (kernel < KERNELS ? (DEPTHWISE ? (32'd1 << kernel) :
                                             ((32'd1 << REAL_CHANNELS) - 32'd1)) : 32'h00000000))
                        $fatal(1, "weight mask mismatch kernel=%0d", kernel);
                end
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
            for (integer i = 0; i < OUTPUT_MEMORY_HALFWORDS; i = i + 1) begin
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
            for (integer i = 0; i < 54; i = i + 1) begin
                word = commands[i];
                last_word = (i == 53);
                case (mode)
                    1: if (i == 7) word = word ^ (64'h1 << 16);
                    2: if (i == 5) word = word ^ (64'h1 << 48);
                    3: if (i == 52) last_word = 1'b1;
                    4: if (i == 53) word = word ^ (64'h1 << 16);
                    5: if (i == 21) word[19:16] = 4'h1;
                    6: if (i == 27) word[47:16] = 32'h00001000;
                    7: if (i == 21) word[47:16] = GROUPED_C2 ? 32'hfffffcf0 : 32'hfffff5f0;
                    13: if (i == 21) word[47] = 1'bx;
                    14: if (i == 21) word[47] = 1'bz;
                    15: if (i == 35)
                        word[47:16] = GROUPED_C2 ? 32'hfffffd10 :
                                      SPLIT_OC ? 32'hfffff310 :
                                      PAD1 ? 32'hffffeb10 :
                                      STRIDE2 ? 32'hfffff910 : 32'hfffff310;
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
            if (!error || error_code !== wanted || busy || done || mem_req_valid || mem_rsp_ready)
                $fatal(1, "profile error=%b code=%0d expected=%0d", error, error_code, wanted);
            repeat (8) begin
                tick();
                if (!error || error_code !== wanted || busy || cmd_ready || mem_req_valid || done)
                    $fatal(1, "profile rejection not sticky");
            end
            if (read_requests != 0 || write_requests != 0)
                $fatal(1, "invalid raw stream touched operand/output memory");
        end
    endtask

    task automatic check_valid_output;
        begin
            for (age = 0; age < 300000; age = age + 1) begin
                tick();
                if (error)
                    $fatal(1, "valid spatial replay failed code=%0d reads=%0d writes=%0d",
                           error_code, read_requests, write_requests);
                if (done) disable check_valid_output;
            end
            $fatal(1, "spatial convolution watchdog");
        end
    endtask

    task automatic verify_valid_case;
        begin
            check_valid_output();
            repeat (8) tick();
            if (error || busy || done || command_count != 54 ||
                read_requests != TOTAL_READS || read_responses != TOTAL_READS ||
                weight_reads != WEIGHT_HALFWORDS || input_reads != INPUT_READS ||
                write_requests != TOTAL_WRITES || write_responses != TOTAL_WRITES ||
                acknowledgments != TOTAL_WRITES || frame_acks != OUTPUT_PIXELS ||
                done_count != 1 || observed_frames != TOTAL_FRAMES)
                $fatal(1, "traffic mismatch cmd=%0d r=%0d/%0d w=%0d/%0d ack=%0d atoms=%0d frames=%0d",
                       command_count, read_requests, read_responses, write_requests,
                       write_responses, acknowledgments, frame_acks, observed_frames);
            for (integer atom = 0; atom < OUTPUT_PIXELS; atom = atom + 1)
                for (integer channel = 0; channel < OUTPUT_CHANNELS; channel = channel + 1) begin
                    if (output_memory[atom * 8 + channel] !== expected[channel * OUTPUT_PIXELS + atom])
                        $fatal(1, "logical NCHW output mismatch atom=%0d channel=%0d",
                               atom, channel);
                    if (device_output[atom * 8 + channel] !== expected[channel * OUTPUT_PIXELS + atom])
                        $fatal(1, "source oracle/device capture mismatch atom=%0d channel=%0d",
                               atom, channel);
                end
            for (integer i = TOTAL_WRITES; i < OUTPUT_MEMORY_HALFWORDS; i = i + 1)
                if (output_memory[i] !== initial_output[i])
                    $fatal(1, "write escaped defined first output plane halfword=%0d", i);
        end
    endtask

    task automatic send_extra_qword;
        begin
            @(negedge clk);
            cmd_data = commands[0];
            cmd_last = 1'b0;
            cmd_valid = 1'b1;
            while (!cmd_ready) tick();
            tick();
            command_count = command_count + 1;
            @(negedge clk);
            cmd_valid = 1'b0;
            cmd_last = 1'b0;
        end
    endtask

    initial begin
        if (!$value$plusargs("FIXTURE=%s", fixture) || !$value$plusargs("MODE=%d", mode))
            $fatal(1, "missing test arguments");
        if (mode < 0 || mode > 15) $fatal(1, "unsupported mode");
        $readmemh({fixture, "/commands.hex"}, commands);
        $readmemh({fixture, "/input.hex"}, input_memory);
        $readmemh({fixture, "/weight.hex"}, weight_memory);
        $readmemh({fixture, "/expected.hex"}, expected);
        $readmemh({fixture, "/device.hex"}, device_output);
        reset_all();
        send_task();
        case (mode)
            0: verify_valid_case();
            1: expect_profile_error(2);
            2: expect_profile_error(1);
            3,4: expect_profile_error(3);
            5,6,7,15: expect_profile_error(4);
            8,9,10,11: begin
                for (age = 0; age < 300000 && !error; age = age + 1) tick();
                if (!error || error_code !== ((mode == 8 || mode == 10) ? 8'd5 : 8'd8) || done)
                    $fatal(1, "memory error mismatch mode=%0d code=%0d", mode, error_code);
                if ((mode == 8 || mode == 9) &&
                    (read_requests != 1 || write_requests != 0))
                    $fatal(1, "first-read fault traffic mismatch r=%0d w=%0d",
                           read_requests, write_requests);
                if (mode == 10 &&
                    (read_requests != TOTAL_READS || write_requests != 1 || write_responses != 1))
                    $fatal(1, "write error traffic mismatch r=%0d w=%0d wrsp=%0d",
                           read_requests, write_requests, write_responses);
                if (mode == 11 &&
                    (read_requests != TOTAL_READS || write_requests != 1 || write_responses != 0))
                    $fatal(1, "write timeout traffic mismatch r=%0d w=%0d wrsp=%0d",
                           read_requests, write_requests, write_responses);
                if (write_requests && output_memory[0] !== initial_output[0])
                    $fatal(1, "failed first output write modified memory");
            end
            12: begin
                verify_valid_case();
                send_extra_qword();
                if (!error || error_code !== 8'd7 || busy || done || mem_req_valid)
                    $fatal(1, "extra raw word was not rejected with code 7");
                repeat (8) begin
                    tick();
                    if (!error || error_code !== 8'd7 || busy || mem_req_valid || done)
                        $fatal(1, "extra-word rejection was not sticky");
                end
                if (command_count != 55) $fatal(1, "extra-word count mismatch");
            end
            13,14: expect_profile_error(4);
            default: $fatal(1, "unexpected mode");
        endcase
        if (DEPTHWISE)
            $display("PASS CONV_3X3_DEPTHWISE mode=%0d commands=%0d reads=%0d writes=%0d frames=%0d",
                     mode, command_count, read_requests, write_requests, observed_frames);
        else if (SPLIT_OC)
            $display("PASS CONV_3X3_SPLITOC mode=%0d commands=%0d reads=%0d writes=%0d frames=%0d",
                     mode, command_count, read_requests, write_requests, observed_frames);
        else if (GROUPED_C2)
            $display("PASS CONV_3X3_GROUPED_C2 mode=%0d commands=%0d reads=%0d writes=%0d frames=%0d",
                     mode, command_count, read_requests, write_requests, observed_frames);
        else if (PAD1)
            $display("PASS CONV_3X3_PAD1_C4 mode=%0d commands=%0d reads=%0d writes=%0d frames=%0d",
                     mode, command_count, read_requests, write_requests, observed_frames);
        else if (STRIDE2)
            $display("PASS CONV_3X3_STRIDE2_C4 mode=%0d commands=%0d reads=%0d writes=%0d frames=%0d",
                     mode, command_count, read_requests, write_requests, observed_frames);
        else
            $display("PASS CONV_3X3_VALID_C4 mode=%0d commands=%0d reads=%0d writes=%0d frames=%0d",
                     mode, command_count, read_requests, write_requests, observed_frames);
        $finish;
    end

    initial begin
        #20000000;
        $fatal(1, "testbench watchdog");
    end
endmodule
