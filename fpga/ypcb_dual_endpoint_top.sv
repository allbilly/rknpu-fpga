// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One host-drivable image carrying both captured endpoints behind a single
// AXI4-Lite slave port, plus a host-visible window onto the shared memory.
//
// Address map (decoded from bits [15:12]):
//
//   0x0_0000 .. 0x0_7fff   shared memory aperture (host BO load / result read)
//   0x0_8000 .. 0x0_8fff   conv-simple page, FP16 profile 0 (RKCS/D014)
//   0x0_9000 .. 0x0_9fff   signed-INT8 pooling page        (RKPP/5050)
//   0x0_a000 .. 0x0_afff   FP32 GEMM transport page        (RKCM/434d)
//   0x0_b000 .. 0x0_bfff   conv-simple page, FP32 profile 3 (RKCS/D015)
//   0x0_c000 .. 0x0_cfff   conv-simple page, FP16 profile 1 (RKCS/D016)
//   0x0_d000 .. 0x0_dfff   conv-simple page, FP16 profile 2 (RKCS/D017)
//   0xe_0000 .. 0xf_ffff   unmapped: explicit SLVERR, never a silent alias
//
// Two conv pages are instantiated rather than one runtime-selected page: the
// geometry is an elaboration parameter in `rk_conv_simple_axi`, and a runtime
// width switch would turn a build-time contract into a run-time one. Each page
// publishes its own DEVICE_ID so a host can tell which profile it reached.
//
// Register offsets inside each page are the 12-bit layout of rk_job_control,
// so one host driver ABI covers all pages.
//
// The front end buffers the AXI write channels independently. AXI-Lite permits
// a master to present W before AW, so each page's own logic -- which only
// completes a register write when it has seen both -- cannot be fed directly
// from the live bus. The front end collects AW and W into one transaction and
// presents both to the selected page in the same cycle. It does not rewrite
// addresses or data: the pages see exactly the QWORDs the host loaded.
//
// Memory arbitration. There is one BRAM request port in this image, so exactly
// one client is granted per transaction:
//
//   * the host window is enabled only while both engine pages are idle;
//   * a page's `memory_ready` is the complement of the other page's `busy`
//     and of the host bridge's `busy`, so a submit cannot start an engine
//     while a host memory access is in flight and vice versa;
//   * the arbiter latches the owner on the grant and holds it until the
//     response handshake, so every response returns to the client that issued
//     the request;
//   * a host access to the memory window stalls (AXI backpressure) while an
//     engine runs, because rk_bram forbids host access to RAM in accelerator
//     use. It is never dropped or redirected.
//
// No queue, reordering, preemption or scheduler. A refused submit is an
// explicit SLVERR from the page.
module ypcb_dual_endpoint_top #(
    parameter bit LED_ACTIVE_LOW = 1'b0,
    parameter int unsigned RESET_HOLD_CYCLES = 64,
    parameter logic [31:0] BRAM_BASE = 32'h00000000,
    parameter int unsigned BRAM_BYTES = 32768,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  wire SYS_CLK,
    // AXI4-Lite slave
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
    // Completion lines, one per page. They assert when that page's result slot
    // is full and drop when the host acknowledges. Exposed so a board image can
    // show them on LEDs and a bench can wait on them without reaching into the
    // endpoint internals.
    output wire        conv_irq,
    output wire        pool_irq,
    output wire        gemm_irq,
    output wire        conv_fp32_irq,
    output wire        conv_k5_irq,
    output wire        conv_c16_irq,
    output wire [2:0]  led_3bits_tri_o
);
    localparam int unsigned PAGE_SHIFT = 12;
    localparam logic [3:0] PAGE_CONV = 4'h8;
    localparam logic [3:0] PAGE_POOL = 4'h9;
    localparam logic [3:0] PAGE_GEMM = 4'hA;
    localparam logic [3:0] PAGE_CONV_FP32 = 4'hB;
    localparam logic [3:0] PAGE_CONV_K5 = 4'hC;
    localparam logic [3:0] PAGE_CONV_C16 = 4'hD;

    // Transaction targets. Plain sized constants (not an enum) so a conditional
    // expression needs no tool-specific cast.
    localparam logic [3:0] T_NONE = 4'd0, T_MEMORY = 4'd1, T_CONV = 4'd2,
                           T_POOL = 4'd3, T_UNMAPPED = 4'd4, T_GEMM = 4'd5,
                           T_CONV_FP32 = 4'd6, T_CONV_K5 = 4'd7, T_CONV_C16 = 4'd8;

    // Front-end states.
    localparam logic [1:0] W_COLLECT = 2'd0, W_DISPATCH = 2'd1, W_RESPONSE = 2'd2;
    localparam logic [1:0] R_IDLE = 2'd0, R_DISPATCH = 2'd1, R_RESPONSE = 2'd2;

    wire reset_n;
    logic [25:0] heartbeat;
    initial heartbeat = 0;

    rk_startup_reset #(.HOLD_CYCLES(RESET_HOLD_CYCLES)) startup (
        .clk(SYS_CLK), .request_reset(1'b0), .rst_n(reset_n)
    );
    always_ff @(posedge SYS_CLK) begin
        if (!reset_n) heartbeat <= 26'd0;
        else heartbeat <= heartbeat + 1'b1;
    end

    // ---- per-page busy, and mutual exclusion over the memory --------------
    wire conv_busy, pool_busy, gemm_busy, conv_fp32_busy, conv_k5_busy,
         conv_c16_busy, host_mem_busy;
    wire any_engine_busy = conv_busy || pool_busy || gemm_busy ||
                           conv_fp32_busy || conv_k5_busy || conv_c16_busy;
    // A page may not start a job while any other engine is running or the host
    // holds the memory. Every page therefore sees the complement of the other
    // pages, and the arbiter below grants exactly one owner per transaction.
    wire conv_memory_ready = reset_n && !pool_busy && !gemm_busy &&
                             !conv_fp32_busy && !conv_k5_busy &&
                             !conv_c16_busy && !host_mem_busy;
    wire pool_memory_ready = reset_n && !conv_busy && !gemm_busy &&
                             !conv_fp32_busy && !conv_k5_busy &&
                             !conv_c16_busy && !host_mem_busy;
    wire gemm_memory_ready = reset_n && !conv_busy && !pool_busy &&
                             !conv_fp32_busy && !conv_k5_busy &&
                             !conv_c16_busy && !host_mem_busy;
    wire conv_fp32_memory_ready = reset_n && !conv_busy && !pool_busy &&
                                  !gemm_busy && !conv_k5_busy &&
                                  !conv_c16_busy && !host_mem_busy;
    wire conv_k5_memory_ready = reset_n && !conv_busy && !pool_busy &&
                                !gemm_busy && !conv_fp32_busy &&
                                !conv_c16_busy && !host_mem_busy;
    wire conv_c16_memory_ready = reset_n && !conv_busy && !pool_busy &&
                                 !gemm_busy && !conv_fp32_busy &&
                                 !conv_k5_busy && !host_mem_busy;
    wire host_memory_enable = reset_n && !any_engine_busy;

    // ---- AXI-Lite front-end state (declared before the pages use it) -------
    logic [1:0] write_state_q, read_state_q;
    logic have_aw_q, have_w_q, aw_accepted_q, w_accepted_q, read_accepted_q;
    logic [31:0] write_address_q, write_data_q, read_address_q;
    logic [3:0] write_strobe_q;
    logic [2:0] write_prot_q, read_prot_q;
    logic [3:0] write_dispatch_q, write_resp_target_q, read_resp_target_q;

    function automatic logic [3:0] decode(input logic [3:0] page);
        decode = (page <= 4'h7) ? T_MEMORY :
                 (page == PAGE_CONV) ? T_CONV :
                 (page == PAGE_POOL) ? T_POOL :
                 (page == PAGE_GEMM) ? T_GEMM :
                 (page == PAGE_CONV_FP32) ? T_CONV_FP32 :
                 (page == PAGE_CONV_K5) ? T_CONV_K5 :
                 (page == PAGE_CONV_C16) ? T_CONV_C16 : T_UNMAPPED;
    endfunction

    // The page of the transaction currently being collected: the buffered
    // address wins once AW has been accepted, so a bus address change cannot
    // retarget an accepted write.
    wire [3:0] pending_write_page = have_aw_q
        ? write_address_q[15:PAGE_SHIFT] : s_axil_awaddr[15:PAGE_SHIFT];
    wire [3:0] write_target = decode(write_address_q[15:PAGE_SHIFT]);
    wire [3:0] read_target = decode(read_address_q[15:PAGE_SHIFT]);

    // Write dispatch: each half is held until the selected slave accepts it.
    wire conv_fp32_awvalid = (write_state_q == W_DISPATCH) &&
                             write_dispatch_q == T_CONV_FP32 && !aw_accepted_q;
    wire conv_fp32_wvalid = (write_state_q == W_DISPATCH) &&
                            write_dispatch_q == T_CONV_FP32 && !w_accepted_q;
    wire conv_k5_awvalid = (write_state_q == W_DISPATCH) &&
                           write_dispatch_q == T_CONV_K5 && !aw_accepted_q;
    wire conv_k5_wvalid = (write_state_q == W_DISPATCH) &&
                          write_dispatch_q == T_CONV_K5 && !w_accepted_q;
    wire conv_c16_awvalid = (write_state_q == W_DISPATCH) &&
                            write_dispatch_q == T_CONV_C16 && !aw_accepted_q;
    wire conv_c16_wvalid = (write_state_q == W_DISPATCH) &&
                           write_dispatch_q == T_CONV_C16 && !w_accepted_q;
    wire gemm_awvalid = (write_state_q == W_DISPATCH) &&
                        write_dispatch_q == T_GEMM && !aw_accepted_q;
    wire gemm_wvalid = (write_state_q == W_DISPATCH) &&
                       write_dispatch_q == T_GEMM && !w_accepted_q;
    wire conv_awvalid = (write_state_q == W_DISPATCH) &&
                        write_dispatch_q == T_CONV && !aw_accepted_q;
    wire conv_wvalid = (write_state_q == W_DISPATCH) &&
                       write_dispatch_q == T_CONV && !w_accepted_q;
    wire pool_awvalid = (write_state_q == W_DISPATCH) &&
                        write_dispatch_q == T_POOL && !aw_accepted_q;
    wire pool_wvalid = (write_state_q == W_DISPATCH) &&
                       write_dispatch_q == T_POOL && !w_accepted_q;
    wire mem_awvalid = (write_state_q == W_DISPATCH) &&
                       write_dispatch_q == T_MEMORY && !aw_accepted_q;
    wire mem_wvalid = (write_state_q == W_DISPATCH) &&
                      write_dispatch_q == T_MEMORY && !w_accepted_q;
    wire unmapped_awvalid = (write_state_q == W_DISPATCH) &&
                            write_dispatch_q == T_UNMAPPED && !aw_accepted_q;
    wire unmapped_wvalid = (write_state_q == W_DISPATCH) &&
                           write_dispatch_q == T_UNMAPPED && !w_accepted_q;

    // Read dispatch: AR is presented exactly once, then the page holds the
    // response internally until the host takes it.
    wire read_dispatching = (read_state_q == R_DISPATCH) && !read_accepted_q;
    wire read_conv_fp32_valid = read_dispatching && read_target == T_CONV_FP32;
    wire read_conv_k5_valid = read_dispatching && read_target == T_CONV_K5;
    wire read_conv_c16_valid = read_dispatching && read_target == T_CONV_C16;
    wire read_gemm_valid = read_dispatching && read_target == T_GEMM;
    wire read_conv_valid = read_dispatching && read_target == T_CONV;
    wire read_pool_valid = read_dispatching && read_target == T_POOL;
    wire read_mem_valid = read_dispatching && read_target == T_MEMORY;
    wire read_unmapped_valid = read_dispatching && read_target == T_UNMAPPED;

    // ---- per-page handshake wires -----------------------------------------
    wire conv_awready, conv_wready, conv_bvalid, conv_arready, conv_rvalid;
    wire pool_awready, pool_wready, pool_bvalid, pool_arready, pool_rvalid;
    wire gemm_awready, gemm_wready, gemm_bvalid, gemm_arready, gemm_rvalid;
    wire conv_fp32_awready, conv_fp32_wready, conv_fp32_bvalid,
         conv_fp32_arready, conv_fp32_rvalid;
    wire conv_k5_awready, conv_k5_wready, conv_k5_bvalid,
         conv_k5_arready, conv_k5_rvalid;
    wire conv_c16_awready, conv_c16_wready, conv_c16_bvalid,
         conv_c16_arready, conv_c16_rvalid;
    wire mem_awready, mem_wready, mem_bvalid, mem_arready, mem_rvalid;
    wire err_awready, err_wready, err_bvalid, err_arready, err_rvalid;
    wire [1:0] conv_bresp, conv_rresp, pool_bresp, pool_rresp;
    wire [1:0] gemm_bresp, gemm_rresp, mem_bresp, mem_rresp, err_bresp, err_rresp;
    wire [1:0] conv_fp32_bresp, conv_fp32_rresp;
    wire [1:0] conv_k5_bresp, conv_k5_rresp;
    wire [1:0] conv_c16_bresp, conv_c16_rresp;
    wire [31:0] conv_rdata, pool_rdata, gemm_rdata, mem_rdata, err_rdata;
    wire [31:0] conv_fp32_rdata;
    wire [31:0] conv_k5_rdata, conv_c16_rdata;

    wire conv_k5_mem_req_valid, conv_k5_mem_req_write, conv_k5_mem_rsp_ready;
    wire [31:0] conv_k5_mem_req_addr;
    wire [15:0] conv_k5_mem_req_wdata;
    wire conv_k5_mem_req_ready, conv_k5_mem_rsp_valid, conv_k5_mem_rsp_error;
    wire [15:0] conv_k5_mem_rsp_rdata;

    wire conv_c16_mem_req_valid, conv_c16_mem_req_write, conv_c16_mem_rsp_ready;
    wire [31:0] conv_c16_mem_req_addr;
    wire [15:0] conv_c16_mem_req_wdata;
    wire conv_c16_mem_req_ready, conv_c16_mem_rsp_valid, conv_c16_mem_rsp_error;
    wire [15:0] conv_c16_mem_rsp_rdata;

    wire conv_fp32_mem_req_valid, conv_fp32_mem_req_write, conv_fp32_mem_rsp_ready;
    wire [31:0] conv_fp32_mem_req_addr;
    wire [15:0] conv_fp32_mem_req_wdata;
    wire conv_fp32_mem_req_ready, conv_fp32_mem_rsp_valid,
         conv_fp32_mem_rsp_error;
    wire [15:0] conv_fp32_mem_rsp_rdata;

    wire gemm_mem_req_valid, gemm_mem_req_write, gemm_mem_rsp_ready;
    wire [31:0] gemm_mem_req_addr;
    wire [15:0] gemm_mem_req_wdata;
    wire gemm_mem_req_ready, gemm_mem_rsp_valid, gemm_mem_rsp_error;
    wire [15:0] gemm_mem_rsp_rdata;

    wire conv_mem_req_valid, conv_mem_req_write, conv_mem_rsp_ready;
    wire [31:0] conv_mem_req_addr;
    wire [15:0] conv_mem_req_wdata;
    wire conv_mem_req_ready, conv_mem_rsp_valid, conv_mem_rsp_error;
    wire [15:0] conv_mem_rsp_rdata;

    wire pool_mem_req_valid, pool_mem_req_write, pool_mem_rsp_ready;
    wire [31:0] pool_mem_req_addr;
    wire [15:0] pool_mem_req_wdata;
    wire pool_mem_req_ready, pool_mem_rsp_valid, pool_mem_rsp_error;
    wire [15:0] pool_mem_rsp_rdata;

    wire host_mem_req_valid, host_mem_req_write, host_mem_rsp_ready;
    wire [31:0] host_mem_req_addr;
    wire [15:0] host_mem_req_wdata;
    wire host_mem_req_ready, host_mem_rsp_valid, host_mem_rsp_error;
    wire [15:0] host_mem_rsp_rdata;

    // ---- conv-simple transport page ---------------------------------------
    rk_conv_simple_axi #(
        .PROFILE(0), .BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES)),
        .WORDS(52), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) conv_page (
        .clk(SYS_CLK), .rst_n(reset_n), .memory_ready(conv_memory_ready),
        .s_axil_awaddr({20'd0, write_address_q[11:0]}),
        .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(conv_awvalid),
        .s_axil_awready(conv_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid(conv_wvalid),
        .s_axil_wready(conv_wready),
        .s_axil_bresp(conv_bresp), .s_axil_bvalid(conv_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_CONV),
        .s_axil_araddr({20'd0, read_address_q[11:0]}),
        .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(read_conv_valid),
        .s_axil_arready(conv_arready),
        .s_axil_rdata(conv_rdata), .s_axil_rresp(conv_rresp),
        .s_axil_rvalid(conv_rvalid),
        .s_axil_rready(s_axil_rready && read_resp_target_q == T_CONV),
        .irq(conv_irq), .busy(conv_busy),
        .mem_req_valid(conv_mem_req_valid), .mem_req_ready(conv_mem_req_ready),
        .mem_req_write(conv_mem_req_write), .mem_req_addr(conv_mem_req_addr),
        .mem_req_wdata(conv_mem_req_wdata),
        .mem_rsp_valid(conv_mem_rsp_valid), .mem_rsp_ready(conv_mem_rsp_ready),
        .mem_rsp_rdata(conv_mem_rsp_rdata), .mem_rsp_error(conv_mem_rsp_error)
    );

    // ---- signed-INT8 pooling transport page --------------------------------
    rk_ppu_pool_axi #(
        .BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES)), .WORDS(26),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) pool_page (
        .clk(SYS_CLK), .rst_n(reset_n), .memory_ready(pool_memory_ready),
        .s_axil_awaddr({20'd0, write_address_q[11:0]}),
        .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(pool_awvalid),
        .s_axil_awready(pool_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid(pool_wvalid),
        .s_axil_wready(pool_wready),
        .s_axil_bresp(pool_bresp), .s_axil_bvalid(pool_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_POOL),
        .s_axil_araddr({20'd0, read_address_q[11:0]}),
        .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(read_pool_valid),
        .s_axil_arready(pool_arready),
        .s_axil_rdata(pool_rdata), .s_axil_rresp(pool_rresp),
        .s_axil_rvalid(pool_rvalid),
        .s_axil_rready(s_axil_rready && read_resp_target_q == T_POOL),
        .irq(pool_irq), .busy(pool_busy),
        .mem_req_valid(pool_mem_req_valid), .mem_req_ready(pool_mem_req_ready),
        .mem_req_write(pool_mem_req_write), .mem_req_addr(pool_mem_req_addr),
        .mem_req_wdata(pool_mem_req_wdata),
        .mem_rsp_valid(pool_mem_rsp_valid), .mem_rsp_ready(pool_mem_rsp_ready),
        .mem_rsp_rdata(pool_mem_rsp_rdata), .mem_rsp_error(pool_mem_rsp_error)
    );

    // ---- conv-simple page, FP32 output (profile 3) -------------------------
    // A second page, not a run-time profile switch: the geometry is an
    // elaboration parameter, so the build fixes which capture this page serves.
    // Its identity is one byte above the FP16 page's so a host can confirm it
    // reached the FP32 profile.
    rk_conv_simple_axi #(
        .PROFILE(3),
        .INPUT_H(8), .INPUT_W(8), .KH(1), .KW(1),
        .INPUT_CHANNELS(4), .KERNELS(8), .C1_BLOCKS(2),
        .ALIGN_C(8), .PACK_C2(4), .CHUNK_LANES(16),
        .OUTPUT_FP16(1'b0),
        .BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES)),
        .WORDS(52), .TIMEOUT_CYCLES(TIMEOUT_CYCLES),
        .DEVICE_ID(32'h524b4415)
    ) conv_fp32_page (
        .clk(SYS_CLK), .rst_n(reset_n),
        .memory_ready(conv_fp32_memory_ready),
        .s_axil_awaddr({20'd0, write_address_q[11:0]}),
        .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(conv_fp32_awvalid),
        .s_axil_awready(conv_fp32_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid(conv_fp32_wvalid),
        .s_axil_wready(conv_fp32_wready),
        .s_axil_bresp(conv_fp32_bresp), .s_axil_bvalid(conv_fp32_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_CONV_FP32),
        .s_axil_araddr({20'd0, read_address_q[11:0]}),
        .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(read_conv_fp32_valid),
        .s_axil_arready(conv_fp32_arready),
        .s_axil_rdata(conv_fp32_rdata), .s_axil_rresp(conv_fp32_rresp),
        .s_axil_rvalid(conv_fp32_rvalid),
        .s_axil_rready(s_axil_rready && read_resp_target_q == T_CONV_FP32),
        .irq(conv_fp32_irq), .busy(conv_fp32_busy),
        .mem_req_valid(conv_fp32_mem_req_valid),
        .mem_req_ready(conv_fp32_mem_req_ready),
        .mem_req_write(conv_fp32_mem_req_write),
        .mem_req_addr(conv_fp32_mem_req_addr),
        .mem_req_wdata(conv_fp32_mem_req_wdata),
        .mem_rsp_valid(conv_fp32_mem_rsp_valid),
        .mem_rsp_ready(conv_fp32_mem_rsp_ready),
        .mem_rsp_rdata(conv_fp32_mem_rsp_rdata),
        .mem_rsp_error(conv_fp32_mem_rsp_error)
    );

    // ---- conv-simple page, profile 1 ---------------------------------
    rk_conv_simple_axi #(
        .PROFILE(1), .INPUT_H(8), .INPUT_W(8), .KH(5), .KW(5),
        .OUTPUT_FP16(1'b1),
        .BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES)),
        .WORDS(52), .TIMEOUT_CYCLES(TIMEOUT_CYCLES),
        .DEVICE_ID(32'h524b4416)
    ) conv_k5_page (
        .clk(SYS_CLK), .rst_n(reset_n),
        .memory_ready(conv_k5_memory_ready),
        .s_axil_awaddr({20'd0, write_address_q[11:0]}),
        .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(conv_k5_awvalid),
        .s_axil_awready(conv_k5_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid(conv_k5_wvalid),
        .s_axil_wready(conv_k5_wready),
        .s_axil_bresp(conv_k5_bresp), .s_axil_bvalid(conv_k5_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_CONV_K5),
        .s_axil_araddr({20'd0, read_address_q[11:0]}),
        .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(read_conv_k5_valid),
        .s_axil_arready(conv_k5_arready),
        .s_axil_rdata(conv_k5_rdata), .s_axil_rresp(conv_k5_rresp),
        .s_axil_rvalid(conv_k5_rvalid),
        .s_axil_rready(s_axil_rready && read_resp_target_q == T_CONV_K5),
        .irq(conv_k5_irq), .busy(conv_k5_busy),
        .mem_req_valid(conv_k5_mem_req_valid),
        .mem_req_ready(conv_k5_mem_req_ready),
        .mem_req_write(conv_k5_mem_req_write),
        .mem_req_addr(conv_k5_mem_req_addr),
        .mem_req_wdata(conv_k5_mem_req_wdata),
        .mem_rsp_valid(conv_k5_mem_rsp_valid),
        .mem_rsp_ready(conv_k5_mem_rsp_ready),
        .mem_rsp_rdata(conv_k5_mem_rsp_rdata),
        .mem_rsp_error(conv_k5_mem_rsp_error)
    );

    // ---- conv-simple page, profile 2 ---------------------------------
    rk_conv_simple_axi #(
        .PROFILE(2), .INPUT_H(8), .INPUT_W(8), .KH(3), .KW(3),
        .INPUT_CHANNELS(16), .C1_BLOCKS(4), .ALIGN_C(16), .PACK_C2(8),
        .OUTPUT_FP16(1'b1),
        .BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES)),
        .WORDS(52), .TIMEOUT_CYCLES(TIMEOUT_CYCLES),
        .DEVICE_ID(32'h524b4417)
    ) conv_c16_page (
        .clk(SYS_CLK), .rst_n(reset_n),
        .memory_ready(conv_c16_memory_ready),
        .s_axil_awaddr({20'd0, write_address_q[11:0]}),
        .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(conv_c16_awvalid),
        .s_axil_awready(conv_c16_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid(conv_c16_wvalid),
        .s_axil_wready(conv_c16_wready),
        .s_axil_bresp(conv_c16_bresp), .s_axil_bvalid(conv_c16_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_CONV_C16),
        .s_axil_araddr({20'd0, read_address_q[11:0]}),
        .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(read_conv_c16_valid),
        .s_axil_arready(conv_c16_arready),
        .s_axil_rdata(conv_c16_rdata), .s_axil_rresp(conv_c16_rresp),
        .s_axil_rvalid(conv_c16_rvalid),
        .s_axil_rready(s_axil_rready && read_resp_target_q == T_CONV_C16),
        .irq(conv_c16_irq), .busy(conv_c16_busy),
        .mem_req_valid(conv_c16_mem_req_valid),
        .mem_req_ready(conv_c16_mem_req_ready),
        .mem_req_write(conv_c16_mem_req_write),
        .mem_req_addr(conv_c16_mem_req_addr),
        .mem_req_wdata(conv_c16_mem_req_wdata),
        .mem_rsp_valid(conv_c16_mem_rsp_valid),
        .mem_rsp_ready(conv_c16_mem_rsp_ready),
        .mem_rsp_rdata(conv_c16_mem_rsp_rdata),
        .mem_rsp_error(conv_c16_mem_rsp_error)
    );

    // ---- FP32 GEMM transport page -----------------------------------------
    // The frozen `conv-gemm-vendor` captures are FP32 output with
    // OUT_CVT_SCALE=0, so this page elaborates the no-conversion tail. Its
    // memory port is the same halfword shape as the other two pages, which is
    // why it needs no AXI bridge inside the image.
    rk_cmac_gemm_axi #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) gemm_page (
        .clk(SYS_CLK), .rst_n(reset_n), .memory_ready(gemm_memory_ready),
        .s_axil_awaddr({20'd0, write_address_q[11:0]}),
        .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(gemm_awvalid),
        .s_axil_awready(gemm_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid(gemm_wvalid),
        .s_axil_wready(gemm_wready),
        .s_axil_bresp(gemm_bresp), .s_axil_bvalid(gemm_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_GEMM),
        .s_axil_araddr({20'd0, read_address_q[11:0]}),
        .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(read_gemm_valid),
        .s_axil_arready(gemm_arready),
        .s_axil_rdata(gemm_rdata), .s_axil_rresp(gemm_rresp),
        .s_axil_rvalid(gemm_rvalid),
        .s_axil_rready(s_axil_rready && read_resp_target_q == T_GEMM),
        .irq(gemm_irq), .busy(gemm_busy),
        .mem_req_valid(gemm_mem_req_valid), .mem_req_ready(gemm_mem_req_ready),
        .mem_req_write(gemm_mem_req_write), .mem_req_addr(gemm_mem_req_addr),
        .mem_req_wdata(gemm_mem_req_wdata),
        .mem_rsp_valid(gemm_mem_rsp_valid), .mem_rsp_ready(gemm_mem_rsp_ready),
        .mem_rsp_rdata(gemm_mem_rsp_rdata), .mem_rsp_error(gemm_mem_rsp_error)
    );

    // ---- host window onto the shared memory --------------------------------
    rk_axil_mem_bridge #(.BASE(BRAM_BASE), .BYTES(33'(BRAM_BYTES))) memory_bridge (
        .clk(SYS_CLK), .rst_n(reset_n),
        .host_enable(host_memory_enable),
        .busy(host_mem_busy),
        .s_axil_awaddr(write_address_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(mem_awvalid),
        .s_axil_awready(mem_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid(mem_wvalid),
        .s_axil_wready(mem_wready),
        .s_axil_bresp(mem_bresp), .s_axil_bvalid(mem_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_MEMORY),
        .s_axil_araddr(read_address_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(read_mem_valid),
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

    // ---- unmapped addresses: always an explicit error ----------------------
    rk_axil_error_slave error_page (
        .clk(SYS_CLK), .rst_n(reset_n),
        .s_axil_awaddr(write_address_q), .s_axil_awprot(write_prot_q),
        .s_axil_awvalid(unmapped_awvalid),
        .s_axil_awready(err_awready),
        .s_axil_wdata(write_data_q), .s_axil_wstrb(write_strobe_q),
        .s_axil_wvalid(unmapped_wvalid),
        .s_axil_wready(err_wready),
        .s_axil_bresp(err_bresp), .s_axil_bvalid(err_bvalid),
        .s_axil_bready(s_axil_bready && write_resp_target_q == T_UNMAPPED),
        .s_axil_araddr(read_address_q), .s_axil_arprot(read_prot_q),
        .s_axil_arvalid(read_unmapped_valid),
        .s_axil_arready(err_arready),
        .s_axil_rdata(err_rdata), .s_axil_rresp(err_rresp),
        .s_axil_rvalid(err_rvalid),
        .s_axil_rready(s_axil_rready && read_resp_target_q == T_UNMAPPED)
    );

    // ---- memory arbitration ------------------------------------------------
    // Three bits: five owners do not fit in two. A 2-bit literal here would
    // truncate OWN_GEMM to OWN_NONE and silently starve that page.
    localparam logic [2:0] OWN_NONE = 3'd0, OWN_CONV = 3'd1,
                           OWN_POOL = 3'd2, OWN_HOST = 3'd3,
                           OWN_GEMM = 3'd4, OWN_CONV_FP32 = 3'd5,
                           OWN_CONV_K5 = 3'd6, OWN_CONV_C16 = 3'd7;
    logic [2:0] owner_q;
    wire owned = (owner_q != OWN_NONE);

    // Clients are mutually exclusive by construction, so the priority order
    // below selects the only client that can legally be requesting.
    wire [2:0] next_owner = conv_mem_req_valid ? OWN_CONV :
                            pool_mem_req_valid ? OWN_POOL :
                            gemm_mem_req_valid ? OWN_GEMM :
                            conv_fp32_mem_req_valid ? OWN_CONV_FP32 :
                            conv_k5_mem_req_valid ? OWN_CONV_K5 :
                            conv_c16_mem_req_valid ? OWN_CONV_C16 :
                            host_mem_req_valid ? OWN_HOST : OWN_NONE;

    wire bram_req_valid = (next_owner != OWN_NONE) && !owned;
    wire bram_req_write = (next_owner == OWN_CONV) ? conv_mem_req_write :
                          (next_owner == OWN_POOL) ? pool_mem_req_write :
                          (next_owner == OWN_GEMM) ? gemm_mem_req_write :
                          (next_owner == OWN_CONV_FP32) ? conv_fp32_mem_req_write :
                          (next_owner == OWN_CONV_K5) ? conv_k5_mem_req_write :
                          (next_owner == OWN_CONV_C16) ? conv_c16_mem_req_write :
                                                     host_mem_req_write;
    wire [31:0] bram_req_addr = (next_owner == OWN_CONV) ? conv_mem_req_addr :
                                (next_owner == OWN_POOL) ? pool_mem_req_addr :
                                (next_owner == OWN_GEMM) ? gemm_mem_req_addr :
                                (next_owner == OWN_CONV_FP32) ? conv_fp32_mem_req_addr :
                                (next_owner == OWN_CONV_K5) ? conv_k5_mem_req_addr :
                                (next_owner == OWN_CONV_C16) ? conv_c16_mem_req_addr :
                                                           host_mem_req_addr;
    wire [15:0] bram_req_wdata = (next_owner == OWN_CONV) ? conv_mem_req_wdata :
                                 (next_owner == OWN_POOL) ? pool_mem_req_wdata :
                                 (next_owner == OWN_GEMM) ? gemm_mem_req_wdata :
                                 (next_owner == OWN_CONV_FP32) ? conv_fp32_mem_req_wdata :
                                 (next_owner == OWN_CONV_K5) ? conv_k5_mem_req_wdata :
                                 (next_owner == OWN_CONV_C16) ? conv_c16_mem_req_wdata :
                                                            host_mem_req_wdata;
    wire bram_req_ready;
    wire bram_rsp_valid;
    wire [15:0] bram_rsp_rdata;
    wire bram_rsp_error;

    assign conv_mem_req_ready = !owned && (next_owner == OWN_CONV) &&
                                bram_req_ready;
    assign pool_mem_req_ready = !owned && (next_owner == OWN_POOL) &&
                                bram_req_ready;
    assign host_mem_req_ready = !owned && (next_owner == OWN_HOST) &&
                               bram_req_ready;
    assign gemm_mem_req_ready = !owned && (next_owner == OWN_GEMM) &&
                                bram_req_ready;
    assign conv_fp32_mem_req_ready = !owned &&
                                     (next_owner == OWN_CONV_FP32) &&
                                     bram_req_ready;
    assign conv_k5_mem_req_ready = !owned && (next_owner == OWN_CONV_K5) &&
                                   bram_req_ready;
    assign conv_c16_mem_req_ready = !owned && (next_owner == OWN_CONV_C16) &&
                                    bram_req_ready;

    assign conv_mem_rsp_valid = bram_rsp_valid && (owner_q == OWN_CONV);
    assign pool_mem_rsp_valid = bram_rsp_valid && (owner_q == OWN_POOL);
    assign host_mem_rsp_valid = bram_rsp_valid && (owner_q == OWN_HOST);
    assign gemm_mem_rsp_valid = bram_rsp_valid && (owner_q == OWN_GEMM);
    assign conv_fp32_mem_rsp_valid = bram_rsp_valid &&
                                     (owner_q == OWN_CONV_FP32);
    assign conv_k5_mem_rsp_valid = bram_rsp_valid && (owner_q == OWN_CONV_K5);
    assign conv_c16_mem_rsp_valid = bram_rsp_valid && (owner_q == OWN_CONV_C16);
    assign conv_mem_rsp_rdata = bram_rsp_rdata;
    assign conv_mem_rsp_error = bram_rsp_error;
    assign pool_mem_rsp_rdata = bram_rsp_rdata;
    assign pool_mem_rsp_error = bram_rsp_error;
    assign host_mem_rsp_rdata = bram_rsp_rdata;
    assign host_mem_rsp_error = bram_rsp_error;
    assign gemm_mem_rsp_rdata = bram_rsp_rdata;
    assign gemm_mem_rsp_error = bram_rsp_error;
    assign conv_fp32_mem_rsp_rdata = bram_rsp_rdata;
    assign conv_fp32_mem_rsp_error = bram_rsp_error;
    assign conv_k5_mem_rsp_rdata = bram_rsp_rdata;
    assign conv_k5_mem_rsp_error = bram_rsp_error;
    assign conv_c16_mem_rsp_rdata = bram_rsp_rdata;
    assign conv_c16_mem_rsp_error = bram_rsp_error;

    wire bram_rsp_ready = (owner_q == OWN_CONV) ? conv_mem_rsp_ready :
                          (owner_q == OWN_POOL) ? pool_mem_rsp_ready :
                          (owner_q == OWN_GEMM) ? gemm_mem_rsp_ready :
                          (owner_q == OWN_CONV_FP32) ? conv_fp32_mem_rsp_ready :
                          (owner_q == OWN_CONV_K5) ? conv_k5_mem_rsp_ready :
                          (owner_q == OWN_CONV_C16) ? conv_c16_mem_rsp_ready :
                          (owner_q == OWN_HOST) ? host_mem_rsp_ready : 1'b0;

    rk_bram #(.BYTES(BRAM_BYTES), .BASE(BRAM_BASE)) memory (
        .clk(SYS_CLK), .rst_n(reset_n),
        .req_valid(bram_req_valid), .req_ready(bram_req_ready),
        .req_write(bram_req_write), .req_addr(bram_req_addr),
        .req_wdata(bram_req_wdata),
        .rsp_valid(bram_rsp_valid), .rsp_ready(bram_rsp_ready),
        .rsp_rdata(bram_rsp_rdata), .rsp_error(bram_rsp_error),
        // The second physical port is left idle: all three clients share the
        // arbitrated request port so that one owner answers every response.
        .host_valid(1'b0), .host_ready(), .host_write(1'b0),
        .host_addr(32'd0), .host_wdata(16'd0),
        .host_rsp_valid(), .host_rsp_ready(1'b0),
        .host_rdata(), .host_error()
    );

    // ---- front-end sequential logic and response mux -----------------------
    wire dispatch_awready = (write_dispatch_q == T_CONV) ? conv_awready :
                            (write_dispatch_q == T_POOL) ? pool_awready :
                            (write_dispatch_q == T_GEMM) ? gemm_awready :
                            (write_dispatch_q == T_CONV_FP32) ? conv_fp32_awready :
                            (write_dispatch_q == T_CONV_K5) ? conv_k5_awready :
                            (write_dispatch_q == T_CONV_C16) ? conv_c16_awready :
                            (write_dispatch_q == T_MEMORY) ? mem_awready :
                            (write_dispatch_q == T_UNMAPPED) ? err_awready : 1'b0;
    wire dispatch_wready = (write_dispatch_q == T_CONV) ? conv_wready :
                           (write_dispatch_q == T_POOL) ? pool_wready :
                           (write_dispatch_q == T_GEMM) ? gemm_wready :
                           (write_dispatch_q == T_CONV_FP32) ? conv_fp32_wready :
                           (write_dispatch_q == T_CONV_K5) ? conv_k5_wready :
                           (write_dispatch_q == T_CONV_C16) ? conv_c16_wready :
                           (write_dispatch_q == T_MEMORY) ? mem_wready :
                           (write_dispatch_q == T_UNMAPPED) ? err_wready : 1'b0;
    wire read_dispatch_ready = (read_target == T_CONV) ? conv_arready :
                               (read_target == T_POOL) ? pool_arready :
                               (read_target == T_GEMM) ? gemm_arready :
                               (read_target == T_CONV_FP32) ? conv_fp32_arready :
                               (read_target == T_CONV_K5) ? conv_k5_arready :
                               (read_target == T_CONV_C16) ? conv_c16_arready :
                               (read_target == T_MEMORY) ? mem_arready :
                               (read_target == T_UNMAPPED) ? err_arready : 1'b0;

    wire dispatch_bvalid = (write_resp_target_q == T_CONV) ? conv_bvalid :
                           (write_resp_target_q == T_POOL) ? pool_bvalid :
                           (write_resp_target_q == T_GEMM) ? gemm_bvalid :
                           (write_resp_target_q == T_CONV_FP32) ? conv_fp32_bvalid :
                           (write_resp_target_q == T_CONV_K5) ? conv_k5_bvalid :
                           (write_resp_target_q == T_CONV_C16) ? conv_c16_bvalid :
                           (write_resp_target_q == T_MEMORY) ? mem_bvalid :
                           (write_resp_target_q == T_UNMAPPED) ? err_bvalid : 1'b0;
    wire [1:0] dispatch_bresp = (write_resp_target_q == T_CONV) ? conv_bresp :
                                (write_resp_target_q == T_POOL) ? pool_bresp :
                                (write_resp_target_q == T_GEMM) ? gemm_bresp :
                                (write_resp_target_q == T_CONV_FP32) ? conv_fp32_bresp :
                                (write_resp_target_q == T_CONV_K5) ? conv_k5_bresp :
                                (write_resp_target_q == T_CONV_C16) ? conv_c16_bresp :
                                (write_resp_target_q == T_MEMORY) ? mem_bresp :
                                (write_resp_target_q == T_UNMAPPED) ? err_bresp : 2'b11;
    wire dispatch_rvalid = (read_resp_target_q == T_CONV) ? conv_rvalid :
                           (read_resp_target_q == T_POOL) ? pool_rvalid :
                           (read_resp_target_q == T_GEMM) ? gemm_rvalid :
                           (read_resp_target_q == T_CONV_FP32) ? conv_fp32_rvalid :
                           (read_resp_target_q == T_CONV_K5) ? conv_k5_rvalid :
                           (read_resp_target_q == T_CONV_C16) ? conv_c16_rvalid :
                           (read_resp_target_q == T_MEMORY) ? mem_rvalid :
                           (read_resp_target_q == T_UNMAPPED) ? err_rvalid : 1'b0;
    wire [31:0] dispatch_rdata = (read_resp_target_q == T_CONV) ? conv_rdata :
                                 (read_resp_target_q == T_POOL) ? pool_rdata :
                                 (read_resp_target_q == T_GEMM) ? gemm_rdata :
                                 (read_resp_target_q == T_CONV_FP32) ? conv_fp32_rdata :
                                 (read_resp_target_q == T_CONV_K5) ? conv_k5_rdata :
                                 (read_resp_target_q == T_CONV_C16) ? conv_c16_rdata :
                                 (read_resp_target_q == T_MEMORY) ? mem_rdata :
                                 (read_resp_target_q == T_UNMAPPED) ? err_rdata : 32'd0;
    wire [1:0] dispatch_rresp = (read_resp_target_q == T_CONV) ? conv_rresp :
                                (read_resp_target_q == T_POOL) ? pool_rresp :
                                (read_resp_target_q == T_GEMM) ? gemm_rresp :
                                (read_resp_target_q == T_CONV_FP32) ? conv_fp32_rresp :
                                (read_resp_target_q == T_CONV_K5) ? conv_k5_rresp :
                                (read_resp_target_q == T_CONV_C16) ? conv_c16_rresp :
                                (read_resp_target_q == T_MEMORY) ? mem_rresp :
                                (read_resp_target_q == T_UNMAPPED) ? err_rresp : 2'b11;

    assign s_axil_awready = (write_state_q == W_COLLECT) && !have_aw_q;
    assign s_axil_wready  = (write_state_q == W_COLLECT) && !have_w_q;
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
                        write_dispatch_q <= decode(pending_write_page);
                        have_aw_q <= 1'b0;
                        have_w_q <= 1'b0;
                        aw_accepted_q <= 1'b0;
                        w_accepted_q <= 1'b0;
                        write_state_q <= W_DISPATCH;
                    end
                end
                W_DISPATCH: begin
                    if (dispatch_awready && !aw_accepted_q) aw_accepted_q <= 1'b1;
                    if (dispatch_wready && !w_accepted_q) w_accepted_q <= 1'b1;
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
                        read_resp_target_q <= decode(s_axil_araddr[15:PAGE_SHIFT]);
                        read_accepted_q <= 1'b0;
                        read_state_q <= R_DISPATCH;
                    end
                end
                R_DISPATCH: begin
                    if (read_dispatch_ready) begin
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

            // A grant is held from acceptance through response completion. If a
            // response and a new request complete in the same cycle the new
            // grant wins, because the memory accepts back-to-back access.
            if (bram_req_valid && bram_req_ready)
                owner_q <= next_owner;
            else if (bram_rsp_valid && bram_rsp_ready)
                owner_q <= OWN_NONE;
        end
    end

    // ---- LEDs: heartbeat plus the two completion lines ---------------------
    // One LED bit now carries three completion lines. They are OR-ed because
    // this image is a bring-up target: a stuck bit means "some job finished",
    // and the result registers say which.
    assign led_3bits_tri_o = {heartbeat[25],
                              pool_irq | gemm_irq | conv_fp32_irq |
                              conv_k5_irq | conv_c16_irq,
                              conv_irq} ^ {3{LED_ACTIVE_LOW}};

    initial begin
        if (BRAM_BYTES < 4 || (BRAM_BYTES & (BRAM_BYTES - 1)) != 0)
            $fatal(1, "shared memory size must be a power of two >= 4");
        if (BRAM_BASE[0])
            $fatal(1, "shared memory base must be even");
        // The endpoint pages live at 0x8000 and 0x9000 in this image, and the
        // read/write decoders assume the aperture ends below them.
        if (BRAM_BASE != 32'h0000_0000 || BRAM_BYTES != 32768)
            $fatal(1, "this image fixes the memory aperture at 0x0000..0x7fff");
        // The three pages occupy 0x8000/0x9000/0xa000 and the aperture must end
        // below them, or a decoder would shadow a page.
        if (BRAM_BYTES > 32768)
            $fatal(1, "the memory aperture collides with a transport page");
    end
endmodule
