// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// USER2 mailbox to AXI4-Lite master adapter.
//
// The board-proven host path in this repository is the OpenTPU USER2 JTAG
// mailbox (`rtl/vendor/opentpu/otpu_jtag_mailbox.sv`). It carries 640-bit frames
// and needs no package pins. This module turns those frames into AXI4-Lite
// transactions, so a host-drivable image does not have to expose a 32-bit AXI
// slave at the top level (which is what blocks a bitstream today: NSTD-1).
//
// Frame layout (unchanged from the mailbox):
//   data[511:0], address[543:512], strobes[547:544], opcode[555:548],
//   sequence[571:556], magic[603:572] = 0x4f54504a
//
// Opcodes:
//   1  register read    one 32-bit AXI read at `address`
//   2  register write   one 32-bit AXI write at `address`, data[31:0]
//   3  block read       16 consecutive 32-bit AXI reads from a 64-byte
//                       aligned address, returned packed into data[511:0]
//   4  block write      16 consecutive 32-bit AXI writes of data[511:0]
//
// Responses: data[511:0], status[519:512], sequence[535:520],
//            magic[567:536]. Status 0 is success; the codes below are explicit
//            and never a silent success.
//
// Rules:
//   * opcodes 1/2 require a word-aligned address; opcodes 3/4 require 64-byte
//     alignment, matching the mailbox's own block semantics.
//   * an AXI error response (SLVERR/DECERR) is status 7, never data.
//   * a timeout is status 0x80 and quarantines until a joint reset, exactly like
//     `rk_jtag_backend`. No transaction is silently dropped.
//   * one request at a time; the host must await its sequence before submitting
//     another frame, which the mailbox already enforces.
//
// There is no CDC here: the mailbox presents its request in the SYS clock
// domain, and the AXI slave is also in that domain.
module rk_jtag_axil_bridge #(
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic         clk,
    input  logic         rst_n,
    // mailbox-facing
    input  logic         req_valid,
    output logic         req_ready,
    input  logic [603:0] req,
    output logic         rsp_valid,
    output logic [511:0] rsp_data,
    output logic [7:0]   rsp_status,
    output logic [15:0]  rsp_seq,
    output logic         fault,
    // AXI4-Lite master
    output logic [31:0]  s_axil_awaddr,
    output logic [2:0]   s_axil_awprot,
    output logic         s_axil_awvalid,
    input  logic         s_axil_awready,
    output logic [31:0]  s_axil_wdata,
    output logic [3:0]   s_axil_wstrb,
    output logic         s_axil_wvalid,
    input  logic         s_axil_wready,
    input  logic [1:0]   s_axil_bresp,
    input  logic         s_axil_bvalid,
    output logic         s_axil_bready,
    output logic [31:0]  s_axil_araddr,
    output logic [2:0]   s_axil_arprot,
    output logic         s_axil_arvalid,
    input  logic         s_axil_arready,
    input  logic [31:0]  s_axil_rdata,
    input  logic [1:0]   s_axil_rresp,
    input  logic         s_axil_rvalid,
    output logic         s_axil_rready
);
    localparam logic [31:0] MAGIC = 32'h4f54504a;

    // Status codes. 5 = malformed frame, 4 = unaligned address,
    // 7 = downstream error, 0x80 = timeout/quarantine.
    localparam logic [7:0] ST_OK = 8'd0, ST_ALIGN = 8'd4, ST_FRAME = 8'd5,
                           ST_DOWNSTREAM = 8'd7, ST_TIMEOUT = 8'h80;

    typedef enum logic [2:0] {
        IDLE, READ_REG, WRITE_REG, BLOCK_READ, BLOCK_WRITE, QUARANTINE
    } state_t;
    state_t state_q;

    logic [31:0] address_q, write_data_q;
    logic [511:0] line_q;
    logic [4:0] word_q;          // 0..15 for the 16 block words
    logic aw_sent_q, w_sent_q, ar_sent_q;
    logic [31:0] wait_q;

    wire [7:0] opcode = req[555:548];
    wire [31:0] frame_address = req[543:512];
    wire [3:0] frame_strobes = req[547:544];
    wire [511:0] frame_data = req[511:0];
    wire is_block = opcode == 8'd3 || opcode == 8'd4;

    assign req_ready = rst_n && state_q == IDLE && !fault;
    assign fault = state_q == QUARANTINE;

    assign s_axil_awvalid = rst_n && (state_q == WRITE_REG || state_q == BLOCK_WRITE)
                            && !aw_sent_q;
    assign s_axil_wvalid = rst_n && (state_q == WRITE_REG || state_q == BLOCK_WRITE)
                           && !w_sent_q;
    assign s_axil_awaddr = address_q;
    assign s_axil_wdata = is_block ? line_q[word_q*32 +: 32] : write_data_q;
    assign s_axil_wstrb = 4'hf;
    assign s_axil_awprot = 3'd0;
    assign s_axil_arvalid = rst_n && (state_q == READ_REG || state_q == BLOCK_READ)
                            && !ar_sent_q;
    assign s_axil_araddr = address_q;
    assign s_axil_arprot = 3'd0;
    assign s_axil_bready = rst_n && (state_q == WRITE_REG || state_q == BLOCK_WRITE);
    assign s_axil_rready = rst_n && (state_q == READ_REG || state_q == BLOCK_READ);

    task automatic respond(input logic [7:0] status, input logic [511:0] data);
        begin
            rsp_valid <= 1'b1;
            rsp_status <= status;
            rsp_data <= data;
            rsp_seq <= req[571:556];
        end
    endtask

    task automatic quarantine(input logic [7:0] status);
        begin
            respond(status, 512'b0);
            state_q <= QUARANTINE;
        end
    endtask

    initial begin
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "JTAG AXI adapter timeout must be positive");
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= IDLE;
            address_q <= 32'd0;
            write_data_q <= 32'd0;
            line_q <= 512'b0;
            word_q <= 5'd0;
            aw_sent_q <= 1'b0;
            w_sent_q <= 1'b0;
            ar_sent_q <= 1'b0;
            wait_q <= 32'd0;
            rsp_valid <= 1'b0;
            rsp_data <= 512'b0;
            rsp_status <= 8'd0;
            rsp_seq <= 16'd0;
        end else begin
            rsp_valid <= 1'b0;
            // Latch that a channel handshake completed, so a slave that
            // accepts AW and W in different cycles is handled correctly.
            if (s_axil_awvalid && s_axil_awready) aw_sent_q <= 1'b1;
            if (s_axil_wvalid && s_axil_wready) w_sent_q <= 1'b1;
            if (s_axil_arvalid && s_axil_arready) ar_sent_q <= 1'b1;

            case (state_q)
                IDLE: if (req_valid && req_ready) begin
                    wait_q <= 32'd0;
                    address_q <= frame_address;
                    write_data_q <= frame_data[31:0];
                    line_q <= frame_data;
                    word_q <= 5'd0;
                    aw_sent_q <= 1'b0; w_sent_q <= 1'b0; ar_sent_q <= 1'b0;

                    if (req[603:572] != MAGIC || opcode < 8'd1 || opcode > 8'd4)
                        respond(ST_FRAME, 512'b0);
                    else if (opcode == 8'd2 && frame_strobes != 4'hf)
                        respond(ST_FRAME, 512'b0);
                    else if (opcode == 8'd1 && frame_data != 512'b0)
                        respond(ST_FRAME, 512'b0);
                    else if ((opcode == 8'd3 || opcode == 8'd4) &&
                             frame_address[5:0] != 6'd0)
                        respond(ST_ALIGN, 512'b0);
                    else if ((opcode == 8'd1 || opcode == 8'd2) &&
                             frame_address[1:0] != 2'd0)
                        respond(ST_ALIGN, 512'b0);
                    else case (opcode)
                        8'd1: state_q <= READ_REG;
                        8'd2: state_q <= WRITE_REG;
                        8'd3: state_q <= BLOCK_READ;
                        8'd4: state_q <= BLOCK_WRITE;
                        default: state_q <= IDLE;
                    endcase
                end

                READ_REG: begin
                    if (s_axil_rvalid) begin
                        if (s_axil_rresp != 2'b00) quarantine(ST_DOWNSTREAM);
                        else begin
                            respond(ST_OK, {480'b0, s_axil_rdata});
                            state_q <= IDLE;
                        end
                    end else if (wait_q == TIMEOUT_CYCLES - 1)
                        quarantine(ST_TIMEOUT);
                    else wait_q <= wait_q + 1'b1;
                end

                WRITE_REG: begin
                    if (s_axil_bvalid) begin
                        if (s_axil_bresp != 2'b00) quarantine(ST_DOWNSTREAM);
                        else begin
                            respond(ST_OK, 512'b0);
                            state_q <= IDLE;
                        end
                    end else if (wait_q == TIMEOUT_CYCLES - 1)
                        quarantine(ST_TIMEOUT);
                    else wait_q <= wait_q + 1'b1;
                end

                BLOCK_READ: begin
                    if (s_axil_rvalid) begin
                        if (s_axil_rresp != 2'b00) quarantine(ST_DOWNSTREAM);
                        else begin
                            if (word_q == 5'd15) begin
                                // The final word still needs its data merged.
                                respond(ST_OK, {s_axil_rdata,
                                                line_q[479:0]});
                                state_q <= IDLE;
                            end else begin
                                line_q[word_q*32 +: 32] <= s_axil_rdata;
                                word_q <= word_q + 1'b1;
                                address_q <= address_q + 32'd4;
                                ar_sent_q <= 1'b0;
                                wait_q <= 32'd0;
                            end
                        end
                    end else if (wait_q == TIMEOUT_CYCLES - 1)
                        quarantine(ST_TIMEOUT);
                    else wait_q <= wait_q + 1'b1;
                end

                BLOCK_WRITE: begin
                    if (s_axil_bvalid) begin
                        if (s_axil_bresp != 2'b00) quarantine(ST_DOWNSTREAM);
                        else if (word_q == 5'd15) begin
                            respond(ST_OK, 512'b0);
                            state_q <= IDLE;
                        end else begin
                            word_q <= word_q + 1'b1;
                            address_q <= address_q + 32'd4;
                            aw_sent_q <= 1'b0;
                            w_sent_q <= 1'b0;
                            wait_q <= 32'd0;
                        end
                    end else if (wait_q == TIMEOUT_CYCLES - 1)
                        quarantine(ST_TIMEOUT);
                    else wait_q <= wait_q + 1'b1;
                end

                QUARANTINE: begin end
                default: quarantine(ST_DOWNSTREAM);
            endcase
        end
    end
endmodule
