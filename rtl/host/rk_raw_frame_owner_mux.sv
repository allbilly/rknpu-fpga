// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Same-clock raw-frame ownership. Source 0=JTAG, source 1=PCIe.
// release_ready must prove the entire retained backend transaction state empty.
// rst_n belongs to the joint retained transaction epoch, not compute/link reset.
module rk_raw_frame_owner_mux (
    input wire clk,rst_n,
    input wire release_ready,
    input wire [1:0] link_healthy,
    input wire [1:0] s_req_valid,
    output logic [1:0] s_req_ready,
    input wire [1:0][603:0] s_req,
    output logic [1:0] s_rsp_valid,
    output logic [1:0][511:0] s_rsp_data,
    output logic [1:0][7:0] s_rsp_status,
    output logic [1:0][15:0] s_rsp_seq,
    output wire m_req_valid,
    input wire m_req_ready,
    output wire [603:0] m_req,
    input wire m_rsp_valid,
    input wire [511:0] m_rsp_data,
    input wire [7:0] m_rsp_status,
    input wire [15:0] m_rsp_seq,
    output logic [1:0] owner,
    output logic [31:0] lease_epoch,
    output logic failed,
    output logic [7:0] failure_code
);
    logic offered,waiting,request_source,last_source;
    logic [603:0] request;
    wire owner_healthy=owner==0 ? 1'b1 : owner==1 ? link_healthy[0]===1'b1 : link_healthy[1]===1'b1;
    wire a_valid=s_req_valid[0]&&link_healthy[0]===1'b1;
    wire b_valid=s_req_valid[1]&&link_healthy[1]===1'b1;
    wire choose_b=b_valid&&(!a_valid||!last_source);
    wire available=rst_n&&(failed||(!offered&&!waiting&&!m_rsp_valid&&owner_healthy));
    wire take=available&&(a_valid||b_valid);
    wire [603:0] selected=choose_b ? s_req[1] : s_req[0];
    wire [1:0] selected_owner=choose_b ? 2'd2 : 2'd1;
    wire [7:0] opcode=selected[555:548];
    wire [31:0] address=selected[543:512];
    wire management=(opcode==1||opcode==2)&&address[31:8]==24'h000006;
    wire accepted=m_req_valid&&m_req_ready;
    assign m_req_valid=rst_n&&offered&&!failed&&owner_healthy;
    assign m_req=request;
    always @* begin
        s_req_ready=0;
        if(available)begin
            if(choose_b)s_req_ready[1]=1;
            else if(link_healthy[0]===1'b1)s_req_ready[0]=1;
        end
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            s_rsp_valid<=0;s_rsp_data<=0;s_rsp_status<=0;s_rsp_seq<=0;
            owner<=0;lease_epoch<=0;failed<=0;failure_code<=0;
            offered<=0;waiting<=0;request<=0;request_source<=0;last_source<=1;
        end else begin
            s_rsp_valid<=0;
            if(accepted)begin offered<=0;waiting<=1;end
            if(!failed&&owner!=0&&!owner_healthy)begin
                failed<=1;failure_code<=1;
            end else if(!failed&&m_rsp_valid)begin
                if(!waiting&&!accepted)begin failed<=1;failure_code<=2;end
                else if(m_rsp_seq!==request[571:556])begin failed<=1;failure_code<=3;end
                else if(m_rsp_status!=0&&m_rsp_data!=0)begin failed<=1;failure_code<=4;end
                else begin
                    offered<=0;waiting<=0;
                    s_rsp_valid[request_source]<=1;
                    s_rsp_data[request_source]<=m_rsp_data;
                    s_rsp_status[request_source]<=m_rsp_status;
                    s_rsp_seq[request_source]<=m_rsp_seq;
                end
            end
            if(take)begin
                last_source<=choose_b;
                s_rsp_data[choose_b]<=0;s_rsp_status[choose_b]<=0;s_rsp_seq[choose_b]<=selected[571:556];
                if(selected[603:572]!==32'h4f54504a)begin
                    s_rsp_valid[choose_b]<=1;s_rsp_status[choose_b]<=3;
                end else if(management)begin
                    s_rsp_valid[choose_b]<=1;
                    if(address[1:0]!=0) s_rsp_status[choose_b]<=3;
                    else if(selected[547:544]!==4'hf)s_rsp_status[choose_b]<=2;
                    else if(opcode==1)begin
                        if(selected[511:0]!==512'd0)s_rsp_status[choose_b]<=2;
                        else case(address)
                            32'h600:s_rsp_data[choose_b]<={480'd0,32'h524b484f};
                            32'h604:s_rsp_data[choose_b]<={480'd0,32'h00010000};
                            32'h608:s_rsp_data[choose_b]<={508'd0,(release_ready===1'b1),failed,owner};
                            32'h610:s_rsp_data[choose_b]<={480'd0,lease_epoch};
                            32'h614:s_rsp_data[choose_b]<={510'd0,selected_owner};
                            32'h618:s_rsp_data[choose_b]<={504'd0,failure_code};
                            32'h61c:s_rsp_data[choose_b]<={480'd0,32'h00000003};
                            default:s_rsp_status[choose_b]<=3;
                        endcase
                    end else if(address!=32'h60c)s_rsp_status[choose_b]<=3;
                    else if(failed||selected[511:32]!==480'd0)s_rsp_status[choose_b]<=2;
                    else if(selected[31:0]==1)begin
                        if(owner!=0||release_ready!==1'b1||lease_epoch==32'hffffffff)s_rsp_status[choose_b]<=2;
                        else begin owner<=selected_owner;lease_epoch<=lease_epoch+1'b1;end
                    end else if(selected[31:0]==2)begin
                        if(owner!=selected_owner||release_ready!==1'b1)s_rsp_status[choose_b]<=2;
                        else owner<=0;
                    end else s_rsp_status[choose_b]<=2;
                end else if(failed||owner!=selected_owner)begin
                    s_rsp_valid[choose_b]<=1;s_rsp_status[choose_b]<=2;
                end else begin
                    request<=selected;request_source<=choose_b;offered<=1;
                end
            end
        end
    end
endmodule
