// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private diagnostic AXI-Lite bank at0x200..0x2ff. FPGA management only; these
// are not RK registers and never encode/execute tensor operations. No board
// integration is implied. The ordinary EW/CMAC banks remain separate.
// CMD(0x20c) accepts only full-strobe value1 once per joint-reset epoch.
// SEED(0x210) is mutable only before that start. There is no clear/restart or
// local-reset command; status and mismatch words remain readable on failure.
// Read snapshots are AR-time values; simultaneous read/write sees old state.
module rk_ddr_capacity_regs #(
    parameter logic [30:0] BASE_ADDR = 0,
    parameter logic [31:0] SPAN_BYTES = 32'h80000000
) (
    input logic clk, joint_rst_n,
    input logic [31:0] s_axil_awaddr,
    input logic [2:0] s_axil_awprot,
    input logic s_axil_awvalid,
    output logic s_axil_awready,
    input logic [31:0] s_axil_wdata,
    input logic [3:0] s_axil_wstrb,
    input logic s_axil_wvalid,
    output logic s_axil_wready,
    output logic [1:0] s_axil_bresp,
    output logic s_axil_bvalid,
    input logic s_axil_bready,
    input logic [31:0] s_axil_araddr,
    input logic [2:0] s_axil_arprot,
    input logic s_axil_arvalid,
    output logic s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0] s_axil_rresp,
    output logic s_axil_rvalid,
    input logic s_axil_rready,
    output logic request_valid,
    input logic request_ready,
    output logic [31:0] request_seed,
    input logic handoff_allowed, owner_busy, owner_done, owner_fault, diagnostic_selected,
    input logic [31:0] completed_writes, completed_reads,
    input logic [31:0] fault_codes,
    input logic [2:0] fault_sources,
    input logic [30:0] mismatch_address, last_completed_write_address,
    input logic [511:0] mismatch_expected, mismatch_actual
);
    logic aw_held, w_held, start_issued, start_pending;
    logic [31:0] saved_awaddr, saved_wdata, configured_seed;
    logic [2:0] saved_awprot;
    logic [3:0] saved_wstrb;
    logic write_commit, write_ok, seed_write, start_write;
    logic invalid_seed, ready_for_start, read_ok;
    logic [31:0] read_value;
    localparam logic [32:0] END_ADDR = {2'b0,BASE_ADDR}+{1'b0,SPAN_BYTES};

    initial begin
        if ((^BASE_ADDR)===1'bx || (^SPAN_BYTES)===1'bx || BASE_ADDR[5:0]!=0 ||
            SPAN_BYTES<64 || SPAN_BYTES[5:0]!=0 || END_ADDR>33'h080000000)
            $fatal(1,"Capacity CSR metadata needs aligned nonempty31-bit span");
    end
    assign s_axil_awready = joint_rst_n && !aw_held && !s_axil_bvalid;
    assign s_axil_wready = joint_rst_n && !w_held && !s_axil_bvalid;
    assign s_axil_arready = joint_rst_n && !s_axil_rvalid;
    assign write_commit = aw_held && w_held && !s_axil_bvalid;
    assign request_valid = joint_rst_n && start_pending;
    assign request_seed = configured_seed;
    assign ready_for_start = request_ready === 1'b1 && handoff_allowed === 1'b1 &&
        owner_busy === 1'b0 && owner_fault === 1'b0 && diagnostic_selected === 1'b0 &&
        !start_issued && !start_pending;
    always_comb begin
        invalid_seed = 0;
`ifndef SYNTHESIS
        if ((^saved_wdata)===1'bx) invalid_seed = 1;
`endif
        write_ok = 0; seed_write = 0; start_write = 0;
        if ((^saved_awaddr)!==1'bx && saved_awprot===0 && saved_wstrb===4'hf && saved_awaddr[1:0]===0) begin
            case(saved_awaddr)
                32'h20c: if (saved_wdata===32'h1 && ready_for_start) begin write_ok=1; start_write=1; end
                32'h210: if (!invalid_seed && !start_issued && !start_pending &&
                    owner_busy===1'b0 && owner_fault===1'b0 && diagnostic_selected===1'b0) begin
                    write_ok=1; seed_write=1;
                end
                default: begin end
            endcase
        end
    end
    always_comb begin
        read_ok = 0; read_value = 0;
        if ((^s_axil_araddr)!==1'bx && s_axil_arprot===0 && s_axil_araddr[1:0]===0) begin
            read_ok = 1;
            case(s_axil_araddr)
                32'h200: read_value=32'h524b4d54; // RKMT: memory diagnostic, not RKAD/RKCD.
                32'h204: read_value=32'h00010000;
                32'h208: read_value={25'b0,start_issued,diagnostic_selected,owner_fault,
                    owner_done,owner_busy,start_pending,ready_for_start};
                32'h210: read_value=configured_seed;
                32'h214: read_value=SPAN_BYTES;
                32'h218: read_value={1'b0,BASE_ADDR};
                32'h21c: read_value=32'h00020040; // two trials, 64-byte line.
                32'h220: read_value=completed_writes;
                32'h224: read_value=completed_reads;
                32'h228: read_value=fault_codes;
                32'h22c: read_value={29'b0,fault_sources};
                32'h230: read_value={1'b0,mismatch_address};
                32'h234: read_value={1'b0,last_completed_write_address};
                default: begin
                    if (s_axil_araddr>=32'h240 && s_axil_araddr<=32'h27c)
                        read_value=mismatch_expected[s_axil_araddr[5:2]*32 +: 32];
                    else if (s_axil_araddr>=32'h280 && s_axil_araddr<=32'h2bc)
                        read_value=mismatch_actual[s_axil_araddr[5:2]*32 +: 32];
                    else begin read_ok=0; read_value=0; end
                end
            endcase
        end
    end
    always_ff @(posedge clk) begin
        if (!joint_rst_n) begin
            aw_held<=0; w_held<=0; saved_awaddr<=0; saved_awprot<=0;
            saved_wdata<=0; saved_wstrb<=0; configured_seed<=32'h3588c350;
            start_issued<=0; start_pending<=0;
            s_axil_bresp<=0; s_axil_bvalid<=0;
            s_axil_rdata<=0; s_axil_rresp<=0; s_axil_rvalid<=0;
        end else begin
            if (s_axil_awvalid && s_axil_awready) begin
                saved_awaddr<=s_axil_awaddr; saved_awprot<=s_axil_awprot; aw_held<=1;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                saved_wdata<=s_axil_wdata; saved_wstrb<=s_axil_wstrb; w_held<=1;
            end
            if (s_axil_bvalid && s_axil_bready) s_axil_bvalid<=0;
            if (s_axil_rvalid && s_axil_rready) s_axil_rvalid<=0;
            if (request_valid && request_ready) start_pending<=0;
            if (write_commit) begin
                aw_held<=0; w_held<=0; s_axil_bvalid<=1;
                s_axil_bresp<=write_ok ? 2'b00 : 2'b10;
                if (seed_write) configured_seed<=saved_wdata;
                if (start_write) begin start_issued<=1; start_pending<=1; end
            end
            if (s_axil_arvalid && s_axil_arready) begin
                s_axil_rvalid<=1; s_axil_rdata<=read_value;
                s_axil_rresp<=read_ok ? 2'b00 : 2'b10;
            end
        end
    end
endmodule
