// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// One-clock AXI-Lite packet endpoint. The raw backend remains the execution
// boundary. PCIe IP, clock crossing and multi-transport ownership are external.
module rk_axil_frame_mailbox (
    input wire clk, rst_n, admission_enable,
    input wire [31:0] s_axil_awaddr,
    input wire [2:0] s_axil_awprot,
    input wire s_axil_awvalid,
    output wire s_axil_awready,
    input wire [31:0] s_axil_wdata,
    input wire [3:0] s_axil_wstrb,
    input wire s_axil_wvalid,
    output wire s_axil_wready,
    output logic [1:0] s_axil_bresp,
    output logic s_axil_bvalid,
    input wire s_axil_bready,
    input wire [31:0] s_axil_araddr,
    input wire [2:0] s_axil_arprot,
    input wire s_axil_arvalid,
    output wire s_axil_arready,
    output logic [31:0] s_axil_rdata,
    output logic [1:0] s_axil_rresp,
    output logic s_axil_rvalid,
    input wire s_axil_rready,
    output wire req_valid,
    input wire req_ready,
    output wire [603:0] req,
    input wire rsp_valid,
    input wire [511:0] rsp_data,
    input wire [7:0] rsp_status,
    input wire [15:0] rsp_seq,
    output wire irq,
    output wire protocol_fault
);
    localparam logic [31:0] MAGIC=32'h4f54504a;
    localparam logic [19:0] FULL=20'hfffff;
    logic aw_pending,w_pending,aw_allowed,w_allowed;
    logic [31:0] aw_address,w_data;
    logic [2:0] aw_protection;
    logic [3:0] w_strobes;
    logic [639:0] staging,response;
    logic [19:0] staged,observed;
    logic [603:0] request;
    logic offered,waiting,held,failed;
    logic [7:0] failure_code;
    logic read_response_word;
    logic [4:0] response_word;
    wire idle=!offered&&!waiting&&!held&&!failed;
    wire write_fire=aw_pending&&w_pending&&!s_axil_bvalid;
    wire accepted=req_valid&&req_ready;
    assign s_axil_awready=rst_n&&!aw_pending&&!s_axil_bvalid;
    assign s_axil_wready=rst_n&&!w_pending&&!s_axil_bvalid;
    assign s_axil_arready=rst_n&&!s_axil_rvalid;
    assign req_valid=rst_n&&offered&&!failed;
    assign req=request;
    assign irq=rst_n&&(held||failed);
    assign protocol_fault=rst_n&&failed;

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            aw_pending<=0;w_pending<=0;aw_allowed<=0;w_allowed<=0;aw_address<=0;aw_protection<=0;w_data<=0;w_strobes<=0;
            s_axil_bvalid<=0;s_axil_bresp<=0;s_axil_rvalid<=0;s_axil_rresp<=0;s_axil_rdata<=0;
            staging<=0;response<=0;staged<=0;observed<=0;request<=0;
            offered<=0;waiting<=0;held<=0;failed<=0;failure_code<=0;
            read_response_word<=0;response_word<=0;
        end else begin
            if(s_axil_awvalid&&s_axil_awready)begin
                aw_pending<=1;aw_allowed<=admission_enable===1'b1;aw_address<=s_axil_awaddr;aw_protection<=s_axil_awprot;
            end
            if(s_axil_wvalid&&s_axil_wready)begin
                w_pending<=1;w_allowed<=admission_enable===1'b1;w_data<=s_axil_wdata;w_strobes<=s_axil_wstrb;
            end
            if(s_axil_bvalid&&s_axil_bready)s_axil_bvalid<=0;
            if(s_axil_rvalid&&s_axil_rready)begin
                s_axil_rvalid<=0;
                if(read_response_word&&s_axil_rresp==0&&held)
                    observed[response_word]<=1;
                read_response_word<=0;
            end
            if(write_fire)begin
                aw_pending<=0;w_pending<=0;s_axil_bvalid<=1;s_axil_bresp<=0;
                if(!aw_allowed||!w_allowed||admission_enable!==1'b1)s_axil_bresp<=2;
                else if(aw_address[1:0]!=0)s_axil_bresp<=3;
                else if(aw_protection!==3'd0||w_strobes!==4'hf)s_axil_bresp<=2;
                else if(aw_address>=32'h40&&aw_address<=32'h8c)begin
                    if(!idle)s_axil_bresp<=2;
                    else begin
                        staging[8'(aw_address-32'h40)*8 +:32]<=w_data;
                        staged[5'((aw_address-32'h40)>>2)]<=1;
                    end
                end else if(aw_address==32'hc)begin
                    if(w_data==1)begin
                        if(!idle||staged!==FULL||staging[639:604]!==36'd0||staging[603:572]!==MAGIC)
                            s_axil_bresp<=2;
                        else begin
                            request<=staging[603:0];offered<=1;
                            observed<=0;response<=0;
                        end
                    end else if(w_data==2)begin
                        if(!held||failed||observed!=FULL)s_axil_bresp<=2;
                        else begin held<=0;observed<=0;staged<=0;end
                    end else s_axil_bresp<=2;
                end else s_axil_bresp<=3;
            end
            if(s_axil_arvalid&&s_axil_arready)begin
                s_axil_rvalid<=1;s_axil_rdata<=0;s_axil_rresp<=0;read_response_word<=0;
                if(admission_enable!==1'b1)s_axil_rresp<=2;
                else if(s_axil_araddr[1:0]!=0)s_axil_rresp<=3;
                else if(s_axil_arprot!==3'd0)s_axil_rresp<=2;
                else if(s_axil_araddr>=32'h100&&s_axil_araddr<=32'h14c)begin
                    if(!held)s_axil_rresp<=2;
                    else begin
                        s_axil_rdata<=response[9'(s_axil_araddr-32'h100)*8 +:32];
                        response_word<=5'((s_axil_araddr-32'h100)>>2);read_response_word<=1;
                    end
                end else if(s_axil_araddr>=32'h40&&s_axil_araddr<=32'h8c)
                    s_axil_rdata<=staging[8'(s_axil_araddr-32'h40)*8 +:32];
                else case(s_axil_araddr)
                    32'h0:s_axil_rdata<=32'h524b5046;
                    32'h4:s_axil_rdata<=32'h00010000;
                    32'h8:s_axil_rdata<={27'd0,(staged==FULL),failed,held,(offered||waiting),idle};
                    32'h10:s_axil_rdata<={12'd0,staged};
                    32'h14:s_axil_rdata<={12'd0,observed};
                    32'h18:s_axil_rdata<={24'd0,failure_code};
                    default:s_axil_rresp<=3;
                endcase
            end
            if(accepted)begin offered<=0;waiting<=1;end
            if(rsp_valid)begin
                if(failed)begin end
                else if(held)begin failed<=1;failure_code<=3;end
                else if(!waiting&&!accepted)begin failed<=1;failure_code<=1;end
                else if(rsp_seq!==request[571:556])begin failed<=1;failure_code<=2;end
                else if(rsp_status!=0&&rsp_data!=0)begin failed<=1;failure_code<=4;end
                else begin
                    response<={72'd0,MAGIC,rsp_seq,rsp_status,rsp_data};
                    waiting<=0;held<=1;observed<=0;
                end
            end
        end
    end
endmodule
