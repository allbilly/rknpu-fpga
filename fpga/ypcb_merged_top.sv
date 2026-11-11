// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// ============================================================================
// IMAGE A SKELETON (S1 scaffolding) -- conv runtime engine + GEMM + transport.
// NOT A BUILT IMAGE YET.
//
// Lead decision D1/D4 (2026-11-11): the merged single image is not adopted
// because the measured runtime engine is 167,858 LUTs (17.8k over the 150k
// single-image ceiling). The two-image split is adopted:
//
//   Image A (this top): runtime conv engine page + FP32 GEMM page + USER2
//                       transport + shared memory window  (~176k LUTs planned)
//   Image B (separate): pooling corpus + EW FP16/FDIV endpoint + ew-int
//                       (~40-45k LUTs; see fpga/ypcb_image_b_top.sv and
//                        docs/MERGED_INTEGRATION_NOTES.md)
//
// The six-page/EW/ew-int/pooling-corpus images remain fallbacks. This file is
// file-only scaffolding: the page slaves are `merged_page_stub` placeholders and
// no synthesis receipt exists.
//
// Image A address map (docs/MERGED_INTEGRATION_NOTES.md §2):
//
//   0x0000_0000 .. 0x0000_ffff   shared host memory window (64 KiB BRAM)
//   0x0001_0000 .. 0x0001_0fff   RKCV  runtime conv engine page    (S1 attach)
//   0x0001_1000 .. 0x0001_1fff   RKCM  FP32 GEMM page              (S2 attach)
//   everything else              explicit SLVERR, never a silent alias
//
// The EW memory aperture at 0x1000_0000 and the pooling pages are NOT in this
// top: they belong to Image B's separate top. Their stubs and decode plan are
// preserved in fpga/ypcb_image_b_top.sv so the split does not lose the work.
//
// Presence gating: PAGE_MASK selects which pages the image claims; every bit of
// REQUIRED_PAGE_MASK must be set or elaboration fails, and bits [6:3] are
// reserved for future images and must be zero here (this top has only three
// page bits). A disabled page decodes to SLVERR instead of aliasing. The build
// Tcl additionally asserts each required page exists with its expected REF_NAME
// (rendered from fpga/merged/merged_sources.json).
//
// Arbitration: one AXI4-Lite transaction at a time, one engine job at a time.
// The host window is enabled only while `any_engine_busy` is low, and each page
// receives `engine_memory_ready`. TODO(S1/S2): replace the aggregate with the
// dual-image complement pattern once the real pages have independent busy
// outputs (fpga/ypcb_dual_endpoint_top.sv does this for six pages today).
//
// Pin/CDC facts are unchanged from the adopted images: only AA28 (SYS_CLK,
// LVCMOS18) and the three LEDs are package pins (fpga/jtag_dual.xdc is reused
// unchanged); the reviewed fpga/host/mailbox_cdc.tcl constraints address
// u_mailbox/u_bscan by hierarchy name, so those instance names are preserved.
// ============================================================================
module ypcb_merged_top #(
    parameter bit LED_ACTIVE_LOW = 1'b0,
    parameter int unsigned RESET_HOLD_CYCLES = 64,
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned BRIDGE_TIMEOUT_CYCLES = 65536,
    parameter logic [31:0] BRAM_BASE = 32'h0000_0000,
    parameter int unsigned BRAM_BYTES = 65536,
    // Page presence mask. bit0 memory window, bit1 RKCV runtime conv page,
    // bit2 RKCM GEMM page. Bits [6:3] are reserved for future images and must be
    // zero in Image A. S1 may build with only {memory, RKCV}; the full Image A
    // sets bit2 once the GEMM page attaches.
    parameter logic [6:0] PAGE_MASK = 7'b000_0111,
    parameter logic [6:0] REQUIRED_PAGE_MASK = 7'b000_0011
) (
    input  wire SYS_CLK,
    output wire [2:0] led_3bits_tri_o
);
    initial begin
        if ((PAGE_MASK & REQUIRED_PAGE_MASK) != REQUIRED_PAGE_MASK)
            $fatal(1, "image A: enabled page mask does not cover the required pages");
        if (PAGE_MASK[6:3] != 4'b0000)
            $fatal(1, "image A: page mask bits [6:3] are reserved for future images");
        if (BRAM_BYTES != 65536 || BRAM_BASE != 32'h0000_0000)
            $fatal(1, "image A: S1 scaffolding fixes a 64 KiB window at 0x0000_0000");
    end

    // ---- clocks, reset, USER2 mailbox transport ---------------------------
    wire clk_ib, clk, reset_n;
    wire tck, capture, shift, update, sel, tdi, tdo;

    IBUF u_ibuf50 (.I(SYS_CLK), .O(clk_ib));
    BUFG u_bufg50 (.I(clk_ib), .O(clk));
    rk_startup_reset #(.HOLD_CYCLES(RESET_HOLD_CYCLES)) startup (
        .clk(clk), .request_reset(1'b0), .rst_n(reset_n)
    );

    wire req_valid, req_ready, rsp_valid;
    wire [603:0] req;
    wire [511:0] rsp_data;
    wire [7:0] rsp_status;
    wire [15:0] rsp_seq;
    wire fault;

    (* DONT_TOUCH = "TRUE" *) BSCANE2 #(.JTAG_CHAIN(2)) u_bscan (
        .TCK(tck), .DRCK(), .CAPTURE(capture), .SHIFT(shift), .UPDATE(update),
        .SEL(sel), .TDI(tdi), .TDO(tdo), .RESET(), .RUNTEST(), .TMS()
    );
    // Hierarchy names preserved: fpga/host/mailbox_cdc.tcl constrains
    // u_mailbox/u_bscan (and their held/response registers) by name.
    (* KEEP_HIERARCHY = "TRUE" *) otpu_jtag_mailbox u_mailbox (
        .clk, .rst(!reset_n), .tck, .capture, .shift, .update, .sel, .tdi,
        .tdo,
        .req_valid, .req_ready, .req,
        .rsp_valid, .rsp_data, .rsp_status, .rsp_seq
    );

    // ---- AXI4-Lite slave from the reviewed bridge -------------------------
    wire [31:0] s_axil_awaddr, s_axil_wdata, s_axil_araddr, s_axil_rdata;
    wire [2:0] s_axil_awprot, s_axil_arprot;
    wire [3:0] s_axil_wstrb;
    wire [1:0] s_axil_bresp, s_axil_rresp;
    wire s_axil_awvalid, s_axil_awready, s_axil_wvalid, s_axil_wready;
    wire s_axil_bvalid, s_axil_bready, s_axil_arvalid, s_axil_arready;
    wire s_axil_rvalid, s_axil_rready;

    rk_jtag_axil_bridge #(.TIMEOUT_CYCLES(BRIDGE_TIMEOUT_CYCLES)) bridge (
        .clk, .rst_n(reset_n),
        .req_valid, .req_ready, .req,
        .rsp_valid, .rsp_data, .rsp_status, .rsp_seq, .fault,
        .s_axil_awaddr, .s_axil_awprot, .s_axil_awvalid, .s_axil_awready,
        .s_axil_wdata, .s_axil_wstrb, .s_axil_wvalid, .s_axil_wready,
        .s_axil_bresp, .s_axil_bvalid, .s_axil_bready,
        .s_axil_araddr, .s_axil_arprot, .s_axil_arvalid, .s_axil_arready,
        .s_axil_rdata, .s_axil_rresp, .s_axil_rvalid, .s_axil_rready
    );

    // ---- transaction targets and Image A address decode -------------------
    localparam logic [3:0] T_NONE = 4'd0, T_MEMORY = 4'd1, T_RKCV = 4'd2,
                           T_RKCM = 4'd3, T_UNMAPPED = 4'd4;

    function automatic logic [3:0] decode(input logic [31:0] address,
                                          input logic [6:0] mask);
        case (address[31:16])
            16'h0000: decode = mask[0] ? T_MEMORY : T_UNMAPPED;
            16'h0001: begin
                // TODO(S1): RKCV <- the runtime conv engine page wrapper.
                // TODO(S2): RKCM <- rk_cmac_gemm_axi (decode-driven, unchanged).
                case (address[15:12])
                    4'h0: decode = mask[1] ? T_RKCV : T_UNMAPPED;
                    4'h1: decode = mask[2] ? T_RKCM : T_UNMAPPED;
                    default: decode = T_UNMAPPED;
                endcase
            end
            default: decode = T_UNMAPPED;
        endcase
    endfunction

    // Page identities read back at offset 0x000 by the stubs (contract-pinned).
    function automatic logic [31:0] page_id(input int unsigned index);
        case (index)
            0: page_id = 32'h524b_4356;  // "RKCV" runtime conv page
            1: page_id = 32'h524b_434d;  // "RKCM" FP32 GEMM page
            default: page_id = 32'h0000_0000;
        endcase
    endfunction

    // ---- AXI4-Lite front end: one transaction at a time -------------------
    // The bridge drives one transaction at a time; this skeleton collects AW/W
    // (or AR) into latches, dispatches to exactly one target and forwards that
    // target's response. It does not queue or reorder.
    localparam logic [1:0] W_COLLECT = 2'd0, W_DISPATCH = 2'd1, W_RESPONSE = 2'd2;
    localparam logic [1:0] R_COLLECT = 2'd0, R_DISPATCH = 2'd1, R_RESPONSE = 2'd2;

    logic [1:0] write_state_q, read_state_q;
    logic [31:0] write_addr_q, write_data_q, read_addr_q;
    logic [3:0] write_strb_q;
    logic [2:0] write_prot_q, read_prot_q;
    logic [3:0] write_target_q, read_target_q;
    logic aw_captured_q, w_captured_q, aw_sent_q, w_sent_q;
    logic ar_captured_q, ar_sent_q;

    wire aw_accept = s_axil_awvalid && s_axil_awready;
    wire w_accept = s_axil_wvalid && s_axil_wready;
    wire ar_accept = s_axil_arvalid && s_axil_arready;

    assign s_axil_awready = reset_n && (write_state_q == W_COLLECT) && !aw_captured_q;
    assign s_axil_wready = reset_n && (write_state_q == W_COLLECT) && !w_captured_q;
    assign s_axil_arready = reset_n && (read_state_q == R_COLLECT) && !ar_captured_q;

    wire dispatch_awvalid = (write_state_q == W_DISPATCH) && !aw_sent_q;
    wire dispatch_wvalid = (write_state_q == W_DISPATCH) && !w_sent_q;
    wire dispatch_arvalid = (read_state_q == R_DISPATCH) && !ar_sent_q;

    // ---- page buses (two stubs: runtime conv, GEMM) ------------------------
    localparam int unsigned NPAGES = 2;
    wire [NPAGES-1:0] page_awvalid, page_awready, page_wvalid, page_wready,
                      page_bvalid, page_arvalid, page_arready, page_rvalid;
    wire [NPAGES*2-1:0] page_bresp, page_rresp;
    wire [NPAGES*32-1:0] page_rdata;
    wire [NPAGES-1:0] page_busy, page_irq, page_done, page_error;
    wire [NPAGES*8-1:0] page_error_code;

    wire host_mem_busy;
    wire any_engine_busy = |page_busy;
    wire host_memory_enable = reset_n && !any_engine_busy;
    // TODO(S1/S2): replace this aggregate with the dual-image complement pattern
    // (each page sees the complement of every OTHER page's busy and of
    // host_mem_busy) once the real engines have independent busy outputs.
    wire engine_memory_ready = reset_n && !host_mem_busy;

    for (genvar p = 0; p < NPAGES; p = p + 1) begin: page_route
        assign page_awvalid[p] = dispatch_awvalid && (write_target_q == 4'(2 + p));
        assign page_wvalid[p] = dispatch_wvalid && (write_target_q == 4'(2 + p));
        assign page_arvalid[p] = dispatch_arvalid && (read_target_q == 4'(2 + p));
    end

    logic page_awready_sel, page_wready_sel, page_bvalid_sel;
    logic [1:0] page_bresp_sel, page_rresp_sel;
    logic page_arready_sel, page_rvalid_sel;
    logic [31:0] page_rdata_sel;
    always_comb begin
        page_awready_sel = 1'b0;
        page_wready_sel = 1'b0;
        page_bvalid_sel = 1'b0;
        page_bresp_sel = 2'b00;
        page_arready_sel = 1'b0;
        page_rvalid_sel = 1'b0;
        page_rdata_sel = 32'd0;
        page_rresp_sel = 2'b00;
        for (integer q = 0; q < NPAGES; q = q + 1) begin
            if (write_target_q == 4'(2 + q)) begin
                page_awready_sel = page_awready[q];
                page_wready_sel = page_wready[q];
                page_bvalid_sel = page_bvalid[q];
                page_bresp_sel = page_bresp[q*2+:2];
            end
            if (read_target_q == 4'(2 + q)) begin
                page_arready_sel = page_arready[q];
                page_rvalid_sel = page_rvalid[q];
                page_rdata_sel = page_rdata[q*32+:32];
                page_rresp_sel = page_rresp[q*2+:2];
            end
        end
    end

    // ---- shared 64 KiB host window (rk_bram + AXI halfword bridge) --------
    wire mem_awready, mem_wready, mem_bvalid, mem_arready, mem_rvalid;
    wire [1:0] mem_bresp, mem_rresp;
    wire [31:0] mem_rdata;
    wire mem_req_valid, mem_req_ready, mem_req_write;
    wire [31:0] mem_req_addr;
    wire [15:0] mem_req_wdata;
    wire mem_rsp_valid, mem_rsp_ready;
    wire [15:0] mem_rsp_rdata;
    wire mem_rsp_error;       // rk_bram response error (driven by rk_bram)

    wire mem_awvalid = dispatch_awvalid && (write_target_q == T_MEMORY);
    wire mem_wvalid = dispatch_wvalid && (write_target_q == T_MEMORY);
    wire mem_arvalid = dispatch_arvalid && (read_target_q == T_MEMORY);
    wire mem_bready = s_axil_bready && (write_state_q == W_RESPONSE) && (write_target_q == T_MEMORY);
    wire mem_rready = s_axil_rready && (read_state_q == R_RESPONSE) && (read_target_q == T_MEMORY);

    // ---- shared-memory arbitration (S1) ----------------------------------
    // The 64 KiB halfword window has ONE physical request port. rk_bram itself
    // permits only one outstanding transaction (`req_ready = !rsp_valid ||
    // rsp_ready`), so the arbitration only has to (a) present one master's
    // request at a time and (b) route the response back to whoever owns the
    // outstanding transaction.
    //
    // Policy: the host keeps priority (it is already gated by
    // host_memory_enable); the runtime conv page uses the port otherwise. A
    // competing request cannot steal a transaction because rk_bram withholds
    // req_ready while a response is outstanding.
    //
    // The first version of this arbiter latched an owner and muxed rsp_ready
    // from the latched owner; that deadlocked the host path because the latched
    // owner's own rsp_ready was still the value from before the transaction
    // began. Tracking the owner of the *outstanding request* (set when the
    // request is accepted) removes that cycle entirely.
    wire host_mem_req_valid, host_mem_req_ready, host_mem_req_write;
    wire [31:0] host_mem_req_addr;
    wire [15:0] host_mem_req_wdata;
    wire host_mem_rsp_valid, host_mem_rsp_ready;
    wire [15:0] host_mem_rsp_rdata;
    wire host_mem_rsp_error;

    wire conv_mem_req_valid, conv_mem_req_ready, conv_mem_req_write;
    wire [31:0] conv_mem_req_addr;
    wire [15:0] conv_mem_req_wdata;
    wire conv_mem_rsp_valid, conv_mem_rsp_ready;
    wire [15:0] conv_mem_rsp_rdata;
    wire conv_mem_rsp_error;

    // Three masters share one port: the host bridge, the runtime conv page and
    // the GEMM page. Priority host > conv > gemm. rk_bram already refuses a
    // second request while a response is pending, so a competing request cannot
    // steal a transaction; the only state needed is which master owns the
    // response currently in flight.
    wire mem_gemm_req_valid, mem_gemm_req_ready, mem_gemm_req_write;
    wire [31:0] mem_gemm_req_addr;
    wire [15:0] mem_gemm_req_wdata;
    wire mem_gemm_rsp_valid, mem_gemm_rsp_ready;
    wire [15:0] mem_gemm_rsp_rdata;
    wire mem_gemm_rsp_error;

    wire mem_grant_host = host_mem_req_valid;
    wire mem_grant_conv = !mem_grant_host && conv_mem_req_valid;
    wire mem_grant_gemm = !mem_grant_host && !mem_grant_conv && mem_gemm_req_valid;

    assign mem_req_valid = mem_grant_host || mem_grant_conv || mem_grant_gemm;
    assign mem_req_write = mem_grant_host ? host_mem_req_write :
                           mem_grant_conv ? conv_mem_req_write : mem_gemm_req_write;
    assign mem_req_addr  = mem_grant_host ? host_mem_req_addr :
                           mem_grant_conv ? conv_mem_req_addr : mem_gemm_req_addr;
    assign mem_req_wdata = mem_grant_host ? host_mem_req_wdata :
                           mem_grant_conv ? conv_mem_req_wdata : mem_gemm_req_wdata;

    assign host_mem_req_ready = mem_grant_host && mem_req_ready;
    assign conv_mem_req_ready = mem_grant_conv && mem_req_ready;
    assign mem_gemm_req_ready = mem_grant_gemm && mem_req_ready;

    // Which master owns the transaction currently in flight: 0 none, 1 host,
    // 2 conv, 3 gemm.
    logic [1:0] mem_rsp_owner_q;
    wire mem_req_accept = mem_req_valid && mem_req_ready;
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) mem_rsp_owner_q <= 2'd1;   // host owns the port at reset
        else if (mem_req_accept)
            mem_rsp_owner_q <= mem_grant_host ? 2'd1 :
                               mem_grant_conv ? 2'd2 : 2'd3;
    end

    assign host_mem_rsp_valid = mem_rsp_valid && mem_rsp_owner_q == 2'd1;
    assign conv_mem_rsp_valid = mem_rsp_valid && mem_rsp_owner_q == 2'd2;
    assign mem_gemm_rsp_valid = mem_rsp_valid && mem_rsp_owner_q == 2'd3;
    assign host_mem_rsp_rdata = mem_rsp_rdata;
    assign conv_mem_rsp_rdata = mem_rsp_rdata;
    assign mem_gemm_rsp_rdata = mem_rsp_rdata;
    assign host_mem_rsp_error = mem_rsp_error;
    assign conv_mem_rsp_error = mem_rsp_error;
    assign mem_gemm_rsp_error = mem_rsp_error;
    assign mem_rsp_ready = (mem_rsp_owner_q == 2'd1) ? host_mem_rsp_ready :
                           (mem_rsp_owner_q == 2'd2) ? conv_mem_rsp_ready :
                                                        mem_gemm_rsp_ready;

    rk_axil_mem_bridge #(.BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES))) memory_bridge (
        .clk(clk), .rst_n(reset_n),
        .host_enable(host_memory_enable),
        .busy(host_mem_busy),
        .s_axil_awaddr(write_addr_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(mem_awvalid), .s_axil_awready(mem_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(mem_wvalid), .s_axil_wready(mem_wready),
        .s_axil_bresp(mem_bresp), .s_axil_bvalid(mem_bvalid),
        .s_axil_bready(mem_bready),
        .s_axil_araddr(read_addr_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(mem_arvalid), .s_axil_arready(mem_arready),
        .s_axil_rdata(mem_rdata), .s_axil_rresp(mem_rresp),
        .s_axil_rvalid(mem_rvalid), .s_axil_rready(mem_rready),
        .mem_req_valid(host_mem_req_valid), .mem_req_ready(host_mem_req_ready),
        .mem_req_write(host_mem_req_write), .mem_req_addr(host_mem_req_addr),
        .mem_req_wdata(host_mem_req_wdata), .mem_rsp_valid(host_mem_rsp_valid),
        .mem_rsp_ready(host_mem_rsp_ready), .mem_rsp_rdata(host_mem_rsp_rdata),
        .mem_rsp_error(host_mem_rsp_error)
    );

    rk_bram #(.BYTES(BRAM_BYTES), .BASE(BRAM_BASE)) memory (
        .clk(clk), .rst_n(reset_n),
        .req_valid(mem_req_valid), .req_ready(mem_req_ready),
        .req_write(mem_req_write), .req_addr(mem_req_addr),
        .req_wdata(mem_req_wdata),
        .rsp_valid(mem_rsp_valid), .rsp_ready(mem_rsp_ready),
        .rsp_rdata(mem_rsp_rdata), .rsp_error(mem_rsp_error),
        // The second physical port stays idle in this architecture: every engine
        // and the host share the arbitrated request port (same choice as the
        // adopted six-page image).
        .host_valid(1'b0), .host_ready(), .host_write(1'b0),
        .host_addr(32'd0), .host_wdata(16'd0),
        .host_rsp_valid(), .host_rsp_ready(1'b0),
        .host_rdata(), .host_error()
    );

    // ---- page stubs: replace one at a time at S1/S2 -----------------------
    // TODO(S1): conv_runtime_page <- rk_conv_runtime_axi (Image-A wrapper around
    //   conveng's rk_conv_runtime_core; ABI pinned in
    //   docs/MERGED_INTEGRATION_NOTES.md §3 and agreed with conveng). Until the
    //   parameterised equivalence rerun is green this slot is the ABI reference
    //   model `merged_job_stub`: it implements the exact register contract the
    //   real page will expose (ID/ABI/STATUS/COMMAND/START/RESULT) and models a
    //   submit->done lifecycle, performing no memory access.
    // TODO(S2): gemm_page <- rk_cmac_gemm_axi (decode-driven, unchanged).
    // S1: the real runtime conv page replaces the ABI reference stub. It owns
    // the register contract (ID/ABI/STATUS/COMMAND/START/RESULT/OBS) and drives
    // the page's own memory master, which the arbiter above serialises against
    // the host bridge. `page_memory_ready` follows the same one-job-at-a-time
    // rule the corpus image uses (no other engine or host transaction active).
    // The conv page may start a job when the host is not holding the memory
    // port and no OTHER engine is running. It must not include its own busy
    // line (that would make a running page report memory_ready=0), and it must
    // not depend on the GEMM stub, which has no engine behind it yet.
    wire conv_page_memory_ready = reset_n && !host_mem_busy;

    rk_conv_runtime_page_axi conv_runtime_page (
        .clk(clk), .rst_n(reset_n),
        .page_cancel(!reset_n),
        .memory_ready(conv_page_memory_ready),
        .s_axil_awaddr(write_addr_q[11:0]), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(page_awvalid[0]), .s_axil_awready(page_awready[0]),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(page_wvalid[0]), .s_axil_wready(page_wready[0]),
        .s_axil_bresp(page_bresp[0*2+:2]), .s_axil_bvalid(page_bvalid[0]),
        .s_axil_bready(s_axil_bready && (write_state_q == W_RESPONSE) &&
                       (write_target_q == T_RKCV)),
        .s_axil_araddr(read_addr_q[11:0]), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(page_arvalid[0]), .s_axil_arready(page_arready[0]),
        .s_axil_rdata(page_rdata[0*32+:32]), .s_axil_rresp(page_rresp[0*2+:2]),
        .s_axil_rvalid(page_rvalid[0]),
        .s_axil_rready(s_axil_rready && (read_state_q == R_RESPONSE) &&
                       (read_target_q == T_RKCV)),
        .mem_req_valid(conv_mem_req_valid), .mem_req_ready(conv_mem_req_ready),
        .mem_req_write(conv_mem_req_write), .mem_req_addr(conv_mem_req_addr),
        .mem_req_wdata(conv_mem_req_wdata), .mem_rsp_valid(conv_mem_rsp_valid),
        .mem_rsp_ready(conv_mem_rsp_ready), .mem_rsp_rdata(conv_mem_rsp_rdata),
        .mem_rsp_error(conv_mem_rsp_error),
        .page_busy(page_busy[0]), .page_done(page_done[0]),
        .page_error(page_error[0]), .page_error_code(page_error_code[0*8+:8])
    );

    // The GEMM page exposes busy/irq only (no done/error lines); tie its status
    // lanes so the page status arrays stay fully driven.
    assign page_done[1] = 1'b0;
    assign page_error[1] = 1'b0;
    assign page_error_code[1*8+:8] = 8'd0;

    // S2: the real CMAC GEMM page replaces the S2 stub. It owns the GEMM job
    // register contract and its own memory master (third port of the arbiter).
    wire gemm_page_memory_ready = reset_n && !host_mem_busy;

    rk_cmac_gemm_axi #(.TIMEOUT_CYCLES(65536)) gemm_page (
        .clk(clk), .rst_n(reset_n), .memory_ready(gemm_page_memory_ready),
        // Window-relative address (low 12 bits): the page is a 4 KiB slave and
        // its job-control decode uses the low byte, so passing the full window
        // address would decode as an unmapped register (rresp=11) and quarantine
        // the host bridge on the FIRST access.
        .s_axil_awaddr(write_addr_q[11:0]), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(page_awvalid[1]), .s_axil_awready(page_awready[1]),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(page_wvalid[1]), .s_axil_wready(page_wready[1]),
        .s_axil_bresp(page_bresp[1*2+:2]), .s_axil_bvalid(page_bvalid[1]),
        .s_axil_bready(s_axil_bready && (write_state_q == W_RESPONSE) &&
                       (write_target_q == T_RKCM)),
        .s_axil_araddr(read_addr_q[11:0]), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(page_arvalid[1]), .s_axil_arready(page_arready[1]),
        .s_axil_rdata(page_rdata[1*32+:32]), .s_axil_rresp(page_rresp[1*2+:2]),
        .s_axil_rvalid(page_rvalid[1]),
        .s_axil_rready(s_axil_rready && (read_state_q == R_RESPONSE) &&
                       (read_target_q == T_RKCM)),
        .irq(page_irq[1]), .busy(page_busy[1]),
        .mem_req_valid(mem_gemm_req_valid), .mem_req_ready(mem_gemm_req_ready),
        .mem_req_write(mem_gemm_req_write), .mem_req_addr(mem_gemm_req_addr),
        .mem_req_wdata(mem_gemm_req_wdata), .mem_rsp_valid(mem_gemm_rsp_valid),
        .mem_rsp_ready(mem_gemm_rsp_ready), .mem_rsp_rdata(mem_gemm_rsp_rdata),
        .mem_rsp_error(mem_gemm_rsp_error)
    );

    // ---- unmapped addresses: explicit SLVERR, never a silent alias --------
    wire err_awvalid = dispatch_awvalid && (write_target_q == T_UNMAPPED);
    wire err_wvalid = dispatch_wvalid && (write_target_q == T_UNMAPPED);
    wire err_arvalid = dispatch_arvalid && (read_target_q == T_UNMAPPED);
    wire err_awready, err_wready, err_bvalid, err_arready, err_rvalid;
    wire [1:0] err_bresp, err_rresp;
    wire [31:0] err_rdata;

    rk_axil_error_slave error_page (
        .clk(clk), .rst_n(reset_n),
        .s_axil_awaddr(write_addr_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(err_awvalid), .s_axil_awready(err_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(err_wvalid), .s_axil_wready(err_wready),
        .s_axil_bresp(err_bresp), .s_axil_bvalid(err_bvalid),
        .s_axil_bready(s_axil_bready && (write_state_q == W_RESPONSE) && (write_target_q == T_UNMAPPED)),
        .s_axil_araddr(read_addr_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(err_arvalid), .s_axil_arready(err_arready),
        .s_axil_rdata(err_rdata), .s_axil_rresp(err_rresp),
        .s_axil_rvalid(err_rvalid),
        .s_axil_rready(s_axil_rready && (read_state_q == R_RESPONSE) && (read_target_q == T_UNMAPPED))
    );

    // ---- dispatch response mux -------------------------------------------
    wire dispatch_awready = (write_target_q == T_MEMORY) ? mem_awready :
                            (write_target_q == T_UNMAPPED) ? err_awready : page_awready_sel;
    wire dispatch_wready = (write_target_q == T_MEMORY) ? mem_wready :
                           (write_target_q == T_UNMAPPED) ? err_wready : page_wready_sel;
    wire dispatch_bvalid = (write_target_q == T_MEMORY) ? mem_bvalid :
                           (write_target_q == T_UNMAPPED) ? err_bvalid : page_bvalid_sel;
    wire [1:0] dispatch_bresp = (write_target_q == T_MEMORY) ? mem_bresp :
                                 (write_target_q == T_UNMAPPED) ? err_bresp : page_bresp_sel;
    wire dispatch_arready = (read_target_q == T_MEMORY) ? mem_arready :
                            (read_target_q == T_UNMAPPED) ? err_arready : page_arready_sel;
    wire dispatch_rvalid = (read_target_q == T_MEMORY) ? mem_rvalid :
                           (read_target_q == T_UNMAPPED) ? err_rvalid : page_rvalid_sel;
    wire [31:0] dispatch_rdata = (read_target_q == T_MEMORY) ? mem_rdata :
                                 (read_target_q == T_UNMAPPED) ? err_rdata : page_rdata_sel;
    wire [1:0] dispatch_rresp = (read_target_q == T_MEMORY) ? mem_rresp :
                                (read_target_q == T_UNMAPPED) ? err_rresp : page_rresp_sel;

    wire dispatch_aw_handshake = dispatch_awvalid && dispatch_awready;
    wire dispatch_w_handshake = dispatch_wvalid && dispatch_wready;
    wire dispatch_ar_handshake = dispatch_arvalid && dispatch_arready;

    assign s_axil_bvalid = reset_n && dispatch_bvalid;
    assign s_axil_bresp = dispatch_bresp;
    assign s_axil_rvalid = reset_n && dispatch_rvalid;
    assign s_axil_rdata = dispatch_rdata;
    assign s_axil_rresp = dispatch_rresp;

    // ---- transaction sequencers ------------------------------------------
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            write_state_q <= W_COLLECT;
            read_state_q <= R_COLLECT;
            aw_captured_q <= 1'b0;
            w_captured_q <= 1'b0;
            aw_sent_q <= 1'b0;
            w_sent_q <= 1'b0;
            ar_captured_q <= 1'b0;
            ar_sent_q <= 1'b0;
            write_addr_q <= 32'd0;
            write_data_q <= 32'd0;
            write_strb_q <= 4'd0;
            write_prot_q <= 3'd0;
            write_target_q <= T_NONE;
            read_addr_q <= 32'd0;
            read_prot_q <= 3'd0;
            read_target_q <= T_NONE;
        end else begin
            case (write_state_q)
                W_COLLECT: begin
                    if (aw_accept) begin
                        write_addr_q <= s_axil_awaddr;
                        write_prot_q <= s_axil_awprot;
                        write_target_q <= decode(s_axil_awaddr, PAGE_MASK);
                        aw_captured_q <= 1'b1;
                    end
                    if (w_accept) begin
                        write_data_q <= s_axil_wdata;
                        write_strb_q <= s_axil_wstrb;
                        w_captured_q <= 1'b1;
                    end
                    if ((aw_captured_q || aw_accept) && (w_captured_q || w_accept)) begin
                        write_state_q <= W_DISPATCH;
                        aw_sent_q <= 1'b0;
                        w_sent_q <= 1'b0;
                    end
                end
                W_DISPATCH: begin
                    if (dispatch_aw_handshake) aw_sent_q <= 1'b1;
                    if (dispatch_w_handshake) w_sent_q <= 1'b1;
                    if ((aw_sent_q || dispatch_aw_handshake) &&
                        (w_sent_q || dispatch_w_handshake))
                        write_state_q <= W_RESPONSE;
                end
                W_RESPONSE: begin
                    if (s_axil_bvalid && s_axil_bready) begin
                        write_state_q <= W_COLLECT;
                        aw_captured_q <= 1'b0;
                        w_captured_q <= 1'b0;
                    end
                end
                default: write_state_q <= W_COLLECT;
            endcase

            case (read_state_q)
                R_COLLECT: begin
                    if (ar_accept) begin
                        read_addr_q <= s_axil_araddr;
                        read_prot_q <= s_axil_arprot;
                        read_target_q <= decode(s_axil_araddr, PAGE_MASK);
                        ar_captured_q <= 1'b1;
                        ar_sent_q <= 1'b0;
                        read_state_q <= R_DISPATCH;
                    end
                end
                R_DISPATCH: begin
                    if (dispatch_ar_handshake) begin
                        ar_sent_q <= 1'b1;
                        read_state_q <= R_RESPONSE;
                    end
                end
                R_RESPONSE: begin
                    if (s_axil_rvalid && s_axil_rready) begin
                        read_state_q <= R_COLLECT;
                        ar_captured_q <= 1'b0;
                    end
                end
                default: read_state_q <= R_COLLECT;
            endcase
        end
    end

    // ---- status and LEDs --------------------------------------------------
    // TODO(S1/S2): replace these stub-derived lines with the real pages'
    // completion/fault lines. LED0 = conv, LED1 = GEMM, LED2 = heartbeat.
    wire conv_irq = page_irq[0];
    wire gemm_irq = page_irq[1];

    logic [25:0] heartbeat;
    initial heartbeat = 0;
    always_ff @(posedge clk) begin
        if (!reset_n) heartbeat <= 26'd0;
        else heartbeat <= heartbeat + 1'b1;
    end

    assign led_3bits_tri_o = {heartbeat[25],
                              gemm_irq | fault,
                              conv_irq | fault}
                             ^ {3{LED_ACTIVE_LOW}};
endmodule
