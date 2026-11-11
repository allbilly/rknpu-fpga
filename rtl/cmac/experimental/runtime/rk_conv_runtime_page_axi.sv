// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Image-A S1 page: AXI4-Lite control page + raw-QWORD capture + runtime engine.
//
// ADDITIVE experimental file (task-13/S1). Instantiates the unchanged
// rk_conv_runtime_core (parameterised C16 construction). Execution boundary:
// the page fetches exactly START_AMOUNT little-endian QWORDs from the shared
// window through its memory master and drives them unchanged into
// cmd_valid/cmd_data/cmd_last; no field rewriting and no CPU fix-ups.
//
// ABI (byte offsets, AXI4-Lite):
//   0x000 R  DEVICE_ID     0x524B4356 ("RKCV")
//   0x004 R  ABI_VERSION   0x00010000
//   0x008 R  STATUS        [0] busy [1] done [2] error [3] cmd_ready
//                          [15:8] error_code [23:16] cmd_ready/obs
//   0x00C W  COMMAND       bit0 = start (ignored while busy)
//   0x010 RW START_ADDRESS shared-window byte address of the QWORD stream
//   0x014 RW START_AMOUNT  number of 64-bit command words (1..54)
//   0x018 RW JOB_TAG
//   0x01C R  RESULT        [0] done [1] error [7:2] status_code
//                          [15:8] completed_tasks
//   0x020 R  OBSERVATION   [7:0] taps [15:8] core_error_code [24:16] atoms
//                          [31] fp16
//   0x024 R  INPUT_BYTES   0x028 R WEIGHT_BYTES   0x02C R OUTPUT_BYTES
//   0x030 R  JOB_TAG_RD
module rk_conv_runtime_page_axi (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        page_cancel,
    // Shared-memory readiness from the top's arbitration, mirrored into STATUS[4].
    input  logic        memory_ready,
    // AXI4-Lite slave
    input  logic [15:0] s_axil_awaddr,
    input  logic [2:0]  s_axil_awprot,
    input  logic        s_axil_awvalid,
    output logic        s_axil_awready,
    input  logic [31:0] s_axil_wdata,
    input  logic [3:0]  s_axil_wstrb,
    input  logic        s_axil_wvalid,
    output logic        s_axil_wready,
    output logic [1:0]  s_axil_bresp,
    output logic        s_axil_bvalid,
    input  logic        s_axil_bready,
    input  logic [15:0] s_axil_araddr,
    input  logic [2:0]  s_axil_arprot,
    input  logic        s_axil_arvalid,
    output logic        s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0]  s_axil_rresp,
    output logic        s_axil_rvalid,
    input  logic        s_axil_rready,
    // Memory master into the merged-image arbiter (shared 64 KiB window)
    output logic        mem_req_valid,
    input  logic        mem_req_ready,
    output logic        mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input  logic        mem_rsp_valid,
    output logic        mem_rsp_ready,
    input  logic [15:0] mem_rsp_rdata,
    input  logic        mem_rsp_error,
    // Page status to the merged top
    output logic        page_busy,
    output logic        page_done,
    output logic        page_error,
    output logic [7:0]  page_error_code
);

    // AXI4-Lite protection signals are accepted for interface compatibility
    // with the merged page bus and are intentionally unused (the page serves
    // only its own 4 KiB control window; data traffic uses mem_*).
    wire unused_prot = s_axil_awprot[0] | s_axil_arprot[0];
    localparam logic [31:0] DEVICE_ID   = 32'h524B_4356;
    localparam logic [31:0] ABI_VERSION = 32'h0001_0000;
    localparam int unsigned MAX_CMDS    = 54;

    // ---- engine -------------------------------------------------------
    logic        eng_rst_n;
    logic        cmd_valid, cmd_ready, cmd_last;
    logic [63:0] cmd_data;
    logic        core_busy, core_ack, core_frame_done, core_done, core_error;
    logic [7:0]  core_error_code;
    logic        core_mem_req_valid, core_mem_req_ready, core_mem_req_write;
    logic [31:0] core_mem_req_addr;
    logic [15:0] core_mem_req_wdata;
    logic        core_mem_rsp_valid, core_mem_rsp_ready;
    logic [15:0] core_mem_rsp_rdata;
    logic        core_mem_rsp_error;
    logic [31:0] d_in_base, d_w_base, d_out_base;
    logic [31:0] d_in_bytes, d_w_bytes, d_out_bytes;
    logic [8:0]  d_atoms;
    logic [7:0]  d_taps;
    logic        d_fp16;

    rk_conv_runtime_core #(.ATOMIC_C(16), .ATOMIC_K(16)) core (
        .clk, .rst_n(eng_rst_n),
        .cmd_valid, .cmd_ready, .cmd_data, .cmd_last,
        .busy(core_busy), .acknowledged(core_ack),
        .frame_done(core_frame_done), .done(core_done), .error(core_error),
        .error_code(core_error_code),
        .mem_req_valid(core_mem_req_valid), .mem_req_ready(core_mem_req_ready),
        .mem_req_write(core_mem_req_write), .mem_req_addr(core_mem_req_addr),
        .mem_req_wdata(core_mem_req_wdata),
        .mem_rsp_valid(core_mem_rsp_valid), .mem_rsp_ready(core_mem_rsp_ready),
        .mem_rsp_rdata(core_mem_rsp_rdata),
        .mem_rsp_error(core_mem_rsp_error),
        .config_input_base(d_in_base), .config_weight_base(d_w_base),
        .config_output_base(d_out_base),
        .input_bytes(d_in_bytes), .weight_bytes(d_w_bytes),
        .output_bytes(d_out_bytes),
        .obs_total_atoms(d_atoms), .obs_taps(d_taps),
        .obs_output_fp16(d_fp16));

    // ---- page registers ----------------------------------------------
    logic [31:0] reg_start_address, reg_start_amount, reg_job_tag;
    logic [31:0] result_q;
    logic [31:0] obs_q, input_bytes_q, weight_bytes_q, output_bytes_q;
    logic        start_pulse;

    // ---- sequencer state ---------------------------------------------
    typedef enum logic [2:0] {IDLE, FETCH_REQ, FETCH_RSP, STREAM, RUN, DONE, ERR}
        page_state_t;
    page_state_t st_q;
    logic [63:0] capture [0:MAX_CMDS-1];
    logic [5:0]  fetch_idx, stream_idx, last_index_q;
    logic [31:0] fetch_addr, amount_q;
    // A command word is 64 bits and the memory master port is 16 bits wide (one
    // halfword per beat), so every QWORD needs FOUR beats. The previous form
    // used a single `fetch_hi` flag and captured only two halfwords (32 bits),
    // silently dropping the upper word of every command; the S1 contract bench
    // now catches that (cmd[0] arrived as 0000_0000_1234_cafe instead of
    // a500_5a00_1234_cafe).
    logic [1:0]  fetch_beat;
    logic [63:0] fetch_acc;

    assign page_busy = (st_q == FETCH_REQ) || (st_q == FETCH_RSP) ||
                       (st_q == STREAM) || (st_q == RUN);
    assign page_done  = (st_q == DONE);
    assign page_error = (st_q == ERR) || core_error || page_cancel;
    assign page_error_code = page_cancel ? 8'd6 :
                             core_error  ? core_error_code : 8'd0;

    wire fetch_owns_mem = (st_q == FETCH_REQ);
    wire core_owns_mem  = (st_q == STREAM) || (st_q == RUN);

    assign mem_req_valid = page_cancel ? 1'b0 :
                           fetch_owns_mem ? 1'b1 :
                           core_owns_mem ? core_mem_req_valid : 1'b0;
    assign mem_req_write = fetch_owns_mem ? 1'b0 : core_mem_req_write;
    assign mem_req_addr  = fetch_owns_mem ? fetch_addr : core_mem_req_addr;
    assign mem_req_wdata = core_mem_req_wdata;
    assign core_mem_req_ready = core_owns_mem && mem_req_ready;
    assign mem_rsp_ready = 1'b1;
    assign core_mem_rsp_valid = core_owns_mem && mem_rsp_valid;
    assign core_mem_rsp_rdata = mem_rsp_rdata;
    assign core_mem_rsp_error = mem_rsp_error;

    // ---- AXI4-Lite slave ---------------------------------------------
    logic [15:0] awaddr_q, araddr_q;
    logic        aw_pending, w_pending, ar_pending;
    logic [31:0] wdata_q;
    logic [31:0] status_word;

    // STATUS uses the authoritative LSB-anchored rk_job_control layout that
    // every other page in the images publishes (see docs/EW_INT_APERTURE_AUDIT.md
    // and docs/MERGED_INTEGRATION_NOTES.md):
    //   [0] can_submit, [1] active, [2] result_valid, [3] result_error,
    //   [4] memory_ready, [5] core_error, [6] core_busy,
    //   [10:8] fields_valid, [15:11] zero, [23:16] error_code, [31:24] zero.
    // Field widths must total 32: an earlier version concatenated 8+8+5+3+7
    // single bits = 31 bits, shifting every field one position left so that
    // memory_ready landed on [5] instead of [4] (caught by the merged scaffold
    // bench: STATUS read 0x381 while the page was idle with the port free).
    assign status_word = {
        8'd0,                                                // [31:24]
        (st_q == ERR || core_error) ? core_error_code : 8'd0, // [23:16]
        5'd0,                                                // [15:11]
        3'b111,                                              // [10:8]
        1'b0,                                                // [7]   reserved
        core_busy,                                           // [6]
        core_error,                                          // [5]
        memory_ready,                                        // [4]
        (st_q == ERR || core_error),                         // [3]
        (st_q == DONE) && !core_error,                        // [2]
        page_busy,                                           // [1]
        (st_q == IDLE)                                       // [0]
    };

    function automatic logic [31:0] reg_read(input logic [15:0] addr);
        case (addr[7:0])
            8'h00: reg_read = DEVICE_ID;
            8'h04: reg_read = ABI_VERSION;
            8'h08: reg_read = status_word;
            // The START/doorbell registers must be READABLE: every other page
            // in the images round-trips its writable registers, and a write-only
            // register set breaks host verification (the merged scaffold bench
            // caught it: START_ADDRESS read back 0 after a successful write).
            8'h10: reg_read = reg_start_address;
            8'h14: reg_read = reg_start_amount;
            8'h18: reg_read = reg_job_tag;
            8'h1c: reg_read = result_q;
            8'h20: reg_read = obs_q;
            8'h24: reg_read = input_bytes_q;
            8'h28: reg_read = weight_bytes_q;
            8'h2c: reg_read = output_bytes_q;
            8'h30: reg_read = reg_job_tag;
            default: reg_read = 32'h0;
        endcase
    endfunction

    assign s_axil_awready = !s_axil_bvalid;
    assign s_axil_wready  = !s_axil_bvalid;
    assign s_axil_bresp   = 2'b00;
    assign s_axil_arready = !s_axil_rvalid;
    assign s_axil_rresp   = 2'b00;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            awaddr_q <= '0; araddr_q <= '0; wdata_q <= '0;
            aw_pending <= 1'b0; w_pending <= 1'b0; ar_pending <= 1'b0;
            s_axil_bvalid <= 1'b0; s_axil_rvalid <= 1'b0;
            s_axil_rdata <= '0;
            reg_start_address <= '0; reg_start_amount <= '0;
            reg_job_tag <= '0; start_pulse <= 1'b0;
        end else begin
            start_pulse <= 1'b0;
            // AW and W are independent channels and a host may assert both in
            // the same cycle. Buffer each one separately: the earlier version
            // applied the write only when aw_pending (a registered flag) was
            // already set, so a simultaneous AW+W lost its data and never
            // produced bvalid, deadlocking the AXI write (and the S1 contract
            // bench, which hung with no output).
            if (s_axil_awvalid && s_axil_awready) begin
                awaddr_q <= s_axil_awaddr; aw_pending <= 1'b1;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                wdata_q <= s_axil_wdata; w_pending <= 1'b1;
            end
            if (aw_pending && w_pending) begin
                case (awaddr_q[7:0])
                    8'h0c: start_pulse <= wdata_q[0];
                    8'h10: reg_start_address <= wdata_q;
                    8'h14: reg_start_amount  <= wdata_q;
                    8'h18: reg_job_tag       <= wdata_q;
                    default: begin end
                endcase
                aw_pending <= 1'b0; w_pending <= 1'b0;
                s_axil_bvalid <= 1'b1;
            end
            if (s_axil_bvalid && s_axil_bready) s_axil_bvalid <= 1'b0;
            // Read address: capture and return in the same cycle. The previous
            // form captured araddr_q and only read it on the NEXT cycle, so
            // reg_read() used a stale address (the first read of a sequence
            // returned the previous transaction's data or the reset value).
            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rdata  <= reg_read(s_axil_araddr);
                s_axil_rvalid <= 1'b1;
            end
            if (s_axil_rvalid && s_axil_rready) s_axil_rvalid <= 1'b0;
        end
    end

    // ---- page sequencer ----------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st_q <= IDLE; eng_rst_n <= 1'b0;
            cmd_valid <= 1'b0; cmd_last <= 1'b0; cmd_data <= '0;
            fetch_idx <= '0; stream_idx <= '0; fetch_addr <= '0;
            amount_q <= '0; fetch_beat <= 2'd0; fetch_acc <= '0;
            last_index_q <= '0;
            result_q <= '0; obs_q <= '0;
            input_bytes_q <= '0; weight_bytes_q <= '0; output_bytes_q <= '0;
        end else begin
            obs_q <= {d_fp16, 7'd0, d_atoms, 8'd0, core_error_code, d_taps};
            input_bytes_q  <= d_in_bytes;
            weight_bytes_q <= d_w_bytes;
            output_bytes_q <= d_out_bytes;
            cmd_valid <= 1'b0;

            if (page_cancel) begin
                st_q <= IDLE; eng_rst_n <= 1'b0; cmd_valid <= 1'b0;
                result_q <= {12'd0, 8'd0, 2'b00, 1'b0, 1'b1, 8'd6};
            end else begin
                case (st_q)
                    IDLE: begin
                        eng_rst_n <= 1'b0;
                        if (start_pulse) begin
                            if ((reg_start_amount != 0) &&
                                (reg_start_amount <= MAX_CMDS) &&
                                ((reg_start_address & 32'h7) == 32'd0) &&
                                (reg_start_address[31:16] == 16'd0)) begin
                                amount_q <= reg_start_amount;
                                // Stream boundary: 52 words -> index 50,
                                // 54 words -> index 53 (the proven leg A/B
                                // harness's CMD_LAST_INDEX).
                                last_index_q <= (reg_start_amount == 32'd52)
                                                ? 6'd50
                                                : (reg_start_amount - 6'd1);
                                fetch_addr <= reg_start_address;
                                fetch_idx <= '0; stream_idx <= '0;
                                fetch_beat <= 2'd0; fetch_acc <= '0;
                                st_q <= FETCH_REQ;
                            end else begin
                                result_q <= {12'd0, 8'd0, 2'b00, 1'b0,
                                             1'b1, 8'd6};
                                st_q <= ERR;
                            end
                        end
                    end
                    FETCH_REQ: if (mem_req_ready) st_q <= FETCH_RSP;
                    FETCH_RSP: if (mem_rsp_valid) begin
                        // Four 16-bit beats per 64-bit command word, little
                        // endian: the first beat is bits[15:0]. fetch_acc holds
                        // the lower three halfwords while the last one arrives.
                        fetch_addr <= fetch_addr + 32'd2;
                        // Little-endian assembly: beat 1 is bits[15:0], beat 2
                        // bits[31:16], beat 3 bits[47:32], beat 4 bits[63:48].
                        // The earlier version PREPENDED each halfword, which put
                        // beat 1 in bits[63:48] and reversed every command word
                        // (the contract bench only matched because it compared
                        // whole words with the same reversal; the 52-QWORD
                        // conv-simple family then failed decoder family
                        // detection with code 3).
                        if (fetch_beat != 2'd3) begin
                            // Place this halfword at (16 * beat) within the word.
                            fetch_acc <= fetch_acc |
                                          (64'(mem_rsp_rdata) << (16 * fetch_beat));
                            fetch_beat <= fetch_beat + 2'd1;
                            st_q <= FETCH_REQ;
                        end else begin
                            fetch_beat <= 2'd0;
                            fetch_acc <= '0;
                            capture[fetch_idx] <= fetch_acc |
                                                  (64'(mem_rsp_rdata) << 48);
                            if (fetch_idx + 1 == amount_q) begin
                                eng_rst_n <= 1'b1;
                                stream_idx <= '0;
                                st_q <= STREAM;
                            end else begin
                                fetch_idx <= fetch_idx + 1;
                                st_q <= FETCH_REQ;
                            end
                        end
                    end
                    STREAM: begin
                        // Present (data, last, valid) TOGETHER and hold them
                        // until the engine accepts the beat. The earlier form
                        // registered data+last one cycle and cleared valid via a
                        // separate branch, so the engine could sample a previous
                        // word or a stale `cmd_last`; that surfaced as decoder
                        // code 3 (cmd_last asserted on the wrong word) for the
                        // 52-QWORD family.
                        // The engine's stream boundary is NOT the last captured
                        // word: the 52-QWORD family carries a trailing zero
                        // padding word after the stream, and the 54-QWORD
                        // family likewise ends at index 53. The proven leg A/B
                        // harness drives `cmd_last` at index 50 (52 family) or
                        // 53 (54 family) — i.e. `amount_q - 2` or
                        // `amount_q - 1`. Deriving it any other way makes the
                        // decoder reject with code 3 (framing).
                        if (!cmd_valid && (stream_idx < amount_q)) begin
                            cmd_data <= capture[stream_idx];
                            cmd_last <= (stream_idx == last_index_q);
                            cmd_valid <= 1'b1;
                        end else if (cmd_valid && cmd_ready) begin
                            cmd_valid <= 1'b0;
                            stream_idx <= stream_idx + 1;
                            if (cmd_last) st_q <= RUN;
                        end
                    end
                    RUN: if (core_done || core_error) begin
                        result_q <= 32'd0;
                        result_q[0] <= core_done;
                        result_q[1] <= core_error;
                        result_q[15:8] <= (core_done && !core_error)
                                          ? 8'd1 : 8'd0;
                        if (core_error) st_q <= ERR;
                        else st_q <= DONE;
                    end
                    DONE: if (start_pulse) st_q <= IDLE;
                    ERR:  if (start_pulse) begin
                        eng_rst_n <= 1'b0; st_q <= IDLE;
                    end
                    default: st_q <= IDLE;
                endcase
            end
        end
    end
endmodule
