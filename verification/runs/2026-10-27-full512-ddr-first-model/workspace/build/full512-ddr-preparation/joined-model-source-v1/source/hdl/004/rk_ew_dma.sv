// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Serial PC fetch/execute boundary. The first amount includes four tail QWORDs;
// encoded next amounts count only the following body. No command is rewritten.
module rk_ew_dma #(
    parameter int unsigned TIMEOUT_CYCLES = 65536,
    parameter int unsigned MAX_TASKS = 4095
) (
    input logic clk, rst_n,
    input logic start_valid,
    output logic start_ready,
    input logic [31:0] start_address, start_amount,
    output logic busy, done, task_done, error,
    output logic [31:0] completed_tasks,
    output logic [7:0] error_code,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic [15:0] mem_rsp_rdata,
    input logic mem_rsp_error
);
    typedef enum logic [2:0] {IDLE, CHECK, FETCH_REQ, FETCH_WAIT, SEND, RUN} state_t;
    state_t state;
    logic [31:0] address, amount, word_index, word_address, stalled_cycles;
    logic [1:0] part;
    logic [63:0] word_data;
    logic fault;
    logic [7:0] fault_code;
    logic cmd_ready, cmd_valid, cfg_valid, cfg_ready, reg_error, engine_error, engine_busy, engine_done;
    logic [7:0] reg_code, engine_code;
    logic [1:0] cfg_op;
    logic [16:0] cfg_count;
    logic [31:0] cfg_a, cfg_b, cfg_dst, next_address, next_amount;
    logic e_req_valid, e_req_write, e_rsp_ready;
    logic [31:0] e_req_addr;
    logic [15:0] e_req_wdata;
    logic framing_ok, is_tail_key, fetch_progress;
    logic [31:0] key, expected_key;
    logic [32:0] command_end;

    initial begin
        if (TIMEOUT_CYCLES == 0 || MAX_TASKS == 0 || MAX_TASKS > 4095)
            $fatal(1, "invalid PC DMA timeout/task limit");
    end
    assign error = fault || reg_error || engine_error;
    assign error_code = fault ? fault_code : reg_error ? reg_code : engine_code;
    assign start_ready = rst_n && state == IDLE && !error;
    assign busy = state != IDLE;
    assign command_end = {1'b0, address} + ({1'b0, amount} << 3);
    assign key = {word_data[63:48], word_data[15:0]};
    assign is_tail_key = key == 32'h01010010 || key == 32'h01010014 ||
                         key == 32'h00410000 || key == 32'h00810008;
    always_comb begin
        expected_key = 0;
        case (amount - word_index)
            4: expected_key = 32'h01010010;
            3: expected_key = 32'h01010014;
            2: expected_key = 32'h00410000;
            1: expected_key = 32'h00810008;
            default: begin end
        endcase
        framing_ok = expected_key == 0 ? !is_tail_key : key == expected_key;
    end
    assign cmd_valid = state == SEND && framing_ok && !error;
    assign fetch_progress = (state == FETCH_REQ && mem_req_ready) ||
                            (state == FETCH_WAIT && mem_rsp_valid);

    rk_ew_regs #(.PC_DMA(1)) regs (
        .clk(clk), .rst_n(rst_n), .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_data(word_data),
        .engine_busy(engine_busy), .engine_error(engine_error), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
        .cfg_op(cfg_op), .cfg_count(cfg_count), .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_dst(cfg_dst),
        .cfg_next_address(next_address), .cfg_next_amount(next_amount), .error(reg_error), .error_code(reg_code)
    );
    rk_ew_engine #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) engine (
        .clk(clk), .rst_n(rst_n), .cfg_valid(cfg_valid), .cfg_ready(cfg_ready),
        .cfg_op(cfg_op), .cfg_count(cfg_count), .cfg_a(cfg_a), .cfg_b(cfg_b), .cfg_dst(cfg_dst),
        .busy(engine_busy), .done(engine_done), .error(engine_error), .error_code(engine_code),
        .mem_req_valid(e_req_valid), .mem_req_ready(mem_req_ready && state == RUN && !error),
        .mem_req_write(e_req_write), .mem_req_addr(e_req_addr), .mem_req_wdata(e_req_wdata),
        .mem_rsp_valid(mem_rsp_valid && state == RUN && !error), .mem_rsp_ready(e_rsp_ready),
        .mem_rsp_rdata(mem_rsp_rdata), .mem_rsp_error(mem_rsp_error)
    );
    always_comb begin
        mem_req_valid = 0; mem_req_write = 0; mem_req_addr = 0; mem_req_wdata = 0; mem_rsp_ready = 0;
        if (!error) begin
            case (state)
                FETCH_REQ: begin
                    mem_req_valid = 1;
                    mem_req_addr = word_address + {29'b0, part, 1'b0};
                end
                FETCH_WAIT: mem_rsp_ready = 1;
                RUN: begin
                    mem_req_valid = e_req_valid; mem_req_write = e_req_write;
                    mem_req_addr = e_req_addr; mem_req_wdata = e_req_wdata; mem_rsp_ready = e_rsp_ready;
                end
                default: begin end
            endcase
        end
    end
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state <= IDLE; address <= 0; amount <= 0; word_index <= 0; word_address <= 0;
            part <= 0; word_data <= 0; stalled_cycles <= 0; fault <= 0; fault_code <= 0;
            done <= 0; task_done <= 0; completed_tasks <= 0;
        end else begin
            done <= 0; task_done <= 0;
            if ((state != FETCH_REQ && state != FETCH_WAIT) || fetch_progress) stalled_cycles <= 0;
            else stalled_cycles <= stalled_cycles + 1;
            if (error) state <= IDLE;
            else case (state)
                IDLE: if (start_valid && start_ready) begin
                    address <= start_address; amount <= start_amount; completed_tasks <= 0; state <= CHECK;
                end
                CHECK: begin
                    if ((|address[3:0]) || amount < 4 || amount > 65539 || command_end > 33'h100000000) begin
                        fault <= 1; fault_code <= 8'd7; state <= IDLE;
                    end else begin
                        word_address <= address; word_index <= 0; part <= 0; state <= FETCH_REQ;
                    end
                end
                FETCH_REQ: if (mem_req_ready) state <= FETCH_WAIT;
                FETCH_WAIT: if (mem_rsp_valid) begin
                    word_data[16*part +: 16] <= mem_rsp_rdata;
                    if (part == 3) state <= SEND;
                    else begin part <= part + 1; state <= FETCH_REQ; end
                end
                SEND: begin
                    if (!framing_ok) begin fault <= 1; fault_code <= 8'd3; state <= IDLE; end
                    else if (cmd_ready) begin
                        if (word_index == amount-1) state <= RUN;
                        else begin
                            word_index <= word_index + 1; word_address <= word_address + 8;
                            part <= 0; state <= FETCH_REQ;
                        end
                    end
                end
                RUN: if (engine_done) begin
                    completed_tasks <= completed_tasks + 1; task_done <= 1;
                    if (next_amount == 0) begin done <= 1; state <= IDLE; end
                    else if (completed_tasks >= MAX_TASKS-1) begin
                        fault <= 1; fault_code <= 8'd7; state <= IDLE;
                    end else begin address <= next_address; amount <= next_amount + 4; state <= CHECK; end
                end
                default: begin fault <= 1; fault_code <= 8'd7; state <= IDLE; end
            endcase
            if (!error && state == FETCH_WAIT && mem_rsp_valid && mem_rsp_error) begin
                fault <= 1; fault_code <= 8'd5; state <= IDLE;
            end else if (!error && (state == FETCH_REQ || state == FETCH_WAIT) && !fetch_progress &&
                         stalled_cycles >= TIMEOUT_CYCLES-1) begin
                fault <= 1; fault_code <= 8'd8; state <= IDLE;
            end
        end
    end
endmodule
