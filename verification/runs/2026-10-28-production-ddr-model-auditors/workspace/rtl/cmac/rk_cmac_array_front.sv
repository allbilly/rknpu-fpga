// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Raw terminal RK command words -> C32/K16 physical operand frames.
// Reuses the strict profile decoder unchanged. This bounded frame buffer is
// not a complete CBUF/CSC implementation or an execution/completion endpoint.
module rk_cmac_array_front #(parameter int unsigned TIMEOUT_CYCLES=65536) (
    input wire clk,rst_n,cmd_valid,
    output wire cmd_ready,
    input wire [63:0] cmd_data,
    input wire downstream_busy,cancel,
    input wire [7:0] cancel_code,
    output wire busy,error,
    output logic stream_done,
    output wire [7:0] error_code,
    output wire mem_req_valid,
    input wire mem_req_ready,
    output logic [31:0] mem_req_addr,
    input wire mem_rsp_valid,
    output wire mem_rsp_ready,
    input wire [15:0] mem_rsp_rdata,
    input wire mem_rsp_error,
    output wire frame_valid,
    input wire frame_ready,
    output logic [511:0] frame_data,
    output logic [8191:0] frame_weight,
    output wire [31:0] frame_data_mask,
    output wire [511:0] frame_weight_mask,
    output wire [31:0] frame_output_address,frame_row,frame_oc,frame_ic,
    output wire frame_first,frame_last,frame_last_output
);
    typedef enum logic [2:0] {IDLE,DATA_REQ,DATA_WAIT,WEIGHT_REQ,WEIGHT_WAIT,EMIT} state_t;
    state_t state;
    wire config_valid,decode_error;
    wire [7:0] decode_code;
    wire [31:0] config_rows,config_input_channels,config_output_channels;
    wire [31:0] config_input_base,config_weight_base,config_output_base;
    logic [31:0] rows,ai,ao,row_index,oc,ic;
    logic [31:0] input_row_base,input_group_base,weight_origin,weight_atom_base,weight_group_base;
    logic [31:0] output_row_base,output_atom_base,stalled_cycles;
    logic [8:0] read_index;
    logic fault,response_data_legal;
    logic [7:0] saved_code,normalized_cancel;
    // Once the raw trigger is accepted, downstream ownership may rise before
    // this handshake. It blocks new command words, not the accepted task.
    wire config_ready=rst_n&&!error&&state==IDLE;
    wire memory_state=state==DATA_REQ||state==DATA_WAIT||state==WEIGHT_REQ||state==WEIGHT_WAIT;
    wire progress=(mem_req_valid&&mem_req_ready)||(mem_rsp_valid&&mem_rsp_ready);
    initial if(TIMEOUT_CYCLES==0) $fatal(1,"TIMEOUT_CYCLES must be positive");
    always @* begin
        case(cancel_code)
            1,2,3,4,5,6,7,8:normalized_cancel=cancel_code;
            default:normalized_cancel=6;
        endcase
        response_data_legal=1;
`ifndef SYNTHESIS
        if((^mem_rsp_rdata)===1'bx) response_data_legal=0;
`endif
    end
    assign error=rst_n&&(fault||cancel||decode_error);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : cancel ? normalized_cancel : decode_error ? decode_code : 8'd0;
    assign busy=rst_n&&!error&&(state!=IDLE||config_valid||downstream_busy);
    assign mem_req_valid=rst_n&&!error&&(state==DATA_REQ||state==WEIGHT_REQ);
    assign mem_rsp_ready=rst_n&&!error&&(state==DATA_WAIT||state==WEIGHT_WAIT);
    assign frame_valid=rst_n&&!error&&state==EMIT;
    assign frame_data_mask='1;
    assign frame_weight_mask='1;
    assign frame_output_address=output_atom_base;
    assign frame_row=row_index;
    assign frame_oc=oc;
    assign frame_ic=ic;
    assign frame_first=ic==0;
    assign frame_last=ic==ai-32;
    assign frame_last_output=row_index==rows-1&&oc==ao-16;
    rk_cmac_profile profile(
        .clk,.rst_n,.cmd_valid,.cmd_ready,.cmd_data,
        .engine_busy(state!=IDLE||downstream_busy),.engine_error(fault||cancel),
        .config_valid,.config_ready,.config_rows,.config_input_channels,.config_output_channels,
        .config_input_base,.config_weight_base,.config_output_base,.error(decode_error),.error_code(decode_code));
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;fault<=0;saved_code<=0;stream_done<=0;rows<=0;ai<=0;ao<=0;row_index<=0;oc<=0;ic<=0;
            input_row_base<=0;input_group_base<=0;weight_origin<=0;weight_atom_base<=0;weight_group_base<=0;
            output_row_base<=0;output_atom_base<=0;stalled_cycles<=0;read_index<=0;mem_req_addr<=0;
            frame_data<=0;frame_weight<=0;
        end else begin
            stream_done<=0;
            if(!fault&&error) begin fault<=1;saved_code<=error_code;end
            if(!error) begin
                if(!memory_state||progress) stalled_cycles<=0;else stalled_cycles<=stalled_cycles+1;
                case(state)
                    IDLE: if(config_valid&&config_ready) begin
                        rows<=config_rows;ai<=config_input_channels;ao<=config_output_channels;
                        row_index<=0;oc<=0;ic<=0;read_index<=0;
                        input_row_base<=config_input_base;input_group_base<=config_input_base;
                        weight_origin<=config_weight_base;weight_atom_base<=config_weight_base;weight_group_base<=config_weight_base;
                        output_row_base<=config_output_base;output_atom_base<=config_output_base;
                        mem_req_addr<=config_input_base;state<=DATA_REQ;
                    end
                    DATA_REQ: if(mem_req_ready) state<=DATA_WAIT;
                    WEIGHT_REQ: if(mem_req_ready) state<=WEIGHT_WAIT;
                    DATA_WAIT,WEIGHT_WAIT: if(mem_rsp_valid) begin
                        case(mem_rsp_error)
                            1'b0: if(!response_data_legal) begin fault<=1;saved_code<=6;end
                            else if(state==DATA_WAIT) begin
                                frame_data[read_index[4:0]*16+:16]<=mem_rsp_rdata;
                                if(read_index==31) begin read_index<=0;mem_req_addr<=weight_group_base;state<=WEIGHT_REQ;end
                                else begin read_index<=read_index+1'b1;mem_req_addr<=mem_req_addr+2;state<=DATA_REQ;end
                            end else begin
                                frame_weight[read_index*16+:16]<=mem_rsp_rdata;
                                if(read_index==511) state<=EMIT;
                                else begin read_index<=read_index+1'b1;mem_req_addr<=mem_req_addr+2;state<=WEIGHT_REQ;end
                            end
                            default:begin fault<=1;saved_code<=5;end
                        endcase
                    end
                    EMIT: if(frame_ready) begin
                        read_index<=0;
                        if(!frame_last) begin
                            ic<=ic+32;input_group_base<=input_group_base+64;weight_group_base<=weight_group_base+1024;
                            mem_req_addr<=input_group_base+64;state<=DATA_REQ;
                        end else if(frame_last_output) begin state<=IDLE;stream_done<=1;end
                        else begin
                            ic<=0;state<=DATA_REQ;
                            if(oc!=ao-16) begin
                                oc<=oc+16;input_group_base<=input_row_base;mem_req_addr<=input_row_base;
                                weight_atom_base<=weight_atom_base+(ai<<5);weight_group_base<=weight_atom_base+(ai<<5);
                                output_atom_base<=output_atom_base+64;
                            end else begin
                                oc<=0;row_index<=row_index+1;
                                input_row_base<=input_row_base+(ai<<1);input_group_base<=input_row_base+(ai<<1);mem_req_addr<=input_row_base+(ai<<1);
                                weight_atom_base<=weight_origin;weight_group_base<=weight_origin;
                                output_row_base<=output_row_base+(ao<<2);output_atom_base<=output_row_base+(ao<<2);
                            end
                        end
                    end
                    default:begin fault<=1;saved_code<=6;end
                endcase
                if(memory_state&&!progress&&stalled_cycles>=TIMEOUT_CYCLES-1) begin fault<=1;saved_code<=8;end
            end
        end
    end
endmodule
