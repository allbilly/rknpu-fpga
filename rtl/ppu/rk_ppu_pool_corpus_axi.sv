// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Host-drivable AXI-Lite page for ONE frozen pooling-corpus fixture.
//
// The command stream is the captured raw PPU stream, unchanged: the page only
// fetches the 26/28 QWORDs the host asked for, hands them to the generated
// strict case gate (`rk_ppu_pool_corpus_case`, generated from the frozen
// fixtures), then streams the fixture's captured input atoms through the
// selected captured pooling leaf and writes the captured output atoms back.
// There is no command rewrite, no CPU arithmetic and no runtime layout repair.
//
// The page keeps the transport ABI of `rk_ppu_pool_axi` (DEVICE_ID, ABI_VERSION,
// STATUS, COMMAND, START_ADDRESS/AMOUNT, JOB_TAG, RESULT_*) and adds two
// read-only identity registers so a host can bind the page to its fixture
// without trusting the address alone:
//
//   0x28  FIXTURE_INDEX   RO  corpus page id (also the page order)
//   0x2c  FIXTURE_CRC32   RO  CRC32 of the frozen fixture name
//
// The atom-stream interface is common to every pooling leaf in rtl/ppu, which
// is why one generic DMA can replay all nineteen cases.
module rk_ppu_pool_corpus_dma #(
    parameter int unsigned CASE = 0,
    parameter logic [31:0] BASE = 32'h00000000,
    parameter logic [32:0] BYTES = 33'd32768,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        start_valid,
    output logic        start_ready,
    input  logic [31:0] start_address,
    input  logic [31:0] start_amount,
    output logic        quiescent,
    output logic        idle_quiet,
    output logic        busy,
    output logic        done,
    output logic        error,
    output logic [7:0]  error_code,
    input  logic        result_ready,
    // Elaboration constants the page publishes as read-only registers.
    output logic [31:0] device_id,
    output logic [31:0] fixture_crc32,
    output logic [4:0]  fixture_index,
    // Serialized 16-bit memory port.
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
    localparam logic [32:0] APERTURE_END = {1'b0, BASE} + BYTES;
    localparam int unsigned MAX_QWORDS = 28;

    typedef enum logic [3:0] {
        ST_IDLE,
        ST_COMMAND_REQUEST, ST_COMMAND_RESPONSE,
        ST_GATE, ST_PROFILE,
        ST_RUN, ST_IN_REQUEST, ST_IN_RESPONSE, ST_IN_SEND,
        ST_OUT_REQUEST, ST_OUT_RESPONSE,
        ST_FINISH, ST_FAILED
    } state_t;
    state_t state_q;

    // Generated per-case gate + captured leaf.
    logic        case_cmd_valid, case_cmd_ready, case_cmd_last;
    logic [63:0] case_cmd_data;
    logic        profile_valid, profile_error;
    logic [7:0]  profile_code;
    logic [31:0] profile_src_base, profile_dst_base;
    logic [5:0]  case_qwords;
    logic [4:0]  case_in_atoms, case_out_atoms, case_index_atom;
    logic        case_index_en;
    logic [31:0] case_index_offset;
    logic        gate_rst_n, leaf_rst_n;
    logic        leaf_in_valid, leaf_in_ready;
    logic [127:0] leaf_in_atom;
    logic        leaf_out_valid, leaf_out_ready, leaf_out_last;
    logic [127:0] leaf_out_atom;

    rk_ppu_pool_corpus_case #(.CASE(CASE)) corpus (
        .clk,
        .gate_rst_n(gate_rst_n), .leaf_rst_n(leaf_rst_n),
        .cmd_valid(case_cmd_valid), .cmd_ready(case_cmd_ready),
        .cmd_data(case_cmd_data), .cmd_last(case_cmd_last),
        .profile_valid, .profile_error, .profile_code,
        .rdma_src_base(profile_src_base), .ppu_dst_base(profile_dst_base),
        .cmd_qwords(case_qwords), .in_atoms(case_in_atoms),
        .out_atoms(case_out_atoms), .index_en(case_index_en),
        .index_atom(case_index_atom), .index_offset(case_index_offset),
        .device_id, .fixture_crc32, .fixture_index,
        .leaf_in_valid, .leaf_in_ready, .leaf_in_atom,
        .leaf_out_valid, .leaf_out_ready, .leaf_out_atom, .leaf_out_last);

    // Command stream buffer: the full unchanged stream is fetched before the
    // strict gate is released, exactly like the existing raw engines.
    logic [63:0] command_qword [0:MAX_QWORDS-1];
    logic [47:0] fetch_word_lo_q;
    logic [5:0]  fetch_qword_q;
    logic [1:0]  fetch_halfword_q;
    logic [5:0]  gate_qword_q;
    logic [31:0] command_base_q;
    logic [32:0] command_end_q;
    logic [31:0] src_base_q, dst_base_q;

    logic [4:0]  in_atom_q, out_atom_q_done;
    logic [2:0]  in_halfword_q, out_halfword_q;
    logic [127:0] input_atom_q, output_atom_q;
    logic        in_pending_q, out_pending_q;
    logic        gate_rst_n_q, leaf_rst_n_q;

    logic request_pending_q, outstanding_q;
    logic mem_req_write_q;
    logic [31:0] mem_req_addr_q;
    logic [15:0] mem_req_wdata_q;
    logic [31:0] wait_cycles_q;
    logic [7:0]  error_code_q;
    logic        protocol_fault_q;
    logic [7:0]  protocol_code_q;

    wire request_fire = request_pending_q && mem_req_ready;
    wire response_fire = outstanding_q && mem_rsp_valid && mem_rsp_ready;
    wire waiting_memory = state_q == ST_COMMAND_RESPONSE ||
                          state_q == ST_IN_RESPONSE ||
                          state_q == ST_OUT_RESPONSE;

    logic bad_status, bad_read_data;
    always @* begin
        bad_status = mem_rsp_error;
        bad_read_data = 1'b0;
`ifndef SYNTHESIS
        if (mem_rsp_error !== 1'b0) bad_status = 1'b1;
        if ((^mem_rsp_rdata) === 1'bx) bad_read_data = 1'b1;
`endif
    end

    initial begin
        if (BYTES == 0 || APERTURE_END > 33'h100000000)
            $fatal(1, "invalid pooling corpus aperture");
        if (TIMEOUT_CYCLES == 0)
            $fatal(1, "pooling corpus timeout must be positive");
    end

    // ---- child resets -----------------------------------------------------
    // The command gate is released only once the complete stream is buffered;
    // the leaf is released only after the published operand windows have been
    // proven. A fault holds both in reset.
    assign gate_rst_n = rst_n && gate_rst_n_q && state_q != ST_FAILED;
    assign leaf_rst_n = rst_n && leaf_rst_n_q && state_q != ST_FAILED;

    // ---- command gate drive ----------------------------------------------
    assign case_cmd_valid = rst_n && state_q == ST_GATE && !profile_error;
    assign case_cmd_data = command_qword[gate_qword_q];
    assign case_cmd_last = gate_qword_q == 6'(case_qwords - 1);

    // ---- captured leaf atom stream ---------------------------------------
    assign leaf_in_valid = rst_n && state_q == ST_IN_SEND;
    assign leaf_in_atom = input_atom_q;
    assign leaf_out_ready = rst_n && !out_pending_q &&
                            state_q != ST_IDLE && state_q != ST_FAILED &&
                            state_q != ST_FINISH;

    // ---- serialized memory master ----------------------------------------
    assign mem_req_valid = rst_n && request_pending_q && state_q != ST_FAILED;
    assign mem_req_write = mem_req_write_q;
    assign mem_req_addr = mem_req_addr_q;
    assign mem_req_wdata = mem_req_wdata_q;
    assign mem_rsp_ready = rst_n && waiting_memory;

    // ---- control/status ---------------------------------------------------
    assign error = rst_n && state_q == ST_FAILED;
    assign error_code = !rst_n ? 8'd0 : error ? error_code_q : 8'd0;
    assign start_ready = rst_n && state_q == ST_IDLE && !waiting_memory;
    assign idle_quiet = state_q == ST_IDLE && !waiting_memory;
    assign quiescent = idle_quiet && !start_valid;
    assign done = rst_n && state_q == ST_FINISH && result_ready;
    assign busy = rst_n && state_q != ST_IDLE && state_q != ST_FINISH &&
                  state_q != ST_FAILED;

    function automatic logic in_aperture(
        input logic [31:0] address,
        input logic [32:0] exclusive_end
    );
        in_aperture = ({1'b0, address} >= {1'b0, BASE}) &&
                      (exclusive_end <= APERTURE_END) &&
                      (exclusive_end > {1'b0, address});
    endfunction

    function automatic logic ranges_overlap(
        input logic [31:0] a_base,
        input logic [32:0] a_end,
        input logic [31:0] b_base,
        input logic [32:0] b_end
    );
        ranges_overlap = ({1'b0, a_base} < b_end) && ({1'b0, b_base} < a_end);
    endfunction

    // Byte offset of one output atom inside the fixture's output BO. The PPU
    // stores the value surface first and the optional uint16 index surface at
    // the captured `index_offset` (16-byte aligned; the generated constants
    // prove the placement for the fixture).
    function automatic logic [31:0] output_atom_offset(input logic [4:0] atom);
        begin
            if (case_index_en && (atom >= case_index_atom))
                output_atom_offset = case_index_offset +
                    ((32'(atom) - 32'(case_index_atom)) << 4);
            else
                output_atom_offset = 32'(atom) << 4;
        end
    endfunction

    function automatic logic [32:0] output_span(input logic [4:0] atoms);
        begin
            output_span = 33'({1'b0, output_atom_offset(5'(atoms - 1'b1))} +
                              32'd16);
        end
    endfunction

    task automatic fail(input logic [7:0] code);
        begin
            state_q <= ST_FAILED;
            error_code_q <= code;
        end
    endtask

    task automatic issue_request(
        input logic is_write,
        input logic [31:0] address,
        input logic [15:0] write_data
    );
        begin
            request_pending_q <= 1'b1;
            mem_req_write_q <= is_write;
            mem_req_addr_q <= address;
            mem_req_wdata_q <= write_data;
        end
    endtask

    // Synchronous reset: rst_n is already a synchronized deassertion.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            command_base_q <= 32'd0;
            command_end_q <= 33'd0;
            fetch_qword_q <= 6'd0;
            fetch_halfword_q <= 2'd0;
            fetch_word_lo_q <= 48'd0;
            gate_qword_q <= 6'd0;
            src_base_q <= 32'd0;
            dst_base_q <= 32'd0;
            in_atom_q <= 5'd0;
            out_atom_q_done <= 5'd0;
            in_halfword_q <= 3'd0;
            out_halfword_q <= 3'd0;
            input_atom_q <= 128'd0;
            output_atom_q <= 128'd0;
            in_pending_q <= 1'b0;
            out_pending_q <= 1'b0;
            gate_rst_n_q <= 1'b0;
            leaf_rst_n_q <= 1'b0;
            request_pending_q <= 1'b0;
            outstanding_q <= 1'b0;
            mem_req_write_q <= 1'b0;
            mem_req_addr_q <= 32'd0;
            mem_req_wdata_q <= 16'd0;
            wait_cycles_q <= 32'd0;
            error_code_q <= 8'd0;
        end else if (state_q != ST_FAILED) begin
            if (request_fire) begin
                request_pending_q <= 1'b0;
                outstanding_q <= 1'b1;
            end
            if (response_fire) outstanding_q <= 1'b0;

            // A pending leaf result is captured whichever memory state the DMA
            // is in; out_ready is lowered until it has been written out, so no
            // result is duplicated or overwritten.
            if (leaf_out_valid && leaf_out_ready) begin
                if (out_atom_q_done == case_out_atoms) begin
                    state_q <= ST_FAILED;
                    error_code_q <= 8'd6;
                end else begin
                    output_atom_q <= leaf_out_atom;
                    out_pending_q <= 1'b1;
                    if (leaf_out_last !==
                        (out_atom_q_done == 5'(case_out_atoms - 1'b1))) begin
                        state_q <= ST_FAILED;
                        error_code_q <= 8'd6;
                    end
                end
            end

            if (mem_rsp_valid && !outstanding_q) begin
                fail(8'd7);
            end else if (response_fire && bad_status) begin
                fail(8'd5);
            end else if (response_fire && bad_read_data &&
                         state_q != ST_OUT_RESPONSE) begin
                fail(8'd6);
            end else if (waiting_memory && !request_fire && !response_fire &&
                         wait_cycles_q >= TIMEOUT_CYCLES - 1) begin
                fail(8'd8);
            end else begin
                if (!waiting_memory || request_fire || response_fire)
                    wait_cycles_q <= 32'd0;
                else
                    wait_cycles_q <= wait_cycles_q + 1'b1;

                case (state_q)
                    ST_IDLE: if (start_valid && start_ready) begin
                        gate_rst_n_q <= 1'b0;
                        leaf_rst_n_q <= 1'b0;
                        if (start_amount != {26'd0, case_qwords}) begin
                            fail(8'd1);
                        end else if (start_address[2:0] != 3'b000 ||
                                     !in_aperture(start_address,
                                                  {1'b0, start_address} +
                                                  {26'd0, case_qwords} * 33'd8)) begin
                            fail(8'd3);
                        end else if ((case_qwords < 6'd26) ||
                                     (case_qwords > 6'(MAX_QWORDS))) begin
                            fail(8'd1);
                        end else begin
                            command_base_q <= start_address;
                            command_end_q <= {1'b0, start_address} +
                                             {26'd0, case_qwords} * 33'd8;
                            fetch_qword_q <= 6'd0;
                            fetch_halfword_q <= 2'd0;
                            gate_qword_q <= 6'd0;
                            in_atom_q <= 5'd0;
                            out_atom_q_done <= 5'd0;
                            in_halfword_q <= 3'd0;
                            out_halfword_q <= 3'd0;
                            in_pending_q <= 1'b0;
                            out_pending_q <= 1'b0;
                            state_q <= ST_COMMAND_REQUEST;
                        end
                    end

                    ST_COMMAND_REQUEST: begin
                        issue_request(1'b0,
                            command_base_q +
                                32'(fetch_qword_q) * 32'd8 +
                                32'(fetch_halfword_q) * 32'd2,
                            16'd0);
                        state_q <= ST_COMMAND_RESPONSE;
                    end

                    ST_COMMAND_RESPONSE: if (response_fire) begin
                        if (fetch_halfword_q == 2'd3) begin
                            command_qword[fetch_qword_q] <=
                                {mem_rsp_rdata, fetch_word_lo_q};
                            if (fetch_qword_q == 6'(case_qwords - 1)) begin
                                gate_rst_n_q <= 1'b1;
                                gate_qword_q <= 6'd0;
                                state_q <= ST_GATE;
                            end else begin
                                fetch_qword_q <= fetch_qword_q + 1'b1;
                                fetch_halfword_q <= 2'd0;
                                state_q <= ST_COMMAND_REQUEST;
                            end
                        end else begin
                            fetch_word_lo_q[16*fetch_halfword_q +: 16] <=
                                mem_rsp_rdata;
                            fetch_halfword_q <= fetch_halfword_q + 1'b1;
                            state_q <= ST_COMMAND_REQUEST;
                        end
                    end

                    ST_GATE: begin
                        if (profile_error) begin
                            fail(profile_code);
                        end else if (case_cmd_ready) begin
                            if (gate_qword_q == 6'(case_qwords - 1)) begin
                                state_q <= ST_PROFILE;
                            end else begin
                                gate_qword_q <= gate_qword_q + 1'b1;
                            end
                        end
                    end

                    ST_PROFILE: begin
                        if (profile_error) begin
                            fail(profile_code);
                        end else if (profile_valid) begin
                            src_base_q <= profile_src_base;
                            dst_base_q <= profile_dst_base;
                            if (profile_src_base[3:0] != 4'd0 ||
                                profile_dst_base[3:0] != 4'd0 ||
                                !in_aperture(profile_src_base,
                                    {1'b0, profile_src_base} +
                                    {26'd0, case_in_atoms} * 33'd16) ||
                                !in_aperture(profile_dst_base,
                                    {1'b0, profile_dst_base} +
                                    output_span(case_out_atoms)) ||
                                ranges_overlap(command_base_q, command_end_q,
                                               profile_src_base,
                                               {1'b0, profile_src_base} +
                                               {26'd0, case_in_atoms} * 33'd16) ||
                                ranges_overlap(command_base_q, command_end_q,
                                               profile_dst_base,
                                               {1'b0, profile_dst_base} +
                                               output_span(case_out_atoms)) ||
                                ranges_overlap(profile_src_base,
                                               {1'b0, profile_src_base} +
                                               {26'd0, case_in_atoms} * 33'd16,
                                               profile_dst_base,
                                               {1'b0, profile_dst_base} +
                                               output_span(case_out_atoms))) begin
                                fail(8'd3);
                            end else begin
                                leaf_rst_n_q <= 1'b1;
                                in_halfword_q <= 3'd0;
                                state_q <= ST_RUN;
                            end
                        end
                    end

                    ST_RUN: begin
                        if (out_pending_q) begin
                            out_halfword_q <= 3'd0;
                            state_q <= ST_OUT_REQUEST;
                        end else if (in_pending_q) begin
                            state_q <= ST_IN_SEND;
                        end else if (in_atom_q < case_in_atoms) begin
                            in_halfword_q <= 3'd0;
                            state_q <= ST_IN_REQUEST;
                        end else if (out_atom_q_done == case_out_atoms) begin
                            state_q <= ST_FINISH;
                        end
                    end

                    ST_IN_REQUEST: begin
                        issue_request(1'b0,
                            src_base_q + (32'(in_atom_q) << 4) +
                                (32'(in_halfword_q) << 1),
                            16'd0);
                        state_q <= ST_IN_RESPONSE;
                    end

                    ST_IN_RESPONSE: if (response_fire) begin
                        input_atom_q[16*in_halfword_q +: 16] <= mem_rsp_rdata;
                        if (in_halfword_q == 3'd7) begin
                            in_pending_q <= 1'b1;
                            state_q <= ST_RUN;
                        end else begin
                            in_halfword_q <= in_halfword_q + 1'b1;
                            state_q <= ST_IN_REQUEST;
                        end
                    end

                    ST_IN_SEND: begin
                        // A leaf that is still busy while it holds an output
                        // result gets the result drained first; the atom stays
                        // pending and is sent afterwards.
                        if (leaf_in_ready) begin
                            in_atom_q <= in_atom_q + 1'b1;
                            in_pending_q <= 1'b0;
                            state_q <= ST_RUN;
                        end else if (out_pending_q) begin
                            state_q <= ST_RUN;
                        end
                    end

                    ST_OUT_REQUEST: begin
                        issue_request(1'b1,
                            dst_base_q + output_atom_offset(out_atom_q_done) +
                                (32'(out_halfword_q) << 1),
                            output_atom_q[16*out_halfword_q +: 16]);
                        state_q <= ST_OUT_RESPONSE;
                    end

                    ST_OUT_RESPONSE: if (response_fire) begin
                        if (out_halfword_q == 3'd7) begin
                            out_atom_q_done <= out_atom_q_done + 1'b1;
                            out_pending_q <= 1'b0;
                            state_q <= ST_RUN;
                        end else begin
                            out_halfword_q <= out_halfword_q + 1'b1;
                            state_q <= ST_OUT_REQUEST;
                        end
                    end

                    ST_FINISH: if (result_ready) begin
                        gate_rst_n_q <= 1'b0;
                        leaf_rst_n_q <= 1'b0;
                        state_q <= ST_IDLE;
                    end

                    default: fail(8'd7);
                endcase
            end
        end
    end
endmodule

// ---------------------------------------------------------------------------
// One AXI4-Lite page per frozen pooling fixture: the transport/ABI half.
module rk_ppu_pool_corpus_axi #(
    parameter int unsigned CASE = 0,
    parameter logic [31:0] BASE = 32'h00000000,
    parameter logic [32:0] BYTES = 33'd32768,
    parameter int unsigned TIMEOUT_CYCLES = 65536
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        memory_ready,
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
    output logic        irq,
    output logic        busy,
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
    logic have_aw, have_w, bvalid, rvalid;
    logic [31:0] write_address, write_data;
    logic [2:0]  write_prot;
    logic [3:0]  write_strobe;
    logic [31:0] command_address, command_amount, job_tag;
    logic [2:0]  fields_valid;
    logic        launch_pending, active, result_valid, result_error;
    logic [31:0] result_tag, result_tasks;
    logic [7:0]  result_code;
    logic        writable, can_submit, engine_busy, engine_error;
    logic [31:0] status_word;
    logic        engine_start_valid, engine_start_ready, engine_done;
    logic [7:0]  engine_error_code;
    logic [31:0] device_id, fixture_crc32;
    logic [4:0]  fixture_index;

    assign writable = !active && !launch_pending && !result_valid &&
                      !engine_error && !engine_busy;
    assign can_submit = writable && (&fields_valid) && memory_ready &&
                        engine_start_ready;
    assign status_word = {21'b0, fields_valid, 1'b0, engine_busy, engine_error,
                          memory_ready, result_error, result_valid, active,
                          can_submit};
    assign engine_start_valid = rst_n && launch_pending;
    assign irq = rst_n && result_valid;
    assign busy = rst_n && (active || launch_pending);
    assign s_axil_awready = rst_n && !have_aw && !bvalid;
    assign s_axil_wready = rst_n && !have_w && !bvalid;
    assign s_axil_arready = rst_n && !rvalid;
    assign s_axil_bvalid = rst_n && bvalid;
    assign s_axil_rvalid = rst_n && rvalid;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            have_aw <= 1'b0; have_w <= 1'b0; bvalid <= 1'b0; rvalid <= 1'b0;
            write_address <= 32'd0; write_data <= 32'd0;
            write_prot <= 3'd0; write_strobe <= 4'd0;
            s_axil_bresp <= 2'd0; s_axil_rresp <= 2'd0;
            s_axil_rdata <= 32'd0;
            command_address <= 32'd0; command_amount <= 32'd0;
            job_tag <= 32'd0;
            fields_valid <= 3'd0;
            launch_pending <= 1'b0; active <= 1'b0;
            result_valid <= 1'b0; result_error <= 1'b0;
            result_tag <= 32'd0; result_tasks <= 32'd0;
            result_code <= 8'd0;
        end else begin
            if (s_axil_bvalid && s_axil_bready) bvalid <= 1'b0;
            if (s_axil_rvalid && s_axil_rready) rvalid <= 1'b0;

            if (s_axil_awvalid && s_axil_awready) begin
                have_aw <= 1'b1;
                write_address <= s_axil_awaddr;
                write_prot <= s_axil_awprot;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                have_w <= 1'b1;
                write_data <= s_axil_wdata;
                write_strobe <= s_axil_wstrb;
            end

            if (have_aw && have_w && !bvalid) begin
                have_aw <= 1'b0; have_w <= 1'b0; bvalid <= 1'b1;
                s_axil_bresp <= 2'b00;
                if (write_prot != 3'd0 || write_strobe != 4'hf)
                    s_axil_bresp <= 2'b10;
                else case (write_address)
                    32'h0c: begin
                        if (write_data == 32'd1 && can_submit) begin
                            active <= 1'b1; launch_pending <= 1'b1;
                            result_tag <= 32'd0; result_tasks <= 32'd0;
                            result_code <= 8'd0; result_error <= 1'b0;
                        end else if (write_data == 32'd2 && result_valid &&
                                     !result_error && !active && !engine_error &&
                                     !engine_busy) begin
                            result_valid <= 1'b0; fields_valid <= 3'd0;
                            command_address <= 32'd0;
                            command_amount <= 32'd0; job_tag <= 32'd0;
                        end else s_axil_bresp <= 2'b10;
                    end
                    32'h10: if (writable) begin
                        command_address <= write_data; fields_valid[0] <= 1'b1;
                    end else s_axil_bresp <= 2'b10;
                    32'h14: if (writable) begin
                        command_amount <= write_data; fields_valid[1] <= 1'b1;
                    end else s_axil_bresp <= 2'b10;
                    32'h18: if (writable) begin
                        job_tag <= write_data; fields_valid[2] <= 1'b1;
                    end else s_axil_bresp <= 2'b10;
                    // Read-only: explicit SLVERR, never a silent accept. The new
                    // identity registers are read-only as well.
                    32'h00, 32'h04, 32'h08, 32'h1c, 32'h20, 32'h24,
                    32'h28, 32'h2c: s_axil_bresp <= 2'b10;
                    default: s_axil_bresp <= 2'b11;
                endcase
            end

            if (s_axil_arvalid && s_axil_arready) begin
                rvalid <= 1'b1; s_axil_rresp <= 2'b00; s_axil_rdata <= 32'd0;
                if (s_axil_arprot != 3'd0) s_axil_rresp <= 2'b10;
                else case (s_axil_araddr)
                    32'h00: s_axil_rdata <= device_id;
                    32'h04: s_axil_rdata <= 32'h00010000;
                    32'h08: s_axil_rdata <= status_word;
                    32'h0c: s_axil_rresp <= 2'b10;
                    32'h10: s_axil_rdata <= command_address;
                    32'h14: s_axil_rdata <= command_amount;
                    32'h18: s_axil_rdata <= job_tag;
                    32'h1c: s_axil_rdata <= result_tag;
                    32'h20: s_axil_rdata <= result_tasks;
                    32'h24: s_axil_rdata <= {24'd0, result_code};
                    32'h28: s_axil_rdata <= {27'd0, fixture_index};
                    32'h2c: s_axil_rdata <= fixture_crc32;
                    default: s_axil_rresp <= 2'b11;
                endcase
            end

            if (engine_start_valid && engine_start_ready)
                launch_pending <= 1'b0;
            if (active && !launch_pending && (engine_error || engine_done)) begin
                active <= 1'b0; result_valid <= 1'b1;
                result_error <= engine_error;
                result_tag <= job_tag;
                result_tasks <= engine_error ? 32'd0 : 32'd1;
                result_code <= engine_error ? engine_error_code : 8'd0;
            end
        end
    end

    rk_ppu_pool_corpus_dma #(
        .CASE(CASE), .BASE(BASE), .BYTES(BYTES),
        .TIMEOUT_CYCLES(TIMEOUT_CYCLES)
    ) engine (
        .clk, .rst_n,
        .start_valid(engine_start_valid), .start_ready(engine_start_ready),
        .start_address(command_address), .start_amount(command_amount),
        .quiescent(), .idle_quiet(),
        .busy(engine_busy), .done(engine_done),
        .error(engine_error), .error_code(engine_error_code),
        .result_ready(1'b1),
        .device_id, .fixture_crc32, .fixture_index,
        .mem_req_valid, .mem_req_ready, .mem_req_write, .mem_req_addr,
        .mem_req_wdata,
        .mem_rsp_valid, .mem_rsp_ready, .mem_rsp_rdata, .mem_rsp_error);
endmodule

// ---------------------------------------------------------------------------
// The captured FP16 maximum-with-index leaf emits its value atom and its
// uint16 index atom on the same handshake. This adapter serialises that pair
// into the two standard atom beats the generic corpus DMA expects (value beat
// first, index beat second, `out_last` on the index beat), so no case-specific
// logic leaks into the engine and the output-atom budget stays the captured
// one (value atoms + index atoms).
module rk_ppu_pool_corpus_index_leaf (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         leaf_valid,
    output logic         leaf_ready,
    input  logic [127:0] leaf_value_atom,
    input  logic [127:0] leaf_index_atom,
    input  logic         leaf_last,
    output logic         out_valid,
    input  logic         out_ready,
    output logic [127:0] out_atom,
    output logic         out_last
);
    typedef enum logic [1:0] {
        S_IDLE, S_VALUE, S_INDEX
    } state_t;
    state_t state_q;
    logic [127:0] value_q, index_q;
    logic last_q;

    assign leaf_ready = rst_n && (state_q == S_IDLE);
    assign out_valid = rst_n && (state_q != S_IDLE);
    assign out_atom = (state_q == S_INDEX) ? index_q : value_q;
    assign out_last = rst_n && (state_q == S_INDEX) && last_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= S_IDLE;
            value_q <= 128'd0;
            index_q <= 128'd0;
            last_q <= 1'b0;
        end else begin
            case (state_q)
                S_IDLE: if (leaf_valid) begin
                    value_q <= leaf_value_atom;
                    index_q <= leaf_index_atom;
                    last_q <= leaf_last;
                    state_q <= S_VALUE;
                end
                S_VALUE: if (out_ready) state_q <= S_INDEX;
                S_INDEX: if (out_ready) state_q <= S_IDLE;
                default: state_q <= S_IDLE;
            endcase
        end
    end
endmodule
