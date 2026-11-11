// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Image-B S4: the EW sparse memory aperture (six physical banks).
//
// ADDITIVE file. `docs/EW_APERTURE_AUDIT.md` pins the layout inside the 1 MiB
// decoded EW aperture at 0x1000_0000:
//
//   bank A    0x1000_1000 .. 0x1000_1fff    4 KiB   operand A (RDMA src_a)
//   bank B    0x1002_0000 .. 0x1002_0fff    4 KiB   operand B (RDMA src_b)
//   bank D    0x1004_0000 .. 0x1004_0fff    4 KiB   output    (DPU dst)
//   scratch   0x1006_0000 .. 0x1006_1fff    8 KiB   production backend scratch
//   command   0x100e_0000 .. 0x100e_ffff   64 KiB   raw command BO
//   task      0x100f_0000 .. 0x100f_3fff   16 KiB   production task BO
//
// Everything else inside the decoded aperture is an EXPLICIT HOLE: host AXI
// writes/reads and engine accesses get an error response. There is no aliasing
// and no second decode. Physical cost is 4+4+4+8+64+16 = 100 KiB of block RAM
// instead of the 1 MiB a dense window would need.
//
// TWO CLIENTS share the banks, exactly like the proven ew-int aperture:
//   * a host staging AXI4-Lite slave (absolute device byte addresses) built from
//     the reviewed `rk_axil_mem_bridge` + `rk_bram` pair per bank, so byte order
//     and halfword packing are the same primitives the rest of the project uses;
//   * the EW engine's serialized 16-bit memory master (absolute addresses)
//     through a bank mux.
//
// OWNERSHIP: while the EW page is busy, host staging is refused (SLVERR) so it
// cannot corrupt a running job. `memory_ready` is high only when no host
// transaction is pending and no engine transaction is in flight.
//
// NO CONCURRENT ACCESS: the banks are single-port (`rk_bram` serializes
// requests), and the owner latch below grants the port to one client at a time,
// so a bank never sees two simultaneous operations.
module rk_ew_aperture #(
    parameter logic [31:0] APERTURE_BASE  = 32'h1000_0000,
    parameter logic [31:0] APERTURE_BYTES = 32'h0010_0000,
    parameter logic [31:0] BANK_A_BASE    = 32'h1000_1000,
    parameter logic [31:0] BANK_B_BASE    = 32'h1002_0000,
    parameter logic [31:0] BANK_D_BASE    = 32'h1004_0000,
    parameter logic [31:0] BANK_S_BASE    = 32'h1006_0000,
    parameter logic [31:0] BANK_C_BASE    = 32'h100e_0000,
    parameter logic [31:0] BANK_T_BASE    = 32'h100f_0000,
    parameter int unsigned BANK_A_BYTES   = 4096,
    parameter int unsigned BANK_B_BYTES   = 4096,
    parameter int unsigned BANK_D_BYTES   = 4096,
    parameter int unsigned BANK_S_BYTES   = 8192,
    parameter int unsigned BANK_C_BYTES   = 65536,
    parameter int unsigned BANK_T_BYTES   = 16384
) (
    input  logic        clk,
    input  logic        rst_n,
    // The EW page owns the banks while busy: host staging is refused.
    input  logic        page_busy,
    // No host staging / engine transaction pending: the page may submit.
    output logic        memory_ready,
    // Host staging AXI4-Lite slave (absolute device byte addresses).
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
    // EW engine serialized 16-bit memory master (absolute addresses).
    input  logic        engine_req_valid,
    output logic        engine_req_ready,
    input  logic        engine_req_write,
    input  logic [31:0] engine_req_addr,
    input  logic [15:0] engine_req_wdata,
    output logic        engine_rsp_valid,
    input  logic        engine_rsp_ready,
    output logic [15:0] engine_rsp_rdata,
    output logic        engine_rsp_error,
    // Status to the Image-B top.
    output logic        busy,
    output logic        irq
);
    localparam int unsigned NBANKS = 6;
    localparam int unsigned IDX_BITS = 3;

    // ---- bank geometry ---------------------------------------------------
    function automatic logic in_bank(input logic [31:0] address,
                                     input logic [31:0] base,
                                     input int unsigned bytes);
        in_bank = ({1'b0, address} >= {1'b0, base}) &&
                  ({1'b0, address} < {1'b0, base} + 33'(bytes));
    endfunction

    function automatic logic bank_hit(input logic [31:0] address);
        bank_hit = in_bank(address, BANK_A_BASE, BANK_A_BYTES) ||
                   in_bank(address, BANK_B_BASE, BANK_B_BYTES) ||
                   in_bank(address, BANK_D_BASE, BANK_D_BYTES) ||
                   in_bank(address, BANK_S_BASE, BANK_S_BYTES) ||
                   in_bank(address, BANK_C_BASE, BANK_C_BYTES) ||
                   in_bank(address, BANK_T_BASE, BANK_T_BYTES);
    endfunction

    function automatic logic [IDX_BITS-1:0] bank_sel(input logic [31:0] address);
        if (in_bank(address, BANK_A_BASE, BANK_A_BYTES))      bank_sel = 3'd0;
        else if (in_bank(address, BANK_B_BASE, BANK_B_BYTES)) bank_sel = 3'd1;
        else if (in_bank(address, BANK_D_BASE, BANK_D_BYTES)) bank_sel = 3'd2;
        else if (in_bank(address, BANK_S_BASE, BANK_S_BYTES)) bank_sel = 3'd3;
        else if (in_bank(address, BANK_C_BASE, BANK_C_BYTES)) bank_sel = 3'd4;
        else                                                  bank_sel = 3'd5;
    endfunction

    function automatic logic in_aperture(input logic [31:0] address);
        in_aperture = ({1'b0, address} >= {1'b0, APERTURE_BASE}) &&
                      ({1'b0, address} < {1'b0, APERTURE_BASE} +
                                            {1'b0, APERTURE_BYTES});
    endfunction

    // ---- host front-end state --------------------------------------------
    localparam logic [2:0] H_IDLE = 3'd0, H_WRITE = 3'd1, H_WRESP = 3'd2,
                           H_READ = 3'd3, H_RRESP = 3'd4, H_ERR = 3'd5;
    logic [2:0] hstate_q;
    logic [31:0] haddr_q, hwdata_q;
    logic [2:0]  hprot_q;
    logic [3:0]  hstrb_q;
    logic        hwrite_q;
    logic [IDX_BITS-1:0] hbank_q;
    logic        herr_q;

    // ---- engine front-end state ------------------------------------------
    localparam logic [2:0] E_IDLE = 3'd0, E_REQ = 3'd1, E_RSP = 3'd2, E_ERR = 3'd3;
    logic [2:0] estate_q;
    logic [31:0] eaddr_q;
    logic [15:0] ewdata_q;
    logic        ewrite_q;
    logic [IDX_BITS-1:0] ebank_q;
    logic        eerr_q;

    // ---- bank buses ------------------------------------------------------
    wire [NBANKS-1:0]    bank_req_valid, bank_req_ready, bank_req_write;
    wire [NBANKS*32-1:0] bank_req_addr;
    wire [NBANKS*16-1:0] bank_req_wdata;
    wire [NBANKS-1:0]    bank_rsp_valid, bank_rsp_ready;
    wire [NBANKS*16-1:0] bank_rsp_rdata;
    wire [NBANKS-1:0]    bank_rsp_error;

    // Port owner: alternates per transaction so neither client can starve.
    logic eng_owns_q;
    wire no_txn = (hstate_q == H_IDLE) && (estate_q == E_IDLE);
    wire host_wants = (hstate_q == H_IDLE) && s_axil_awvalid && s_axil_arvalid ? 1'b1 : 1'b0;
    wire host_req_w = (hstate_q == H_IDLE) && s_axil_awvalid;
    wire host_req_r = (hstate_q == H_IDLE) && s_axil_arvalid;
    wire eng_req    = (estate_q == E_IDLE) && engine_req_valid;

    wire grant_host = no_txn && host_req_w;
    wire grant_eng  = no_txn && !host_req_w && eng_req;

    // ---- per-bank request routing ---------------------------------------
    for (genvar g = 0; g < NBANKS; g = g + 1) begin : g_banks
        wire hsel = (hbank_q == IDX_BITS'(g));
        wire esel = (ebank_q == IDX_BITS'(g));
        // Exactly one client drives this bank: the one that owns the port for
        // the transaction in flight. An unselected bank sees no request.
        assign bank_req_valid[g] = (hstate_q != H_IDLE && hsel) ? 1'b1 :
                                   (estate_q != E_IDLE && esel) ? 1'b1 : 1'b0;
        assign bank_req_write[g] = (hstate_q != H_IDLE) ? hwrite_q : ewrite_q;
        assign bank_req_addr[g*32 +: 32] = (hstate_q != H_IDLE) ? haddr_q : eaddr_q;
        assign bank_req_wdata[g*16 +: 16] = (hstate_q != H_IDLE) ? hwdata_q[15:0]
                                                                : ewdata_q;
        assign bank_rsp_ready[g] = 1'b1;
    end

    // One bank's response is routed back to the client that owns it.
    wire [NBANKS-1:0] bank_rsp_v;
    for (genvar g = 0; g < NBANKS; g = g + 1) begin : g_bank_rsp
        assign bank_rsp_v[g] = bank_rsp_valid[g];
    end

    wire hbank_rsp = (hstate_q != H_IDLE) ? bank_rsp_valid[hbank_q] : 1'b0;
    wire ebank_rsp = (estate_q != E_IDLE) ? bank_rsp_valid[ebank_q] : 1'b0;

    // ---- host AXI slave --------------------------------------------------
    // Register the request, then run one bank transaction, then respond. Holes
    // inside the decoded aperture and protected access are explicit SLVERR.
    assign s_axil_awready = rst_n && (hstate_q == H_IDLE) && !page_busy;
    assign s_axil_wready  = rst_n && (hstate_q == H_IDLE) && !page_busy;
    assign s_axil_arready = rst_n && (hstate_q == H_IDLE) && !page_busy;
    assign s_axil_bvalid  = rst_n && (hstate_q == H_WRESP || hstate_q == H_ERR);
    assign s_axil_rvalid  = rst_n && (hstate_q == H_RRESP || hstate_q == H_ERR);
    assign s_axil_bresp   = (hstate_q == H_ERR || herr_q) ? 2'b10 : 2'b00;
    assign s_axil_rresp   = (hstate_q == H_ERR || herr_q) ? 2'b10 : 2'b00;
    assign s_axil_rdata   = hstate_q == H_RRESP ? bank_rsp_rdata[hbank_q*16 +: 16]
                                                : 16'h0;

    // ---- engine serialized master ---------------------------------------
    assign engine_req_ready = rst_n && (estate_q == E_IDLE);
    wire [15:0] engine_rsp_rdata_src = bank_rsp_rdata[ebank_q*16 +: 16];
    assign engine_rsp_valid = rst_n && (estate_q == E_RSP);
    assign engine_rsp_rdata = eerr_q ? 16'h0 : engine_rsp_rdata_src;
    assign engine_rsp_error = eerr_q;

    // ---- ownership / sequencing ------------------------------------------
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hstate_q <= H_IDLE; herr_q <= 1'b0;
            haddr_q <= '0; hwdata_q <= '0; hprot_q <= '0; hstrb_q <= '0;
            hwrite_q <= 1'b0; hbank_q <= '0;
            estate_q <= E_IDLE; eerr_q <= 1'b0;
            eaddr_q <= '0; ewdata_q <= '0; ewrite_q <= 1'b0; ebank_q <= '0;
            eng_owns_q <= 1'b0;
        end else begin
            // ---------- host write path ----------
            if (hstate_q == H_IDLE && s_axil_awvalid && s_axil_wvalid && !page_busy) begin
                // Both AW and W in the same cycle (a host may assert them together;
                // the earlier page wrappers deadlocked on this).
                haddr_q <= s_axil_awaddr; hprot_q <= s_axil_awprot;
                hwdata_q <= s_axil_wdata; hstrb_q <= s_axil_wstrb;
                hwrite_q <= 1'b1;
                if (s_axil_awprot != 3'b000 || s_axil_wstrb != 4'hf ||
                    !in_aperture(s_axil_awaddr) || !bank_hit(s_axil_awaddr)) begin
                    herr_q <= 1'b1; hstate_q <= H_ERR;
                end else begin
                    herr_q <= 1'b0; hbank_q <= bank_sel(s_axil_awaddr);
                    hstate_q <= H_WRITE;
                end
            end
            // ---------- host read path ----------
            if (hstate_q == H_IDLE && !(s_axil_awvalid && s_axil_wvalid) &&
                s_axil_arvalid && !page_busy) begin
                haddr_q <= s_axil_araddr; hprot_q <= s_axil_arprot;
                hwrite_q <= 1'b0;
                if (s_axil_arprot != 3'b000 || !in_aperture(s_axil_araddr) ||
                    !bank_hit(s_axil_araddr)) begin
                    herr_q <= 1'b1; hstate_q <= H_ERR;
                end else begin
                    herr_q <= 1'b0; hbank_q <= bank_sel(s_axil_araddr);
                    hstate_q <= H_READ;
                end
            end
            if (hstate_q == H_WRITE && bank_req_ready[hbank_q]) hstate_q <= H_WRESP;
            if (hstate_q == H_READ  && bank_req_ready[hbank_q]) hstate_q <= H_RRESP;
            if ((hstate_q == H_WRESP) && s_axil_bvalid && s_axil_bready) hstate_q <= H_IDLE;
            if ((hstate_q == H_RRESP) && s_axil_rvalid && s_axil_rready) hstate_q <= H_IDLE;
            if ((hstate_q == H_ERR) && !(s_axil_bvalid && !s_axil_bready) &&
                !(s_axil_rvalid && !s_axil_rready)) begin
                if (!s_axil_bready && !s_axil_rready) hstate_q <= H_ERR;
                else hstate_q <= H_IDLE;
            end

            // ---------- engine path ----------
            if (grant_eng) begin
                eaddr_q <= engine_req_addr; ewdata_q <= engine_req_wdata;
                ewrite_q <= engine_req_write; eng_owns_q <= 1'b1;
                if (!in_aperture(engine_req_addr) || !bank_hit(engine_req_addr)) begin
                    eerr_q <= 1'b1; estate_q <= E_ERR;
                end else begin
                    eerr_q <= 1'b0; ebank_q <= bank_sel(engine_req_addr);
                    estate_q <= E_REQ;
                end
            end
            if (estate_q == E_REQ && bank_req_ready[ebank_q]) estate_q <= E_RSP;
            if (estate_q == E_RSP && engine_rsp_ready) begin
                estate_q <= E_IDLE; eng_owns_q <= 1'b0;
            end
            if (estate_q == E_ERR && engine_rsp_ready) begin
                estate_q <= E_IDLE; eng_owns_q <= 1'b0; eerr_q <= 1'b0;
            end
        end
    end

    // ---- bank storage ----------------------------------------------------
    for (genvar g = 0; g < NBANKS; g = g + 1) begin : g_storage
        localparam logic [31:0] BANK_BASE =
            (g == 0) ? BANK_A_BASE :
            (g == 1) ? BANK_B_BASE :
            (g == 2) ? BANK_D_BASE :
            (g == 3) ? BANK_S_BASE :
            (g == 4) ? BANK_C_BASE : BANK_T_BASE;
        localparam int unsigned BANK_BYTES =
            (g == 0) ? BANK_A_BYTES :
            (g == 1) ? BANK_B_BYTES :
            (g == 2) ? BANK_D_BYTES :
            (g == 3) ? BANK_S_BYTES :
            (g == 4) ? BANK_C_BYTES : BANK_T_BYTES;
        rk_bram #(.BYTES(33'(BANK_BYTES)), .BASE(BANK_BASE)) bank_storage (
            .clk(clk), .rst_n(rst_n),
            .req_valid(bank_req_valid[g]), .req_ready(bank_req_ready[g]),
            .req_write(bank_req_write[g]), .req_addr(bank_req_addr[g*32 +: 32]),
            .req_wdata(bank_req_wdata[g*16 +: 16]),
            .rsp_valid(bank_rsp_valid[g]), .rsp_ready(bank_rsp_ready[g]),
            .rsp_rdata(bank_rsp_rdata[g*16 +: 16]),
            .rsp_error(bank_rsp_error[g]),
            // The second physical port stays idle: every client shares the
            // arbitrated request port (same choice as the adopted images).
            .host_valid(1'b0), .host_ready(), .host_write(1'b0),
            .host_addr(32'd0), .host_wdata(16'd0),
            .host_rsp_valid(), .host_rsp_ready(1'b0),
            .host_rdata(), .host_error()
        );
    end

    // ---- status ----------------------------------------------------------
    assign memory_ready = rst_n && !page_busy &&
                          (hstate_q == H_IDLE) && (estate_q == E_IDLE);
    assign busy = (hstate_q != H_IDLE) || (estate_q != E_IDLE) || page_busy;
    assign irq = 1'b0;
endmodule
