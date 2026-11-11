// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Equivalence harness: the adopted per-profile conv core vs the runtime-decoded
// conv engine (EXPERIMENTAL prototype) on the SAME frozen fixture.
//
// Both engines receive the SAME unchanged raw command QWORDs, the same packed
// operand bytes and the same memory handshake contract, each through its own
// memory model with identical initial contents. The bench compares:
//
//   * the complete operand read-address sequence (in order);
//   * the complete output write sequence (address, data, order);
//   * both complete memory images (written bytes and untouched canaries);
//   * completion/acknowledgement/frame counters and terminal status;
//   * the buffer sizes the runtime decoder published against the fixture BOs.
//
// The complete memory images are dumped as hex for the runner, which compares
// the written output BO bytes against the fixture's expected/device capture.
//
// MODE=0 is the equivalence replay. MODE>=1 exercises the runtime decoder only
// (the reference core is held in reset): MUT_MODE selects a mutation of the raw
// stream and MUT_CODE is the explicit decoder code it must raise. A rejected
// stream must not touch operand or output memory.
module tb_conv_runtime_equiv #(
    parameter int unsigned FAMILY = 0,        // 0 = vendor 3x3 core, 1 = conv-simple
    parameter int unsigned NUM_CMD = 54,
    // Elaboration widths of the runtime engine under test. The adopted
    // reference cores are fixed at ATOMIC_C=32 / ATOMIC_K=16, so the runtime
    // frame buses (ATOMIC_C lanes, ATOMIC_K groups) must be expanded into the
    // reference packing before the per-frame hashes are compared. This is a
    // harness-layout normalisation only; no runtime RTL is changed.
    parameter int unsigned RT_ATOMIC_C = 16,
    parameter int unsigned RT_ATOMIC_K = 16,
    parameter bit V_STRIDE2 = 1'b0,
    parameter bit V_PAD1 = 1'b0,
    parameter bit V_GROUPED = 1'b0,
    parameter bit V_SPLITOC = 1'b0,
    parameter bit V_DEPTHWISE = 1'b0,
    parameter int unsigned S_PROFILE = 0,
    parameter int unsigned S_INPUT_H = 8,
    parameter int unsigned S_INPUT_W = 8,
    parameter int unsigned S_KH = 3,
    parameter int unsigned S_KW = 3,
    parameter int unsigned S_INPUT_CHANNELS = 4,
    parameter int unsigned S_KERNELS = 8,
    parameter int unsigned S_C1_BLOCKS = 2,
    parameter int unsigned S_ALIGN_C = 8,
    parameter int unsigned S_PACK_C2 = 4,
    parameter int unsigned S_CHUNK_LANES = 16,
    parameter bit S_OUTPUT_FP16 = 1'b1,
    parameter int unsigned MEM_WORDS = 16384,
    parameter int unsigned TIMEOUT_CYCLES = 400000
);
    localparam int unsigned CMD_WORDS = 54;
    localparam int unsigned FIFO_DEPTH = 1024;
    localparam int unsigned CMD_LAST_INDEX = (FAMILY == 1) ? 50 : 53;

    logic clk = 1'b0;
    always #5 clk = ~clk;

    logic rst_n = 1'b0;
    logic ref_rst_n = 1'b0;

    logic        cmd_valid_rt, cmd_valid_ref;
    logic [63:0] cmd_data;
    logic        cmd_last;
    wire         rt_cmd_ready, ref_cmd_ready;

    wire        rt_busy, rt_acknowledged, rt_frame_done, rt_done;
    wire        rt_error;
    wire [7:0]  rt_error_code;
    wire        rt_req_valid, rt_req_write, rt_rsp_ready;
    wire [31:0] rt_req_addr;
    wire [15:0] rt_req_wdata;
    logic       rt_req_ready, rt_rsp_valid, rt_rsp_error;
    logic [15:0] rt_rsp_rdata;
    wire [31:0] rt_input_base, rt_weight_base, rt_output_base;
    wire [31:0] rt_input_bytes, rt_weight_bytes, rt_output_bytes;
    wire [8:0]  rt_total_atoms;
    wire [7:0]  rt_taps;
    wire        rt_output_fp16;

    wire        ref_busy, ref_acknowledged, ref_frame_done, ref_done;
    wire        ref_error;
    wire [7:0]  ref_error_code;
    wire        ref_req_valid, ref_req_write, ref_rsp_ready;
    wire [31:0] ref_req_addr;
    wire [15:0] ref_req_wdata;
    logic       ref_req_ready, ref_rsp_valid, ref_rsp_error;
    logic [15:0] ref_rsp_rdata;

    logic        rt_dump_req, ref_dump_req;

    rk_conv_runtime_core #(.ATOMIC_C(RT_ATOMIC_C), .ATOMIC_K(RT_ATOMIC_K)) runtime (
        .clk, .rst_n,
        .cmd_valid(cmd_valid_rt), .cmd_ready(rt_cmd_ready),
        .cmd_data, .cmd_last,
        .busy(rt_busy), .acknowledged(rt_acknowledged),
        .frame_done(rt_frame_done), .done(rt_done),
        .error(rt_error), .error_code(rt_error_code),
        .mem_req_valid(rt_req_valid), .mem_req_ready(rt_req_ready),
        .mem_req_write(rt_req_write), .mem_req_addr(rt_req_addr),
        .mem_req_wdata(rt_req_wdata),
        .mem_rsp_valid(rt_rsp_valid), .mem_rsp_ready(rt_rsp_ready),
        .mem_rsp_rdata(rt_rsp_rdata), .mem_rsp_error(rt_rsp_error),
        .config_input_base(rt_input_base), .config_weight_base(rt_weight_base),
        .config_output_base(rt_output_base),
        .input_bytes(rt_input_bytes), .weight_bytes(rt_weight_bytes),
        .output_bytes(rt_output_bytes),
        .obs_total_atoms(rt_total_atoms), .obs_taps(rt_taps),
        .obs_output_fp16(rt_output_fp16));

    generate
        if (FAMILY == 0) begin : g_vendor
            rk_conv_3x3_valid_c4_core #(
                .STRIDE2(V_STRIDE2), .PAD1_ZERO_FRAME(V_PAD1),
                .GROUPED_C2(V_GROUPED), .SPLIT_OC_C16(V_SPLITOC),
                .DEPTHWISE_C3(V_DEPTHWISE), .TIMEOUT_CYCLES(65536)
            ) reference (
                .clk, .rst_n(ref_rst_n),
                .cmd_valid(cmd_valid_ref), .cmd_ready(ref_cmd_ready),
                .cmd_data, .cmd_last,
                .busy(ref_busy), .acknowledged(ref_acknowledged),
                .frame_done(ref_frame_done), .done(ref_done),
                .error(ref_error), .error_code(ref_error_code),
                .mem_req_valid(ref_req_valid), .mem_req_ready(ref_req_ready),
                .mem_req_write(ref_req_write), .mem_req_addr(ref_req_addr),
                .mem_req_wdata(ref_req_wdata),
                .mem_rsp_valid(ref_rsp_valid), .mem_rsp_ready(ref_rsp_ready),
                .mem_rsp_rdata(ref_rsp_rdata), .mem_rsp_error(ref_rsp_error));
        end else begin : g_simple
            rk_conv_simple_core #(
                .PROFILE(S_PROFILE),
                .INPUT_H(S_INPUT_H), .INPUT_W(S_INPUT_W),
                .KH(S_KH), .KW(S_KW),
                .INPUT_CHANNELS(S_INPUT_CHANNELS), .KERNELS(S_KERNELS),
                .C1_BLOCKS(S_C1_BLOCKS), .ALIGN_C(S_ALIGN_C),
                .PACK_C2(S_PACK_C2), .CHUNK_LANES(S_CHUNK_LANES),
                .OUTPUT_FP16(S_OUTPUT_FP16), .TIMEOUT_CYCLES(65536)
            ) reference (
                .clk, .rst_n(ref_rst_n),
                .cmd_valid(cmd_valid_ref), .cmd_ready(ref_cmd_ready),
                .cmd_data, .cmd_last,
                .busy(ref_busy), .acknowledged(ref_acknowledged),
                .frame_done(ref_frame_done), .done(ref_done),
                .error(ref_error), .error_code(ref_error_code),
                .mem_req_valid(ref_req_valid), .mem_req_ready(ref_req_ready),
                .mem_req_write(ref_req_write), .mem_req_addr(ref_req_addr),
                .mem_req_wdata(ref_req_wdata),
                .mem_rsp_valid(ref_rsp_valid), .mem_rsp_ready(ref_rsp_ready),
                .mem_rsp_rdata(ref_rsp_rdata), .mem_rsp_error(ref_rsp_error));
        end
    endgenerate

    // Reference engine's frame stream is the schedule contract: observe it at
    // the core/front boundary (the production per-profile cores expose the
    // front bus inside the core; only the selected family is elaborated).
    wire        ref_frame_valid, ref_frame_ready;
    wire [31:0] ref_frame_address, ref_frame_data_mask;
    wire [511:0] ref_frame_data, ref_frame_weight_mask;
    wire [8191:0] ref_frame_weight;
    wire g_ref_first, g_ref_last, g_ref_last_output;
    generate
        if (FAMILY == 0) begin : g_ref_frame
            assign ref_frame_valid = g_vendor.reference.front.frame_valid;
            assign ref_frame_ready = g_vendor.reference.front.frame_ready;
            assign ref_frame_address = g_vendor.reference.front.frame_output_address;
            assign ref_frame_data_mask =
                g_vendor.reference.front.frame_data_mask;
            assign ref_frame_weight_mask =
                g_vendor.reference.front.frame_weight_mask;
            assign ref_frame_data = g_vendor.reference.front.frame_data;
            assign ref_frame_weight = g_vendor.reference.front.frame_weight;
            assign g_ref_first = g_vendor.reference.front.frame_first;
            assign g_ref_last = g_vendor.reference.front.frame_last;
            assign g_ref_last_output =
                g_vendor.reference.front.frame_last_output;
        end else begin : g_simple_frame
            assign ref_frame_valid = g_simple.reference.front.frame_valid;
            assign ref_frame_ready = g_simple.reference.front.frame_ready;
            assign ref_frame_address = g_simple.reference.front.frame_output_address;
            assign ref_frame_data_mask =
                g_simple.reference.front.frame_data_mask;
            assign ref_frame_weight_mask =
                g_simple.reference.front.frame_weight_mask;
            assign ref_frame_data = g_simple.reference.front.frame_data;
            assign ref_frame_weight = g_simple.reference.front.frame_weight;
            assign g_ref_first = g_simple.reference.front.frame_first;
            assign g_ref_last = g_simple.reference.front.frame_last;
            assign g_ref_last_output =
                g_simple.reference.front.frame_last_output;
        end
    endgenerate

    wire rt_frame_fire = runtime.frame_valid && runtime.frame_ready;
    wire ref_frame_fire = ref_frame_valid && ref_frame_ready;

    // Frame-stream comparison: a per-frame hash of (address,masks), data and
    // weight. The first difference is reported by component so a front
    // construction bug is localised without guessing.
    function automatic logic [63:0] frame_meta_hash(
        input logic [31:0] address, input logic [31:0] data_mask,
        input logic [511:0] weight_mask, input logic first, last, last_out);
        logic [63:0] h;
        begin
            h = 64'hcbf2_9ce4_8422_2325 ^ {32'd0, address};
            h = h * 64'd1099511628211 ^ {32'd0, data_mask};
            h = h * 64'd1099511628211 ^
                {32'd0, weight_mask[511:480]} ^ {32'd0, weight_mask[255:224]};
            h = h * 64'd1099511628211 ^
                {63'd0, first} ^ {62'd0, last, 1'b0} ^
                {63'd0, last_out};
            frame_meta_hash = h;
        end
    endfunction

    function automatic logic [63:0] frame_bus_hash(input logic [8191:0] bus,
                                                   input integer words);
        integer i;
        logic [63:0] h;
        begin
            h = 64'h8422_2325_cbf2_9ce4;
            for (i = 0; i < words; i = i + 1)
                h = (h ^ bus[i*64 +: 64]) * 64'd1099511628211;
            frame_bus_hash = h;
        end
    endfunction

    localparam int unsigned FRAME_FIFO = 32;
    logic [191:0] frame_fifo_rt [0:FRAME_FIFO-1];
    logic [191:0] frame_fifo_ref [0:FRAME_FIFO-1];
    integer fr_rt_push, fr_rt_pop, fr_ref_push, fr_ref_pop;
    integer rt_frames, ref_frames;

    tb_runtime_mem #(.WORDS(MEM_WORDS)) mem_rt (
        .clk, .rst_n,
        .req_valid(rt_req_valid), .req_ready(rt_req_ready),
        .req_write(rt_req_write), .req_addr(rt_req_addr),
        .req_wdata(rt_req_wdata),
        .rsp_valid(rt_rsp_valid), .rsp_ready(rt_rsp_ready),
        .rsp_rdata(rt_rsp_rdata), .rsp_error(rt_rsp_error),
        .dump_req(rt_dump_req));

    tb_runtime_mem #(.WORDS(MEM_WORDS), .IS_REF(1'b1)) mem_ref (
        .clk, .rst_n(ref_rst_n),
        .req_valid(ref_req_valid), .req_ready(ref_req_ready),
        .req_write(ref_req_write), .req_addr(ref_req_addr),
        .req_wdata(ref_req_wdata),
        .rsp_valid(ref_rsp_valid), .rsp_ready(ref_rsp_ready),
        .rsp_rdata(ref_rsp_rdata), .rsp_error(ref_rsp_error),
        .dump_req(ref_dump_req));

    logic [63:0] commands [0:NUM_CMD-1];

    integer in_base, in_hw, w_base, w_hw, out_base, out_hw;
    integer mode, mut_mode, mut_index, mut_code;
    integer mut_xor_lo, mut_xor_hi, mut_val_lo, mut_val_hi;
    string fixture;

    integer rt_reads, ref_reads, rt_writes, ref_writes;
    integer rt_acks, ref_acks, rt_frame_acks, ref_frame_acks;
    integer rt_dones, ref_dones;
    logic   rt_done_d, ref_done_d;
    integer age, index_i;

    logic [31:0] rd_fifo_rt [0:FIFO_DEPTH-1];
    logic [31:0] rd_fifo_ref [0:FIFO_DEPTH-1];
    logic [47:0] wr_fifo_rt [0:FIFO_DEPTH-1];
    logic [47:0] wr_fifo_ref [0:FIFO_DEPTH-1];
    integer rd_rt_push, rd_rt_pop, rd_ref_push, rd_ref_pop;
    integer wr_rt_push, wr_rt_pop, wr_ref_push, wr_ref_pop;

    task automatic tick;
        begin @(posedge clk); #2; end
    endtask

    // ------------------------------------------------------------------
    // First-frame ASSEMBLE cycle trace (diagnostic only, TB-side hierarchical
    // probes; enabled until the first frame is emitted). This separates the
    // operand read address stream from the placement lane counters when the
    // first-frame data bus is wrong.
    // ------------------------------------------------------------------
    integer asm_dbg_count;
    logic   asm_dbg_en;
    initial begin
        asm_dbg_count = 0;
        asm_dbg_en = 1'b1;
    end
    always @(posedge clk) begin
        if (asm_dbg_en && runtime.front.state_q == 4'd5 && rt_frames == 0 &&
            asm_dbg_count <= 80) begin
            $display("ASM_DBG n=%0d a=%0d re=%0d ra=%0d rd=%04x pc=%0d ir=%0d ci=%0d fw=%0d ic=%0d pix=%0d",
                     asm_dbg_count, runtime.front.a_index_q,
                     runtime.front.input_read_en, runtime.front.i_raddr_q,
                     runtime.front.input_rdata_q, runtime.front.p_c_q,
                     runtime.front.i_raddr_q, runtime.front.c_issue_q,
                     runtime.front.cfg_frame_weight_halfwords,
                     runtime.front.cfg_input_channels,
                     runtime.front.frame_pixel);
            asm_dbg_count <= asm_dbg_count + 1;
            if (asm_dbg_count == 80) asm_dbg_en <= 1'b0;
        end
    end

    // ------------------------------------------------------------------
    // Clocked frame-stream observation and comparison.
    // ------------------------------------------------------------------
    // ------------------------------------------------------------------
    // Frame-bus layout normalisation (runtime ATOMIC_C=16 -> reference 32).
    // The runtime front packs weight halfword (k*ATOMIC_C + lane)*16 while the
    // adopted front packs (k*32 + lane)*16. Expanding the lane group into the
    // reference's 32-lane group (upper lanes zero, as the reference's masked
    // lanes are) makes the per-frame hashes compare equal content. Data lanes
    // and the data mask live at bit 0 upward in both, so a width extension is
    // enough there.
    // ------------------------------------------------------------------
    localparam int REF_ATOMIC_C = 32;
    localparam int REF_ATOMIC_K = 16;
    wire [REF_ATOMIC_K*REF_ATOMIC_C*16-1:0] rt_weight_norm;
    wire [REF_ATOMIC_K*REF_ATOMIC_C-1:0]    rt_weight_mask_norm;
    wire [REF_ATOMIC_C*16-1:0]              rt_data_norm;
    wire [REF_ATOMIC_C-1:0]                 rt_data_mask_norm;

    // Every reference lane group is driven in full (low RT groups carry the
    // runtime's (lane,channel) slots, the rest are zero) so no bit is left
    // undriven (an unwritten slice would hash as X).
    generate
        for (genvar nk = 0; nk < REF_ATOMIC_K; nk = nk + 1) begin : g_rt_frames
            if (nk < RT_ATOMIC_K) begin : g_copy
                assign rt_weight_norm[(nk*REF_ATOMIC_C)*16 +: REF_ATOMIC_C*16] =
                    {{((REF_ATOMIC_C-RT_ATOMIC_C)*16){1'b0}},
                     runtime.frame_weight[(nk*RT_ATOMIC_C)*16 +: RT_ATOMIC_C*16]};
                assign rt_weight_mask_norm[nk*REF_ATOMIC_C +: REF_ATOMIC_C] =
                    {{(REF_ATOMIC_C-RT_ATOMIC_C){1'b0}},
                     runtime.frame_weight_mask[nk*RT_ATOMIC_C +: RT_ATOMIC_C]};
            end else begin : g_zero
                assign rt_weight_norm[(nk*REF_ATOMIC_C)*16 +: REF_ATOMIC_C*16] = '0;
                assign rt_weight_mask_norm[nk*REF_ATOMIC_C +: REF_ATOMIC_C] = '0;
            end
        end
    endgenerate
    assign rt_data_norm = {{(REF_ATOMIC_C-RT_ATOMIC_C){16'd0}}, runtime.frame_data};
    assign rt_data_mask_norm = {{(REF_ATOMIC_C-RT_ATOMIC_C){1'b0}}, runtime.frame_data_mask};

    always @(posedge clk) begin : frame_observer
        if (!rst_n) begin
            fr_rt_push = 0; fr_rt_pop = 0;
            fr_ref_push = 0; fr_ref_pop = 0;
            rt_frames = 0; ref_frames = 0;
        end else begin
            if (rt_frame_fire) begin
                frame_fifo_rt[fr_rt_push % FRAME_FIFO] = {
                    frame_meta_hash(runtime.frame_output_address,
                                    rt_data_mask_norm,
                                    rt_weight_mask_norm,
                                    runtime.frame_first, runtime.frame_last,
                                    runtime.frame_last_output),
                    frame_bus_hash(rt_data_norm, 8),
                    frame_bus_hash(rt_weight_norm, 128)};
                fr_rt_push = fr_rt_push + 1;
                rt_frames = rt_frames + 1;
            end
            if (ref_frame_fire) begin
                frame_fifo_ref[fr_ref_push % FRAME_FIFO] = {
                    frame_meta_hash(ref_frame_address,
                                    {{(REF_ATOMIC_C-32){1'b0}}, ref_frame_data_mask},
                                    {{(REF_ATOMIC_K*REF_ATOMIC_C-512){1'b0}},
                                     ref_frame_weight_mask},
                                    g_ref_first, g_ref_last, g_ref_last_output),
                    frame_bus_hash({512'd0, ref_frame_data}, 8),
                    frame_bus_hash(ref_frame_weight, 128)};
                fr_ref_push = fr_ref_push + 1;
                ref_frames = ref_frames + 1;
            end
            if (fr_rt_push - fr_rt_pop >= FRAME_FIFO ||
                fr_ref_push - fr_ref_pop >= FRAME_FIFO)
                $fatal(1, "frame comparison FIFO overflow");
            if (fr_rt_pop < fr_rt_push && fr_ref_pop < fr_ref_push) begin
                if (frame_fifo_rt[fr_rt_pop % FRAME_FIFO] !==
                    frame_fifo_ref[fr_ref_pop % FRAME_FIFO]) begin
                    if (frame_fifo_rt[fr_rt_pop % FRAME_FIFO][191:128] !==
                        frame_fifo_ref[fr_ref_pop % FRAME_FIFO][191:128])
                        $fatal(1, "frame META diverged at frame %0d/%0d: rt=%016x ref=%016x",
                               fr_rt_pop, fr_ref_pop,
                               frame_fifo_rt[fr_rt_pop % FRAME_FIFO][191:128],
                               frame_fifo_ref[fr_ref_pop % FRAME_FIFO][191:128]);
                    else if (frame_fifo_rt[fr_rt_pop % FRAME_FIFO][127:64] !==
                             frame_fifo_ref[fr_ref_pop % FRAME_FIFO][127:64]) begin
                        if (fr_rt_pop == 0) begin
                            // First-frame forensics: show the raw data bus words
                            // and the operand stores of both engines. This
                            // separates an operand-load problem from a
                            // frame-assembly/placement problem.
                            $display("DATA_DBG rt_words=%016x %016x %016x %016x %016x %016x %016x %016x",
                                     runtime.frame_data[63:0],
                                     runtime.frame_data[127:64],
                                     runtime.frame_data[191:128],
                                     runtime.frame_data[255:192],
                                     runtime.frame_data[319:256],
                                     runtime.frame_data[383:320],
                                     runtime.frame_data[447:384],
                                     runtime.frame_data[511:448]);
                            $display("DATA_DBG ref_words=%016x %016x %016x %016x %016x %016x %016x %016x",
                                     ref_frame_data[63:0],
                                     ref_frame_data[127:64],
                                     ref_frame_data[191:128],
                                     ref_frame_data[255:192],
                                     ref_frame_data[319:256],
                                     ref_frame_data[383:320],
                                     ref_frame_data[447:384],
                                     ref_frame_data[511:448]);
                            $display("DATA_DBG rt_store=%04x %04x %04x %04x %04x %04x %04x %04x",
                                     runtime.front.input_store[0],
                                     runtime.front.input_store[1],
                                     runtime.front.input_store[2],
                                     runtime.front.input_store[3],
                                     runtime.front.input_store[4],
                                     runtime.front.input_store[5],
                                     runtime.front.input_store[6],
                                     runtime.front.input_store[7]);
                        end
                        $fatal(1, "frame DATA diverged at frame %0d/%0d: rt=%016x ref=%016x",
                               fr_rt_pop, fr_ref_pop,
                               frame_fifo_rt[fr_rt_pop % FRAME_FIFO][127:64],
                               frame_fifo_ref[fr_ref_pop % FRAME_FIFO][127:64]);
                    end
                    else
                        $fatal(1, "frame WEIGHT diverged at frame %0d/%0d: rt=%016x ref=%016x",
                               fr_rt_pop, fr_ref_pop,
                               frame_fifo_rt[fr_rt_pop % FRAME_FIFO][63:0],
                               frame_fifo_ref[fr_ref_pop % FRAME_FIFO][63:0]);
                end
                fr_rt_pop = fr_rt_pop + 1;
                fr_ref_pop = fr_ref_pop + 1;
            end
        end
    end

    // ------------------------------------------------------------------
    // Clocked traffic observation: BO-range checks, read/write sequence
    // comparison (FIFO), counters. This is the equivalence evidence that the
    // two engines consumed the same operands in the same order and wrote the
    // same bytes in the same order.
    // ------------------------------------------------------------------
    always @(posedge clk) begin : observer
        if (!rst_n) begin
            rd_rt_push = 0; rd_rt_pop = 0;
            rd_ref_push = 0; rd_ref_pop = 0;
            wr_rt_push = 0; wr_rt_pop = 0;
            wr_ref_push = 0; wr_ref_pop = 0;
            rt_reads = 0; ref_reads = 0; rt_writes = 0; ref_writes = 0;
            rt_acks = 0; ref_acks = 0; rt_frame_acks = 0; ref_frame_acks = 0;
            rt_dones = 0; ref_dones = 0;
            rt_done_d = 1'b0; ref_done_d = 1'b0;
        end else begin
            if (rt_acknowledged) rt_acks = rt_acks + 1;
            if (ref_acknowledged) ref_acks = ref_acks + 1;
            if (rt_frame_done) rt_frame_acks = rt_frame_acks + 1;
            if (ref_frame_done) ref_frame_acks = ref_frame_acks + 1;
            if (rt_done && !rt_done_d) rt_dones = rt_dones + 1;
            if (ref_done && !ref_done_d) ref_dones = ref_dones + 1;
            rt_done_d = rt_done;
            ref_done_d = ref_done;
            if (rt_req_valid && rt_req_ready) begin
                if (rt_req_write) begin
                    if (rt_req_addr < out_base ||
                        rt_req_addr >= out_base + out_hw * 2)
                        $fatal(1, "runtime write outside the output BO: %08x",
                               rt_req_addr);
                    wr_fifo_rt[wr_rt_push % FIFO_DEPTH] =
                        {rt_req_addr[31:1], rt_req_wdata};
                    wr_rt_push = wr_rt_push + 1;
                    rt_writes = rt_writes + 1;
                end else begin
                    if (!((rt_req_addr >= in_base &&
                           rt_req_addr < in_base + in_hw * 2) ||
                          (rt_req_addr >= w_base &&
                           rt_req_addr < w_base + w_hw * 2)))
                        $fatal(1, "runtime read outside the operand BOs: %08x",
                               rt_req_addr);
                    rd_fifo_rt[rd_rt_push % FIFO_DEPTH] = rt_req_addr;
                    rd_rt_push = rd_rt_push + 1;
                    rt_reads = rt_reads + 1;
                end
            end
            if (ref_req_valid && ref_req_ready) begin
                if (ref_req_write) begin
                    if (ref_req_addr < out_base ||
                        ref_req_addr >= out_base + out_hw * 2)
                        $fatal(1, "reference write outside the output BO: %08x",
                               ref_req_addr);
                    wr_fifo_ref[wr_ref_push % FIFO_DEPTH] =
                        {ref_req_addr[31:1], ref_req_wdata};
                    wr_ref_push = wr_ref_push + 1;
                    ref_writes = ref_writes + 1;
                end else begin
                    if (!((ref_req_addr >= in_base &&
                           ref_req_addr < in_base + in_hw * 2) ||
                          (ref_req_addr >= w_base &&
                           ref_req_addr < w_base + w_hw * 2)))
                        $fatal(1, "reference read outside the operand BOs: %08x",
                               ref_req_addr);
                    rd_fifo_ref[rd_ref_push % FIFO_DEPTH] = ref_req_addr;
                    rd_ref_push = rd_ref_push + 1;
                    ref_reads = ref_reads + 1;
                end
            end
            if (rd_rt_push - rd_rt_pop >= FIFO_DEPTH ||
                rd_ref_push - rd_ref_pop >= FIFO_DEPTH ||
                wr_rt_push - wr_rt_pop >= FIFO_DEPTH ||
                wr_ref_push - wr_ref_pop >= FIFO_DEPTH)
                $fatal(1, "traffic comparison FIFO overflow");
            if (rd_rt_pop < rd_rt_push && rd_ref_pop < rd_ref_push) begin
                if (rd_fifo_rt[rd_rt_pop % FIFO_DEPTH] !==
                    rd_fifo_ref[rd_ref_pop % FIFO_DEPTH])
                    $fatal(1, "operand read sequence diverged at read %0d/%0d: rt=%08x ref=%08x",
                           rd_rt_pop, rd_ref_pop,
                           rd_fifo_rt[rd_rt_pop % FIFO_DEPTH],
                           rd_fifo_ref[rd_ref_pop % FIFO_DEPTH]);
                rd_rt_pop = rd_rt_pop + 1;
                rd_ref_pop = rd_ref_pop + 1;
            end
            if (wr_rt_pop < wr_rt_push && wr_ref_pop < wr_ref_push) begin
                if (wr_fifo_rt[wr_rt_pop % FIFO_DEPTH] !==
                    wr_fifo_ref[wr_ref_pop % FIFO_DEPTH])
                    $fatal(1, "output write sequence diverged at write %0d/%0d: rt=%011x ref=%011x",
                           wr_rt_pop, wr_ref_pop,
                           wr_fifo_rt[wr_rt_pop % FIFO_DEPTH],
                           wr_fifo_ref[wr_ref_pop % FIFO_DEPTH]);
                wr_rt_pop = wr_rt_pop + 1;
                wr_ref_pop = wr_ref_pop + 1;
            end
        end
    end

    // ------------------------------------------------------------------
    // Main sequence.
    // ------------------------------------------------------------------
    integer tb_cycles;
    integer stall_snapshot_writes, stall_snapshot_frames, stall_count;
    initial tb_cycles = 0;
    initial begin
        stall_snapshot_writes = -1;
        stall_snapshot_frames = -1;
        stall_count = 0;
    end
    always @(posedge clk) begin
        tb_cycles <= tb_cycles + 1;
        if (tb_cycles != 0 && (tb_cycles % 20000) == 0) begin
            if (rt_writes == stall_snapshot_writes &&
                ref_writes == stall_snapshot_writes &&
                rt_frames == stall_snapshot_frames &&
                ref_frames == stall_snapshot_frames) begin
                stall_count = stall_count + 1;
                if (stall_count >= 1)
                    $fatal(1, "bench stalled: no frame/write progress for 40k cycles (rt_frames=%0d ref_frames=%0d rt_writes=%0d ref_writes=%0d rt_done=%0d ref_done=%0d)",
                           rt_frames, ref_frames, rt_writes, ref_writes,
                           rt_dones, ref_dones);
            end else begin
                stall_count = 0;
            end
            stall_snapshot_writes = rt_writes;
            stall_snapshot_frames = rt_frames;
            $display("TB_PROGRESS cycles=%0d rt_done=%0d ref_done=%0d rt_err=%0d ref_err=%0d reads=%0d/%0d writes=%0d/%0d acks=%0d/%0d",
                     tb_cycles, rt_done, ref_done, rt_error, ref_error,
                     rt_reads, ref_reads, rt_writes, ref_writes,
                     rt_acks, ref_acks);
            $fflush();
        end
    end

    task automatic request_dumps;
        begin
            rt_dump_req = 1'b1;
            ref_dump_req = (mode == 0) ? 1'b1 : 1'b0;
            repeat (6) tick();
            rt_dump_req = 1'b0;
            ref_dump_req = 1'b0;
        end
    endtask

    task automatic send_stream;
        logic [63:0] word;
        logic        last_bit;
        integer      i;
        integer      wait_ok;
        begin
            for (i = 0; i < NUM_CMD; i = i + 1) begin
                word = commands[i];
                last_bit = (i == CMD_LAST_INDEX);
                if (mut_mode == 1 && i == mut_index)
                    word[47:16] = word[47:16] ^ mut_xor_lo[31:0];
                else if (mut_mode == 2 && i == mut_index)
                    word[63:48] = word[63:48] ^ mut_xor_lo[15:0];
                else if (mut_mode == 3 && i == mut_index)
                    word[15:0] = word[15:0] ^ mut_xor_lo[15:0];
                else if (mut_mode == 4 && i == mut_index)
                    last_bit = 1'b1;
                else if (mut_mode == 6 && i == mut_index)
                    word[47:16] = mut_val_lo[31:0];
                else if (mut_mode == 8 && i == mut_index)
                    word = commands[mut_index + 1];
                else if (mut_mode == 8 && i == mut_index + 1)
                    word = commands[mut_index];
                if (mut_mode == 10 && i == mut_index) word[47] = 1'bx;
                // Wait, with cmd_valid low, until both engines can accept the
                // next word; then drive it for exactly one clock edge and drop
                // cmd_valid again. A word must never be accepted twice (the
                // strict decoders accept exactly one job).
                wait_ok = 0;
                while (wait_ok == 0) begin
                    @(negedge clk);
                    if (rt_error || (mode == 0 && ref_error))
                        wait_ok = 2;
                    else if (rt_cmd_ready &&
                             (mode != 0 || ref_cmd_ready))
                        wait_ok = 1;
                end
                if (wait_ok == 2) begin
                    cmd_last = 1'b0;
                    i = NUM_CMD;
                end else begin
                    cmd_data = word;
                    cmd_last = last_bit;
                    cmd_valid_rt = 1'b1;
                    cmd_valid_ref = (mode == 0);
                    @(posedge clk);
                    @(negedge clk);
                    cmd_valid_rt = 1'b0;
                    cmd_valid_ref = 1'b0;
                    if (rt_error || (mode == 0 && ref_error)) begin
                        cmd_last = 1'b0;
                        i = NUM_CMD;
                    end
                end
            end
            if (mut_mode == 9) begin
                // One extra raw word after the complete stream: the decoder
                // has locked the configuration and must refuse a second job.
                wait_ok = 0;
                while (wait_ok == 0) begin
                    @(negedge clk);
                    if (rt_error) wait_ok = 2;
                    else if (rt_cmd_ready) wait_ok = 1;
                end
                if (wait_ok == 1) begin
                    cmd_data = commands[0];
                    cmd_last = 1'b0;
                    cmd_valid_rt = 1'b1;
                    @(posedge clk);
                    @(negedge clk);
                    cmd_valid_rt = 1'b0;
                end
            end
            @(negedge clk);
            cmd_valid_rt = 1'b0; cmd_valid_ref = 1'b0;
            cmd_last = 1'b0;
        end
    endtask

    task automatic load_fixture;
        begin
            for (index_i = 0; index_i < NUM_CMD; index_i = index_i + 1)
                commands[index_i] = 64'h0;
            $readmemh({fixture, "/commands.hex"}, commands);
        end
    endtask

    initial begin : main
        integer dummy;
        if (!$value$plusargs("FIXTURE=%s", fixture))
            $fatal(1, "missing +FIXTURE=<fixture dir>");
        if (!$value$plusargs("MODE=%d", mode)) $fatal(1, "missing +MODE");
        if (!$value$plusargs("IN_BASE=%d", in_base)) $fatal(1, "missing +IN_BASE");
        if (!$value$plusargs("IN_HW=%d", in_hw)) $fatal(1, "missing +IN_HW");
        if (!$value$plusargs("W_BASE=%d", w_base)) $fatal(1, "missing +W_BASE");
        if (!$value$plusargs("W_HW=%d", w_hw)) $fatal(1, "missing +W_HW");
        if (!$value$plusargs("OUT_BASE=%d", out_base)) $fatal(1, "missing +OUT_BASE");
        if (!$value$plusargs("OUT_HW=%d", out_hw)) $fatal(1, "missing +OUT_HW");
        mut_mode = 0; mut_index = 0; mut_code = 0;
        mut_xor_lo = 0; mut_xor_hi = 0; mut_val_lo = 0; mut_val_hi = 0;
        dummy = $value$plusargs("MUT_MODE=%d", mut_mode);
        dummy = $value$plusargs("MUT_INDEX=%d", mut_index);
        dummy = $value$plusargs("MUT_CODE=%d", mut_code);
        dummy = $value$plusargs("MUT_XOR_LO=%d", mut_xor_lo);
        dummy = $value$plusargs("MUT_XOR_HI=%d", mut_xor_hi);
        dummy = $value$plusargs("MUT_VAL_LO=%d", mut_val_lo);
        dummy = $value$plusargs("MUT_VAL_HI=%d", mut_val_hi);

        load_fixture();
        cmd_valid_rt = 1'b0; cmd_valid_ref = 1'b0;
        cmd_data = 64'd0; cmd_last = 1'b0;

        @(negedge clk); rst_n = 1'b0; ref_rst_n = 1'b0;
        repeat (4) tick();
        @(negedge clk); rst_n = 1'b1;
        if (mode == 0) ref_rst_n = 1'b1;
        repeat (4) tick();
        if (!rt_cmd_ready) $fatal(1, "runtime core not ready after reset");
        if (mode == 0 && !ref_cmd_ready)
            $fatal(1, "reference core not ready after reset");

        send_stream();

        age = 0;
        while (age < TIMEOUT_CYCLES) begin
            tick();
            age = age + 1;
            if (mode == 0) begin
                if ((rt_dones > 0 || rt_error) && (ref_dones > 0 || ref_error))
                    age = TIMEOUT_CYCLES;
            end else if (rt_dones > 0 || rt_error) begin
                age = TIMEOUT_CYCLES;
            end
        end
        repeat (16) tick();

        if (mode == 2) begin
            if (rt_error)
                $fatal(1, "runtime replay-only error code=%0d", rt_error_code);
            if (rt_dones != 1)
                $fatal(1, "runtime replay-only done count=%0d", rt_dones);
            request_dumps();
            $display("PASS RUNTIME_ONLY reads=%0d writes=%0d acks=%0d frames=%0d atoms=%0d taps=%0d fp16=%0d sim_ns=%0d",
                     rt_reads, rt_writes, rt_acks, rt_frame_acks,
                     rt_total_atoms, rt_taps, rt_output_fp16, $time);
            $finish;
        end

        if (mode == 1) begin
            $display("DEBUG_REJECT mut=%0d idx=%0d xor=%0d val=%0d code=%0d ",
                     mut_mode, mut_index, mut_xor_lo, mut_val_lo, rt_error_code);
            $display("DEBUG_DECODE state=%0d word_index=%0d saved=%0d check=%0d",
                     runtime.decoder.state_q, runtime.decoder.word_index_q,
                     runtime.decoder.saved_code_q,
                     runtime.decoder.check_code);
            if (!rt_error) $fatal(1, "runtime decoder did not reject the stream");
            if (rt_error_code !== mut_code[7:0])
                $fatal(1, "runtime decoder code %0d != expected %0d",
                       rt_error_code, mut_code);
            if (rt_busy || rt_done)
                $fatal(1, "rejected stream left the runtime engine busy/done");
            if (rt_reads != 0 || rt_writes != 0)
                $fatal(1, "rejected stream touched memory: r=%0d w=%0d",
                       rt_reads, rt_writes);
            $display("PASS RUNTIME_REJECT mut=%0d index=%0d code=%0d reads=%0d writes=%0d sim_ns=%0d",
                     mut_mode, mut_index, rt_error_code, rt_reads, rt_writes,
                     $time);
            $finish;
        end

        if (rt_error)
            $fatal(1, "runtime engine error code=%0d", rt_error_code);
        if (ref_error)
            $fatal(1, "reference engine error code=%0d", ref_error_code);
        if (rt_dones != 1 || ref_dones != 1)
            $fatal(1, "done pulse count mismatch rt=%0d ref=%0d",
                   rt_dones, ref_dones);
        if (rt_acks != ref_acks)
            $fatal(1, "acknowledgement count mismatch rt=%0d ref=%0d",
                   rt_acks, ref_acks);
        if (rt_frame_acks != ref_frame_acks)
            $fatal(1, "frame ack count mismatch rt=%0d ref=%0d",
                   rt_frame_acks, ref_frame_acks);
        if (rt_frames != ref_frames)
            $fatal(1, "frame stream length mismatch rt=%0d ref=%0d",
                   rt_frames, ref_frames);
        if (fr_rt_pop != fr_rt_push || fr_ref_pop != fr_ref_push)
            $fatal(1, "frame comparison FIFOs not drained: rt=%0d/%0d ref=%0d/%0d",
                   fr_rt_pop, fr_rt_push, fr_ref_pop, fr_ref_push);
        if (rt_reads != ref_reads)
            $fatal(1, "read count mismatch rt=%0d ref=%0d", rt_reads, ref_reads);
        if (rt_writes != ref_writes)
            $fatal(1, "write count mismatch rt=%0d ref=%0d", rt_writes, ref_writes);
        if (rd_rt_pop != rd_rt_push || rd_ref_pop != rd_ref_push ||
            wr_rt_pop != wr_rt_push || wr_ref_pop != wr_ref_push)
            $fatal(1, "traffic sequence FIFOs not drained");
        if (rt_input_bytes != (in_hw * 2) || rt_weight_bytes != (w_hw * 2) ||
            rt_output_bytes != (out_hw * 2))
            $fatal(1, "runtime buffer sizes r=%0d/%0d w=%0d/%0d o=%0d/%0d",
                   rt_input_bytes, in_hw * 2, rt_weight_bytes, w_hw * 2,
                   rt_output_bytes, out_hw * 2);

        request_dumps();

        $display("PASS RUNTIME_EQUIV reads=%0d writes=%0d acks=%0d frames=%0d atoms=%0d taps=%0d fp16=%0d sim_ns=%0d",
                 rt_reads, rt_writes, rt_acks, rt_frame_acks, rt_total_atoms,
                 rt_taps, rt_output_fp16, $time);
        $finish;
    end

    initial begin
        #(TIMEOUT_CYCLES * 10);
        $fatal(1, "testbench watchdog");
    end
endmodule

// ---------------------------------------------------------------------------
// Shared-layout memory model: one 16-bit word per address, host init/readback,
// random engine-side ready timing. Same behaviour as the strict conv benches.
// ---------------------------------------------------------------------------
module tb_runtime_mem #(
    parameter int unsigned WORDS = 16384,
    // 0 = runtime engine's model, 1 = reference engine's model. Only selects
    // which dump plusarg this instance uses.
    parameter bit IS_REF = 1'b0
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        req_valid,
    output logic        req_ready,
    input  logic        req_write,
    input  logic [31:0] req_addr,
    input  logic [15:0] req_wdata,
    output logic        rsp_valid,
    input  logic        rsp_ready,
    output logic [15:0] rsp_rdata,
    output logic        rsp_error,
    // One-shot image dump request from the bench (no hierarchical memory
    // access: the model owns both its contents and its dump file).
    input  logic        dump_req
);
    logic [15:0] mem [0:WORDS-1];
    logic [31:0] rng;
    logic        pending, pending_write;
    logic [31:0] pending_address;
    logic [15:0] pending_data;
    logic [7:0]  delay_left;

    string  dump_path;
    integer dump_done;
    integer dump_fd;
    integer dump_k;

    assign req_ready = rst_n && !pending && (rng[2:0] != 3'b000);
    assign rsp_valid = rst_n && pending && (delay_left == 8'd0);
    assign rsp_rdata = pending_data;
    assign rsp_error = 1'b0;

    task automatic dump_image;
        begin
            if (!dump_done) begin
                dump_fd = $fopen(dump_path, "w");
                if (dump_fd != 0) begin
                    for (dump_k = 0; dump_k < WORDS; dump_k = dump_k + 1)
                        $fwrite(dump_fd, "%04x\n", mem[dump_k]);
                    $fclose(dump_fd);
                    dump_done = 1;
                end
            end
        end
    endtask

    initial begin : init_memory
        string  f;
        string  selected;
        // The bench provides one pre-built full-memory image per case (canary
        // fill + operand BOs are baked in by the Python runner), so the model
        // does exactly one $readmemh of an exactly-sized file: no clock cycles,
        // no short-read warning, and no hierarchical access from the bench.
        if ($value$plusargs("INIT_FILE=%s", f)) $readmemh(f, mem);
        dump_done = 0;
        dump_path = "";
        if (IS_REF) begin
            if ($value$plusargs("REF_DUMP=%s", selected)) dump_path = selected;
        end else begin
            if ($value$plusargs("RT_DUMP=%s", selected)) dump_path = selected;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rng <= 32'h3c4c9a31;
            pending <= 1'b0;
            pending_write <= 1'b0;
            pending_address <= 32'd0;
            pending_data <= 16'd0;
            delay_left <= 8'd0;
        end else begin
            if (dump_req && !dump_done) dump_image();
            // Engine port: one outstanding request, random ready timing.
            rng <= rng * 32'd1664525 + 32'd1013904223;
            if (req_valid && req_ready) begin
                pending <= 1'b1;
                pending_write <= req_write;
                pending_address <= req_addr;
                pending_data <= req_write ? req_wdata : mem[req_addr[15:1]];
                delay_left <= {5'd0, rng[5:3]} + 8'd1;
            end
            if (pending) begin
                if (delay_left != 0) begin
                    delay_left <= delay_left - 8'd1;
                end else if (rsp_ready) begin
                    pending <= 1'b0;
                    if (pending_write)
                        mem[pending_address[15:1]] <= pending_data;
                end
            end
        end
    end
endmodule
