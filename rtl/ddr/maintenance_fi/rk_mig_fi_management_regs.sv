// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private RKFI management bank. These are FPGA diagnostic CSR words, not RK
// NPU command registers. It never issues tensor arithmetic or repairs data.
// CLAIM is retained until joint reset. Successful line responses require all
// sixteen raw words to be consumed before ACK; ACK never releases ownership.
module rk_mig_fi_management_regs #(
    parameter logic [31:0] BASE=0,
    parameter logic [32:0] BYTES=33'h080000000,
    parameter int unsigned TIMEOUT_CYCLES=65536
) (
    input logic clk,joint_rst_n,claim_eligible,startup_complete,memory_initialized,
    input logic parent_fault,control_fault,recovery_required,owner_granted,
    output logic owner_request,local_fault,transaction_quiet,
    output logic [7:0] local_fault_code,
    input logic [71:0] observed_mask,
    input logic [8:0] known_mask_bytes,
    input logic mask_disarmed,
    input logic mc_ecc_valid,mc_read_data_valid,fi_clear,
    input logic [7:0] mc_single,mc_multiple,
    input logic [28:0] mc_ecc_address,
    output logic ctrl_req_valid,ctrl_req_write,
    input logic ctrl_req_ready,
    output logic [31:0] ctrl_req_address,ctrl_req_data,
    output logic [3:0] ctrl_req_strobe,
    output logic [2:0] ctrl_req_protection,
    input logic ctrl_rsp_valid,
    output logic ctrl_rsp_ready,
    input logic [1:0] ctrl_rsp_response,
    output logic line_req_valid,line_req_write,
    input logic line_req_ready,
    output logic [31:0] line_req_address,
    output logic [511:0] line_req_data,
    output logic [1:0] line_expected_response,
    input logic line_rsp_valid,line_rsp_matched,
    output logic line_rsp_ready,
    input logic [511:0] line_rsp_data,
    input logic [1:0] line_rsp_response,
    input logic [31:0] s_axil_awaddr,s_axil_wdata,s_axil_araddr,
    input logic [2:0] s_axil_awprot,s_axil_arprot,
    input logic [3:0] s_axil_wstrb,
    input logic s_axil_awvalid,s_axil_wvalid,s_axil_bready,s_axil_arvalid,s_axil_rready,
    output logic s_axil_awready,s_axil_wready,s_axil_bvalid,s_axil_arready,s_axil_rvalid,
    output logic [1:0] s_axil_bresp,s_axil_rresp,
    output logic [31:0] s_axil_rdata
);
    typedef enum logic [2:0] {IDLE,WAIT_OWNER,ISSUE_CTRL,WAIT_CTRL,ISSUE_LINE,WAIT_LINE} state_t;
    state_t state;
    logic claimed,grant_seen,aw_held,w_held,result_valid,result_matched;
    logic [31:0] saved_awaddr,saved_wdata;
    logic [2:0] saved_awprot;
    logic [3:0] saved_wstrb;
    logic [31:0] staged_ctrl_address,staged_ctrl_data,staged_line_address;
    logic [1:0] staged_expected_response,result_response;
    logic [511:0] staged_line_data,result_data;
    logic [3:0] fields_valid;
    logic [15:0] data_valid_words,result_consumed_words;
    logic [2:0] active_command,result_command;
    logic [31:0] wait_count,command_ordinal,ce_count,ue_count,clear_count,read_count;
    logic [28:0] last_ecc_address;
    logic [17:0] last_ecc_meta;
    logic [31:0] last_line_address,last_ctrl_address;
    logic write_commit,write_ok,write_mapped,program_allowed,busy;
    logic do_claim,do_ctrl,do_line_write,do_line_read,do_ack;
    logic write_data_word;
    logic [3:0] write_word_index,read_word_index,held_result_word_index;
    logic read_result_word,held_result_word;
    logic [31:0] read_value,status_word;
    logic [1:0] read_response;
    logic line_address_in_range;
    logic [7:0] fault_now;
    wire below_base;
    if(BASE==0)begin: zero_base
        assign below_base=0;
    end else begin: nonzero_base
        assign below_base={1'b0,saved_wdata}<{1'b0,BASE};
    end
    initial begin
        if(BASE[31]||BASE[5:0]!=0||BYTES<64||BYTES[5:0]!=0||
           {1'b0,BASE}+BYTES>33'h080000000||TIMEOUT_CYCLES==0)
            $fatal(1,"Invalid private RKFI geometry/timeout");
    end
    assign busy=state!=IDLE;
    // Result ownership, all partial AXI-Lite channels and downstream request/
    // response state are consumed before a live whole-reset quiet witness.
    // CLAIM itself remains retained until joint reset and is not bus traffic.
    assign transaction_quiet=joint_rst_n && state==IDLE && !aw_held && !w_held &&
        !s_axil_bvalid && !s_axil_rvalid && !result_valid &&
        !ctrl_req_valid && !ctrl_rsp_valid && !line_req_valid && !line_rsp_valid;

    assign owner_request=joint_rst_n&&claimed;
    assign program_allowed=claimed&&owner_granted===1'b1&&!busy&&!result_valid&&!local_fault&&
        fault_now==0&&control_fault===1'b0&&command_ordinal!=32'hffffffff;
    assign write_commit=aw_held&&w_held&&!s_axil_bvalid;
    assign s_axil_awready=joint_rst_n&&!aw_held&&!s_axil_bvalid;
    assign s_axil_wready=joint_rst_n&&!w_held&&!s_axil_bvalid;
    assign s_axil_arready=joint_rst_n&&!s_axil_rvalid;
    assign ctrl_req_valid=joint_rst_n&&state==ISSUE_CTRL;
    assign ctrl_req_write=1;
    assign ctrl_req_address=staged_ctrl_address;
    assign ctrl_req_data=staged_ctrl_data;
    assign ctrl_req_strobe=4'hf;
    assign ctrl_req_protection=0;
    assign ctrl_rsp_ready=joint_rst_n&&state==WAIT_CTRL;
    assign line_req_valid=joint_rst_n&&state==ISSUE_LINE;
    assign line_req_write=active_command==3;
    assign line_req_address=staged_line_address;
    assign line_req_data=staged_line_data;
    assign line_expected_response=staged_expected_response;
    assign line_rsp_ready=joint_rst_n&&state==WAIT_LINE;
    assign line_address_in_range=(^saved_wdata)!==1'bx&&saved_wdata[5:0]===0&&!below_base&&
        {1'b0,saved_wdata}+33'd64<={1'b0,BASE}+BYTES;
    always_comb begin
        status_word=0;
        status_word[0]=!claimed&&!local_fault&&fault_now==0&&owner_granted===1'b0&&
            claim_eligible===1'b1&&startup_complete===1'b1&&memory_initialized===1'b1&&
            parent_fault===1'b0&&control_fault===1'b0&&mask_disarmed===1'b1&&
            known_mask_bytes===9'h1ff&&observed_mask===72'b0;
        status_word[1]=claimed;status_word[2]=owner_granted;status_word[3]=busy;
        status_word[4]=result_valid;status_word[5]=result_matched;status_word[6]=recovery_required;
        status_word[7]=parent_fault;status_word[8]=control_fault;status_word[9]=local_fault;
        status_word[10]=memory_initialized;status_word[12]=mask_disarmed;status_word[13]=startup_complete;
        write_ok=0;write_mapped=0;do_claim=0;do_ctrl=0;do_line_write=0;do_line_read=0;do_ack=0;
        write_data_word=0;write_word_index=0;
        if((^saved_awaddr)!==1'bx&&saved_awaddr[31:8]===24'h000003&&saved_awaddr[1:0]===0)begin
            case(saved_awaddr)
                32'h30c:begin
                    write_mapped=1;
                    case(saved_wdata)
                        32'd1:if(status_word[0]&&!busy&&!result_valid)begin write_ok=1;do_claim=1;end
                        32'd2:if(program_allowed&&fields_valid[1:0]===2'b11&&
                            (staged_ctrl_address!==32'h380||staged_ctrl_data[31:8]===0))begin write_ok=1;do_ctrl=1;end
                        32'd3:if(program_allowed&&fields_valid[3:2]===2'b11&&
                            staged_expected_response===0&&data_valid_words===16'hffff)begin write_ok=1;do_line_write=1;end
                        32'd4:if(program_allowed&&fields_valid[3:2]===2'b11)begin write_ok=1;do_line_read=1;end
                        32'd5:if(!busy&&result_valid&&(result_command!=4||result_consumed_words===16'hffff))begin write_ok=1;do_ack=1;end
                        default:begin end
                    endcase
                end
                32'h310:begin write_mapped=1;write_ok=program_allowed&&
                    (saved_wdata===32'h300||saved_wdata===32'h304||saved_wdata===32'h380);end
                32'h314:begin write_mapped=1;write_ok=program_allowed;end
                32'h318:begin write_mapped=1;write_ok=program_allowed&&line_address_in_range;end
                32'h31c:begin write_mapped=1;write_ok=program_allowed&&(saved_wdata===0||saved_wdata===2);end
                32'h300,32'h304,32'h308,32'h320,32'h324,32'h328,32'h32c,32'h330,32'h334,
                32'h338,32'h33c,32'h340,32'h344,32'h348,32'h34c,32'h350,32'h354,32'h358,32'h35c:
                    write_mapped=1;
                32'h3e0,32'h3e4,32'h3e8:write_mapped=1;
                default:begin end
            endcase
            for(int word_index=0;word_index<16;word_index++)begin
                if(saved_awaddr===32'h360+32'(word_index*4))begin
                    write_mapped=1;write_ok=program_allowed;write_data_word=1;write_word_index=4'(word_index);
                end
                if(saved_awaddr===32'h3a0+32'(word_index*4))write_mapped=1;
            end
        end
        if(saved_awprot!==0||saved_wstrb!==4'hf||(^saved_wdata)===1'bx||saved_awaddr[1:0]!==0)write_ok=0;
    end
    always_comb begin
        read_value=0;read_response=2'b11;read_result_word=0;read_word_index=0;
        if((^s_axil_araddr)!==1'bx&&s_axil_araddr[31:8]===24'h000003&&s_axil_araddr[1:0]===0)begin
            case(s_axil_araddr)
                32'h300:begin read_value=32'h524b4649;read_response=0;end
                32'h304:begin read_value=32'h00010000;read_response=0;end
                32'h308:begin read_value=status_word;read_response=0;end
                32'h310:begin read_value=staged_ctrl_address;read_response=0;end
                32'h314:begin read_value=staged_ctrl_data;read_response=0;end
                32'h318:begin read_value=staged_line_address;read_response=0;end
                32'h31c:begin read_value={30'b0,staged_expected_response};read_response=0;end
                32'h320:begin read_value={13'b0,result_command,7'b0,result_matched,6'b0,result_response};read_response=0;end
                32'h324:begin read_value={24'b0,local_fault_code};read_response=0;end
                32'h328:begin read_value={23'b0,known_mask_bytes};read_response=0;end
                32'h32c:begin read_value=observed_mask[31:0];read_response=0;end
                32'h330:begin read_value=observed_mask[63:32];read_response=0;end
                32'h334:begin read_value={24'b0,observed_mask[71:64]};read_response=0;end
                32'h338:begin read_value=ce_count;read_response=0;end
                32'h33c:begin read_value=ue_count;read_response=0;end
                32'h340:begin read_value={3'b0,last_ecc_address};read_response=0;end
                32'h344:begin read_value={14'b0,last_ecc_meta};read_response=0;end
                32'h348:begin read_value=clear_count;read_response=0;end
                32'h34c:begin read_value=read_count;read_response=0;end
                32'h350:begin read_value=last_line_address;read_response=0;end
                32'h354:begin read_value=last_ctrl_address;read_response=0;end
                32'h358:begin read_value=command_ordinal;read_response=0;end
                32'h35c:begin read_value={data_valid_words,12'b0,fields_valid};read_response=0;end
                32'h3e0:begin read_value=BASE;read_response=0;end
                32'h3e4:begin read_value=BYTES[31:0];read_response=0;end
                32'h3e8:begin read_value=32'h00010040;read_response=0;end
                32'h30c:read_response=2'b10;
                default:begin end
            endcase
            for(int word_index=0;word_index<16;word_index++)begin
                if(s_axil_araddr===32'h360+32'(word_index*4))read_response=2'b10;
                if(s_axil_araddr===32'h3a0+32'(word_index*4))begin
                    read_response=2'b10;
                    if(result_valid&&result_command==4)begin
                        read_response=0;read_value=result_data[word_index*32+:32];
                        read_result_word=1;read_word_index=4'(word_index);
                    end
                end
            end
        end
        if(s_axil_arprot!==0||s_axil_araddr[1:0]!==0)read_response=2'b10;
        if(read_response!=0)begin read_value=0;read_result_word=0;end
    end
    always_comb begin
        fault_now=0;
        if(busy&&wait_count>=TIMEOUT_CYCLES-1)fault_now=1;
        else if((ctrl_rsp_valid!==1'b0&&(ctrl_rsp_valid!==1'b1||state!=WAIT_CTRL))||
                (line_rsp_valid!==1'b0&&(line_rsp_valid!==1'b1||state!=WAIT_LINE)))fault_now=2;
        else if(claimed&&grant_seen&&owner_granted!==1'b1)fault_now=3;
        else if(startup_complete===1'b1&&((mc_ecc_valid!==1'b0&&mc_ecc_valid!==1'b1)||
                (mc_read_data_valid!==1'b0&&mc_read_data_valid!==1'b1)||
                (fi_clear!==1'b0&&fi_clear!==1'b1)||
                (mc_ecc_valid===1'b1&&((^mc_single)===1'bx||(^mc_multiple)===1'bx||
                    ((|mc_single|| |mc_multiple)&&(^mc_ecc_address)===1'bx)))))fault_now=4;
        else if(startup_complete===1'b1&&((mc_ecc_valid&&|mc_single&&ce_count==32'hffffffff)||
                (mc_ecc_valid&&|mc_multiple&&ue_count==32'hffffffff)||
                (fi_clear&&clear_count==32'hffffffff)||(mc_read_data_valid&&read_count==32'hffffffff)))fault_now=5;
        else if(claimed&&control_fault!==1'b0)fault_now=6;
        else if((state==WAIT_CTRL&&ctrl_rsp_valid===1'b1&&ctrl_rsp_response!==0)||
                (state==WAIT_LINE&&line_rsp_valid===1'b1&&line_rsp_matched!==1'b1))fault_now=7;
    end
    always_ff @(posedge clk)begin
        if(!joint_rst_n)begin
            state<=IDLE;claimed<=0;grant_seen<=0;local_fault<=0;local_fault_code<=0;
            aw_held<=0;w_held<=0;saved_awaddr<=0;saved_wdata<=0;saved_awprot<=0;saved_wstrb<=0;
            s_axil_bvalid<=0;s_axil_bresp<=0;s_axil_rvalid<=0;s_axil_rresp<=0;s_axil_rdata<=0;
            staged_ctrl_address<=0;staged_ctrl_data<=0;staged_line_address<=0;staged_expected_response<=0;
            staged_line_data<=0;fields_valid<=0;data_valid_words<=0;
            active_command<=0;result_command<=0;result_data<=0;result_response<=0;
            result_valid<=0;result_matched<=0;result_consumed_words<=0;
            held_result_word<=0;held_result_word_index<=0;wait_count<=0;command_ordinal<=0;
            ce_count<=0;ue_count<=0;clear_count<=0;read_count<=0;last_ecc_address<=0;last_ecc_meta<=0;
            last_line_address<=0;last_ctrl_address<=0;
        end else begin
            if(!local_fault&&fault_now!=0)begin local_fault<=1;local_fault_code<=fault_now;end
            if(claimed&&owner_granted===1'b1)grant_seen<=1;
            if(busy)begin if(wait_count<TIMEOUT_CYCLES)wait_count<=wait_count+1'b1;end
            else wait_count<=0;
            if(s_axil_bvalid&&s_axil_bready)s_axil_bvalid<=0;
            if(s_axil_rvalid&&s_axil_rready)begin
                s_axil_rvalid<=0;
                if(held_result_word)result_consumed_words[held_result_word_index]<=1;
                held_result_word<=0;
            end
            if(s_axil_awvalid&&s_axil_awready)begin aw_held<=1;saved_awaddr<=s_axil_awaddr;saved_awprot<=s_axil_awprot;end
            if(s_axil_wvalid&&s_axil_wready)begin w_held<=1;saved_wdata<=s_axil_wdata;saved_wstrb<=s_axil_wstrb;end
            if(s_axil_arvalid&&s_axil_arready)begin
                s_axil_rvalid<=1;s_axil_rdata<=read_value;s_axil_rresp<=read_response;
                held_result_word<=read_result_word;held_result_word_index<=read_word_index;
            end
            // Counts never clear on CLAIM or ACK. An overflow is sticky failure,
            // preserving the saturated observed count until whole-domain reset.
            if(startup_complete===1'b1)begin
                if(mc_ecc_valid===1'b1)begin
                    if(|mc_single&&ce_count!=32'hffffffff)ce_count<=ce_count+1'b1;
                    if(|mc_multiple&&ue_count!=32'hffffffff)ue_count<=ue_count+1'b1;
                    if(|mc_single|| |mc_multiple)begin
                        last_ecc_address<=mc_ecc_address;last_ecc_meta<={mc_read_data_valid,mc_ecc_valid,mc_multiple,mc_single};
                    end
                end
                if(fi_clear===1'b1&&clear_count!=32'hffffffff)clear_count<=clear_count+1'b1;
                if(mc_read_data_valid===1'b1&&read_count!=32'hffffffff)read_count<=read_count+1'b1;
            end
            case(state)
                WAIT_OWNER:if(owner_granted===1'b1)begin
                    state<=IDLE;result_valid<=1;result_matched<=!local_fault&&fault_now==0;
                    result_response<=0;result_data<=0;result_command<=1;result_consumed_words<=0;
                end
                ISSUE_CTRL:if(ctrl_req_valid&&ctrl_req_ready)state<=WAIT_CTRL;
                WAIT_CTRL:if(ctrl_rsp_valid===1'b1)begin
                    state<=IDLE;result_valid<=1;result_matched<=ctrl_rsp_response===0&&!local_fault&&fault_now==0;
                    result_response<=ctrl_rsp_response;result_data<=0;result_command<=2;result_consumed_words<=0;
                end
                ISSUE_LINE:if(line_req_valid&&line_req_ready)state<=WAIT_LINE;
                WAIT_LINE:if(line_rsp_valid===1'b1)begin
                    state<=IDLE;result_valid<=1;result_matched<=line_rsp_matched===1'b1&&!local_fault&&fault_now==0;
                    result_response<=line_rsp_response;result_data<=line_rsp_data;result_command<=active_command;result_consumed_words<=0;
                end
                default:begin end
            endcase
            if(write_commit)begin
                aw_held<=0;w_held<=0;s_axil_bvalid<=1;
                s_axil_bresp<=write_ok?2'b00:(write_mapped?2'b10:2'b11);
                if(write_ok)begin
                    if(write_data_word)begin staged_line_data[write_word_index*32+:32]<=saved_wdata;data_valid_words[write_word_index]<=1;end
                    case(saved_awaddr)
                        32'h310:begin staged_ctrl_address<=saved_wdata;fields_valid[0]<=1;end
                        32'h314:begin staged_ctrl_data<=saved_wdata;fields_valid[1]<=1;end
                        32'h318:begin staged_line_address<=saved_wdata;fields_valid[2]<=1;end
                        32'h31c:begin staged_expected_response<=saved_wdata[1:0];fields_valid[3]<=1;end
                        default:begin end
                    endcase
                    if(do_claim)begin claimed<=1;state<=WAIT_OWNER;active_command<=1;wait_count<=0;end
                    if(do_ctrl||do_line_write||do_line_read)begin
                        command_ordinal<=command_ordinal+1'b1;wait_count<=0;
                        if(do_ctrl)begin state<=ISSUE_CTRL;active_command<=2;last_ctrl_address<=staged_ctrl_address;end
                        else begin state<=ISSUE_LINE;active_command<=do_line_write?3'd3:3'd4;last_line_address<=staged_line_address;end
                    end
                    if(do_ack)begin result_valid<=0;result_matched<=0;fields_valid<=0;data_valid_words<=0;result_consumed_words<=0;end
                end
            end
        end
    end
endmodule
