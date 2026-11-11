// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Image-B ew-int sparse memory aperture (task-23).
//
// ADDITIVE file. It presents the four physical 4 KiB banks pinned by
// docs/EW_INT_APERTURE_AUDIT.md inside the 1 MiB decoded aperture at
// 0x1100_0000:
//
//   bank A  0x1100_1000..0x1100_1fff   operand a (RDMA.SRC_BASE_ADDR)
//   bank B  0x1100_2000..0x1100_2fff   operand b (RDMA.EW_BASE_ADDR)
//   bank D  0x1100_3000..0x1100_3fff   output    (DPU.DST_BASE_ADDR)
//   bank C  0x1100_4000..0x1100_4fff   raw command BO (page START_ADDRESS)
//
// Everything else inside the decoded aperture is an explicit hole: AXI writes
// and reads get SLVERR, engine accesses get a memory-response error. There is
// no aliasing and no second decode. Physical cost is four RAMB36 tiles
// (2048x16 each) instead of the 256 tiles a dense 1 MiB window would need.
//
// Two clients share the banks:
//   * the host staging AXI4-Lite slave (32-bit, all four byte strobes
//     required, protected access SLVERR) uses the frozen rk_axil_mem_bridge /
//     rk_bram pair per bank, so byte order and halfword packing are the same
//     reviewed primitives as the rest of the project;
//   * the ew-int page's serialized 16-bit memory master (absolute addresses)
//     reaches the same banks through a bank mux.
//
// Ownership discipline (same as the standalone ew-int image): while the page is
// busy the host staging port refuses access with SLVERR and cannot corrupt a
// running job; `memory_ready` is high only when no host transaction is pending
// and no engine transaction is in flight, so the page can submit safely. Bank
// contents are never reset (BRAM inference); the platform resets the control
// domain only.
module rk_ew_int_aperture #(
    parameter logic [31:0] APERTURE_BASE = 32'h1100_0000,
    parameter logic [31:0] APERTURE_BYTES = 32'h0010_0000,
    parameter logic [31:0] BANK_A_BASE = 32'h1100_1000,
    parameter logic [31:0] BANK_B_BASE = 32'h1100_2000,
    parameter logic [31:0] BANK_D_BASE = 32'h1100_3000,
    parameter logic [31:0] BANK_C_BASE = 32'h1100_4000,
    parameter int unsigned BANK_BYTES = 4096
) (
    input  logic        clk,
    input  logic        rst_n,
    // The ew-int page owns the banks while busy: host staging is refused.
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
    // ew-int page serialized 16-bit memory master (absolute addresses).
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
    localparam int unsigned NBANKS = 4;

    function automatic logic in_bank(input logic [31:0] address,
                                     input logic [31:0] base);
        in_bank = ({1'b0, address} >= {1'b0, base}) &&
                  ({1'b0, address} < {1'b0, base} + 33'(BANK_BYTES));
    endfunction

    function automatic logic [1:0] bank_sel(input logic [31:0] address);
        if (in_bank(address, BANK_A_BASE)) bank_sel = 2'd0;
        else if (in_bank(address, BANK_B_BASE)) bank_sel = 2'd1;
        else if (in_bank(address, BANK_D_BASE)) bank_sel = 2'd2;
        else if (in_bank(address, BANK_C_BASE)) bank_sel = 2'd3;
        else bank_sel = 2'd0;
    endfunction

    function automatic logic bank_hit(input logic [31:0] address);
        bank_hit = in_bank(address, BANK_A_BASE) || in_bank(address, BANK_B_BASE) ||
                   in_bank(address, BANK_D_BASE) || in_bank(address, BANK_C_BASE);
    endfunction

    function automatic logic in_aperture(input logic [31:0] address);
        in_aperture = ({1'b0, address} >= {1'b0, APERTURE_BASE}) &&
                      ({1'b0, address} < {1'b0, APERTURE_BASE} +
                                            {1'b0, APERTURE_BYTES});
    endfunction

    // ---- host front-end state --------------------------------------------
    localparam logic [2:0] H_IDLE = 3'd0, H_WRITE = 3'd1, H_WRESP = 3'd2,
                           H_READ = 3'd3;
    localparam logic [2:0] E_IDLE = 3'd0, E_REQ = 3'd1, E_RSP = 3'd2,
                           E_OUT = 3'd3, E_HOLE = 3'd4;

    logic [2:0] host_state_q;
    logic [31:0] awaddr_q, wdata_q, araddr_q;
    logic [2:0] awprot_q, arprot_q;
    logic [3:0] wstrb_q;
    logic aw_have, w_have, ar_have, aw_sent, w_sent, ar_sent;
    logic hole_write_q, hole_read_q;

    logic [2:0] eng_state_q;
    logic [1:0] eng_bank_q;
    logic [31:0] eng_addr_q;
    logic [15:0] eng_wdata_q;
    logic eng_write_q, eng_resp_error_q;
    logic [15:0] eng_resp_rdata_q;

    // ---- per-bank host bridge + BRAM + engine mux ------------------------
    logic [NBANKS-1:0] bank_awvalid, bank_awready, bank_wvalid, bank_wready;
    logic [NBANKS-1:0] bank_bvalid, bank_arvalid, bank_arready, bank_rvalid;
    logic [NBANKS-1:0] bank_host_busy;
    logic [NBANKS*2-1:0] bank_bresp, bank_rresp;
    logic [NBANKS*32-1:0] bank_rdata;
    logic [NBANKS-1:0] bank_req_valid, bank_req_ready, bank_req_write;
    logic [NBANKS*32-1:0] bank_req_addr;
    logic [NBANKS*16-1:0] bank_req_wdata;
    logic [NBANKS-1:0] bank_rsp_valid, bank_rsp_ready, bank_rsp_error;
    logic [NBANKS*16-1:0] bank_rsp_rdata;

    logic [1:0] write_bank, read_bank;
    logic write_hole, read_hole;

    // Explicit port-select muxes (portable across simulators; indexed
    // part-selects on packed vectors are not supported by all four-state tools).
    logic [31:0] host_rdata_mux;
    logic [1:0] host_bresp_mux, host_rresp_mux;
    logic [15:0] engine_rdata_mux;
    logic engine_error_mux;

    always_comb begin
        host_rdata_mux = 32'd0;
        host_bresp_mux = 2'd0;
        host_rresp_mux = 2'd0;
        engine_rdata_mux = 16'd0;
        engine_error_mux = 1'b0;
        case (read_bank)
            2'd0: host_rdata_mux = bank_rdata[31:0];
            2'd1: host_rdata_mux = bank_rdata[63:32];
            2'd2: host_rdata_mux = bank_rdata[95:64];
            default: host_rdata_mux = bank_rdata[127:96];
        endcase
        case (read_bank)
            2'd0: host_rresp_mux = bank_rresp[1:0];
            2'd1: host_rresp_mux = bank_rresp[3:2];
            2'd2: host_rresp_mux = bank_rresp[5:4];
            default: host_rresp_mux = bank_rresp[7:6];
        endcase
        case (write_bank)
            2'd0: host_bresp_mux = bank_bresp[1:0];
            2'd1: host_bresp_mux = bank_bresp[3:2];
            2'd2: host_bresp_mux = bank_bresp[5:4];
            default: host_bresp_mux = bank_bresp[7:6];
        endcase
        case (eng_bank_q)
            2'd0: engine_rdata_mux = bank_rsp_rdata[15:0];
            2'd1: engine_rdata_mux = bank_rsp_rdata[31:16];
            2'd2: engine_rdata_mux = bank_rsp_rdata[47:32];
            default: engine_rdata_mux = bank_rsp_rdata[63:48];
        endcase
        case (eng_bank_q)
            2'd0: engine_error_mux = bank_rsp_error[0];
            2'd1: engine_error_mux = bank_rsp_error[1];
            2'd2: engine_error_mux = bank_rsp_error[2];
            default: engine_error_mux = bank_rsp_error[3];
        endcase
    end

    assign write_bank = bank_sel(awaddr_q);
    assign read_bank = bank_sel(araddr_q);
    assign write_hole = page_busy || !in_aperture(awaddr_q) || !bank_hit(awaddr_q);
    assign read_hole = page_busy || !in_aperture(araddr_q) || !bank_hit(araddr_q);

    assign busy = (host_state_q != H_IDLE) || aw_have || w_have || ar_have ||
                  (|bank_host_busy);
    assign irq = 1'b0;
    assign memory_ready = rst_n && !busy && (eng_state_q == E_IDLE) &&
                          !engine_req_valid;

    assign s_axil_awready = rst_n && (host_state_q == H_IDLE) && !aw_have;
    assign s_axil_wready = rst_n && (host_state_q == H_IDLE) && !w_have;
    assign s_axil_arready = rst_n && (host_state_q == H_IDLE) && !ar_have;
    assign s_axil_bvalid = (host_state_q == H_WRESP) &&
                           (hole_write_q || bank_bvalid[write_bank]);
    assign s_axil_bresp = hole_write_q ? 2'b10 : host_bresp_mux;
    assign s_axil_rvalid = (host_state_q == H_READ) &&
                           (hole_read_q || bank_rvalid[read_bank]);
    assign s_axil_rresp = hole_read_q ? 2'b10 : host_rresp_mux;
    assign s_axil_rdata = hole_read_q ? 32'd0 : host_rdata_mux;

    // ---- engine-side memory master (absolute addresses) -------------------
    assign engine_req_ready = rst_n && (eng_state_q == E_IDLE);
    assign engine_rsp_valid = (eng_state_q == E_OUT) || (eng_state_q == E_HOLE);
    assign engine_rsp_rdata = (eng_state_q == E_HOLE) ? 16'd0 : eng_resp_rdata_q;
    assign engine_rsp_error = (eng_state_q == E_HOLE) ? 1'b1 : eng_resp_error_q;

    for (genvar g = 0; g < NBANKS; g = g + 1) begin: bank
        localparam logic [31:0] BANK_BASE = (g == 0) ? BANK_A_BASE :
                                            (g == 1) ? BANK_B_BASE :
                                            (g == 2) ? BANK_D_BASE : BANK_C_BASE;
        wire bridge_req_valid, bridge_req_write, bridge_req_ready;
        wire [31:0] bridge_req_addr;
        wire [15:0] bridge_req_wdata;
        wire bridge_rsp_valid, bridge_rsp_ready, bridge_rsp_error;
        wire [15:0] bridge_rsp_rdata;
        wire host_enable;
        wire eng_req_owner, eng_rsp_owner;

        assign host_enable = rst_n && !page_busy;
        assign eng_req_owner = (eng_state_q == E_REQ) && (eng_bank_q == 2'(g));
        assign eng_rsp_owner = (eng_state_q == E_RSP) && (eng_bank_q == 2'(g));

        rk_axil_mem_bridge #(.BASE(BANK_BASE), .BYTES(33'(BANK_BYTES)))
        host_bridge (
            .clk(clk), .rst_n(rst_n), .host_enable(host_enable),
            .busy(bank_host_busy[g]),
            .s_axil_awaddr(awaddr_q), .s_axil_awprot(awprot_q),
            .s_axil_awvalid(bank_awvalid[g]), .s_axil_awready(bank_awready[g]),
            .s_axil_wdata(wdata_q), .s_axil_wstrb(wstrb_q),
            .s_axil_wvalid(bank_wvalid[g]), .s_axil_wready(bank_wready[g]),
            .s_axil_bresp(bank_bresp[g*2+:2]), .s_axil_bvalid(bank_bvalid[g]),
            .s_axil_bready(bank_bvalid[g] && s_axil_bready),
            .s_axil_araddr(araddr_q), .s_axil_arprot(arprot_q),
            .s_axil_arvalid(bank_arvalid[g]), .s_axil_arready(bank_arready[g]),
            .s_axil_rdata(bank_rdata[g*32+:32]),
            .s_axil_rresp(bank_rresp[g*2+:2]),
            .s_axil_rvalid(bank_rvalid[g]),
            .s_axil_rready(bank_rvalid[g] && s_axil_rready),
            .mem_req_valid(bridge_req_valid), .mem_req_ready(bridge_req_ready),
            .mem_req_write(bridge_req_write), .mem_req_addr(bridge_req_addr),
            .mem_req_wdata(bridge_req_wdata),
            .mem_rsp_valid(bridge_rsp_valid), .mem_rsp_ready(bridge_rsp_ready),
            .mem_rsp_rdata(bridge_rsp_rdata), .mem_rsp_error(bridge_rsp_error)
        );

        // Request-port mux: the engine owns only its selected bank and only in
        // the request phase; the host bridge owns the bank otherwise.
        assign bank_req_valid[g] = eng_req_owner ? 1'b1 : bridge_req_valid;
        assign bank_req_write[g] = eng_req_owner ? eng_write_q : bridge_req_write;
        assign bank_req_addr[g*32+:32] = eng_req_owner ? eng_addr_q : bridge_req_addr;
        assign bank_req_wdata[g*16+:16] = eng_req_owner ? eng_wdata_q : bridge_req_wdata;
        assign bridge_req_ready = eng_req_owner ? 1'b0 : bank_req_ready[g];
        assign bank_rsp_ready[g] = eng_rsp_owner ? 1'b1 : bridge_rsp_ready;
        assign bridge_rsp_valid = (eng_rsp_owner || eng_req_owner) ? 1'b0
                                                                  : bank_rsp_valid[g];
        assign bridge_rsp_rdata = bank_rsp_rdata[g*16+:16];
        assign bridge_rsp_error = bank_rsp_error[g];

        rk_bram #(.BYTES(BANK_BYTES), .BASE(BANK_BASE)) bank_storage (
            .clk(clk), .rst_n(rst_n),
            .req_valid(bank_req_valid[g]), .req_ready(bank_req_ready[g]),
            .req_write(bank_req_write[g]), .req_addr(bank_req_addr[g*32+:32]),
            .req_wdata(bank_req_wdata[g*16+:16]),
            .rsp_valid(bank_rsp_valid[g]), .rsp_ready(bank_rsp_ready[g]),
            .rsp_rdata(bank_rsp_rdata[g*16+:16]), .rsp_error(bank_rsp_error[g]),
            // The second physical BRAM port is intentionally unused: the host
            // staging path and the engine share the arbitrated request port,
            // exactly like the adopted Image-B scaffold's shared window.
            .host_valid(1'b0), .host_ready(), .host_write(1'b0),
            .host_addr(32'd0), .host_wdata(16'd0),
            .host_rsp_valid(), .host_rsp_ready(1'b0),
            .host_rdata(), .host_error()
        );
    end

    // ---- host AXI4-Lite front end (one transaction at a time) ------------
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            host_state_q <= H_IDLE;
            aw_have <= 1'b0; w_have <= 1'b0; ar_have <= 1'b0;
            aw_sent <= 1'b0; w_sent <= 1'b0; ar_sent <= 1'b0;
            awaddr_q <= 32'd0; wdata_q <= 32'd0; araddr_q <= 32'd0;
            awprot_q <= 3'd0; arprot_q <= 3'd0; wstrb_q <= 4'd0;
            hole_write_q <= 1'b0; hole_read_q <= 1'b0;
            bank_awvalid <= '0; bank_wvalid <= '0; bank_arvalid <= '0;
        end else begin
            bank_awvalid <= '0;
            bank_wvalid <= '0;
            bank_arvalid <= '0;
            case (host_state_q)
                H_IDLE: begin
                    if (s_axil_awvalid && s_axil_awready) begin
                        awaddr_q <= s_axil_awaddr;
                        awprot_q <= s_axil_awprot;
                        aw_have <= 1'b1;
                    end
                    if (s_axil_wvalid && s_axil_wready) begin
                        wdata_q <= s_axil_wdata;
                        wstrb_q <= s_axil_wstrb;
                        w_have <= 1'b1;
                    end
                    if (s_axil_arvalid && s_axil_arready) begin
                        araddr_q <= s_axil_araddr;
                        arprot_q <= s_axil_arprot;
                        ar_have <= 1'b1;
                    end
                    if (aw_have && w_have) begin
                        aw_sent <= 1'b0;
                        w_sent <= 1'b0;
                        hole_write_q <= write_hole;
                        host_state_q <= H_WRITE;
                    end else if (ar_have) begin
                        ar_sent <= 1'b0;
                        hole_read_q <= read_hole;
                        host_state_q <= H_READ;
                    end
                end
                H_WRITE: begin
                    if (hole_write_q) begin
                        if (s_axil_bvalid && s_axil_bready) begin
                            aw_have <= 1'b0; w_have <= 1'b0;
                            host_state_q <= H_IDLE;
                        end
                    end else begin
                        if (!aw_sent) begin
                            bank_awvalid[write_bank] <= 1'b1;
                            if (bank_awready[write_bank]) aw_sent <= 1'b1;
                        end
                        if (!w_sent) begin
                            bank_wvalid[write_bank] <= 1'b1;
                            if (bank_wready[write_bank]) w_sent <= 1'b1;
                        end
                        if ((aw_sent || bank_awready[write_bank]) &&
                            (w_sent || bank_wready[write_bank]))
                            host_state_q <= H_WRESP;
                    end
                end
                H_WRESP: begin
                    if (s_axil_bvalid && s_axil_bready) begin
                        aw_have <= 1'b0;
                        w_have <= 1'b0;
                        host_state_q <= H_IDLE;
                    end
                end
                H_READ: begin
                    if (hole_read_q) begin
                        if (s_axil_rvalid && s_axil_rready) begin
                            ar_have <= 1'b0;
                            host_state_q <= H_IDLE;
                        end
                    end else if (bank_rvalid[read_bank]) begin
                        if (s_axil_rready) begin
                            ar_have <= 1'b0;
                            host_state_q <= H_IDLE;
                        end
                    end else if (!ar_sent) begin
                        bank_arvalid[read_bank] <= 1'b1;
                        if (bank_arready[read_bank]) ar_sent <= 1'b1;
                    end
                end
                default: host_state_q <= H_IDLE;
            endcase
        end
    end

    // ---- engine-side memory master FSM -----------------------------------
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            eng_state_q <= E_IDLE;
            eng_bank_q <= 2'd0;
            eng_addr_q <= 32'd0;
            eng_wdata_q <= 16'd0;
            eng_write_q <= 1'b0;
            eng_resp_error_q <= 1'b0;
            eng_resp_rdata_q <= 16'd0;
        end else begin
            case (eng_state_q)
                E_IDLE: begin
                    if (engine_req_valid) begin
                        eng_addr_q <= engine_req_addr;
                        eng_wdata_q <= engine_req_wdata;
                        eng_write_q <= engine_req_write;
                        eng_bank_q <= bank_sel(engine_req_addr);
                        if (!in_aperture(engine_req_addr) ||
                            !bank_hit(engine_req_addr)) begin
                            eng_state_q <= E_HOLE;
                        end else begin
                            eng_state_q <= E_REQ;
                        end
                    end
                end
                E_REQ: if (bank_req_ready[eng_bank_q]) eng_state_q <= E_RSP;
                E_RSP: begin
                    if (bank_rsp_valid[eng_bank_q]) begin
                        eng_resp_rdata_q <= engine_rdata_mux;
                        eng_resp_error_q <= engine_error_mux;
                        eng_state_q <= E_OUT;
                    end
                end
                E_OUT: if (engine_rsp_ready) eng_state_q <= E_IDLE;
                E_HOLE: if (engine_rsp_ready) eng_state_q <= E_IDLE;
                default: eng_state_q <= E_IDLE;
            endcase
        end
    end
endmodule
