// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private FPGA raw-QWORD extension. Static u32 indices select unchanged u16
// lanes; ffffffff writes zero. No floating-point arithmetic or host data fixup.
// One memory transaction at a time. Faults retain held VALID and drain late
// responses; only a joint reset can recover a faulted epoch.
module rk_layout_dma #(
    parameter logic [31:0] BASE=32'h10000000,
    parameter logic [32:0] BYTES=33'd1048576,
    parameter int unsigned TIMEOUT_CYCLES=65536
) (
    input wire clk,rst_n,start_valid,
    output wire start_ready,quiescent,
    input wire [31:0] start_address,start_amount,
    output wire busy,done,error,
    output wire [7:0] error_code,
    input wire result_ready,
    output wire mem_req_valid,
    input wire mem_req_ready,
    output logic mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rsp_rdata,
    input wire mem_rsp_error
);
    typedef enum logic [3:0] {IDLE,START_CHECK,CMD_REQ,CMD_RSP,CMD_CHECK,SPAN_CHECK,
        INDEX_REQ,INDEX_RSP,INDEX_CHECK,SOURCE_REQ,SOURCE_RSP,WRITE_REQ,WRITE_RSP,FINISH,FAILED} state_t;
    state_t state;
    logic [31:0] command_address,amount,source_address,destination_address,table_address;
    logic [31:0] count,source_elements,lane,index_data,wait_cycles;
    logic [63:0] word_data;
    logic [15:0] lane_data;
    logic [3:0] word_index;
    logic [1:0] part;
    logic index_high,request_pending,outstanding;
    logic [7:0] saved_code;
    wire [32:0] aperture_end={1'b0,BASE}+BYTES;
    // The bounds on count/source_elements are checked before using these
    // shifts. Widen first so overflow cannot wrap a descriptor into the window.
    wire [32:0] source_end={1'b0,source_address}+({1'b0,source_elements}<<1);
    wire [32:0] destination_end={1'b0,destination_address}+({1'b0,count}<<1);
    wire [32:0] table_end={1'b0,table_address}+({1'b0,count}<<2);
    wire [32:0] command_end={1'b0,command_address}+33'd72;
    wire req_fire=mem_req_valid&&mem_req_ready;
    wire rsp_fire=mem_rsp_valid&&mem_rsp_ready;
    wire waiting=state==CMD_RSP||state==INDEX_RSP||state==SOURCE_RSP||state==WRITE_RSP;
    logic bad_status,bad_data;
    assign quiescent=state==IDLE&&!request_pending&&!outstanding&&!start_valid;
    assign start_ready=rst_n&&state==IDLE&&!request_pending&&!outstanding;
    assign busy=rst_n&&state!=IDLE&&state!=FAILED;
    assign done=rst_n&&state==FINISH;
    assign error=rst_n&&state==FAILED;
    assign error_code=error ? saved_code : 8'd0;
    assign mem_req_valid=rst_n&&request_pending;
    assign mem_rsp_ready=rst_n&&(outstanding||state==FAILED);
    always @* begin
        bad_status=mem_rsp_error;bad_data=0;
`ifndef SYNTHESIS
        if(mem_rsp_error!==1'b0)bad_status=1;
        if((^mem_rsp_rdata)===1'bx)bad_data=1;
`endif
    end
    function automatic logic overlaps(input logic [31:0] a,b,input logic [32:0] ae,be);
        overlaps={1'b0,a}<be&&{1'b0,b}<ae;
    endfunction
    function automatic logic in_window(input logic [31:0] a,input logic [32:0] e);
        in_window=a>=BASE&&e<=aperture_end&&e>{1'b0,a};
    endfunction
    task automatic fail(input logic [7:0] code);
        state<=FAILED;saved_code<=code;
        // Do not clear request_pending or outstanding here.
    endtask
    task automatic request(input logic wr,input logic [31:0] addr,input logic [15:0] data);
        request_pending<=1;mem_req_write<=wr;mem_req_addr<=addr;mem_req_wdata<=data;
    endtask
    initial if(BYTES<72||aperture_end>33'h100000000||TIMEOUT_CYCLES==0)
        $fatal(1,"Invalid raw layout aperture/timeout");
    always @(posedge clk)begin
        if(!rst_n)begin
            state<=IDLE;command_address<=0;amount<=0;source_address<=0;destination_address<=0;table_address<=0;
            count<=0;source_elements<=0;lane<=0;index_data<=0;wait_cycles<=0;word_data<=0;lane_data<=0;
            word_index<=0;part<=0;index_high<=0;request_pending<=0;outstanding<=0;saved_code<=0;
            mem_req_write<=0;mem_req_addr<=0;mem_req_wdata<=0;
        end else begin
            if(req_fire)begin request_pending<=0;outstanding<=1;end
            if(rsp_fire)outstanding<=0;
            if(state!=FAILED)begin
                if(mem_rsp_valid&&!outstanding)fail(7);
                else if(rsp_fire&&(bad_status||(state!=WRITE_RSP&&bad_data)))fail(bad_status ? 8'd5 : 8'd6);
                else if(waiting&&!req_fire&&!rsp_fire&&wait_cycles==TIMEOUT_CYCLES-1)fail(8);
                else begin
                    if(!waiting||req_fire||rsp_fire)wait_cycles<=0;
                    else wait_cycles<=wait_cycles+1'b1;
                    case(state)
                        IDLE:if(start_valid&&start_ready)begin
                            command_address<=start_address;amount<=start_amount;state<=START_CHECK;
                        end
                        START_CHECK:begin
                            if(amount!=9||command_address[3:0]!=0||!in_window(command_address,command_end))fail(1);
                            else begin word_index<=0;part<=0;state<=CMD_REQ;end
                        end
                        CMD_REQ:begin
                            request(0,command_address+{25'd0,word_index,3'b0}+{29'd0,part,1'b0},0);state<=CMD_RSP;
                        end
                        CMD_RSP:if(rsp_fire)begin
                            word_data[16*part+:16]<=mem_rsp_rdata;
                            if(part==3)state<=CMD_CHECK;
                            else begin part<=part+1'b1;state<=CMD_REQ;end
                        end
                        CMD_CHECK:begin
                            if(word_data[63:48]!=16'hff01||word_data[15:0]!={10'd0,word_index,2'b0})fail(2);
                            else if((word_index==0&&word_data[47:16]!=32'h00010002)||
                                    ((word_index==6||word_index==7)&&word_data[47:16]!=0)||
                                    (word_index==8&&word_data[47:16]!=1))fail(2);
                            else begin
                                case(word_index)
                                    1:source_address<=word_data[47:16];
                                    2:destination_address<=word_data[47:16];
                                    3:table_address<=word_data[47:16];
                                    4:count<=word_data[47:16];
                                    5:source_elements<=word_data[47:16];
                                    default:begin end
                                endcase
                                if(word_index==8)state<=SPAN_CHECK;
                                else begin word_index<=word_index+1'b1;part<=0;state<=CMD_REQ;end
                            end
                        end
                        SPAN_CHECK:begin
                            if(count==0||source_elements==0||{1'b0,count}>(BYTES>>2)||
                                {1'b0,source_elements}>(BYTES>>1)||source_address[0]||destination_address[0]||table_address[1:0]!=0||
                                !in_window(source_address,source_end)||!in_window(destination_address,destination_end)||
                                !in_window(table_address,table_end)||
                                overlaps(source_address,destination_address,source_end,destination_end)||
                                overlaps(source_address,table_address,source_end,table_end)||
                                overlaps(source_address,command_address,source_end,command_end)||
                                overlaps(destination_address,table_address,destination_end,table_end)||
                                overlaps(destination_address,command_address,destination_end,command_end)||
                                overlaps(table_address,command_address,table_end,command_end))fail(3);
                            else begin lane<=0;index_high<=0;state<=INDEX_REQ;end
                        end
                        INDEX_REQ:begin
                            request(0,table_address+(lane<<2)+{30'd0,index_high,1'b0},0);state<=INDEX_RSP;
                        end
                        INDEX_RSP:if(rsp_fire)begin
                            if(index_high)begin index_data[31:16]<=mem_rsp_rdata;state<=INDEX_CHECK;end
                            else begin index_data[15:0]<=mem_rsp_rdata;index_high<=1;state<=INDEX_REQ;end
                        end
                        INDEX_CHECK:begin
                            if(index_data==32'hffffffff)begin lane_data<=0;state<=WRITE_REQ;end
                            else if(index_data>=source_elements)fail(4);
                            else state<=SOURCE_REQ;
                        end
                        SOURCE_REQ:begin request(0,source_address+(index_data<<1),0);state<=SOURCE_RSP;end
                        SOURCE_RSP:if(rsp_fire)begin lane_data<=mem_rsp_rdata;state<=WRITE_REQ;end
                        WRITE_REQ:begin request(1,destination_address+(lane<<1),lane_data);state<=WRITE_RSP;end
                        WRITE_RSP:if(rsp_fire)begin
                            if(lane==count-1)state<=FINISH;
                            else begin lane<=lane+1'b1;index_high<=0;state<=INDEX_REQ;end
                        end
                        FINISH:if(result_ready)state<=IDLE;
                        default:fail(7);
                    endcase
                end
            end
        end
    end
endmodule
