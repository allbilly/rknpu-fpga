// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// UNSELECTED retained admission barrier. No numerical command interpretation.
module rk_whole_reset_frame_gate (
    input wire ui_clk, power_rst_n, ui_clients_rst_n,
    input wire admission_block, parent_drained,
    input wire s_req_valid,
    output wire s_req_ready,
    input wire [603:0] s_req,
    output logic s_rsp_valid,
    output logic [511:0] s_rsp_data,
    output logic [7:0] s_rsp_status,
    output logic [15:0] s_rsp_seq,
    output wire m_req_valid,
    input wire m_req_ready,
    output wire [603:0] m_req,
    input wire m_rsp_valid,
    input wire [511:0] m_rsp_data,
    input wire [7:0] m_rsp_status,
    input wire [15:0] m_rsp_seq,
    output wire sealed_quiet,
    output logic gate_fault
);
    typedef enum logic [1:0] {OPEN,DRAIN,SEALED} state_t;
    state_t state;
    logic pending,reject_waiting;
    wire available=(power_rst_n===1'b1)&&(ui_clients_rst_n===1'b1)&&
        !pending&&!s_rsp_valid&&((state===OPEN)||(state===DRAIN))&&(m_rsp_valid===1'b0);
    wire raw_unknown=(^s_req)===1'bx;
    wire deny=(admission_block!==1'b0)||reject_waiting||gate_fault||raw_unknown;
    assign s_req_ready=available&&(deny||(m_req_ready===1'b1));
    assign m_req_valid=available&&!deny&&(s_req_valid===1'b1);
    assign m_req=s_req;
    // Once sealed, no request or denial response can be admitted before release.
    // Parent drainage may fall during the subsequent reset/bootstrap/init.
    assign sealed_quiet=(gate_fault===1'b0)&&(state===SEALED)&&!pending&&!s_rsp_valid&&
        (parent_drained===1'b1)&&(m_rsp_valid===1'b0)&&!m_req_valid;

    always @(posedge ui_clk or negedge power_rst_n)begin
        if(!power_rst_n)begin
            state<=OPEN;pending<=0;reject_waiting<=0;gate_fault<=0;
            s_rsp_valid<=0;s_rsp_data<=0;s_rsp_status<=0;s_rsp_seq<=0;
        end else begin
            s_rsp_valid<=0;
            // A client reset with an owned request violates the integration's
            // drain-before-reset contract. Keep ownership, fail closed; it must
            // not become a false quiet witness or automatic retry.
            if(pending&&ui_clients_rst_n!==1'b1)gate_fault<=1;
            // Backend response registers may be uninitialized before their
            // first synchronous reset edge. They are not live protocol inputs
            // while the client epoch is held reset. Owned requests still make
            // an unexpected reset a sticky failure above.
            if(ui_clients_rst_n===1'b1&&m_rsp_valid!==1'b0)begin
                if(m_rsp_valid===1'b1&&pending)begin
                    pending<=0;s_rsp_valid<=1;
                    s_rsp_data<=m_rsp_data;s_rsp_status<=m_rsp_status;s_rsp_seq<=m_rsp_seq;
                end else gate_fault<=1;
            end
            if(s_req_valid===1'b1&&s_req_ready===1'b1)begin
                if(deny)begin
                    s_rsp_valid<=1;s_rsp_data<=0;s_rsp_seq<=s_req[571:556];
                    s_rsp_status<=(gate_fault||(^admission_block)===1'bx||raw_unknown)?8'd5:8'd2;
                    reject_waiting<=0;
                end else pending<=1;
            end
            case(state)
                OPEN:if(admission_block!==1'b0)state<=DRAIN;
                DRAIN:begin
                    if(admission_block===1'b0)state<=OPEN;
                    else if(admission_block===1'b1&&gate_fault===1'b0&&!pending&&!s_rsp_valid&&
                            s_req_valid===1'b0&&parent_drained===1'b1&&m_rsp_valid===1'b0)
                        state<=SEALED;
                end
                SEALED:begin
                    // The upstream mailbox must hold this unaccepted frame
                    // across the client reset. Deny it after barrier release;
                    // never reinterpret it as work for the new memory epoch.
                    if(s_req_valid===1'b1)reject_waiting<=1;
                    if(admission_block===1'b0)state<=OPEN;
                end
                default:begin state<=SEALED;gate_fault<=1;end
            endcase
        end
    end
endmodule
