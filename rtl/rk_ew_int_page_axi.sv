// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Image-B page form for the captured integer elementwise family (RKEI).
//
// ADDITIVE file (task-23). It does not replace or edit any frozen module:
// the page reuses the frozen transport register block rk_job_control and the
// already replayed integer decoder/engine (rk_ew_int_regs, rk_ew_int_engine).
//
// Execution boundary: the page reads exactly START_AMOUNT little-endian QWORDs
// from START_ADDRESS over its serialized 16-bit memory master, captures them
// verbatim (no field rewrite, no CPU fix-ups), enforces the frozen four-QWORD
// PC tail framing, and then drives the captured QWORDs unchanged into the
// integer decoder. The engine then executes against the same aperture.
//
// Register ABI: the unchanged rk_job_control page contract (byte offsets from
// the page base 0x0002_4000, AXI4-Lite, 32-bit):
//   0x00 R  DEVICE_ID     0x524b4549 ("RKEI")
//   0x04 R  ABI_VERSION   0x00010000
//   0x08 R  STATUS        frozen rk_job_control word, LSB-anchored (authoritative;
//                         see docs/EW_INT_APERTURE_AUDIT.md §6):
//                           [0] can_submit      [1] active
//                           [2] result_valid    [3] result_error
//                           [4] memory_ready    [5] core_error
//                           [6] core_busy       [10:8] fields_valid
//                           [31:11] zero
//                         (The earlier [20:18]/[16]/[15]/[14] bit sketch was WRONG;
//                          the bench and runner poll the positions above.)
//   0x0c W  COMMAND       1=submit (only when can_submit), 2=ack (success only)
//   0x10 RW START_ADDRESS 8-byte aligned byte address of the raw command BO
//                         (page form: inside the command bank at 0x1100_4000)
//   0x14 RW START_AMOUNT  captured QWORD count: 18 (simple), 31 (regroup),
//                         44 (layout); any other value fails closed with code 6
//   0x18 RW JOB_TAG       0x1c R RESULT_TAG  0x20 R RESULT_TASKS
//   0x24 R  RESULT_CODE   {24'b0, error_code}; 0 = success
//   all other offsets/read-only writes: AXI SLVERR/DECERR from rk_job_control.
//
// Fail-closed page result codes (same 8-entry map as the integer decoder):
//   0 success, 1 unknown register/target, 2 unsupported value/op/dtype,
//   3 incomplete/framing, 4 invalid address, 5 memory bus error,
//   6 invalid page command (amount/shape/address outside the captured forms),
//   7 unsupported PC chain, 8 timeout.
// A failed job is sticky until fabric reset (frozen rk_job_control has no
// error-ack); the decoder/engine are reset for every job, so clean jobs run
// back-to-back without a fabric reset. RESULT_TASKS is 1 on success.
module rk_ew_int_page_axi #(
    parameter logic [31:0] DEVICE_ID = 32'h524b4549,
    parameter logic [31:0] ABI_VERSION = 32'h0001_0000,
    parameter logic [31:0] COMMAND_BANK_BASE = 32'h1100_4000,
    parameter logic [31:0] COMMAND_BANK_BYTES = 32'd4096,
    parameter int unsigned MAX_COMMAND_QWORDS = 44,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    // Memory subsystem says the aperture is quiescent (host staging finished).
    input  logic        memory_ready,
    // Platform-level abort: does not touch AXI, forces the engine off the bus.
    input  logic        page_cancel,
    // AXI4-Lite control page (offsets within the 4 KiB page).
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
    // Serialized 16-bit memory master into the ew-int aperture. Addresses are
    // absolute device byte addresses (the captured command words are staged
    // verbatim); one outstanding transaction, response required for reads and
    // writes (same contract as the standalone image).
    output logic        mem_req_valid,
    input  logic        mem_req_ready,
    output logic        mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input  logic        mem_rsp_valid,
    output logic        mem_rsp_ready,
    input  logic [15:0] mem_rsp_rdata,
    input  logic        mem_rsp_error,
    // Page status to the Image-B top / arbitration aggregate.
    output logic        page_busy,
    output logic        page_done,
    output logic        page_error,
    output logic [7:0]  page_error_code,
    output logic        irq
);
    localparam int unsigned DEPTH = (MAX_COMMAND_QWORDS > 44) ? MAX_COMMAND_QWORDS : 44;
    localparam logic [31:0] TAIL_KEY0 = 32'h0101_0010;  // PC_REG.BASE_ADDRESS
    localparam logic [31:0] TAIL_KEY1 = 32'h0101_0014;  // PC_REG.REGISTER_AMOUNTS
    localparam logic [31:0] TAIL_KEY2 = 32'h0041_0000;  // VERSION
    localparam logic [31:0] TAIL_KEY3 = 32'h0081_0008;  // PC.OPERATION_ENABLE

    typedef enum logic [3:0] {
        IDLE, FETCH_REQ, FETCH_RSP, CHECK, STREAM, ISSUE, RUN, FINISH_OK,
        FINISH_ERR
    } state_t;
    state_t st_q;

    // frozen transport register block interface
    logic core_start_valid, core_start_ready, core_busy, core_done, core_error;
    logic [31:0] core_start_address, core_start_amount, core_completed_tasks;
    logic [7:0] core_error_code;

    // integer decoder/engine interface. The decoder/engine are held in reset
    // except during the issue/run phases of a job, so every job starts from a
    // clean decoder/engine state (reset-per-job).
    wire eng_rst_n = rst_n && ((st_q == CHECK) || (st_q == STREAM) ||
                                (st_q == ISSUE) || (st_q == RUN));
    logic cmd_valid, cmd_ready, reg_error, cfg_valid, cfg_ready;
    logic [63:0] cmd_data;
    logic [2:0] cfg_op;
    logic [1:0] cfg_dtype, cfg_in_item, cfg_out_item;
    logic [15:0] cfg_count;
    logic [31:0] cfg_a, cfg_b, cfg_dst;
    logic [7:0] reg_code;
    logic engine_busy, engine_done, engine_error;
    logic [7:0] engine_code;
    logic engine_req_valid, engine_req_ready, engine_req_write;
    logic [31:0] engine_req_addr;
    logic [15:0] engine_req_wdata;
    logic engine_rsp_valid, engine_rsp_ready;
    logic [15:0] engine_rsp_rdata;
    logic engine_rsp_error;

    // page sequencer state
    logic [63:0] capture [0:DEPTH-1];
    logic [63:0] tail_word [0:3];
    logic [31:0] amount_q, fetch_addr_q, stall_q, run_stall_q;
    logic [5:0] tail_idx;
    logic [7:0] fetch_idx_q, stream_idx_q;
    logic [1:0] fetch_half_q;
    logic [47:0] fetch_acc_q;
    logic tail_ok, start_ok, fetch_phase, run_phase;
    logic job_done_q, job_error_q;
    logic [7:0] page_code_q;
    integer i;

    rk_job_control #(.DEVICE_ID(DEVICE_ID), .ABI_VERSION(ABI_VERSION)) control (
        .clk(clk), .rst_n(rst_n),
        .memory_ready(memory_ready && !page_cancel && (st_q == IDLE)),
        .s_axil_awaddr({16'd0, s_axil_awaddr}), .s_axil_awprot(s_axil_awprot),
        .s_axil_awvalid(s_axil_awvalid), .s_axil_awready(s_axil_awready),
        .s_axil_wdata(s_axil_wdata), .s_axil_wstrb(s_axil_wstrb),
        .s_axil_wvalid(s_axil_wvalid), .s_axil_wready(s_axil_wready),
        .s_axil_bresp(s_axil_bresp), .s_axil_bvalid(s_axil_bvalid),
        .s_axil_bready(s_axil_bready),
        .s_axil_araddr({16'd0, s_axil_araddr}), .s_axil_arprot(s_axil_arprot),
        .s_axil_arvalid(s_axil_arvalid), .s_axil_arready(s_axil_arready),
        .s_axil_rdata(s_axil_rdata), .s_axil_rresp(s_axil_rresp),
        .s_axil_rvalid(s_axil_rvalid), .s_axil_rready(s_axil_rready),
        .irq(irq),
        .core_start_valid(core_start_valid), .core_start_ready(core_start_ready),
        .core_start_address(core_start_address),
        .core_start_amount(core_start_amount),
        .core_busy(core_busy), .core_done(core_done), .core_error(core_error),
        .core_error_code(core_error_code),
        .core_completed_tasks(core_completed_tasks)
    );

    rk_ew_int_regs regs (
        .clk(clk), .rst_n(eng_rst_n),
        .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_data(cmd_data),
        .engine_busy(engine_busy), .engine_error(engine_error),
        .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
        .cfg_op(cfg_op), .cfg_dtype(cfg_dtype),
        .cfg_in_item(cfg_in_item), .cfg_out_item(cfg_out_item),
        .cfg_count(cfg_count), .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_dst(cfg_dst),
        .error(reg_error), .error_code(reg_code)
    );

    rk_ew_int_engine #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) engine (
        .clk(clk), .rst_n(eng_rst_n),
        .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
        .cfg_op(cfg_op), .cfg_dtype(cfg_dtype),
        .cfg_in_item(cfg_in_item), .cfg_out_item(cfg_out_item),
        .cfg_count(cfg_count), .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_dst(cfg_dst),
        .busy(engine_busy), .done(engine_done),
        .error(engine_error), .error_code(engine_code),
        .mem_req_valid(engine_req_valid), .mem_req_ready(engine_req_ready),
        .mem_req_write(engine_req_write), .mem_req_addr(engine_req_addr),
        .mem_req_wdata(engine_req_wdata),
        .mem_rsp_valid(engine_rsp_valid), .mem_rsp_ready(engine_rsp_ready),
        .mem_rsp_rdata(engine_rsp_rdata), .mem_rsp_error(engine_rsp_error)
    );

    assign page_busy = (st_q != IDLE);
    assign page_done = job_done_q;
    assign page_error = job_error_q;
    assign page_error_code = page_code_q;
    assign core_start_ready = (st_q == IDLE) && !page_cancel;
    assign core_busy = (st_q != IDLE) || engine_busy || cfg_valid;
    assign core_done = (st_q == FINISH_OK);
    assign core_error = (st_q == FINISH_ERR) || (page_cancel && st_q != IDLE);
    assign core_error_code = core_error && page_cancel ? 8'd6 : page_code_q;
    assign core_completed_tasks = (st_q == FINISH_OK) ? 32'd1 : 32'd0;

    // A raw command BO is valid for the page form only when it has one of the
    // three captured shapes and fits inside the command bank at an 8-byte
    // aligned base. Everything else is an explicit invalid page command (6).
    always_comb begin
        start_ok = 1'b1;
        if (!((core_start_amount == 32'd18) || (core_start_amount == 32'd31) ||
              (core_start_amount == 32'd44))) start_ok = 1'b0;
        if (core_start_amount > 32'(MAX_COMMAND_QWORDS)) start_ok = 1'b0;
        if (core_start_address[2:0] != 3'd0) start_ok = 1'b0;
        if (core_start_address < COMMAND_BANK_BASE) start_ok = 1'b0;
        if ({1'b0, core_start_address} + ({1'b0, core_start_amount} << 3) >
            {1'b0, COMMAND_BANK_BASE} + {1'b0, COMMAND_BANK_BYTES})
            start_ok = 1'b0;
    end

    // Frozen four-QWORD terminal framing (same keys as rk_ew_int_dma).
    always_comb begin
        tail_ok = 1'b1;
        tail_idx = 6'd0;
        tail_word[0] = 64'd0;
        tail_word[1] = 64'd0;
        tail_word[2] = 64'd0;
        tail_word[3] = 64'd0;
        if ((amount_q < 32'd4) || (amount_q > 32'(DEPTH))) begin
            tail_ok = 1'b0;
        end else begin
            for (i = 0; i < 4; i = i + 1) begin
                tail_idx = amount_q[5:0] - 6'd4 + 6'(i);
                tail_word[i] = capture[tail_idx];
            end
            if (tail_word[0][63:48] != TAIL_KEY0[31:16] ||
                tail_word[0][15:0] != TAIL_KEY0[15:0]) tail_ok = 1'b0;
            if (tail_word[1][63:48] != TAIL_KEY1[31:16] ||
                tail_word[1][15:0] != TAIL_KEY1[15:0]) tail_ok = 1'b0;
            if (tail_word[2][63:48] != TAIL_KEY2[31:16] ||
                tail_word[2][15:0] != TAIL_KEY2[15:0]) tail_ok = 1'b0;
            if (tail_word[3][63:48] != TAIL_KEY3[31:16] ||
                tail_word[3][15:0] != TAIL_KEY3[15:0]) tail_ok = 1'b0;
        end
    end

    // Memory master: the capture phase and the engine phase never overlap.
    assign fetch_phase = (st_q == FETCH_REQ) || (st_q == FETCH_RSP);
    assign run_phase = (st_q == RUN);
    assign mem_req_valid = fetch_phase ? (st_q == FETCH_REQ)
                                       : (run_phase && engine_req_valid);
    assign mem_req_write = run_phase && engine_req_write;
    assign mem_req_addr = fetch_phase ? fetch_addr_q : engine_req_addr;
    assign mem_req_wdata = run_phase ? engine_req_wdata : 16'd0;
    assign mem_rsp_ready = fetch_phase ? (st_q == FETCH_RSP)
                                       : (run_phase && engine_rsp_ready);
    assign engine_req_ready = run_phase && mem_req_ready;
    assign engine_rsp_valid = run_phase && mem_rsp_valid;
    assign engine_rsp_rdata = mem_rsp_rdata;
    assign engine_rsp_error = mem_rsp_error;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            st_q <= IDLE;
            cmd_valid <= 1'b0;
            cmd_data <= 64'd0;
            amount_q <= 32'd0;
            fetch_addr_q <= 32'd0;
            fetch_idx_q <= 8'd0;
            stream_idx_q <= 8'd0;
            fetch_half_q <= 2'd0;
            fetch_acc_q <= 48'd0;
            stall_q <= 32'd0;
            run_stall_q <= 32'd0;
            job_done_q <= 1'b0;
            job_error_q <= 1'b0;
            page_code_q <= 8'd0;
        end else begin
            cmd_valid <= 1'b0;
            if (page_cancel && (st_q != IDLE)) begin
                st_q <= IDLE;
                page_code_q <= 8'd6;
                job_error_q <= 1'b1;
            end else begin
                case (st_q)
                    IDLE: begin
                        if (core_start_valid && core_start_ready) begin
                            amount_q <= core_start_amount;
                            fetch_addr_q <= core_start_address;
                            fetch_idx_q <= 8'd0;
                            stream_idx_q <= 8'd0;
                            fetch_half_q <= 2'd0;
                            fetch_acc_q <= 48'd0;
                            stall_q <= 32'd0;
                            run_stall_q <= 32'd0;
                            job_done_q <= 1'b0;
                            job_error_q <= 1'b0;
                            page_code_q <= 8'd0;
                            if (!start_ok) begin
                                page_code_q <= 8'd6;
                                st_q <= FINISH_ERR;
                            end else begin
                                st_q <= FETCH_REQ;
                            end
                        end
                    end
                    FETCH_REQ: if (mem_req_ready) st_q <= FETCH_RSP;
                    FETCH_RSP: begin
                        if (mem_rsp_valid && mem_rsp_error) begin
                            page_code_q <= 8'd5;
                            st_q <= FINISH_ERR;
                        end else if (mem_rsp_valid) begin
                            fetch_acc_q <= {mem_rsp_rdata, fetch_acc_q[47:16]};
                            fetch_addr_q <= fetch_addr_q + 32'd2;
                            if (fetch_half_q == 2'd3) begin
                                capture[fetch_idx_q[5:0]] <=
                                    {mem_rsp_rdata, fetch_acc_q};
                                fetch_half_q <= 2'd0;
                                if (fetch_idx_q + 8'd1 == amount_q[7:0]) begin
                                    st_q <= CHECK;
                                end else begin
                                    fetch_idx_q <= fetch_idx_q + 8'd1;
                                    st_q <= FETCH_REQ;
                                end
                            end else begin
                                fetch_half_q <= fetch_half_q + 2'd1;
                                st_q <= FETCH_REQ;
                            end
                        end
                    end
                    CHECK: begin
                        if (!tail_ok) begin
                            page_code_q <= 8'd3;
                            st_q <= FINISH_ERR;
                        end else begin
                            stream_idx_q <= 8'd0;
                            st_q <= STREAM;
                        end
                    end
                    STREAM: begin
                        if (reg_error) begin
                            page_code_q <= reg_code;
                            st_q <= FINISH_ERR;
                        end else if (!cmd_valid && cmd_ready &&
                                     (stream_idx_q < amount_q[7:0])) begin
                            cmd_data <= capture[stream_idx_q[5:0]];
                            cmd_valid <= 1'b1;
                            stream_idx_q <= stream_idx_q + 8'd1;
                        end else if (cmd_valid && cmd_ready) begin
                            cmd_valid <= 1'b0;
                            if (stream_idx_q >= amount_q[7:0]) st_q <= ISSUE;
                        end
                    end
                    ISSUE: begin
                        // The last QWORD may itself be rejected by the decoder
                        // (unsupported op/dtype/register), in which case the
                        // decoder latches an error instead of starting the
                        // engine. Wait for exactly one of the two outcomes.
                        if (reg_error) begin
                            page_code_q <= reg_code;
                            st_q <= FINISH_ERR;
                        end else if (engine_error) begin
                            page_code_q <= engine_code;
                            st_q <= FINISH_ERR;
                        end else if (engine_busy || cfg_valid) begin
                            st_q <= RUN;
                        end else begin
                            stall_q <= stall_q + 32'd1;
                            if (stall_q >= 32'(TIMEOUT_CYCLES) - 32'd1) begin
                                page_code_q <= 8'd8;
                                st_q <= FINISH_ERR;
                            end
                        end
                    end
                    RUN: begin
                        if (engine_done) begin
                            st_q <= FINISH_OK;
                        end else if (engine_error) begin
                            page_code_q <= engine_code;
                            st_q <= FINISH_ERR;
                        end else begin
                            run_stall_q <= run_stall_q + 32'd1;
                            if (run_stall_q >= 32'(TIMEOUT_CYCLES) * 32'd8) begin
                                page_code_q <= 8'd8;
                                st_q <= FINISH_ERR;
                            end
                        end
                    end
                    FINISH_OK: begin
                        job_done_q <= 1'b1;
                        st_q <= IDLE;
                    end
                    FINISH_ERR: begin
                        job_error_q <= 1'b1;
                        st_q <= IDLE;
                    end
                    default: st_q <= IDLE;
                endcase
                // Capture-phase stall watchdog so a wedged memory arbiter cannot
                // hang the page. The engine has its own memory timeout.
                if ((fetch_phase && !((mem_req_valid && mem_req_ready) ||
                                      (mem_rsp_valid && mem_rsp_ready))) ||
                    (st_q == ISSUE)) begin
                    stall_q <= stall_q + 32'd1;
                    if (stall_q >= 32'(TIMEOUT_CYCLES) - 32'd1) begin
                        page_code_q <= 8'd8;
                        st_q <= FINISH_ERR;
                    end
                end else begin
                    stall_q <= 32'd0;
                end
            end
        end
    end
endmodule
