// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Reset preparation for AMD axi_clock_converter v2.1 AXI4-Lite async mode.
// Both domains belong to ONE retained transaction epoch. Link/PERST/compute
// reset must never drive epoch_rst_n. A clock stopped during initialization
// keeps the bridge unavailable, without blocking the independent UI/JTAG path.
// Readiness records initialization history; it does not detect later clock
// loss. A separate link/clock-health mechanism must quarantine that epoch.
// This module does not synchronize link health, revoke ownership, or replace
// the sticky link-epoch guard. Assert epoch_rst_n low at initialization. The
// two ready outputs can rise at different times; downstream admission must be
// qualified before exposing upstream traffic, using synchronized readiness.
// Actual converter integration and physical CDC remain separate gates.
module rk_pcie_bridge_reset #(
    parameter integer SYNC_STAGES = 3,
    parameter integer RESET_EDGES = 8,
    parameter integer SETTLE_EDGES = 5
) (
    input wire epoch_rst_n,
    input wire s_clk, m_clk,
    output wire s_aresetn, m_aresetn,
    output wire s_ready, m_ready
);
    // The vendor Lite channel FSM and reset-delay registers are synchronous.
    // Hold each external reset through local edges and a peer reset witness;
    // then count local post-release settling edges before publishing readiness.
    // AMD's handshake synchronizer has no reset input. These counts apply to
    // converter C_SRC_SYNC_FF=C_DEST_SYNC_FF=SYNC_STAGES, not an arbitrary IP.
    localparam integer STAGES = SYNC_STAGES < 3 ? 3 : SYNC_STAGES;
    localparam integer RESET_BITS = RESET_EDGES < 2 ? 1 : $clog2(RESET_EDGES);
    localparam integer SETTLE_BITS = SETTLE_EDGES < 2 ? 1 : $clog2(SETTLE_EDGES);
    // Only these reset synchronizers see the SYS-domain epoch directly.
    // Every functional register below leaves reset on its own clock edge.
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-2:0] s_local_release_early, m_local_release_early;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic s_local_rst_n, m_local_rst_n;
    logic [RESET_BITS-1:0] s_reset_edges, m_reset_edges;
    logic [SETTLE_BITS-1:0] s_settle_edges, m_settle_edges;
    logic s_reset_seen, m_reset_seen, s_settled, m_settled;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] s_peer_reset, m_peer_reset;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] s_peer_settled, m_peer_settled;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) logic [STAGES-1:0] s_release, m_release;

    initial begin
        if (SYNC_STAGES < 3 || SYNC_STAGES > 10 ||
            RESET_EDGES < 2*SYNC_STAGES+2 || RESET_EDGES > 65536 ||
            SETTLE_EDGES < SYNC_STAGES+2 || SETTLE_EDGES > 65536)
            $fatal(1,"Invalid async AXI-Lite bridge reset/settling contract");
    end

    assign s_aresetn=s_release[STAGES-1];
    assign m_aresetn=m_release[STAGES-1];
    assign s_ready=s_settled && s_peer_settled[STAGES-1];
    assign m_ready=m_settled && m_peer_settled[STAGES-1];

    always_ff @(posedge s_clk or negedge epoch_rst_n) begin
        if (!epoch_rst_n) begin s_local_release_early<=0; s_local_rst_n<=0; end
        else begin
            s_local_release_early<={s_local_release_early[STAGES-3:0],1'b1};
            s_local_rst_n<=s_local_release_early[STAGES-2];
        end
    end
    always_ff @(posedge m_clk or negedge epoch_rst_n) begin
        if (!epoch_rst_n) begin m_local_release_early<=0; m_local_rst_n<=0; end
        else begin
            m_local_release_early<={m_local_release_early[STAGES-3:0],1'b1};
            m_local_rst_n<=m_local_release_early[STAGES-2];
        end
    end

    always_ff @(posedge s_clk or negedge s_local_rst_n) begin
        if (!s_local_rst_n) begin
            s_reset_edges<=0;s_reset_seen<=0;s_peer_reset<=0;s_release<=0;
            s_settle_edges<=0;s_settled<=0;s_peer_settled<=0;
        end else begin
            s_peer_reset<={s_peer_reset[STAGES-2:0],m_reset_seen};
            s_peer_settled<={s_peer_settled[STAGES-2:0],m_settled};
            if (!s_reset_seen) begin
                if (s_reset_edges==RESET_BITS'(RESET_EDGES-1)) s_reset_seen<=1;
                else s_reset_edges<=s_reset_edges+1'b1;
            end
            if (s_reset_seen && s_peer_reset[STAGES-1])
                s_release<={s_release[STAGES-2:0],1'b1};
            if (s_aresetn && !s_settled) begin
                if (s_settle_edges==SETTLE_BITS'(SETTLE_EDGES-1)) s_settled<=1;
                else s_settle_edges<=s_settle_edges+1'b1;
            end
        end
    end

    always_ff @(posedge m_clk or negedge m_local_rst_n) begin
        if (!m_local_rst_n) begin
            m_reset_edges<=0;m_reset_seen<=0;m_peer_reset<=0;m_release<=0;
            m_settle_edges<=0;m_settled<=0;m_peer_settled<=0;
        end else begin
            m_peer_reset<={m_peer_reset[STAGES-2:0],s_reset_seen};
            m_peer_settled<={m_peer_settled[STAGES-2:0],s_settled};
            if (!m_reset_seen) begin
                if (m_reset_edges==RESET_BITS'(RESET_EDGES-1)) m_reset_seen<=1;
                else m_reset_edges<=m_reset_edges+1'b1;
            end
            if (m_reset_seen && m_peer_reset[STAGES-1])
                m_release<={m_release[STAGES-2:0],1'b1};
            if (m_aresetn && !m_settled) begin
                if (m_settle_edges==SETTLE_BITS'(SETTLE_EDGES-1)) m_settled<=1;
                else m_settle_edges<=m_settle_edges+1'b1;
            end
        end
    end
endmodule
