// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Minimal AXI4-Lite page stub for the merged-image integration skeleton.
//
// This is SCAFFOLDING, not an engine. It exists so `fpga/ypcb_merged_top.sv`
// elaborates with the planned page map and so a future page can replace one
// instance without changing the routing in the top:
//
//   * offset 0x000 reads the page's 32-bit device identity (the same identity
//     word a real page publishes);
//   * offset 0x004 is one writable scratch word that round-trips, proving the
//     page was addressed (a bench/contract probe);
//   * offset 0x008 reads {31'b0, memory_ready} so the shared-memory readiness
//     input is observable during scaffolding;
//   * any other offset reads 0 and writes are ignored.
//
// TODO (two-image split): replace each instance with the real slave, keeping the
// same AXI4-Lite port slice, the `memory_ready` input and the `busy`/`irq`
// outputs. Image A: S1 `conv_runtime_page` <- rk_conv_runtime_axi, S2
// `gemm_page` <- rk_cmac_gemm_axi. Image B: S3 pooling pages, S4 EW front end +
// sparse aperture. The real pages must validate their register fields and fault
// explicitly instead of ignoring writes; this stub's permissive behaviour must
// not survive into a built image.
module merged_page_stub #(
    parameter logic [31:0] PAGE_ID = 32'h0000_0000
) (
    input  logic        clk,
    input  logic        rst_n,
    // A single shared-memory readiness line from the merged top's arbitration.
    input  logic        memory_ready,
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
    // Engine status. Stubs are always idle and never complete a job.
    output logic        busy,
    output logic        irq
);
    logic [31:0] scratch_q;
    logic aw_pending_q, w_pending_q, bvalid_q, rvalid_q;
    logic [31:0] write_address_q, write_data_q, read_address_q;
    logic [31:0] read_data_q;

    assign busy = 1'b0;
    assign irq  = 1'b0;

    assign s_axil_awready = rst_n && !aw_pending_q && !bvalid_q;
    assign s_axil_wready  = rst_n && !w_pending_q && !bvalid_q;
    assign s_axil_arready = rst_n && !rvalid_q;
    assign s_axil_bvalid  = rst_n && bvalid_q;
    assign s_axil_bresp   = 2'b00;
    assign s_axil_rvalid  = rst_n && rvalid_q;
    assign s_axil_rresp   = 2'b00;
    assign s_axil_rdata   = read_data_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            scratch_q <= 32'd0;
            aw_pending_q <= 1'b0;
            w_pending_q <= 1'b0;
            bvalid_q <= 1'b0;
            rvalid_q <= 1'b0;
            write_address_q <= 32'd0;
            write_data_q <= 32'd0;
            read_address_q <= 32'd0;
            read_data_q <= 32'd0;
        end else begin
            if (s_axil_bvalid && s_axil_bready) bvalid_q <= 1'b0;
            if (s_axil_rvalid && s_axil_rready) rvalid_q <= 1'b0;
            if (s_axil_awvalid && s_axil_awready) begin
                aw_pending_q <= 1'b1;
                write_address_q <= s_axil_awaddr;
            end
            if (s_axil_wvalid && s_axil_wready) begin
                w_pending_q <= 1'b1;
                write_data_q <= s_axil_wdata;
            end
            if (aw_pending_q && w_pending_q && !bvalid_q) begin
                aw_pending_q <= 1'b0;
                w_pending_q <= 1'b0;
                bvalid_q <= 1'b1;
                // TODO(S1..S4): the real page validates offset/fields and faults
                // explicitly. The stub only round-trips its scratch word.
                if (write_address_q[11:0] == 12'h004)
                    scratch_q <= write_data_q;
            end
            if (s_axil_arvalid && s_axil_arready) begin
                read_address_q <= s_axil_araddr;
                rvalid_q <= 1'b1;
                case (s_axil_araddr[11:0])
                    12'h000: read_data_q <= PAGE_ID;
                    12'h004: read_data_q <= scratch_q;
                    12'h008: read_data_q <= {31'd0, memory_ready};
                    default: read_data_q <= 32'd0;
                endcase
            end
        end
    end
endmodule
