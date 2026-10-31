// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Unselected maintenance boundary. Configuration-lifetime UI state, not a
// link-health gate. Drain accepted channels before closing new slave READY.
module rk_axil_maintenance_seal (
    input wire clk, power_rst_n, ui_clients_rst_n,
    input wire admission_block, drain_ready,
    output wire packet_admission_enable, sealed_quiet,
    output logic seal_fault,
    input wire [31:0] s_awaddr,
    input wire [2:0] s_awprot,
    input wire s_awvalid,
    output wire s_awready,
    input wire [31:0] s_wdata,
    input wire [3:0] s_wstrb,
    input wire s_wvalid,
    output wire s_wready,
    output wire [1:0] s_bresp,
    output wire s_bvalid,
    input wire s_bready,
    input wire [31:0] s_araddr,
    input wire [2:0] s_arprot,
    input wire s_arvalid,
    output wire s_arready,
    output wire [31:0] s_rdata,
    output wire [1:0] s_rresp,
    output wire s_rvalid,
    input wire s_rready,
    output wire [31:0] m_awaddr,
    output wire [2:0] m_awprot,
    output wire m_awvalid,
    input wire m_awready,
    output wire [31:0] m_wdata,
    output wire [3:0] m_wstrb,
    output wire m_wvalid,
    input wire m_wready,
    input wire [1:0] m_bresp,
    input wire m_bvalid,
    output wire m_bready,
    output wire [31:0] m_araddr,
    output wire [2:0] m_arprot,
    output wire m_arvalid,
    input wire m_arready,
    input wire [31:0] m_rdata,
    input wire [1:0] m_rresp,
    input wire m_rvalid,
    output wire m_rready
);
    typedef enum logic [1:0] {OPEN,DRAIN,SEALED} state_t;
    state_t state;
    logic epoch_started;
    wire transfer_enable=(power_rst_n===1'b1)&&(ui_clients_rst_n===1'b1)&&
        ((state===OPEN)||(state===DRAIN));
    assign packet_admission_enable=(power_rst_n===1'b1)&&(ui_clients_rst_n===1'b1)&&
        (state===OPEN)&&(admission_block===1'b0)&&(seal_fault===1'b0);
    assign sealed_quiet=(power_rst_n===1'b1)&&(state===SEALED)&&
        (admission_block===1'b1)&&(seal_fault===1'b0)&&
        (m_bvalid===1'b0)&&(m_rvalid===1'b0);
    assign m_awaddr=s_awaddr;
    assign m_awprot=s_awprot;
    assign m_awvalid=transfer_enable&&s_awvalid;
    assign s_awready=transfer_enable&&m_awready;
    assign m_wdata=s_wdata;
    assign m_wstrb=s_wstrb;
    assign m_wvalid=transfer_enable&&s_wvalid;
    assign s_wready=transfer_enable&&m_wready;
    assign m_araddr=s_araddr;
    assign m_arprot=s_arprot;
    assign m_arvalid=transfer_enable&&s_arvalid;
    assign s_arready=transfer_enable&&m_arready;
    // Accepted responses are never suppressed by maintenance or local state.
    assign s_bresp=m_bresp;
    assign s_bvalid=m_bvalid;
    assign m_bready=s_bready;
    assign s_rdata=m_rdata;
    assign s_rresp=m_rresp;
    assign s_rvalid=m_rvalid;
    assign m_rready=s_rready;

    always @(posedge clk or negedge power_rst_n) begin
        if(!power_rst_n)begin state<=OPEN;seal_fault<=0;epoch_started<=0;end
        else begin
            if(ui_clients_rst_n===1'b1)epoch_started<=1;
            if(admission_block!==1'b0&&admission_block!==1'b1)seal_fault<=1;
            if(epoch_started&&ui_clients_rst_n!==1'b1&&state!==SEALED)seal_fault<=1;
            case(state)
                OPEN:if(admission_block!==1'b0)state<=DRAIN;
                DRAIN:begin
                    if(admission_block===1'b0)state<=OPEN;
                    else if(admission_block===1'b1&&seal_fault===1'b0&&
                            ui_clients_rst_n===1'b1&&drain_ready===1'b1&&
                            s_awvalid===1'b0&&s_wvalid===1'b0&&s_arvalid===1'b0&&
                            m_bvalid===1'b0&&m_rvalid===1'b0)state<=SEALED;
                end
                SEALED:begin
                    // drain_ready may fall during the accepted reset/bootstrap.
                    // New response activity in an active client epoch is a
                    // violated drain witness, not permission to hide a response.
                    if(ui_clients_rst_n===1'b1&&(m_bvalid!==1'b0||m_rvalid!==1'b0))seal_fault<=1;
                    if(admission_block===1'b0)state<=OPEN;
                end
                default:begin state<=SEALED;seal_fault<=1;end
            endcase
        end
    end
endmodule
