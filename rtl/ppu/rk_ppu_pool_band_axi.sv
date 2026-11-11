// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Image-B S3: the pooling-corpus page BAND.
//
// ADDITIVE integration file. It turns the decided 19 x 4 KiB band form
// (0x0001_0000 .. 0x0002_2fff, one corpus case per 4 KiB page) into ONE
// AXI4-Lite slave + ONE memory master, so `ypcb_image_b_top` keeps its page-bus
// structure unchanged while the band stops being a placeholder stub.
//
// Why a wrapper instead of 19 lanes in the top: the band occupies 19 consecutive
// 4 KiB windows but presents itself to the top as a single "pool band" page. The
// wrapper does the per-page selection internally (page index = window >> 12) and
// arbitrates the 19 engine memory masters behind one port, which is the same
// discipline the Image-A merged top uses for its companies.
//
// Memory arbitration: `rk_bram` refuses a second request while a response is
// outstanding (`req_ready = !rsp_valid || rsp_ready`), so the pages cannot steal
// each other's beats. The wrapper only has to present one master at a time and
// remember whose response is in flight. Fixed priority: lowest live index wins,
// so a page that is idling never blocks a page that is requesting.
//
// Everything here is additive: no adopted page, no frozen file and no existing
// top is modified.
module rk_ppu_pool_band_axi #(
    parameter int unsigned N_PAGES = 19,
    // Window-relative base of the band inside the AXI address space. The top
    // passes the full window address, so the wrapper masks to the band.
    parameter logic [31:0] BAND_BASE = 32'h0001_0000,
    // Per-page memory aperture (the shared 64 KiB halfword window).
    parameter logic [31:0] MEM_BASE = 32'h0000_0000,
    parameter logic [32:0] MEM_BYTES = 33'd65536,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        memory_ready,
    // AXI4-Lite slave (one page for the whole band)
    input  logic [31:0] s_axil_awaddr,
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
    input  logic [31:0] s_axil_araddr,
    input  logic [2:0]  s_axil_arprot,
    input  logic        s_axil_arvalid,
    output logic        s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0]  s_axil_rresp,
    output logic        s_axil_rvalid,
    input  logic        s_axil_rready,
    // One engine memory master for the whole band.
    output logic        mem_req_valid,
    input  logic        mem_req_ready,
    output logic        mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input  logic        mem_rsp_valid,
    output logic        mem_rsp_ready,
    input  logic [15:0] mem_rsp_rdata,
    input  logic        mem_rsp_error,
    // Observation
    output logic        busy,
    output logic        irq
);
    localparam int unsigned IDX_BITS = (N_PAGES <= 1) ? 1 : $clog2(N_PAGES);

    // ---- page selection -------------------------------------------------
    // The band is 19 consecutive 4 KiB windows. A page index is only valid when
    // the whole address lies inside that page's window; anything else is an
    // explicit no-page (the top's own decode already rejects out-of-band
    // addresses, so this is a belt-and-braces check).
    function automatic logic page_ok(input logic [31:0] address);
        page_ok = (address >= BAND_BASE) &&
                  (address < BAND_BASE + 32'(N_PAGES) * 32'd4096);
    endfunction
    function automatic logic [IDX_BITS-1:0] page_index(input logic [31:0] address);
        page_index = IDX_BITS'((address - BAND_BASE) >> 12);
    endfunction

    // ---- per-page buses -------------------------------------------------
    wire [N_PAGES-1:0] pg_awvalid, pg_awready, pg_wvalid, pg_wready;
    wire [N_PAGES-1:0] pg_bvalid, pg_arvalid, pg_arready, pg_rvalid;
    wire [N_PAGES-1:0] pg_busy, pg_irq;
    wire [N_PAGES*2-1:0] pg_bresp, pg_rresp;
    wire [N_PAGES*32-1:0] pg_rdata;

    wire [N_PAGES-1:0]         pg_mem_req_valid, pg_mem_req_ready, pg_mem_req_write;
    wire [N_PAGES*32-1:0]      pg_mem_req_addr;
    wire [N_PAGES*16-1:0]      pg_mem_req_wdata;
    wire [N_PAGES-1:0]         pg_mem_rsp_valid, pg_mem_rsp_ready;
    wire [N_PAGES*16-1:0]      pg_mem_rsp_rdata;
    wire [N_PAGES-1:0]         pg_mem_rsp_error;
    // Response nets driven BY the wrapper (the pages are responders here).
    wire [N_PAGES-1:0]         pg_mem_rsp_valid_n;
    wire [N_PAGES*16-1:0]      pg_mem_rsp_rdata_n;
    wire [N_PAGES-1:0]         pg_mem_rsp_error_n;

    // Selected page for the in-flight AXI transaction. Captured when the
    // transaction is accepted so the response can be routed back.
    logic [IDX_BITS-1:0] aw_page_q, ar_page_q;
    logic pv_aw_q, pv_ar_q;

    wire aw_hit = page_ok(s_axil_awaddr);
    wire ar_hit = page_ok(s_axil_araddr);
    wire [IDX_BITS-1:0] aw_idx = page_index(s_axil_awaddr);
    wire [IDX_BITS-1:0] ar_idx = page_index(s_axil_araddr);

    for (genvar p = 0; p < N_PAGES; p = p + 1) begin : g_pages
        assign pg_awvalid[p] = s_axil_awvalid && aw_hit && (aw_idx == IDX_BITS'(p));
        assign pg_wvalid[p]  = s_axil_wvalid  && pv_aw_q && (aw_page_q == IDX_BITS'(p));
        assign pg_arvalid[p] = s_axil_arvalid && ar_hit && (ar_idx == IDX_BITS'(p));
    end

    assign s_axil_awready = aw_hit && pg_awready[aw_idx];
    assign s_axil_wready  = pv_aw_q && pg_wready[aw_page_q];
    assign s_axil_arready = ar_hit && pg_arready[ar_idx];

    // ---- response mux ---------------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            aw_page_q <= '0; ar_page_q <= '0;
            pv_aw_q <= 1'b0; pv_ar_q <= 1'b0;
        end else begin
            if (s_axil_awvalid && aw_hit && pg_awready[aw_idx]) begin
                aw_page_q <= aw_idx; pv_aw_q <= 1'b1;
            end
            if (s_axil_bvalid && s_axil_bready) pv_aw_q <= 1'b0;
            if (s_axil_arvalid && ar_hit && pg_arready[ar_idx]) begin
                ar_page_q <= ar_idx; pv_ar_q <= 1'b1;
            end
            if (s_axil_rvalid && s_axil_rready) pv_ar_q <= 1'b0;
        end
    end

    assign s_axil_bvalid = pv_aw_q ? pg_bvalid[aw_page_q] : 1'b0;
    assign s_axil_bresp  = pv_aw_q ? pg_bresp[aw_page_q*2 +: 2] : 2'b00;
    assign s_axil_rvalid = pv_ar_q ? pg_rvalid[ar_page_q] : 1'b0;
    assign s_axil_rresp  = pv_ar_q ? pg_rresp[ar_page_q*2 +: 2] : 2'b00;
    assign s_axil_rdata  = pv_ar_q ? pg_rdata[ar_page_q*32 +: 32] : 32'd0;

    assign busy = |pg_busy;
    assign irq  = |pg_irq;

    // ---- 19 -> 1 memory arbitration -------------------------------------
    logic [IDX_BITS-1:0] mem_page_q;
    logic mem_owner_v_q;
    wire [IDX_BITS-1:0] mem_req_idx;
    logic mem_grant_any;

    assign mem_req_idx = '0;   // replaced by the priority chain below

    // Priority: lowest live index. Only one master may be granted, and only
    // while no response is outstanding.
    logic [N_PAGES-1:0] grant_vec;
    always_comb begin
        grant_vec = '0;
        if (!mem_owner_v_q) begin
            // synthesis: small priority encoder (19 entries is trivial)
            for (int p = N_PAGES - 1; p >= 0; p = p - 1) begin
                if (pg_mem_req_valid[p]) begin
                    grant_vec = '0;
                    grant_vec[p] = 1'b1;
                end
            end
        end
    end
    wire [IDX_BITS-1:0] grant_idx;

    // One-hot vector to index (priority encoder).
    logic [IDX_BITS-1:0] enc;
    always_comb begin
        enc = '0;
        for (int p = 0; p < N_PAGES; p = p + 1)
            if (grant_vec[p]) enc = IDX_BITS'(p);
    end
    assign grant_idx = enc;
    assign mem_grant_any = |grant_vec;

    // Select with an explicit index (one-hot -> index) rather than a variable
    // part-select, which keeps the width inference unambiguous.
    assign mem_req_valid = mem_grant_any && pg_mem_req_valid[grant_idx];
    assign mem_req_write = pg_mem_req_write[grant_idx];
    assign mem_req_addr  = pg_mem_req_addr[grant_idx*32 +: 32];
    assign mem_req_wdata = pg_mem_req_wdata[grant_idx*16 +: 16];

    // Forward the memory response to the page that owns the outstanding
    // transaction. NOTE: pg_mem_rsp_valid is the page's INPUT in this direction
    // (the page is the responder here), so it must not appear on the right-hand
    // side. An earlier version wrote `pg_mem_rsp_valid[p] = pg_mem_rsp_valid[p]
    // && ...`, which is a self-referential combinational loop in every one of the
    // 19 instances (Vivado LUTLP-1 Critical Warning, blocking the build's DRC
    // gate).
    for (genvar p = 0; p < N_PAGES; p = p + 1) begin : g_memresp
        assign pg_mem_req_ready[p] = grant_vec[p] && mem_req_ready;
        assign pg_mem_rsp_valid_n[p] = mem_rsp_valid && mem_owner_v_q &&
                                       (mem_page_q == IDX_BITS'(p));
        assign pg_mem_rsp_rdata_n[p*16 +: 16] = mem_rsp_rdata;
        assign pg_mem_rsp_error_n[p] = mem_rsp_error;
    end
    assign mem_rsp_ready = mem_owner_v_q ? pg_mem_rsp_ready[mem_page_q] : 1'b0;

    wire mem_accept = mem_req_valid && mem_req_ready;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mem_page_q <= '0; mem_owner_v_q <= 1'b0;
        end else begin
            if (mem_accept) begin
                mem_page_q <= grant_idx; mem_owner_v_q <= 1'b1;
            end
            if (mem_owner_v_q && mem_rsp_valid && mem_rsp_ready)
                mem_owner_v_q <= 1'b0;
        end
    end

    // ---- the 19 corpus pages ---------------------------------------------
    localparam logic [31:0] PAGE_SPAN = 32'd4096;
    for (genvar p = 0; p < N_PAGES; p = p + 1) begin : g_page_inst
        // KEEP_HIERARCHY mirrors the standalone corpus image: without it the
        // flattener synthesises a one-LUT combinatorial loop inside the captured
        // leaf engines (Vivado LUTLP-1 Critical Warning), which the Image-B DRC
        // gate correctly refuses. It also keeps the page boundary intact for the
        // REF_NAME page-presence gate.
        (* KEEP_HIERARCHY = "TRUE" *)
        rk_ppu_pool_corpus_axi #(
            .CASE(p),
            .BASE(MEM_BASE), .BYTES(MEM_BYTES),
            .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
        ) pool_page (
            .clk(clk), .rst_n(rst_n), .memory_ready(memory_ready),
            .s_axil_awaddr(s_axil_awaddr),
            .s_axil_awprot(s_axil_awprot),
            .s_axil_awvalid(pg_awvalid[p]), .s_axil_awready(pg_awready[p]),
            .s_axil_wdata(s_axil_wdata), .s_axil_wstrb(s_axil_wstrb),
            .s_axil_wvalid(pg_wvalid[p]), .s_axil_wready(pg_wready[p]),
            .s_axil_bresp(pg_bresp[p*2 +: 2]), .s_axil_bvalid(pg_bvalid[p]),
            .s_axil_bready(s_axil_bready && pv_aw_q &&
                           (aw_page_q == IDX_BITS'(p))),
            .s_axil_araddr(s_axil_araddr),
            .s_axil_arprot(s_axil_arprot),
            .s_axil_arvalid(pg_arvalid[p]), .s_axil_arready(pg_arready[p]),
            .s_axil_rdata(pg_rdata[p*32 +: 32]),
            .s_axil_rresp(pg_rresp[p*2 +: 2]),
            .s_axil_rvalid(pg_rvalid[p]),
            .s_axil_rready(s_axil_rready && pv_ar_q &&
                           (ar_page_q == IDX_BITS'(p))),
            .mem_req_valid(pg_mem_req_valid[p]),
            .mem_req_ready(pg_mem_req_ready[p]),
            .mem_req_write(pg_mem_req_write[p]),
            .mem_req_addr(pg_mem_req_addr[p*32 +: 32]),
            .mem_req_wdata(pg_mem_req_wdata[p*16 +: 16]),
            .mem_rsp_valid(pg_mem_rsp_valid_n[p]),
            .mem_rsp_ready(pg_mem_rsp_ready[p]),
            .mem_rsp_rdata(pg_mem_rsp_rdata_n[p*16 +: 16]),
            .mem_rsp_error(pg_mem_rsp_error_n[p]),
            .busy(pg_busy[p]), .irq(pg_irq[p])
        );
    end
endmodule
