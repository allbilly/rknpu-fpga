// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// SYS-clock backend for the unchanged OpenTPU USER2 mailbox framing.
// One owner/one request at a time. Fault recovery is a JOINT domain reset.
module rk_jtag_backend #(
    parameter int unsigned BYTES = 1048576,
    parameter logic [31:0] BASE = 32'h10000000,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input logic clk, rst_n,
    input logic req_valid,
    output logic req_ready,
    input logic [603:0] req,
    output logic rsp_valid,
    output logic [511:0] rsp_data,
    output logic [7:0] rsp_status,
    output logic [15:0] rsp_seq,
    output logic fault, memory_busy,
    input logic memory_available,
    output logic [31:0] s_axil_awaddr,
    output logic [2:0] s_axil_awprot,
    output logic s_axil_awvalid,
    input logic s_axil_awready,
    output logic [31:0] s_axil_wdata,
    output logic [3:0] s_axil_wstrb,
    output logic s_axil_wvalid,
    input logic s_axil_wready,
    input logic [1:0] s_axil_bresp,
    input logic s_axil_bvalid,
    output logic s_axil_bready,
    output logic [31:0] s_axil_araddr,
    output logic [2:0] s_axil_arprot,
    output logic s_axil_arvalid,
    input logic s_axil_arready,
    input logic [31:0] s_axil_rdata,
    input logic [1:0] s_axil_rresp,
    input logic s_axil_rvalid,
    output logic s_axil_rready,
    output logic host_valid,
    input logic host_ready,
    output logic host_write,
    output logic [31:0] host_addr,
    output logic [15:0] host_wdata,
    input logic host_rsp_valid,
    output logic host_rsp_ready,
    input logic [15:0] host_rdata,
    input logic host_error
);
    typedef enum logic [2:0] {IDLE, WRITE_REG, READ_REG, MEM_REQ, MEM_RSP, QUARANTINE} state_t;
    state_t state;
    logic aw_pending, w_pending, ar_pending, mem_pending;
    logic aw_sent, w_sent, ar_sent;
    logic [31:0] wait_cycles;
    logic [4:0] word_index;
    logic [511:0] line_data;
    wire [7:0] opcode = req[555:548];
    wire [31:0] address = req[543:512];
    wire [32:0] end_address = {1'b0,address} + 33'd64;

    initial begin
        if (BYTES < 64 || (BYTES & (BYTES-1)) != 0 || BASE[5:0] != 0 ||
            ({1'b0,BASE} + 33'(BYTES)) > 33'h080000000 || TIMEOUT_CYCLES == 0)
            $fatal(1,"JTAG BRAM needs aligned power-of-two capacity in the 31-bit range and positive timeout");
    end
    assign req_ready = rst_n && state == IDLE && !fault;
    assign memory_busy = state == MEM_REQ || state == MEM_RSP || fault;
    assign s_axil_awprot = 0;
    assign s_axil_arprot = 0;
    assign s_axil_awvalid = rst_n && aw_pending;
    assign s_axil_wvalid = rst_n && w_pending;
    assign s_axil_arvalid = rst_n && ar_pending;
    assign s_axil_bready = rst_n && (state == WRITE_REG || fault);
    assign s_axil_rready = rst_n && (state == READ_REG || fault);
    assign host_valid = rst_n && mem_pending;
    assign host_rsp_ready = rst_n && (state == MEM_RSP || fault);
    assign host_wdata = line_data[16*word_index +: 16];

    task automatic finish(input logic [7:0] status, input logic [511:0] data);
        rsp_valid <= 1;
        rsp_status <= status;
        rsp_data <= data;
        state <= IDLE;
        wait_cycles <= 0;
    endtask
    task automatic quarantine(input logic [7:0] status);
        finish(status,512'b0);
        fault <= 1;
        state <= QUARANTINE;
        // Keep asserted requests stable until accepted; late responses drain.
        // Only a joint reset may discard a downstream transaction.
    endtask

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state <= IDLE; fault <= 0; rsp_valid <= 0; rsp_data <= 0;
            rsp_status <= 0; rsp_seq <= 0; wait_cycles <= 0;
            aw_pending <= 0; w_pending <= 0; ar_pending <= 0; mem_pending <= 0;
            aw_sent <= 0; w_sent <= 0; ar_sent <= 0;
            s_axil_awaddr <= 0; s_axil_wdata <= 0; s_axil_wstrb <= 0; s_axil_araddr <= 0;
            host_addr <= 0; host_write <= 0; line_data <= 0; word_index <= 0;
        end else begin
            rsp_valid <= 0;
            if (s_axil_awvalid && s_axil_awready) begin aw_pending <= 0; aw_sent <= 1; end
            if (s_axil_wvalid && s_axil_wready) begin w_pending <= 0; w_sent <= 1; end
            if (s_axil_arvalid && s_axil_arready) begin ar_pending <= 0; ar_sent <= 1; end
            if (host_valid && host_ready) mem_pending <= 0;
            case (state)
                IDLE: if (req_valid && req_ready) begin
                    rsp_seq <= req[571:556];
                    wait_cycles <= 0; aw_sent <= 0; w_sent <= 0; ar_sent <= 0;
                    if (req[603:572] != 32'h4f54504a || opcode < 1 || opcode > 4)
                        finish(8'd5,512'b0);
                    else if (((opcode == 1 || opcode == 3) && req[511:0] != 0) ||
                             (opcode == 2 && req[511:32] != 0) ||
                             (opcode != 2 && req[547:544] != 4'hf))
                        finish(8'd5,512'b0);
                    else if ((opcode <= 2 && address[1:0] != 0) ||
                             (opcode >= 3 && address[5:0] != 0))
                        finish(8'd4,512'b0);
                    else if (opcode >= 3 && (address < BASE ||
                             end_address > ({1'b0,BASE}+33'(BYTES))))
                        finish(8'd6,512'b0);
                    else case (opcode)
                        1: begin
                            s_axil_araddr <= address; ar_pending <= 1; state <= READ_REG;
                        end
                        2: begin
                            s_axil_awaddr <= address; s_axil_wdata <= req[31:0];
                            s_axil_wstrb <= req[547:544];
                            aw_pending <= 1; w_pending <= 1; state <= WRITE_REG;
                        end
                        3,4: if (!memory_available) finish(8'd2,512'b0);
                             else begin
                                 line_data <= req[511:0]; word_index <= 0;
                                 host_addr <= address; host_write <= opcode == 4;
                                 mem_pending <= 1; state <= MEM_REQ;
                             end
                        default: finish(8'd5,512'b0);
                    endcase
                end
                WRITE_REG: begin
                    if (s_axil_bvalid) begin
                        if (!aw_sent || !w_sent || s_axil_bresp == 1)
                            quarantine(8'd7);
                        else finish({6'b0,s_axil_bresp},512'b0);
                    end else if ((s_axil_awvalid && s_axil_awready) || (s_axil_wvalid && s_axil_wready))
                        wait_cycles <= 0;
                    else if (wait_cycles == TIMEOUT_CYCLES-1) quarantine(8'h80);
                    else wait_cycles <= wait_cycles+1'b1;
                end
                READ_REG: begin
                    if (s_axil_rvalid) begin
                        if (!ar_sent || s_axil_rresp == 1)
                            quarantine(8'd7);
                        else finish({6'b0,s_axil_rresp},s_axil_rresp == 0 ? {480'b0,s_axil_rdata} : 512'b0);
                    end else if (s_axil_arvalid && s_axil_arready) wait_cycles <= 0;
                    else if (wait_cycles == TIMEOUT_CYCLES-1) quarantine(8'h80);
                    else wait_cycles <= wait_cycles+1'b1;
                end
                MEM_REQ: begin
                    if (host_valid && host_ready) begin state <= MEM_RSP; wait_cycles <= 0; end
                    else if (wait_cycles == TIMEOUT_CYCLES-1) quarantine(8'h80);
                    else wait_cycles <= wait_cycles+1'b1;
                end
                MEM_RSP: begin
                    if (host_rsp_valid) begin
                        if (host_error) finish(8'd2,512'b0);
                        else if (word_index == 31)
                            finish(0,host_write ? 512'b0 : {host_rdata,line_data[495:0]});
                        else begin
                            if (!host_write) line_data[16*word_index +: 16] <= host_rdata;
                            word_index <= word_index+1'b1; host_addr <= host_addr+2;
                            mem_pending <= 1; state <= MEM_REQ; wait_cycles <= 0;
                        end
                    end else if (wait_cycles == TIMEOUT_CYCLES-1) quarantine(8'h80);
                    else wait_cycles <= wait_cycles+1'b1;
                end
                QUARANTINE: begin end
                default: quarantine(8'd7);
            endcase
        end
    end
endmodule
