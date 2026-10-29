// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Preparation-only management CSR. Independent of the compute reset island.
// A reset starts only from healthy, already quiescent state; busy requests
// return SLVERR. No reset, BO reload or recovery is implied by a read/ACK.
module rk_compute_reset_regs (
    input wire clk,rst_n,healthy,quiescent,reset_blocked,
    output wire reset_request_valid,
    input wire reset_request_ready,reset_result_valid,reset_result_error,
    input wire [7:0] reset_error_code,
    input wire [31:0] reset_epoch,
    output wire reset_result_ready,
    input wire [31:0] s_axil_awaddr,s_axil_wdata,s_axil_araddr,
    input wire [2:0] s_axil_awprot,s_axil_arprot,
    input wire [3:0] s_axil_wstrb,
    input wire s_axil_awvalid,s_axil_wvalid,s_axil_bready,s_axil_arvalid,s_axil_rready,
    output wire s_axil_awready,s_axil_wready,s_axil_arready,
    output logic s_axil_bvalid,s_axil_rvalid,
    output logic [1:0] s_axil_bresp,s_axil_rresp,
    output logic [31:0] s_axil_rdata
);
    logic have_aw,have_w;
    logic [31:0] address,data;
    logic [2:0] protection;
    logic [3:0] strobe;
    wire commit=rst_n&&have_aw&&have_w&&!s_axil_bvalid;
    wire write_legal=address===32'h0000050c&&protection===3'd0&&strobe===4'hf;
    // These direct commit qualifications are sampled by the register bank
    // and the sequencer on the same UI edge. No registered pulse can be lost
    // if readiness changes between AXI acceptance and action execution.
    assign reset_request_valid=commit&&write_legal&&data===32'd1&&healthy===1'b1&&
        quiescent===1'b1&&reset_request_ready===1'b1&&reset_blocked===1'b0&&
        reset_result_valid===1'b0&&reset_result_error===1'b0;
    assign reset_result_ready=commit&&write_legal&&data===32'd2&&healthy===1'b1&&
        quiescent===1'b1&&reset_result_valid===1'b1&&reset_result_error===1'b0;
    assign s_axil_awready=rst_n&&!have_aw&&!s_axil_bvalid;
    assign s_axil_wready=rst_n&&!have_w&&!s_axil_bvalid;
    assign s_axil_arready=rst_n&&!s_axil_rvalid;
    wire known_healthy=healthy===1'b1,known_quiet=quiescent===1'b1;
    wire blocked=reset_blocked!==1'b0,failed=reset_result_error!==1'b0;
    wire available=reset_request_ready===1'b1&&!blocked&&known_healthy&&known_quiet&&
                   reset_result_valid===1'b0&&!failed;
    wire [31:0] status={26'd0,known_quiet,known_healthy,failed,reset_result_valid===1'b1,blocked,available};
    always @(posedge clk)begin
        if(!rst_n)begin
            have_aw<=0;have_w<=0;address<=0;data<=0;protection<=0;strobe<=0;
            s_axil_bvalid<=0;s_axil_bresp<=0;s_axil_rvalid<=0;s_axil_rresp<=0;s_axil_rdata<=0;
        end else begin
            if(s_axil_awvalid&&s_axil_awready)begin have_aw<=1;address<=s_axil_awaddr;protection<=s_axil_awprot;end
            if(s_axil_wvalid&&s_axil_wready)begin have_w<=1;data<=s_axil_wdata;strobe<=s_axil_wstrb;end
            if(commit)begin
                have_aw<=0;have_w<=0;s_axil_bvalid<=1;
                if(address!==32'h0000050c)s_axil_bresp<=3;
                else if(!write_legal||(!reset_request_valid&&!reset_result_ready))s_axil_bresp<=2;
                else s_axil_bresp<=0;
            end
            if(s_axil_bvalid&&s_axil_bready)s_axil_bvalid<=0;
            if(s_axil_arvalid&&s_axil_arready)begin
                s_axil_rvalid<=1;s_axil_rresp<=0;s_axil_rdata<=0;
                if(s_axil_arprot!==3'd0)s_axil_rresp<=2;
                else case(s_axil_araddr)
                    32'h500:s_axil_rdata<=32'h524b5253; // RKRS
                    32'h504:s_axil_rdata<=32'h00010000;
                    32'h508:s_axil_rdata<=status;
                    32'h510:s_axil_rdata<=reset_epoch;
                    32'h514:s_axil_rdata<=reset_result_error ? {24'd0,reset_error_code} : 32'd0;
                    32'h518:s_axil_rdata<=32'h00010004; // retained BO / four local hold edges
                    default:s_axil_rresp<=3;
                endcase
            end
            if(s_axil_rvalid&&s_axil_rready)s_axil_rvalid<=0;
        end
    end
endmodule
