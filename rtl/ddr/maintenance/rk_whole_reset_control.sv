// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// SYS-clock maintenance component. Not selected by an existing board profile.
// power_rst_n is CONFIGURATION/startup-only, never a client/MIG/link/TAP reset.
// Remote witnesses must already be qualified into SYS by the integration.
module rk_whole_reset_control #(
    parameter logic [63:0] TIMEOUT_CYCLES = 64'd5000000000,
    parameter integer STABLE_SAMPLES = 2
) (
    input wire sys_clk, power_rst_n,
    input wire req_valid,
    output wire req_ready,
    input wire [603:0] req,
    output logic rsp_valid,
    output logic [511:0] rsp_data,
    output logic [7:0] rsp_status,
    output logic [15:0] rsp_seq,
    output logic quiesce_request,
    input wire quiesce_ack, quiescent,
    output wire reset_request,
    input wire reset_ready, reset_asserted, reset_complete, reset_fault,
    input wire [7:0] reset_fault_code,
    input wire platform_ready
);
    localparam logic [31:0] START_KEY=32'h53545254;
    localparam logic [31:0] CANCEL_KEY=32'h43414e43;
    localparam logic [31:0] ACK_KEY=32'h41434b21;
    // Keep invalid configurations elaboratable so the explicit time-zero
    // rejection below runs in both simulators. Valid limits are unchanged.
    localparam logic [63:0] SAFE_TIMEOUT=TIMEOUT_CYCLES>0?TIMEOUT_CYCLES:64'd2;
    localparam integer SAFE_SAMPLES=STABLE_SAMPLES>0?STABLE_SAMPLES:2;
    typedef enum logic [2:0] {IDLE,QUIESCE,WAIT_ASSERT,WAIT_COMPLETE,WAIT_READY,RESULT} state_t;
    state_t state;
    logic [31:0] attempts,success_epoch,stable_count;
    logic [63:0] wait_cycles;
    logic [7:0] saved_error,saved_sequence_code;
    logic [2:0] saved_phase;
    logic reset_sent,assertion_seen;
    logic fault_clear_seen,terminal_fault_seen,completion_seen;
    logic [31:0] ready_samples;
    logic failure_now;
    logic [7:0] failure_code;
    logic [31:0] status_word,read_value;
    logic [7:0] command_status;
    logic command_start,command_cancel,command_ack;
    wire active=(state===QUIESCE)||(state===WAIT_ASSERT)||
                (state===WAIT_COMPLETE)||(state===WAIT_READY);
    wire start_allowed=(state===IDLE)&&reset_ready===1'b1&&
        quiesce_ack===1'b0&&quiescent===1'b0&&
        attempts!=32'hffffffff&&success_epoch!=32'hffffffff;
    // An accepted coordinator request is never cancelled by a timeout/ACK.
    // Failed issued operations retain the barrier until terminal fault or
    // actual completion plus initialization; otherwise configuration recovery
    // is required. ACK is an explicit release, not a success/retry operation.
    wire ack_allowed=(state===RESULT)&&(!reset_sent||
        (terminal_fault_seen&&reset_fault===1'b1&&
         (^reset_fault_code)!==1'bx&&reset_fault_code>=1&&reset_fault_code<=7)||
        (assertion_seen&&completion_seen&&ready_samples>=32'(SAFE_SAMPLES)&&
         reset_complete===1'b1&&reset_fault===1'b0&&
         reset_asserted===1'b0&&platform_ready===1'b1));
    assign req_ready=power_rst_n&&!rsp_valid;
    wire command_fire=(req_valid===1'b1)&&(req_ready===1'b1);

    initial begin
        if((^TIMEOUT_CYCLES)===1'bx||TIMEOUT_CYCLES==0||
           (^STABLE_SAMPLES)===1'bx||STABLE_SAMPLES<1||STABLE_SAMPLES>65536)
            $fatal(1,"Invalid whole-reset control deadline/freshness");
    end

    always @* begin
        failure_code=0;
        if(active)begin
            if((^{quiesce_ack,quiescent,reset_ready,reset_asserted,
                  reset_complete,reset_fault,platform_ready})===1'bx)
                failure_code=7;
            else if(reset_sent&&reset_fault&&
                    ((^reset_fault_code)===1'bx||reset_fault_code<1||reset_fault_code>7))
                failure_code=7;
            else if(({1'b0,wait_cycles}+65'd1)>={1'b0,SAFE_TIMEOUT})failure_code=1;
            else if(reset_sent&&fault_clear_seen&&reset_fault)failure_code=3;
            else if(state==WAIT_READY&&(!reset_complete||reset_asserted))failure_code=4;
        end
        failure_now=failure_code!=0;
    end

    always @* begin
        status_word=0;
        status_word[0]=start_allowed;
        status_word[1]=active;
        status_word[2]=state===RESULT;
        status_word[3]=(state===RESULT)&&saved_error!=0;
        status_word[4]=quiesce_request;
        status_word[5]=reset_sent;
        status_word[6]=assertion_seen;
        status_word[7]=quiesce_ack;
        status_word[8]=quiescent;
        status_word[9]=reset_complete;
        status_word[10]=reset_fault;
        status_word[11]=platform_ready;
        read_value=0;command_status=0;
        command_start=0;command_cancel=0;command_ack=0;
        if((^req)===1'bx||req[603:572]!==32'h4f54504a||
           (req[555:548]!==8'd1&&req[555:548]!==8'd2)||
           req[547:544]!==4'hf||
           (req[555:548]===8'd1&&req[511:0]!==512'd0)||
           (req[555:548]===8'd2&&req[511:32]!==480'd0))command_status=5;
        else if(req[513:512]!==2'b00)command_status=4;
        else if(req[555:548]==1)begin
            case(req[543:512])
                32'h00:read_value=32'h524b5052; // RKPR, project maintenance ABI
                32'h04:read_value=32'h00010000;
                32'h08:read_value=status_word;
                32'h10:read_value=attempts;
                32'h14:read_value=success_epoch;
                32'h18:read_value={24'd0,saved_error};
                32'h1c:read_value=32'h00010001;
                32'h20:read_value={29'd0,saved_phase};
                32'h24:read_value={24'd0,saved_sequence_code};
                32'h28:read_value=TIMEOUT_CYCLES[31:0];
                32'h2c:read_value=TIMEOUT_CYCLES[63:32];
                default:command_status=2;
            endcase
            if((^read_value)===1'bx)command_status=2;
        end else if(req[543:512]==32'h0c)begin
            case(req[31:0])
                START_KEY:if(start_allowed&&!failure_now)command_start=1;
                          else command_status=2;
                CANCEL_KEY:if(state===QUIESCE&&!failure_now)command_cancel=1;
                           else command_status=2;
                ACK_KEY:if(ack_allowed)command_ack=1;
                        else command_status=2;
                default:command_status=2;
            endcase
        end else command_status=2;
        if(command_status!=0)read_value=0;
    end

    // One SYS-edge admission to the existing same-clock coordinator. It is
    // asserted only when READY is already known high; there is no pending
    // VALID that a local deadline could withdraw or fire after reporting FAIL.
    assign reset_request=power_rst_n&&(state===QUIESCE)&&!failure_now&&
        quiesce_ack===1'b1&&quiescent===1'b1&&reset_ready===1'b1&&
        ((({1'b0,stable_count}+33'd1)>={1'b0,32'(SAFE_SAMPLES)})===1'b1)&&
        !(command_fire&&command_cancel);

    always @(posedge sys_clk or negedge power_rst_n)begin
        if(!power_rst_n)begin
            state<=IDLE;attempts<=0;success_epoch<=0;stable_count<=0;wait_cycles<=0;
            saved_error<=0;saved_sequence_code<=0;saved_phase<=0;
            reset_sent<=0;assertion_seen<=0;quiesce_request<=0;
            fault_clear_seen<=0;terminal_fault_seen<=0;completion_seen<=0;ready_samples<=0;
            rsp_valid<=0;rsp_data<=0;rsp_status<=0;rsp_seq<=0;
        end else begin
            rsp_valid<=0;
            // Continue observing an issued operation after local timeout.
            // These witnesses can authorize explicit ACK of a failed result,
            // but never upgrade that result or increment its success epoch.
            if(reset_sent&&(active||state===RESULT))begin
                if(reset_fault===1'b0)begin
                    fault_clear_seen<=1;terminal_fault_seen<=0;
                end
                if(fault_clear_seen&&reset_fault===1'b1&&
                   (^reset_fault_code)!==1'bx&&reset_fault_code>=1&&reset_fault_code<=7)
                    terminal_fault_seen<=1;
                if(reset_asserted===1'b1&&reset_complete===1'b0&&platform_ready===1'b0)
                    assertion_seen<=1;
                if(assertion_seen&&reset_complete===1'b1&&reset_asserted===1'b0)
                    completion_seen<=1;
                if(assertion_seen&&completion_seen&&reset_complete===1'b1&&
                   reset_fault===1'b0&&reset_asserted===1'b0&&platform_ready===1'b1)begin
                    if(ready_samples<32'(SAFE_SAMPLES))ready_samples<=ready_samples+1'b1;
                end else ready_samples<=0;
            end
            if(active&&wait_cycles<SAFE_TIMEOUT)wait_cycles<=wait_cycles+1'b1;
            if(failure_now)begin
                state<=RESULT;saved_error<=failure_code;saved_phase<=state;
                saved_sequence_code<=failure_code==3?reset_fault_code:8'd0;
                stable_count<=0;
            end else case(state)
                IDLE:begin end
                QUIESCE:begin
                    if(quiesce_ack===1'b1&&quiescent===1'b1)begin
                        if(stable_count<32'(SAFE_SAMPLES))stable_count<=stable_count+1'b1;
                    end else stable_count<=0;
                    if(reset_request)begin
                        reset_sent<=1;state<=WAIT_ASSERT;stable_count<=0;
                        fault_clear_seen<=reset_fault===1'b0;
                    end
                end
                WAIT_ASSERT:begin
                    // Both low observations must belong to this actual
                    // assertion, rejecting retained COMPLETE/READY levels.
                    if(reset_asserted===1'b1&&reset_complete===1'b0&&platform_ready===1'b0)begin
                        state<=WAIT_COMPLETE;
                    end
                end
                WAIT_COMPLETE:if(reset_complete===1'b1&&reset_asserted===1'b0)begin
                    state<=WAIT_READY;stable_count<=0;
                end
                WAIT_READY:begin
                    if(platform_ready===1'b1&&reset_fault===1'b0)begin
                        if(({1'b0,stable_count}+33'd1)>={1'b0,32'(SAFE_SAMPLES)})begin
                            success_epoch<=success_epoch+1'b1;state<=RESULT;
                            saved_error<=0;saved_sequence_code<=0;saved_phase<=WAIT_READY;
                            stable_count<=0;
                        end else stable_count<=stable_count+1'b1;
                    end else stable_count<=0;
                end
                RESULT:begin end
                default:begin
                    state<=RESULT;saved_error<=8;saved_sequence_code<=0;saved_phase<=state;
                end
            endcase
            if(command_fire)begin
                rsp_valid<=1;rsp_status<=command_status;rsp_seq<=req[571:556];
                rsp_data<=req[555:548]===8'd1&&command_status==0?{480'd0,read_value}:512'd0;
                if(command_start)begin
                    attempts<=attempts+1'b1;state<=QUIESCE;quiesce_request<=1;
                    stable_count<=0;wait_cycles<=0;reset_sent<=0;assertion_seen<=0;
                    fault_clear_seen<=0;terminal_fault_seen<=0;completion_seen<=0;ready_samples<=0;
                    saved_error<=0;saved_sequence_code<=0;saved_phase<=0;
                end
                if(command_cancel)begin
                    state<=RESULT;quiesce_request<=0;saved_error<=2;saved_phase<=QUIESCE;
                    saved_sequence_code<=0;stable_count<=0;
                end
                if(command_ack)begin
                    state<=IDLE;quiesce_request<=0;stable_count<=0;
                end
            end
        end
    end
endmodule
