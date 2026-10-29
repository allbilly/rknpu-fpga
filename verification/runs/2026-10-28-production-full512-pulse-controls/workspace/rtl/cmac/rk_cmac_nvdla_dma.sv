// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Staged standalone CMAC descriptor path. Backend amount=45 counts the body;
// all 49 final QWORDs are fetched unchanged, including the CMAC-specific tail.
// Not an EW chain parser, RK DRM ABI, PCIe shell or runtime gather fallback.
module rk_cmac_nvdla_dma #(parameter int unsigned TIMEOUT_CYCLES=65536) (
    input logic clk,rst_n,start_valid,
    output logic start_ready,
    input logic [31:0] start_address,start_amount,
    output logic busy,done,acknowledged,address_done,operand_done,error,
    output logic [7:0] error_code,
    output logic mem_req_valid,
    input logic mem_req_ready,
    output logic mem_req_write,
    output logic [31:0] mem_req_addr,
    output logic [15:0] mem_req_wdata,
    input logic mem_rsp_valid,
    output logic mem_rsp_ready,
    input logic [15:0] mem_rsp_rdata,
    input logic mem_rsp_error
);
    typedef enum logic [2:0] {IDLE,CHECK,FETCH_REQ,FETCH_WAIT,SEND,RUN} state_t;
    state_t state;
    logic [31:0] address,amount,stalled_cycles;
    logic [32:0] command_end;
    logic [5:0] word_index;
    logic [1:0] part;
    logic [63:0] word_data;
    logic fault,core_ready,core_busy,core_done,core_ack,core_error;
    logic core_address_done,core_operand_done,core_req,core_write,core_rsp_ready;
    logic [7:0] saved_code,core_code;
    logic [31:0] core_address,key,expected_key;
    logic [15:0] core_data;
    logic framing_ok,is_tail_key,fetch_progress,bad_status,bad_data;
    initial if (TIMEOUT_CYCLES==0) $fatal(1,"invalid CMAC DMA timeout");
    assign error=rst_n&&(fault||core_error);
    assign error_code=!rst_n ? 8'd0 : fault ? saved_code : core_code;
    assign start_ready=rst_n&&!error&&state==IDLE&&!core_busy;
    assign busy=rst_n&&!error&&state!=IDLE;
    assign done=rst_n&&!error&&state==RUN&&core_done;
    assign acknowledged=rst_n&&!error&&state==RUN&&core_ack;
    assign address_done=core_address_done&&!error;
    assign operand_done=core_operand_done&&!error;
    assign command_end={1'b0,address}+33'd392;
    assign key={word_data[63:48],word_data[15:0]};
    assign is_tail_key=key==32'h00010000||key==32'h01010014||key==32'h00410000||key==32'h00810008;
    always @* begin
        expected_key=0;
        case (word_index)
            45:expected_key=32'h00010000;
            46:expected_key=32'h01010014;
            47:expected_key=32'h00410000;
            48:expected_key=32'h00810008;
            default:begin end
        endcase
        framing_ok=expected_key==0 ? !is_tail_key : key==expected_key;
        bad_status=mem_rsp_error;
        bad_data=0;
`ifndef SYNTHESIS
        if (mem_rsp_error!==1'b0) bad_status=1;
        if ((^mem_rsp_rdata)===1'bx) bad_data=1;
`endif
    end
    assign fetch_progress=(state==FETCH_REQ&&mem_req_ready)||(state==FETCH_WAIT&&mem_rsp_valid);
    rk_cmac_nvdla_core #(.TIMEOUT_CYCLES(TIMEOUT_CYCLES)) core(
        .clk,.rst_n,.cmd_valid(state==SEND&&framing_ok&&!error),.cmd_ready(core_ready),.cmd_data(word_data),
        .busy(core_busy),.done(core_done),.acknowledged(core_ack),.address_done(core_address_done),
        .operand_done(core_operand_done),.error(core_error),.error_code(core_code),
        .mem_req_valid(core_req),.mem_req_ready(mem_req_ready&&state==RUN&&!error),
        .mem_req_write(core_write),.mem_req_addr(core_address),.mem_req_wdata(core_data),
        .mem_rsp_valid(mem_rsp_valid&&state==RUN&&!error),.mem_rsp_ready(core_rsp_ready),
        .mem_rsp_rdata,.mem_rsp_error);
    always @* begin
        mem_req_valid=0;mem_req_write=0;mem_req_addr=0;mem_req_wdata=0;mem_rsp_ready=0;
        if (rst_n&&!error) case (state)
            FETCH_REQ:begin
                mem_req_valid=1;mem_req_addr=address+{23'd0,word_index,3'b0}+{29'd0,part,1'b0};
            end
            FETCH_WAIT:mem_rsp_ready=1;
            RUN:begin
                mem_req_valid=core_req;mem_req_write=core_write;mem_req_addr=core_address;
                mem_req_wdata=core_data;mem_rsp_ready=core_rsp_ready;
            end
            default:begin end
        endcase
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state<=IDLE;address<=0;amount<=0;word_index<=0;part<=0;word_data<=0;
            stalled_cycles<=0;fault<=0;saved_code<=0;
        end else begin
            if (!fault&&core_error) begin fault<=1;saved_code<=core_code;end
            if (error) state<=IDLE;
            else begin
                if ((state!=FETCH_REQ&&state!=FETCH_WAIT)||fetch_progress) stalled_cycles<=0;
                else stalled_cycles<=stalled_cycles+1'b1;
                case (state)
                    IDLE:if (start_valid&&start_ready) begin
                        address<=start_address;amount<=start_amount;state<=CHECK;
                    end
                    CHECK:begin
                        if (amount!=45||address[3:0]!=0||command_end>33'h100000000) begin
                            fault<=1;saved_code<=7;state<=IDLE;
                        end else begin word_index<=0;part<=0;state<=FETCH_REQ;end
                    end
                    FETCH_REQ:if (mem_req_ready) state<=FETCH_WAIT;
                    FETCH_WAIT:if (mem_rsp_valid) begin
                        if (bad_status||bad_data) begin fault<=1;saved_code<=bad_status ? 8'd5 : 8'd6;state<=IDLE;end
                        else begin
                            word_data[16*part+:16]<=mem_rsp_rdata;
                            if (part==3) state<=SEND;
                            else begin part<=part+1'b1;state<=FETCH_REQ;end
                        end
                    end
                    SEND:begin
                        if (!framing_ok) begin fault<=1;saved_code<=3;state<=IDLE;end
                        else if (core_ready) begin
                            if (word_index==48) state<=RUN;
                            else begin word_index<=word_index+1'b1;part<=0;state<=FETCH_REQ;end
                        end
                    end
                    RUN:if (core_done) state<=IDLE;
                    default:begin fault<=1;saved_code<=7;state<=IDLE;end
                endcase
                if ((state==FETCH_REQ||state==FETCH_WAIT)&&!fetch_progress&&stalled_cycles>=TIMEOUT_CYCLES-1) begin
                    fault<=1;saved_code<=8;state<=IDLE;
                end
            end
        end
    end
endmodule
