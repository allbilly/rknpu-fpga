// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// AXI4-Lite to halfword memory bridge.
//
// The accelerator engines use a serialized 16-bit memory port (`mem_req_*`,
// one outstanding transaction). A host needs to load command/operand buffers and
// read result buffers through the same aperture. This bridge turns one 32-bit
// AXI4-Lite access into exactly two halfword transactions and exposes no other
// addressing mode.
//
// Rules, all explicit failures:
//   * writes require all four byte strobes; a partial write is SLVERR rather
//     than being partially applied;
//   * an address outside [BASE, BASE+BYTES) or not 4-byte aligned is SLVERR;
//   * a protected write or read is SLVERR;
//   * a memory response error becomes an AXI SLVERR, never a good transfer with
//     wrong data;
//   * `host_enable` withdraws awready/wready/arready, so a disabled bridge
//     stalls the host instead of touching memory.
//
// Each beat waits for its own memory response before the next request is
// issued, so the low halfword of a read is always captured in the cycle its
// response arrives. There is no burst, no CDC, no unaligned support and no
// MMIO side effect: AXI `awprot`/`arprot` must be 3'b000.
//
// The state machine is written as one priority ladder rather than a case with
// a default arm: in a single always_ff block the last assignment wins, so a
// `default: state_q <= IDLE` arm would silently cancel the transition it was
// supposed to accompany.
module rk_axil_mem_bridge #(
    parameter logic [31:0] BASE = 32'h00000000,
    parameter logic [32:0] BYTES = 33'd1048576
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        host_enable,
    // True from an accepted AXI access until its response handshake. The
    // platform uses this to keep the engines off the memory while the host
    // owns it (rk_bram forbids concurrent host/accelerator access).
    output logic        busy,
    // AXI4-Lite slave
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
    // serialized halfword port (shared with the engines)
    output logic        mem_req_valid,
    input  logic        mem_req_ready,
    output logic        mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input  logic        mem_rsp_valid,
    output logic        mem_rsp_ready,
    input  logic [15:0] mem_rsp_rdata,
    input  logic        mem_rsp_error
);
    localparam logic [3:0] IDLE         = 4'd0,
                           WRITE_LO_REQ = 4'd1,
                           WRITE_LO_RSP = 4'd2,
                           WRITE_HI_REQ = 4'd3,
                           WRITE_HI_RSP = 4'd4,
                           WRITE_ACK    = 4'd5,
                           READ_LO_REQ  = 4'd6,
                           READ_LO_RSP  = 4'd7,
                           READ_HI_REQ  = 4'd8,
                           READ_HI_RSP  = 4'd9,
                           RESPONSE     = 4'd10;
    logic [3:0] state_q;

    logic [31:0] address_q, write_data_q, read_data_q;
    logic [15:0] read_lo_q;
    logic aw_pending_q, w_pending_q;
    logic error_q;   // sticky fault for this transaction, cleared at the next one

    // A 33-bit subtraction cannot wrap into the aperture: when the address is
    // below BASE the result is >= 2^32+1, which no legal BYTES value admits.
    function automatic logic address_ok(input logic [31:0] address);
        logic [32:0] offset;
        offset = {1'b0, address} - {1'b0, BASE};
        address_ok = (offset < BYTES) && (address[1:0] == 2'b00);
    endfunction

    wire in_write = state_q == WRITE_LO_REQ || state_q == WRITE_HI_REQ;
    wire in_read = state_q == READ_LO_REQ || state_q == READ_HI_REQ;
    wire in_request = in_write || in_read;
    wire in_response = state_q == WRITE_LO_RSP || state_q == WRITE_HI_RSP ||
                       state_q == READ_LO_RSP || state_q == READ_HI_RSP;
    wire high_beat = state_q == WRITE_HI_REQ || state_q == WRITE_HI_RSP ||
                     state_q == READ_HI_REQ || state_q == READ_HI_RSP;

    // A write transaction may only start once both AW and W have arrived.
    wire write_pair_ready = aw_pending_q && w_pending_q;

    assign busy = state_q != IDLE;

    assign s_axil_awready = rst_n && host_enable && !aw_pending_q &&
                            state_q == IDLE;
    assign s_axil_wready = rst_n && host_enable && !w_pending_q &&
                           state_q == IDLE;
    assign s_axil_arready = rst_n && host_enable && state_q == IDLE;
    assign s_axil_bvalid = rst_n && state_q == WRITE_ACK;
    assign s_axil_rvalid = rst_n && state_q == RESPONSE;
    assign s_axil_bresp = error_q ? 2'b10 : 2'b00;
    assign s_axil_rresp = error_q ? 2'b10 : 2'b00;
    assign s_axil_rdata = read_data_q;

    assign mem_req_valid = rst_n && in_request;
    assign mem_req_write = in_write;
    assign mem_req_addr = address_q + (high_beat ? 32'd2 : 32'd0);
    assign mem_req_wdata = high_beat ? write_data_q[31:16]
                                     : write_data_q[15:0];
    assign mem_rsp_ready = rst_n && in_response;

    initial begin
        if (BYTES == 0 || BYTES > 33'h100000000)
            $fatal(1, "bridge aperture must be a positive 32-bit range");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= IDLE;
            address_q <= 32'd0;
            write_data_q <= 32'd0;
            read_data_q <= 32'd0;
            read_lo_q <= 16'd0;
            aw_pending_q <= 1'b0;
            w_pending_q <= 1'b0;
            error_q <= 1'b0;
        end else begin
            // Capture the address and data channels independently.
            if (s_axil_awvalid && s_axil_awready) begin
                aw_pending_q <= 1'b1;
                address_q <= s_axil_awaddr;
                error_q <= (s_axil_awprot != 3'd0) ||
                           !address_ok(s_axil_awaddr);
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_pending_q <= 1'b1;
                write_data_q <= s_axil_wdata;
                if (s_axil_wstrb != 4'hf)
                    error_q <= 1'b1;
            end

            // IDLE has its own branch so no default arm can override it.
            if (state_q == IDLE) begin
                if (write_pair_ready) begin
                    aw_pending_q <= 1'b0;
                    w_pending_q <= 1'b0;
                    state_q <= error_q ? WRITE_ACK : WRITE_LO_REQ;
                end else if (s_axil_arvalid && s_axil_arready) begin
                    address_q <= s_axil_araddr;
                    read_lo_q <= 16'd0;
                    error_q <= (s_axil_arprot != 3'd0) ||
                               !address_ok(s_axil_araddr);
                    state_q <= ((s_axil_arprot != 3'd0) ||
                                !address_ok(s_axil_araddr))
                                   ? RESPONSE : READ_LO_REQ;
                end
            end else begin
                case (state_q)
                    WRITE_LO_REQ: if (mem_req_ready)
                        state_q <= WRITE_LO_RSP;
                    WRITE_LO_RSP: if (mem_rsp_valid) begin
                        if (mem_rsp_error) error_q <= 1'b1;
                        state_q <= WRITE_HI_REQ;
                    end
                    WRITE_HI_REQ: if (mem_req_ready)
                        state_q <= WRITE_HI_RSP;
                    WRITE_HI_RSP: if (mem_rsp_valid) begin
                        if (mem_rsp_error) error_q <= 1'b1;
                        state_q <= WRITE_ACK;
                    end
                    WRITE_ACK: if (s_axil_bready) begin
                        state_q <= IDLE;
                        error_q <= 1'b0;
                    end

                    READ_LO_REQ: if (mem_req_ready)
                        state_q <= READ_LO_RSP;
                    READ_LO_RSP: if (mem_rsp_valid) begin
                        read_lo_q <= mem_rsp_rdata;
                        if (mem_rsp_error) error_q <= 1'b1;
                        state_q <= READ_HI_REQ;
                    end
                    READ_HI_REQ: if (mem_req_ready)
                        state_q <= READ_HI_RSP;
                    READ_HI_RSP: if (mem_rsp_valid) begin
                        read_data_q <= {mem_rsp_rdata, read_lo_q};
                        if (mem_rsp_error) error_q <= 1'b1;
                        state_q <= RESPONSE;
                    end
                    RESPONSE: if (s_axil_rready) begin
                        state_q <= IDLE;
                        error_q <= 1'b0;
                    end

                    default: state_q <= IDLE;
                endcase
            end
        end
    end
endmodule
