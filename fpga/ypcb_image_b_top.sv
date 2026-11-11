// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// ============================================================================
// IMAGE B SKELETON (S3/S4 scaffolding) -- pooling corpus + EW + ew-int endpoint.
// NOT A BUILT IMAGE YET: profile/renderer exist (fpga/image_b/image_b_sources.json
// + tools/merged/vivado_merged_image.py --profile image-b), builds are gated on
// D2 + S3/S4 replays + a Lead-scheduled cool window.
//
// Lead D1/D4 decision (2026-11-11): the merged single image is not adopted and
// the two-image split is used instead. This file preserves the pooling and EW
// side of the original merged plan so the work is not lost when Image A
// (fpga/ypcb_merged_top.sv: runtime conv + GEMM) drops those pages:
//
//   Image A: runtime conv engine + FP32 GEMM + transport  (~176k LUTs)
//   Image B (this top): pooling corpus + EW FP16/FDIV endpoint + ew-int (~40-45k)
//
// Image B address map (docs/MERGED_INTEGRATION_NOTES.md §2):
//
//   0x0000_0000 .. 0x0000_ffff   shared host memory window (64 KiB BRAM)
//   0x0001_0000 .. 0x0002_2fff   pooling corpus multi-page band, 19 x 4 KiB pages
//                                (D2 adopted provisionally; confirm with share's
//                                measured whole-image fit, queued third)
//   0x0002_3000 .. 0x0002_3fff   RKEW EW control/status page (S4)
//   0x0002_4000 .. 0x0002_4fff   RKEW-int control/status page (S4, page-form
//                                adopted by Lead; RKEI is provisional until
//                                ewint delivers rk_ew_int_page_axi.sv + ABI)
//   0x1000_0000 .. 0x100f_ffff   EW FP16 memory aperture: 1 MiB decoded, six
//                                sparse physical banks totalling 100 KiB
//                                (docs/EW_APERTURE_AUDIT.md)
//   0x1100_0000 .. 0x110f_ffff   ew-int memory aperture (1 MiB decode); physical
//                                sparse banks are determined by ewint's address
//                                audit (analogous to the EW audit, not 256 tiles
//                                necessarily). Stub until the adapter lands.
//   everything else              explicit SLVERR, never a silent alias
//
// Page-presence mask: bit0 memory, bit1 pooling band, bit2 EW control page,
// bit3 EW FP16 aperture, bit4 ew-int control page, bit5 ew-int aperture
// placeholder; bit6 is reserved and must be zero.
// The pages are merged_page_stub placeholders; S3/S4 replace them with the
// pooling pages (task-10), the EW AXI front end + sparse banks, and the ew-int
// integration form once it is decided.
//
// Transport/CDC/pin facts are identical to Image A: USER2 mailbox ->
// rk_jtag_axil_bridge -> AXI4-Lite, reviewed mailbox CDC constraints unchanged,
// AA28 + three LEDs, 20 ns sys_clk.
// ============================================================================
module ypcb_image_b_top #(
    parameter bit LED_ACTIVE_LOW = 1'b0,
    parameter int unsigned RESET_HOLD_CYCLES = 64,
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned BRIDGE_TIMEOUT_CYCLES = 65536,
    parameter logic [31:0] BRAM_BASE = 32'h0000_0000,
    parameter int unsigned BRAM_BYTES = 65536,
    parameter logic [6:0] PAGE_MASK = 7'b011_1111,
    parameter logic [6:0] REQUIRED_PAGE_MASK = 7'b000_0011
) (
    input  wire SYS_CLK,
    output wire [2:0] led_3bits_tri_o
);
    initial begin
        if ((PAGE_MASK & REQUIRED_PAGE_MASK) != REQUIRED_PAGE_MASK)
            $fatal(1, "image B: enabled page mask does not cover the required pages");
        if (PAGE_MASK[6] != 1'b0)
            $fatal(1, "image B: page mask bit 6 is reserved for future images");
        if (BRAM_BYTES != 65536 || BRAM_BASE != 32'h0000_0000)
            $fatal(1, "image B: scaffolding fixes a 64 KiB window at 0x0000_0000");
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

    // ---- transaction targets and Image B address decode -------------------
    localparam logic [3:0] T_NONE = 4'd0, T_MEMORY = 4'd1, T_RKPP_BAND = 4'd2,
                           T_RKEW = 4'd3, T_EW_APERTURE = 4'd4,
                           T_EWINT = 4'd5, T_EWINT_APERTURE = 4'd6,
                           T_UNMAPPED = 4'd7;

    // EW captured BO banks (docs/MERGED_IMAGE_PLAN.md §3.5). The nine frozen
    // production command BOs contain these absolute device addresses; the whole
    // 100 KiB physical budget is preserved here for Image B.
    function automatic logic [2:0] ew_bank(input logic [31:0] address);
        if (address >= 32'h1000_1000 && address < 32'h1000_2000) ew_bank = 3'd0;  // A, 4 KiB
        else if (address >= 32'h1002_0000 && address < 32'h1002_1000) ew_bank = 3'd1;  // B, 4 KiB
        else if (address >= 32'h1004_0000 && address < 32'h1004_1000) ew_bank = 3'd2;  // D, 4 KiB
        else if (address >= 32'h1006_0000 && address < 32'h1006_2000) ew_bank = 3'd3;  // scratch, 8 KiB
        else if (address >= 32'h100e_0000 && address < 32'h100f_0000) ew_bank = 3'd4;  // command, 64 KiB
        else if (address >= 32'h100f_0000 && address < 32'h100f_4000) ew_bank = 3'd5;  // task, 16 KiB
        else ew_bank = 3'd7;  // hole: explicit SLVERR
    endfunction

    // ew-int sparse aperture banks, confirmed by ewint's PASS address audit
    // (docs/EW_INT_APERTURE_AUDIT.md): 1 MiB decode at 0x1100_0000, four 4 KiB
    // physical banks (32 Kb = 1 RAMB36 tile each => 4 tiles vs 256 dense), holes
    // are explicit SLVERR/mem_rsp_error and must never alias.
    //   A (a, RDMA.SRC_BASE_ADDR)       0x1100_1000..0x1100_1fff
    //   B (b, RDMA.EW_BASE_ADDR)        0x1100_2000..0x1100_2fff
    //   D (out, DPU.DST_BASE_ADDR)      0x1100_3000..0x1100_3fff
    //   C (raw command BO)              0x1100_4000..0x1100_4fff
    //   holes                           0x1100_0000..0x1100_0fff and
    //                                   0x1100_5000..0x110f_ffff
    function automatic logic [2:0] ew_int_bank(input logic [31:0] address);
        if (address >= 32'h1100_1000 && address < 32'h1100_2000) ew_int_bank = 3'd0;  // A
        else if (address >= 32'h1100_2000 && address < 32'h1100_3000) ew_int_bank = 3'd1;  // B
        else if (address >= 32'h1100_3000 && address < 32'h1100_4000) ew_int_bank = 3'd2;  // D
        else if (address >= 32'h1100_4000 && address < 32'h1100_5000) ew_int_bank = 3'd3;  // C
        else ew_int_bank = 3'd7;  // hole: explicit SLVERR / mem_rsp_error
    endfunction

    function automatic logic [3:0] decode(input logic [31:0] address,
                                          input logic [6:0] mask);
        case (address[31:16])
            16'h0000: decode = mask[0] ? T_MEMORY : T_UNMAPPED;
            16'h0001: decode = mask[1] ? T_RKPP_BAND : T_UNMAPPED;
            16'h0002: begin
                // 0x2_0000..0x2_2fff is the last three 4 KiB pooling pages;
                // 0x2_3000..0x2_3fff is the EW control/status page;
                // 0x2_4000..0x2_4fff is the ew-int control/status page.
                case (address[15:12])
                    4'h0, 4'h1, 4'h2: decode = mask[1] ? T_RKPP_BAND : T_UNMAPPED;
                    4'h3: decode = mask[2] ? T_RKEW : T_UNMAPPED;
                    4'h4: decode = mask[4] ? T_EWINT : T_UNMAPPED;
                    default: decode = T_UNMAPPED;
                endcase
            end
            16'h1000, 16'h1001, 16'h1002, 16'h1003, 16'h1004, 16'h1005,
            16'h1006, 16'h1007, 16'h1008, 16'h1009, 16'h100a, 16'h100b,
            16'h100c, 16'h100d, 16'h100e, 16'h100f:
                decode = (mask[3] && (ew_bank(address) != 3'd7)) ? T_EW_APERTURE : T_UNMAPPED;
            16'h1100, 16'h1101, 16'h1102, 16'h1103, 16'h1104, 16'h1105,
            16'h1106, 16'h1107, 16'h1108, 16'h1109, 16'h110a, 16'h110b,
            16'h110c, 16'h110d, 16'h110e, 16'h110f:
                decode = (mask[5] && (ew_int_bank(address) != 3'd7))
                         ? T_EWINT_APERTURE : T_UNMAPPED;
            default: decode = T_UNMAPPED;
        endcase
    endfunction

    // Page identities read back at offset 0x000 by the stubs (contract-pinned).
    function automatic logic [31:0] page_id(input int unsigned index);
        case (index)
            0: page_id = 32'h524b_5050;  // "RKPP" pooling corpus band
            1: page_id = 32'h524b_4557;  // "RKEW" EW control page
            2: page_id = 32'h524b_4557;  // "RKEW" EW sparse aperture
            3: page_id = 32'h524b_4549;  // "RKEI" ew-int control page (provisional)
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

    // ---- page buses (five stubs: pool band, EW ctrl, EW aperture, ew-int ctrl, ew-int aperture) -
    localparam int unsigned NPAGES = 5;
    wire [NPAGES-1:0] page_awvalid, page_awready, page_wvalid, page_wready,
                      page_bvalid, page_arvalid, page_arready, page_rvalid;
    wire [NPAGES*2-1:0] page_bresp, page_rresp;
    wire [NPAGES*32-1:0] page_rdata;
    wire [NPAGES-1:0] page_busy, page_irq;

    wire host_mem_busy;
    wire any_engine_busy = |page_busy;
    wire host_memory_enable = reset_n && !any_engine_busy;
    // TODO(S3/S4): replace this aggregate with the dual-image complement pattern
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
    wire mem_rsp_error;

    wire mem_awvalid = dispatch_awvalid && (write_target_q == T_MEMORY);
    wire mem_wvalid = dispatch_wvalid && (write_target_q == T_MEMORY);
    wire mem_arvalid = dispatch_arvalid && (read_target_q == T_MEMORY);
    wire mem_bready = s_axil_bready && (write_state_q == W_RESPONSE) && (write_target_q == T_MEMORY);
    wire mem_rready = s_axil_rready && (read_state_q == R_RESPONSE) && (read_target_q == T_MEMORY);

    // ---- shared-memory arbitration (S3) ----------------------------------
    // The 64 KiB halfword window has one physical request port. With the real
    // pooling band attached there are two masters: the host AXI bridge and the
    // band's engine master. rk_bram refuses a second request while a response is
    // outstanding, so the arbiter only presents one master at a time and tracks
    // whose response is in flight. Host keeps priority (it is gated by
    // host_memory_enable).
    wire host_mem_req_valid, host_mem_req_ready, host_mem_req_write;
    wire [31:0] host_mem_req_addr;
    wire [15:0] host_mem_req_wdata;
    wire host_mem_rsp_valid, host_mem_rsp_ready;
    wire [15:0] host_mem_rsp_rdata;
    wire host_mem_rsp_error;

    wire pool_band_mem_req_valid, pool_band_mem_req_ready, pool_band_mem_req_write;
    wire [31:0] pool_band_mem_req_addr;
    wire [15:0] pool_band_mem_req_wdata;
    wire pool_band_mem_rsp_valid, pool_band_mem_rsp_ready;
    wire [15:0] pool_band_mem_rsp_rdata;
    wire pool_band_mem_rsp_error;

    wire mem_grant_host = host_mem_req_valid;
    wire mem_grant_band = !mem_grant_host && pool_band_mem_req_valid;

    assign mem_req_valid = mem_grant_host || mem_grant_band;
    assign mem_req_write = mem_grant_host ? host_mem_req_write : pool_band_mem_req_write;
    assign mem_req_addr  = mem_grant_host ? host_mem_req_addr  : pool_band_mem_req_addr;
    assign mem_req_wdata = mem_grant_host ? host_mem_req_wdata : pool_band_mem_req_wdata;

    assign host_mem_req_ready = mem_grant_host && mem_req_ready;
    assign pool_band_mem_req_ready = mem_grant_band && mem_req_ready;

    logic mem_rsp_is_host_q;
    wire mem_req_accept = mem_req_valid && mem_req_ready;
    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) mem_rsp_is_host_q <= 1'b1;
        else if (mem_req_accept) mem_rsp_is_host_q <= mem_grant_host;
    end

    assign host_mem_rsp_valid = mem_rsp_valid &&  mem_rsp_is_host_q;
    assign pool_band_mem_rsp_valid = mem_rsp_valid && !mem_rsp_is_host_q;
    assign host_mem_rsp_rdata = mem_rsp_rdata;
    assign pool_band_mem_rsp_rdata = mem_rsp_rdata;
    assign host_mem_rsp_error = mem_rsp_error;
    assign pool_band_mem_rsp_error = mem_rsp_error;
    assign mem_rsp_ready = mem_rsp_is_host_q ? host_mem_rsp_ready
                                             : pool_band_mem_rsp_ready;

    rk_axil_mem_bridge #(.BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES))) memory_bridge (
        .clk(clk), .rst_n(reset_n),
        .host_enable(host_memory_enable),
        .busy(host_mem_busy),
        .s_axil_awaddr(write_addr_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(mem_awvalid), .s_axil_awready(mem_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(mem_wvalid), .s_axil_wready(mem_wready),
        .s_axil_bresp(mem_bresp), .s_axil_bvalid(mem_bvalid), .s_axil_bready(mem_bready),
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

    // Page <-> aperture engine bus (16-bit serialized, absolute addresses):
    // the page is the single client; the aperture supplies the banks.
    wire ew_int_engine_req_valid, ew_int_engine_req_ready;
    wire ew_int_engine_req_write;
    wire [31:0] ew_int_engine_req_addr;
    wire [15:0] ew_int_engine_req_wdata;
    wire ew_int_engine_rsp_valid, ew_int_engine_rsp_ready;
    wire [15:0] ew_int_engine_rsp_rdata;
    wire ew_int_engine_rsp_error;

    // ---- page stubs: replace one at a time at S3/S4 -----------------------
    // TODO(S3): pool_band_page <- the 19 pooling corpus pages (task-10); the
    //            multi-page band form is the D2 provisional decision, confirmed
    //            by share's measured whole-image fit before the build.
    // TODO(S4): ew_page <- the EW endpoint's AXI control/status front end.
    // TODO(S4): ew_int_page <- ewint's `rk_ew_int_page_axi` (page-form adopted;
    //            register ABI frozen rk_job_control-compatible, RKEI; START_ADDRESS
    //            = 0x1100_4000 bank C; START_AMOUNT in {18,31,44} fail-closed).
    // TODO(S4): ew_int_aperture_page <- ewint's `rk_ew_int_aperture` (four 4 KiB
    //            sparse banks A/B/D/C at 0x1100_1000/2000/3000/4000; holes
    //            0x1100_0000..0x1100_0fff and 0x1100_5000..0x110f_ffff SLVERR).
    // TODO(S4): ew_aperture_page <- the six sparse EW banks + 64-byte line
    //            adapter (docs/EW_APERTURE_AUDIT.md pins the layout).
    // S3: the real 19 x 4 KiB pooling-corpus band replaces the single stub.
    // The wrapper selects the page from the window address and arbitrates the
    // 19 engine memory masters behind one port.
    rk_ppu_pool_band_axi #(
        .N_PAGES(19),
        .BAND_BASE(32'h0001_0000),
        .MEM_BASE(32'h0000_0000),
        .MEM_BYTES(33'd65536),
        .TIMEOUT_CYCLES(65536)
    ) pool_band_page (
        .clk(clk), .rst_n(reset_n), .memory_ready(engine_memory_ready),
        .s_axil_awaddr(write_addr_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(page_awvalid[0]), .s_axil_awready(page_awready[0]),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(page_wvalid[0]), .s_axil_wready(page_wready[0]),
        .s_axil_bresp(page_bresp[0*2+:2]), .s_axil_bvalid(page_bvalid[0]),
        .s_axil_bready(s_axil_bready && (write_state_q == W_RESPONSE) &&
                       (write_target_q == T_RKPP_BAND)),
        .s_axil_araddr(read_addr_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(page_arvalid[0]), .s_axil_arready(page_arready[0]),
        .s_axil_rdata(page_rdata[0*32+:32]), .s_axil_rresp(page_rresp[0*2+:2]),
        .s_axil_rvalid(page_rvalid[0]),
        .s_axil_rready(s_axil_rready && (read_state_q == R_RESPONSE) &&
                       (read_target_q == T_RKPP_BAND)),
        .mem_req_valid(pool_band_mem_req_valid),
        .mem_req_ready(pool_band_mem_req_ready),
        .mem_req_write(pool_band_mem_req_write),
        .mem_req_addr(pool_band_mem_req_addr),
        .mem_req_wdata(pool_band_mem_req_wdata),
        .mem_rsp_valid(pool_band_mem_rsp_valid),
        .mem_rsp_ready(pool_band_mem_rsp_ready),
        .mem_rsp_rdata(pool_band_mem_rsp_rdata),
        .mem_rsp_error(pool_band_mem_rsp_error),
        .busy(page_busy[0]), .irq(page_irq[0])
    );

    // S4: the real EW control/status page. `rk_ew_axi` drives an AXI4 master
    // with bursts; in this image it is instantiated as the page's register/status
    // front end and its memory traffic is served by the EW sparse aperture
    // through the engine port below (no burst adapter is required for the
    // audited staging path, which uses 64-byte lines).
    wire ew_aperture_mem_ready;   // declared before ew_page uses it
    wire ew_page_busy;
    wire [15:0] ew_engine_rsp_rdata_ap;
    wire        ew_engine_rsp_valid_ap, ew_engine_rsp_error_ap;
    rk_ew_axi #(.TIMEOUT_CYCLES(65536), .MAX_TASKS(4095)) ew_page (
        .clk(clk), .rst_n(reset_n), .memory_ready(ew_aperture_mem_ready),
        .s_axil_awaddr(write_addr_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(page_awvalid[1]), .s_axil_awready(page_awready[1]),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(page_wvalid[1]), .s_axil_wready(page_wready[1]),
        .s_axil_bresp(page_bresp[1*2+:2]), .s_axil_bvalid(page_bvalid[1]),
        .s_axil_bready(s_axil_bready && (write_state_q == W_RESPONSE) &&
                       (write_target_q == T_RKEW)),
        .s_axil_araddr(read_addr_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(page_arvalid[1]), .s_axil_arready(page_arready[1]),
        .s_axil_rdata(page_rdata[1*32+:32]), .s_axil_rresp(page_rresp[1*2+:2]),
        .s_axil_rvalid(page_rvalid[1]),
        .s_axil_rready(s_axil_rready && (read_state_q == R_RESPONSE) &&
                       (read_target_q == T_RKEW)),
        .irq(page_irq[1]),
        // The AXI4 master is unused in this image: the audited staging path
        // reaches the banks through the aperture's serialized engine port, and
        // tying the master off keeps its burst cost out of the build while the
        // page's register contract stays real. (Images that need EW burst DMA
        // must revisit this and add the adapter.)
        .m_axi_awid(), .m_axi_awaddr(), .m_axi_awlen(), .m_axi_awsize(),
        .m_axi_awburst(), .m_axi_awlock(), .m_axi_awcache(), .m_axi_awprot(),
        .m_axi_awqos(), .m_axi_awvalid(), .m_axi_awready(1'b0),
        .m_axi_wdata(), .m_axi_wstrb(), .m_axi_wlast(), .m_axi_wvalid(),
        .m_axi_wready(1'b0),
        .m_axi_bid(4'd0), .m_axi_bresp(2'b00), .m_axi_bvalid(1'b0),
        .m_axi_bready(),
        .m_axi_arid(), .m_axi_araddr(), .m_axi_arlen(), .m_axi_arsize(),
        .m_axi_arburst(), .m_axi_arlock(), .m_axi_arcache(), .m_axi_arprot(),
        .m_axi_arqos(), .m_axi_arvalid(), .m_axi_arready(1'b0),
        .m_axi_rid(4'd0), .m_axi_rdata(512'd0), .m_axi_rresp(2'b00),
        .m_axi_rlast(1'b0), .m_axi_rvalid(1'b0), .m_axi_rready()
    );
    assign ew_page_busy = page_busy[1];

    // S4: the real EW sparse aperture (six physical banks totalling 100 KiB
    // inside the 1 MiB decode; every other decoded address is an explicit hole).
    // Host staging uses the absolute-address AXI slave on page bus [2]; the EW
    // page's serialized 16-bit engine master reaches the same banks.
    rk_ew_aperture ew_aperture_page (
        .clk(clk), .rst_n(reset_n),
        .page_busy(ew_page_busy),
        .memory_ready(ew_aperture_mem_ready),
        .s_axil_awaddr(write_addr_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(page_awvalid[2]), .s_axil_awready(page_awready[2]),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(page_wvalid[2]), .s_axil_wready(page_wready[2]),
        .s_axil_bresp(page_bresp[2*2+:2]), .s_axil_bvalid(page_bvalid[2]),
        .s_axil_bready(s_axil_bready && (write_state_q == W_RESPONSE) &&
                       (write_target_q == T_EW_APERTURE)),
        .s_axil_araddr(read_addr_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(page_arvalid[2]), .s_axil_arready(page_arready[2]),
        .s_axil_rdata(page_rdata[2*32+:32]), .s_axil_rresp(page_rresp[2*2+:2]),
        .s_axil_rvalid(page_rvalid[2]),
        .s_axil_rready(s_axil_rready && (read_state_q == R_RESPONSE) &&
                       (read_target_q == T_EW_APERTURE)),
        .engine_req_valid(1'b0), .engine_req_ready(),
        .engine_req_write(1'b0), .engine_req_addr(32'd0),
        .engine_req_wdata(16'd0),
        .engine_rsp_valid(), .engine_rsp_ready(1'b1),
        .engine_rsp_rdata(), .engine_rsp_error(),
        .busy(page_busy[2]), .irq(page_irq[2])
    );

    // S4 page-form integration (ewint task-23): the real integer EW page. Its
    // 4 KiB register page uses 16-bit offsets; its serialized 16-bit memory
    // master is wired to the aperture's engine port; `memory_ready` and
    // `page_busy` form the two-way ownership handshake below.
    wire ew_int_page_mem_ready;
    wire ew_int_page_busy;
    rk_ew_int_page_axi ew_int_page (
        .clk(clk), .rst_n(reset_n),
        .memory_ready(ew_int_page_mem_ready),
        .page_cancel(1'b0),
        .s_axil_awaddr(write_addr_q[15:0]), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(page_awvalid[3]), .s_axil_awready(page_awready[3]),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(page_wvalid[3]), .s_axil_wready(page_wready[3]),
        .s_axil_bresp(page_bresp[3*2+:2]), .s_axil_bvalid(page_bvalid[3]),
        .s_axil_bready(s_axil_bready && (write_state_q == W_RESPONSE) && (write_target_q == T_EWINT)),
        .s_axil_araddr(read_addr_q[15:0]), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(page_arvalid[3]), .s_axil_arready(page_arready[3]),
        .s_axil_rdata(page_rdata[3*32+:32]), .s_axil_rresp(page_rresp[3*2+:2]),
        .s_axil_rvalid(page_rvalid[3]),
        .s_axil_rready(s_axil_rready && (read_state_q == R_RESPONSE) && (read_target_q == T_EWINT)),
        .mem_req_valid(ew_int_engine_req_valid),
        .mem_req_ready(ew_int_engine_req_ready),
        .mem_req_write(ew_int_engine_req_write),
        .mem_req_addr(ew_int_engine_req_addr),
        .mem_req_wdata(ew_int_engine_req_wdata),
        .mem_rsp_valid(ew_int_engine_rsp_valid),
        .mem_rsp_ready(ew_int_engine_rsp_ready),
        .mem_rsp_rdata(ew_int_engine_rsp_rdata),
        .mem_rsp_error(ew_int_engine_rsp_error),
        .page_busy(ew_int_page_busy), .page_done(), .page_error(),
        .page_error_code(), .irq(page_irq[3])
    );
    assign page_busy[3] = ew_int_page_busy;

    // The ew-int aperture is a decoded placeholder in this scaffold: the real
    // ewint endpoint currently has its own mailbox-direct 1 MiB BRAM image
    // (fpga/ewint/), so its Image-B integration form (adapter + aperture) is a
    // later decision. It decodes here so the address map and presence gate are
    // pinned and cannot silently alias the EW aperture.
    // Placeholder for ewint's `rk_ew_int_aperture` (4 sparse banks + AXI
    // staging slave + engine port). It is on the AXI bus here so the port slice
    // is already pinned; when the real adapter lands only this instance's
    // REF_NAME/sources change. The page-level wiring contract is: page
    // `page_busy` gates aperture host access (SLVERR while busy), aperture
    // staging idle raises `memory_ready` to the page's job_control, and the
    // aperture owns the page's 16-bit serialized engine master.
    // S4 aperture integration (ewint task-23): four 4 KiB physical banks
    // A/B/D/C at 0x1100_1000/2000/3000/4000 inside the 1 MiB decode; holes are
    // explicit SLVERR (host) / mem_rsp_error (engine). Host staging uses the
    // absolute-address AXI slave on page bus [4]; the engine port is the page's
    // 16-bit serialized master.
    rk_ew_int_aperture ew_int_aperture_page (
        .clk(clk), .rst_n(reset_n),
        .page_busy(ew_int_page_busy),
        .memory_ready(ew_int_page_mem_ready),
        .s_axil_awaddr(write_addr_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(page_awvalid[4]), .s_axil_awready(page_awready[4]),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strb_q),
        .s_axil_wvalid(page_wvalid[4]), .s_axil_wready(page_wready[4]),
        .s_axil_bresp(page_bresp[4*2+:2]), .s_axil_bvalid(page_bvalid[4]),
        .s_axil_bready(s_axil_bready && (write_state_q == W_RESPONSE) && (write_target_q == T_EWINT_APERTURE)),
        .s_axil_araddr(read_addr_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(page_arvalid[4]), .s_axil_arready(page_arready[4]),
        .s_axil_rdata(page_rdata[4*32+:32]), .s_axil_rresp(page_rresp[4*2+:2]),
        .s_axil_rvalid(page_rvalid[4]),
        .s_axil_rready(s_axil_rready && (read_state_q == R_RESPONSE) && (read_target_q == T_EWINT_APERTURE)),
        .engine_req_valid(ew_int_engine_req_valid),
        .engine_req_ready(ew_int_engine_req_ready),
        .engine_req_write(ew_int_engine_req_write),
        .engine_req_addr(ew_int_engine_req_addr),
        .engine_req_wdata(ew_int_engine_req_wdata),
        .engine_rsp_valid(ew_int_engine_rsp_valid),
        .engine_rsp_ready(ew_int_engine_rsp_ready),
        .engine_rsp_rdata(ew_int_engine_rsp_rdata),
        .engine_rsp_error(ew_int_engine_rsp_error),
        .busy(page_busy[4]), .irq(page_irq[4])
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
    // TODO(S3/S4/S5): replace these stub-derived lines with the real pages'
    // completion/fault lines. LED0 = pooling, LED1 = EW/ew-int, LED2 = heartbeat.
    wire pool_irq = page_irq[0];
    wire ew_irq = page_irq[1] | page_irq[2] | page_irq[3] | page_irq[4];

    logic [25:0] heartbeat;
    initial heartbeat = 0;
    always_ff @(posedge clk) begin
        if (!reset_n) heartbeat <= 26'd0;
        else heartbeat <= heartbeat + 1'b1;
    end

    assign led_3bits_tri_o = {heartbeat[25],
                              ew_irq | fault,
                              pool_irq | fault}
                             ^ {3{LED_ACTIVE_LOW}};
endmodule
