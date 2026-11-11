// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Pooling-corpus image: one AXI4-Lite page per frozen pooling fixture.
//
// Address map (decoded from the full 32-bit address):
//
//   0x0000_0000 .. 0x0000_7fff   shared 32 KiB memory aperture (BO load/read)
//   0x0000_8000 + i*0x1000       corpus page i (i = 0 .. N_PAGES-1, default 19)
//   0x0001_0000 .. 0xffff_ffff   unmapped: explicit SLVERR, never an alias
//
// Page i replays exactly the frozen fixture named by the generated
// `rk_ppu_pool_corpus_case` CASE i: the host loads the patched raw command
// stream and the fixture's input/output BOs into the memory window, writes the
// page's START_ADDRESS/START_AMOUNT, submits, and reads the complete 4096-byte
// BO back. The page publishes its corpus index and fixture-name CRC32 so the
// host can bind page <-> fixture without trusting the address alone.
//
// Memory arbitration copies the proven six-page pattern: exactly one BRAM
// request port, one client granted per transaction, the grant latched until its
// response returns, and the host window enabled only while every engine is idle.
// A page's `memory_ready` is the complement of "any engine busy" plus the host
// bridge, so at most one corpus job can be active at a time; a refused submit
// is an explicit SLVERR from the page.
module ypcb_ppu_corpus_top #(
    parameter int unsigned N_PAGES = 19,
    parameter int unsigned RESET_HOLD_CYCLES = 64,
    parameter logic [31:0] BRAM_BASE = 32'h00000000,
    parameter int unsigned BRAM_BYTES = 32768,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  wire SYS_CLK,
    input  wire [31:0] s_axil_awaddr,
    input  wire [2:0]  s_axil_awprot,
    input  wire        s_axil_awvalid,
    output wire        s_axil_awready,
    input  wire [31:0] s_axil_wdata,
    input  wire [3:0]  s_axil_wstrb,
    input  wire        s_axil_wvalid,
    output wire        s_axil_wready,
    output wire [1:0]  s_axil_bresp,
    output wire        s_axil_bvalid,
    input  wire        s_axil_bready,
    input  wire [31:0] s_axil_araddr,
    input  wire [2:0]  s_axil_arprot,
    input  wire        s_axil_arvalid,
    output wire        s_axil_arready,
    output wire [31:0] s_axil_rdata,
    output wire [1:0]  s_axil_rresp,
    output wire        s_axil_rvalid,
    input  wire        s_axil_rready,
    // One completion line per corpus page. They assert when that page's result
    // slot is full and drop when the host acknowledges the result.
    output wire [N_PAGES-1:0] page_irq
);
    localparam int unsigned PAGE_SHIFT = 12;
    localparam int unsigned PAGE_FIRST = 8;   // 0x8000
    localparam int unsigned IDX_BITS = (N_PAGES <= 1) ? 1 : $clog2(N_PAGES);
    localparam int unsigned OWN_BITS = $clog2(N_PAGES + 2);

    // Transport transaction targets.
    localparam logic [5:0] T_NONE = 6'd63, T_MEMORY = 6'd32, T_UNMAPPED = 6'd33;
    localparam logic [OWN_BITS-1:0] OWN_NONE = OWN_BITS'(N_PAGES + 1);
    localparam logic [OWN_BITS-1:0] OWN_HOST = OWN_BITS'(N_PAGES);

    // Front-end states.
    localparam logic [1:0] W_COLLECT = 2'd0, W_DISPATCH = 2'd1,
                           W_RESPONSE = 2'd2;
    localparam logic [1:0] R_IDLE = 2'd0, R_DISPATCH = 2'd1, R_RESPONSE = 2'd2;

    initial begin
        if (N_PAGES == 0)
            $fatal(1, "pooling corpus image needs at least one page");
        if (BRAM_BYTES < 4096 || (BRAM_BYTES & (BRAM_BYTES - 1)) != 0)
            $fatal(1, "shared memory size must be a power of two >= 4096");
        if (BRAM_BASE != 32'h0000_0000 || BRAM_BYTES != 32768)
            $fatal(1, "this image fixes the memory aperture at 0x0000..0x7fff");
        if (N_PAGES > 32)
            $fatal(1, "corpus image decodes at most 32 pages");
    end

    wire reset_n;
    rk_startup_reset #(.HOLD_CYCLES(RESET_HOLD_CYCLES)) startup (
        .clk(SYS_CLK), .request_reset(1'b0), .rst_n(reset_n)
    );

    // ---- page address decode ---------------------------------------------
    function automatic logic [5:0] decode(input logic [31:0] address);
        logic [11:0] page_code;
        begin
            page_code = address[19:PAGE_SHIFT];
            if (address[31:15] == 17'd0) begin
                decode = T_MEMORY;                        // 0x0000..0x7fff
            end else if ((address[31:20] == 12'd0) &&
                         (page_code >= 12'(PAGE_FIRST)) &&
                         (page_code < 12'(PAGE_FIRST + N_PAGES))) begin
                decode = 6'(page_code - 12'(PAGE_FIRST));  // corpus page
            end else begin
                decode = T_UNMAPPED;
            end
        end
    endfunction

    function automatic logic is_page(input logic [5:0] target);
        is_page = target < 6'(N_PAGES);
    endfunction

    // ---- AXI-Lite front-end state ----------------------------------------
    logic [1:0] write_state_q, read_state_q;
    logic have_aw_q, have_w_q, aw_accepted_q, w_accepted_q, read_accepted_q;
    logic [31:0] write_address_q, write_data_q, read_address_q;
    logic [3:0] write_strobe_q;
    logic [2:0] write_prot_q, read_prot_q;
    logic [5:0] write_dispatch_q, write_resp_target_q, read_target_q,
                read_resp_target_q;

    wire [5:0] pending_write_target = decode(
        have_aw_q ? write_address_q : s_axil_awaddr);

    // ---- per-page AXI/memory/status vectors ------------------------------
    wire [N_PAGES-1:0] page_awready, page_wready, page_bvalid, page_arready,
                       page_rvalid;
    wire [N_PAGES*2-1:0] page_bresp, page_rresp;
    wire [N_PAGES*32-1:0] page_rdata;
    wire [N_PAGES-1:0] page_awvalid, page_wvalid, page_arvalid;
    wire [N_PAGES-1:0] page_bready, page_rready;
    wire [N_PAGES-1:0] page_busy, page_memory_ready;
    wire [N_PAGES-1:0] page_mem_req_valid, page_mem_req_write,
                       page_mem_rsp_valid, page_mem_rsp_ready,
                       page_mem_rsp_error;
    logic [N_PAGES-1:0] page_mem_req_ready;
    wire [N_PAGES*32-1:0] page_mem_req_addr;
    wire [N_PAGES*16-1:0] page_mem_req_wdata, page_mem_rsp_rdata;

    wire host_mem_req_valid, host_mem_req_write;
    logic host_mem_req_ready;
    wire [31:0] host_mem_req_addr;
    wire [15:0] host_mem_req_wdata;
    wire host_mem_rsp_valid, host_mem_rsp_ready, host_mem_rsp_error;
    wire [15:0] host_mem_rsp_rdata;
    wire host_mem_busy;

    wire [N_PAGES-1:0] page_irq_q;
    assign page_irq = page_irq_q;

    wire any_engine_busy = |page_busy;
    genvar g;
    generate
        for (g = 0; g < N_PAGES; g = g + 1) begin : g_pages
            // One job at a time across the whole image: a page may start only
            // while no other engine and no host transaction holds the memory.
            assign page_memory_ready[g] = reset_n && !any_engine_busy &&
                                          !host_mem_busy;
            assign page_awvalid[g] = (write_state_q == W_DISPATCH) &&
                                     (write_dispatch_q == 6'(g)) &&
                                     !aw_accepted_q;
            assign page_wvalid[g] = (write_state_q == W_DISPATCH) &&
                                    (write_dispatch_q == 6'(g)) &&
                                    !w_accepted_q;
            assign page_arvalid[g] = (read_state_q == R_DISPATCH) &&
                                      (read_target_q == 6'(g)) &&
                                      !read_accepted_q;
            assign page_bready[g] = s_axil_bready &&
                                    (write_resp_target_q == 6'(g));
            assign page_rready[g] = s_axil_rready &&
                                    (read_resp_target_q == 6'(g));

            (* KEEP_HIERARCHY = "TRUE" *)
            rk_ppu_pool_corpus_axi #(
                .CASE(g),
                .BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES)),
                .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
            ) pool_page (
                .clk(SYS_CLK), .rst_n(reset_n),
                .memory_ready(page_memory_ready[g]),
                .s_axil_awaddr({20'd0, write_address_q[11:0]}),
                .s_axil_awprot(write_prot_q),
                .s_axil_awvalid(page_awvalid[g]),
                .s_axil_awready(page_awready[g]),
                .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
                .s_axil_wvalid(page_wvalid[g]),
                .s_axil_wready(page_wready[g]),
                .s_axil_bresp(page_bresp[2*g +: 2]),
                .s_axil_bvalid(page_bvalid[g]),
                .s_axil_bready(page_bready[g]),
                .s_axil_araddr({20'd0, read_address_q[11:0]}),
                .s_axil_arprot(read_prot_q),
                .s_axil_arvalid(page_arvalid[g]),
                .s_axil_arready(page_arready[g]),
                .s_axil_rdata(page_rdata[32*g +: 32]),
                .s_axil_rresp(page_rresp[2*g +: 2]),
                .s_axil_rvalid(page_rvalid[g]),
                .s_axil_rready(page_rready[g]),
                .irq(page_irq_q[g]), .busy(page_busy[g]),
                .mem_req_valid(page_mem_req_valid[g]),
                .mem_req_ready(page_mem_req_ready[g]),
                .mem_req_write(page_mem_req_write[g]),
                .mem_req_addr(page_mem_req_addr[32*g +: 32]),
                .mem_req_wdata(page_mem_req_wdata[16*g +: 16]),
                .mem_rsp_valid(page_mem_rsp_valid[g]),
                .mem_rsp_ready(page_mem_rsp_ready[g]),
                .mem_rsp_rdata(page_mem_rsp_rdata[16*g +: 16]),
                .mem_rsp_error(page_mem_rsp_error[g])
            );
        end
    endgenerate

    // ---- dispatch readies/responses: memory, unmapped, or a corpus page ---
    logic dispatch_awready, dispatch_wready, dispatch_bvalid, dispatch_arready,
          dispatch_rvalid;
    logic [1:0] dispatch_bresp, dispatch_rresp;
    logic [31:0] dispatch_rdata;
    wire mem_awready, mem_wready, mem_bvalid, mem_arready, mem_rvalid;
    wire [1:0] mem_bresp, mem_rresp;
    wire [31:0] mem_rdata;
    wire err_awready, err_wready, err_bvalid, err_arready, err_rvalid;
    wire [1:0] err_bresp, err_rresp;
    wire [31:0] err_rdata;

    always_comb begin
        dispatch_awready = 1'b0;
        dispatch_wready = 1'b0;
        dispatch_bvalid = 1'b0;
        dispatch_bresp = 2'b11;
        dispatch_rvalid = 1'b0;
        dispatch_rresp = 2'b11;
        dispatch_rdata = 32'd0;
        dispatch_arready = 1'b0;
        if (write_dispatch_q == T_MEMORY) begin
            dispatch_awready = mem_awready;
            dispatch_wready = mem_wready;
        end else if (write_dispatch_q == T_UNMAPPED) begin
            dispatch_awready = err_awready;
            dispatch_wready = err_wready;
        end else if (is_page(write_dispatch_q)) begin
            dispatch_awready = page_awready[write_dispatch_q[IDX_BITS-1:0]];
            dispatch_wready = page_wready[write_dispatch_q[IDX_BITS-1:0]];
        end
        if (read_target_q == T_MEMORY) begin
            dispatch_arready = mem_arready;
        end else if (read_target_q == T_UNMAPPED) begin
            dispatch_arready = err_arready;
        end else if (is_page(read_target_q)) begin
            dispatch_arready = page_arready[read_target_q[IDX_BITS-1:0]];
        end
        if (write_resp_target_q == T_MEMORY) begin
            dispatch_bvalid = mem_bvalid;
            dispatch_bresp = mem_bresp;
        end else if (write_resp_target_q == T_UNMAPPED) begin
            dispatch_bvalid = err_bvalid;
            dispatch_bresp = err_bresp;
        end else if (is_page(write_resp_target_q)) begin
            dispatch_bvalid = page_bvalid[write_resp_target_q[IDX_BITS-1:0]];
            dispatch_bresp = page_bresp[2*write_resp_target_q[IDX_BITS-1:0] +: 2];
        end
        if (read_resp_target_q == T_MEMORY) begin
            dispatch_rvalid = mem_rvalid;
            dispatch_rdata = mem_rdata;
            dispatch_rresp = mem_rresp;
        end else if (read_resp_target_q == T_UNMAPPED) begin
            dispatch_rvalid = err_rvalid;
            dispatch_rdata = err_rdata;
            dispatch_rresp = err_rresp;
        end else if (is_page(read_resp_target_q)) begin
            dispatch_rvalid = page_rvalid[read_resp_target_q[IDX_BITS-1:0]];
            dispatch_rdata = page_rdata[32*read_resp_target_q[IDX_BITS-1:0] +: 32];
            dispatch_rresp = page_rresp[2*read_resp_target_q[IDX_BITS-1:0] +: 2];
        end
    end

    // ---- host memory bridge and unmapped-address slave -------------------
    rk_axil_mem_bridge #(.BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES)))
    memory_bridge (
        .clk(SYS_CLK), .rst_n(reset_n),
        .host_enable(reset_n && !any_engine_busy),
        .busy(host_mem_busy),
        .s_axil_awaddr(write_address_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid((write_state_q == W_DISPATCH) &&
                        (write_dispatch_q == T_MEMORY) && !aw_accepted_q),
        .s_axil_awready(mem_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid((write_state_q == W_DISPATCH) &&
                       (write_dispatch_q == T_MEMORY) && !w_accepted_q),
        .s_axil_wready(mem_wready),
        .s_axil_bresp(mem_bresp), .s_axil_bvalid(mem_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_MEMORY),
        .s_axil_araddr(read_address_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid((read_state_q == R_DISPATCH) &&
                        (read_target_q == T_MEMORY) && !read_accepted_q),
        .s_axil_arready(mem_arready),
        .s_axil_rdata(mem_rdata), .s_axil_rresp(mem_rresp),
        .s_axil_rvalid(mem_rvalid),
        .s_axil_rready(s_axil_rready && read_resp_target_q == T_MEMORY),
        .mem_req_valid(host_mem_req_valid), .mem_req_ready(host_mem_req_ready),
        .mem_req_write(host_mem_req_write), .mem_req_addr(host_mem_req_addr),
        .mem_req_wdata(host_mem_req_wdata),
        .mem_rsp_valid(host_mem_rsp_valid), .mem_rsp_ready(host_mem_rsp_ready),
        .mem_rsp_rdata(host_mem_rsp_rdata), .mem_rsp_error(host_mem_rsp_error)
    );

    rk_axil_error_slave error_page (
        .clk(SYS_CLK), .rst_n(reset_n),
        .s_axil_awaddr(write_address_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid((write_state_q == W_DISPATCH) &&
                        (write_dispatch_q == T_UNMAPPED) && !aw_accepted_q),
        .s_axil_awready(err_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid((write_state_q == W_DISPATCH) &&
                       (write_dispatch_q == T_UNMAPPED) && !w_accepted_q),
        .s_axil_wready(err_wready),
        .s_axil_bresp(err_bresp), .s_axil_bvalid(err_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_UNMAPPED),
        .s_axil_araddr(read_address_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid((read_state_q == R_DISPATCH) &&
                        (read_target_q == T_UNMAPPED) && !read_accepted_q),
        .s_axil_arready(err_arready),
        .s_axil_rdata(err_rdata), .s_axil_rresp(err_rresp),
        .s_axil_rvalid(err_rvalid),
        .s_axil_rready(s_axil_rready && read_resp_target_q == T_UNMAPPED)
    );

    // ---- single BRAM port, one granted owner per transaction -------------
    logic [OWN_BITS-1:0] owner_q, next_owner;
    wire owned = owner_q != OWN_NONE;
    logic bram_req_valid, bram_req_write, bram_req_ready;
    logic [31:0] bram_req_addr;
    logic [15:0] bram_req_wdata;
    wire bram_rsp_valid, bram_rsp_error;
    logic bram_rsp_ready;
    wire [15:0] bram_rsp_rdata;

    always_comb begin
        next_owner = OWN_NONE;
        for (int p = N_PAGES - 1; p >= 0; p = p - 1) begin
            if (page_mem_req_valid[p]) next_owner = OWN_BITS'(p);
        end
        if (host_mem_req_valid) next_owner = OWN_HOST;
        bram_req_valid = !owned && (next_owner != OWN_NONE);
        bram_req_write = 1'b0;
        bram_req_addr = 32'd0;
        bram_req_wdata = 16'd0;
        if (next_owner == OWN_HOST) begin
            bram_req_write = host_mem_req_write;
            bram_req_addr = host_mem_req_addr;
            bram_req_wdata = host_mem_req_wdata;
        end else begin
            for (int p = 0; p < N_PAGES; p = p + 1) begin
                if (next_owner == OWN_BITS'(p)) begin
                    bram_req_write = page_mem_req_write[p];
                    bram_req_addr = page_mem_req_addr[32*p +: 32];
                    bram_req_wdata = page_mem_req_wdata[16*p +: 16];
                end
            end
        end
        for (int p = 0; p < N_PAGES; p = p + 1) begin
            page_mem_req_ready[p] = !owned && (next_owner == OWN_BITS'(p)) &&
                                    bram_req_ready;
        end
        host_mem_req_ready = !owned && (next_owner == OWN_HOST) &&
                             bram_req_ready;
        bram_rsp_ready = 1'b0;
        if (owner_q == OWN_HOST) bram_rsp_ready = host_mem_rsp_ready;
        for (int p = 0; p < N_PAGES; p = p + 1) begin
            if (owner_q == OWN_BITS'(p)) bram_rsp_ready = page_mem_rsp_ready[p];
        end
    end

    generate
        for (g = 0; g < N_PAGES; g = g + 1) begin : g_mem_rsp
            assign page_mem_rsp_valid[g] = bram_rsp_valid &&
                                           (owner_q == OWN_BITS'(g));
            assign page_mem_rsp_rdata[16*g +: 16] = bram_rsp_rdata;
            assign page_mem_rsp_error[g] = bram_rsp_error;
        end
    endgenerate
    assign host_mem_rsp_valid = bram_rsp_valid && (owner_q == OWN_HOST);
    assign host_mem_rsp_rdata = bram_rsp_rdata;
    assign host_mem_rsp_error = bram_rsp_error;

    rk_bram #(.BYTES(BRAM_BYTES), .BASE(BRAM_BASE)) memory (
        .clk(SYS_CLK), .rst_n(reset_n),
        .req_valid(bram_req_valid), .req_ready(bram_req_ready),
        .req_write(bram_req_write), .req_addr(bram_req_addr),
        .req_wdata(bram_req_wdata),
        .rsp_valid(bram_rsp_valid), .rsp_ready(bram_rsp_ready),
        .rsp_rdata(bram_rsp_rdata), .rsp_error(bram_rsp_error),
        .host_valid(1'b0), .host_ready(), .host_write(1'b0),
        .host_addr(32'd0), .host_wdata(16'd0),
        .host_rsp_valid(), .host_rsp_ready(1'b0),
        .host_rdata(), .host_error()
    );

    // ---- front-end sequencers --------------------------------------------
    assign s_axil_awready = (write_state_q == W_COLLECT) && !have_aw_q;
    assign s_axil_wready = (write_state_q == W_COLLECT) && !have_w_q;
    assign s_axil_arready = (read_state_q == R_IDLE);
    assign s_axil_bvalid = (write_state_q == W_RESPONSE) && dispatch_bvalid;
    assign s_axil_bresp = (write_state_q == W_RESPONSE) ? dispatch_bresp : 2'b11;
    assign s_axil_rvalid = (read_state_q == R_RESPONSE) && dispatch_rvalid;
    assign s_axil_rdata = dispatch_rdata;
    assign s_axil_rresp = dispatch_rresp;

    always_ff @(posedge SYS_CLK) begin
        if (!reset_n) begin
            write_state_q <= W_COLLECT;
            read_state_q <= R_IDLE;
            have_aw_q <= 1'b0;
            have_w_q <= 1'b0;
            aw_accepted_q <= 1'b0;
            w_accepted_q <= 1'b0;
            read_accepted_q <= 1'b0;
            write_address_q <= 32'd0;
            write_data_q <= 32'd0;
            write_strobe_q <= 4'd0;
            write_prot_q <= 3'd0;
            read_address_q <= 32'd0;
            read_prot_q <= 3'd0;
            write_dispatch_q <= T_NONE;
            write_resp_target_q <= T_NONE;
            read_target_q <= T_NONE;
            read_resp_target_q <= T_NONE;
            owner_q <= OWN_NONE;
        end else begin
            case (write_state_q)
                W_COLLECT: begin
                    if (s_axil_awvalid && !have_aw_q) begin
                        have_aw_q <= 1'b1;
                        write_address_q <= s_axil_awaddr;
                        write_prot_q <= s_axil_awprot;
                    end
                    if (s_axil_wvalid && !have_w_q) begin
                        have_w_q <= 1'b1;
                        write_data_q <= s_axil_wdata;
                        write_strobe_q <= s_axil_wstrb;
                    end
                    if ((have_aw_q || (s_axil_awvalid && !have_aw_q)) &&
                        (have_w_q || (s_axil_wvalid && !have_w_q))) begin
                        write_dispatch_q <= pending_write_target;
                        have_aw_q <= 1'b0;
                        have_w_q <= 1'b0;
                        aw_accepted_q <= 1'b0;
                        w_accepted_q <= 1'b0;
                        write_state_q <= W_DISPATCH;
                    end
                end
                W_DISPATCH: begin
                    if (dispatch_awready && !aw_accepted_q)
                        aw_accepted_q <= 1'b1;
                    if (dispatch_wready && !w_accepted_q)
                        w_accepted_q <= 1'b1;
                    if ((aw_accepted_q || dispatch_awready) &&
                        (w_accepted_q || dispatch_wready)) begin
                        write_resp_target_q <= write_dispatch_q;
                        write_state_q <= W_RESPONSE;
                    end
                end
                W_RESPONSE: begin
                    if (dispatch_bvalid && s_axil_bready) begin
                        write_state_q <= W_COLLECT;
                        write_resp_target_q <= T_NONE;
                    end
                end
                default: write_state_q <= W_COLLECT;
            endcase

            case (read_state_q)
                R_IDLE: begin
                    if (s_axil_arvalid && s_axil_arready) begin
                        read_address_q <= s_axil_araddr;
                        read_prot_q <= s_axil_arprot;
                        read_target_q <= decode(s_axil_araddr);
                        read_accepted_q <= 1'b0;
                        read_state_q <= R_DISPATCH;
                    end
                end
                R_DISPATCH: begin
                    if (dispatch_arready) begin
                        read_resp_target_q <= read_target_q;
                        read_accepted_q <= 1'b1;
                        read_state_q <= R_RESPONSE;
                    end
                end
                R_RESPONSE: begin
                    if (dispatch_rvalid && s_axil_rready) begin
                        read_state_q <= R_IDLE;
                        read_resp_target_q <= T_NONE;
                        read_accepted_q <= 1'b0;
                    end
                end
                default: read_state_q <= R_IDLE;
            endcase

            // A grant is held from acceptance through response completion.
            if (bram_req_valid && bram_req_ready)
                owner_q <= next_owner;
            else if (bram_rsp_valid && bram_rsp_ready)
                owner_q <= OWN_NONE;
        end
    end
endmodule
