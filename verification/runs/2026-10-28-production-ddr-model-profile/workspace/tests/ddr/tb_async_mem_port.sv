// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_async_mem_port #(parameter integer DUT_STAGES=3);
  logic s_clk,d_clk,s_run,d_run,s_rst_n,d_rst_n,s_admission_enable;
  logic s_mem_req_valid,s_mem_req_write,s_mem_rsp_ready;
  logic [31:0] s_mem_req_addr;
  logic [15:0] s_mem_req_wdata;
  wire s_mem_req_ready,s_mem_rsp_valid,s_mem_rsp_error,s_protocol_fault;
  wire [15:0] s_mem_rsp_rdata;
  wire d_mem_req_valid,d_mem_req_write,d_mem_rsp_ready,d_protocol_fault;
  wire [31:0] d_mem_req_addr;
  wire [15:0] d_mem_req_wdata;
  logic d_allow_req,force_response,model_rsp_valid,model_rsp_error,model_pending;
  logic [15:0] model_rsp_data,model_next_data;
  logic model_next_error;
  logic [3:0] response_delay;
  logic [31:0] random_s,random_d;
  wire d_mem_req_ready=d_rst_n&&d_allow_req&&random_d[0];
  wire d_mem_rsp_valid=force_response||model_rsp_valid;
  wire [15:0] d_mem_rsp_rdata=force_response?16'hdead:model_rsp_data;
  wire d_mem_rsp_error=force_response?1'b0:model_rsp_error;
  rk_async_mem_port #(.SYNC_STAGES(DUT_STAGES)) dut(.*);
  initial begin s_clk=0;d_clk=0;s_run=1;d_run=1;end
  always begin #10;if(s_run)s_clk=~s_clk;end
  always begin #3.75;if(d_run)d_clk=~d_clk;end
  function automatic logic[15:0] signature(input logic write,input logic[31:0] address,input logic[15:0] data);
    signature=address[31:16]^address[15:0]^data^{15'b0,write};
  endfunction
  integer source_count,destination_count,response_count,total_good;
  logic [48:0] expected_request;
  logic [15:0] expected_response;
  logic expected_error,override_error,local_failure;
  logic s_stalled,d_stalled;
  logic [16:0] held_response;
  logic [48:0] held_request;

  always @(posedge s_clk or negedge s_rst_n)begin
    if(!s_rst_n)begin
      random_s<=32'h3588cdc1;source_count<=0;response_count<=0;
      expected_request<=0;expected_response<=0;expected_error<=0;
      s_stalled<=0;held_response<=0;
    end else begin
      random_s<={random_s[30:0],random_s[31]^random_s[21]^random_s[1]^random_s[0]};
      if(s_mem_req_valid&&s_mem_req_ready)begin
        source_count<=source_count+1;
        expected_request<={s_mem_req_write,s_mem_req_addr,s_mem_req_wdata};
        expected_response<=local_failure?16'b0:signature(s_mem_req_write,s_mem_req_addr,s_mem_req_wdata);
        expected_error<=override_error||s_mem_req_addr[7];
      end
      if(s_stalled&&(!s_mem_rsp_valid||{s_mem_rsp_error,s_mem_rsp_rdata}!==held_response))
        $fatal(1,"Source response changed under backpressure");
      s_stalled<=s_mem_rsp_valid&&!s_mem_rsp_ready;
      held_response<={s_mem_rsp_error,s_mem_rsp_rdata};
      if(s_mem_rsp_valid&&s_mem_rsp_ready)begin
        if(response_count>=source_count||s_mem_rsp_rdata!==expected_response||s_mem_rsp_error!==expected_error)
          $fatal(1,"Unexpected/incorrect source completion");
        response_count<=response_count+1;
      end
    end
  end
  always @(posedge d_clk or negedge d_rst_n)begin
    if(!d_rst_n)begin
      random_d<=32'h7532bb01;destination_count<=0;
      model_pending<=0;model_rsp_valid<=0;model_rsp_data<=0;model_rsp_error<=0;
      model_next_data<=0;model_next_error<=0;response_delay<=0;
      d_stalled<=0;held_request<=0;
    end else begin
      random_d<={random_d[30:0],random_d[31]^random_d[21]^random_d[1]^random_d[0]};
      if(d_stalled&&(!d_mem_req_valid||{d_mem_req_write,d_mem_req_addr,d_mem_req_wdata}!==held_request))
        $fatal(1,"Destination request withdrawn/changed while stalled");
      d_stalled<=d_mem_req_valid&&!d_mem_req_ready;
      held_request<={d_mem_req_write,d_mem_req_addr,d_mem_req_wdata};
      if(d_mem_req_valid&&d_mem_req_ready)begin
        if(model_pending||model_rsp_valid||{d_mem_req_write,d_mem_req_addr,d_mem_req_wdata}!==expected_request)
          $fatal(1,"Destination changed/duplicated source bytes");
        destination_count<=destination_count+1;model_pending<=1;
        model_next_data<=signature(d_mem_req_write,d_mem_req_addr,d_mem_req_wdata);
        model_next_error<=d_mem_req_addr[7];response_delay<={1'b0,random_d[3:1]};
      end
      if(model_pending)begin
        if(response_delay==0)begin
          model_pending<=0;model_rsp_valid<=1;model_rsp_data<=model_next_data;model_rsp_error<=model_next_error;
        end else response_delay<=response_delay-1'b1;
      end
      if(model_rsp_valid&&d_mem_rsp_ready)model_rsp_valid<=0;
    end
  end
  task automatic reset_epoch;
    s_admission_enable=0;s_mem_req_valid=0;force_response=0;
    s_rst_n=0;d_rst_n=0;s_mem_rsp_ready=1;d_allow_req=1;
    override_error=0;local_failure=0;
    repeat(5)@(negedge s_clk);
    s_rst_n=1;@(negedge d_clk);d_rst_n=1;
    repeat(8)@(negedge s_clk);s_admission_enable=1;
  endtask
  task automatic send(input logic write,input logic[31:0]address,input logic[15:0]data);
    integer guard;
    @(negedge s_clk);guard=0;
    while(!s_mem_req_ready)begin @(negedge s_clk);guard=guard+1;if(guard>5000)$fatal(1,"Source admission timeout");end
    s_mem_req_valid=1;s_mem_req_write=write;s_mem_req_addr=address;s_mem_req_wdata=data;
    @(posedge s_clk);if(!s_mem_req_ready)$fatal(1,"Admission disappeared before handshake");
    @(negedge s_clk);s_mem_req_valid=0;
  endtask
  task automatic finish_one;
    integer guard;
    guard=0;
    while(response_count!=source_count)begin @(negedge s_clk);guard=guard+1;if(guard>5000)$fatal(1,"Source result timeout");end
    total_good=total_good+1;
  endtask
  integer mode,prior;
  initial begin
    s_rst_n=0;d_rst_n=0;s_admission_enable=0;s_mem_req_valid=0;s_mem_req_write=0;
    s_mem_req_addr=0;s_mem_req_wdata=0;s_mem_rsp_ready=1;d_allow_req=1;force_response=0;
    override_error=0;local_failure=0;total_good=0;
    if(!$value$plusargs("MODE=%d",mode))mode=0;
    reset_epoch();
    if(mode==0)begin
      repeat(256)begin
        send(random_s[0],random_s,{random_s[15:0]});
        @(negedge s_clk);s_mem_rsp_ready=0;
        repeat(12)@(negedge s_clk);
        s_mem_rsp_ready=1;finish_one();
      end
      if(source_count!=256||destination_count!=256||response_count!=256||s_protocol_fault||d_protocol_fault)
        $fatal(1,"Normal transfer inventory/fault mismatch");
    end else if(mode==1)begin
      d_allow_req=0;send(1,32'hf1230002,16'hbf01);wait(d_mem_req_valid);
      @(negedge d_clk);d_run=0;
      repeat(60)@(negedge s_clk);
      if(s_mem_rsp_valid||s_mem_req_ready||response_count!=0)$fatal(1,"Stopped destination fabricated progress");
      d_run=1;d_allow_req=1;finish_one();
      send(0,32'h81230040,16'h1234);@(negedge s_clk);s_run=0;
      repeat(100)@(negedge d_clk);
      if(s_mem_req_ready||source_count!=2||destination_count!=2)$fatal(1,"Stopped source lost ownership");
      s_run=1;finish_one();
      d_allow_req=0;send(1,32'h10000010,16'habcd);wait(d_mem_req_valid);
      // Whole epoch cancels both bridge halves and the downstream model.
      reset_epoch();repeat(40)@(negedge s_clk);
      if(s_mem_rsp_valid||source_count!=0||destination_count!=0||response_count!=0)$fatal(1,"Old reset epoch escaped");
      send(1,32'hfedc0020,16'hbeef);finish_one();
    end else if(mode==2)begin
      // An unsolicited response before the request crosses must fail it,
      // without creating a downstream memory operation.
      override_error=1;local_failure=1;send(0,32'h10000040,0);force_response=1;
      repeat(3)@(negedge d_clk);force_response=0;finish_one();
      repeat(12)@(negedge s_clk);
      if(destination_count!=0||!d_protocol_fault||!s_protocol_fault||s_mem_req_ready)$fatal(1,"Early response was silently accepted");
      reset_epoch();d_allow_req=0;override_error=1;
      send(1,32'h10000040,16'h0020);wait(d_mem_req_valid);
      @(negedge d_clk);force_response=1;
      repeat(3)@(negedge d_clk);force_response=0;
      repeat(12)@(negedge s_clk);
      if(!d_mem_req_valid||s_mem_rsp_valid||!s_protocol_fault)$fatal(1,"Fault canceled an already offered request");
      d_allow_req=1;finish_one();
      reset_epoch();s_mem_rsp_ready=0;
      send(0,32'h10000040,16'h1234);wait(s_mem_rsp_valid);
      // A later protocol fault is separate from the already held payload.
      @(negedge d_clk);force_response=1;
      repeat(3)@(negedge d_clk);force_response=0;
      repeat(12)@(negedge s_clk);prior=response_count;
      if(!s_protocol_fault||!s_mem_rsp_valid||s_mem_rsp_error||s_mem_req_ready)$fatal(1,"Held response/fault contract changed");
      s_mem_rsp_ready=1;finish_one();
      if(response_count!=prior+1)$fatal(1,"Held response did not complete exactly once");
    end else $fatal(1,"Unknown bridge test mode");
    $display("PASS async_mem_port mode=%0d completed=%0d seed=3588cdc1 source_only_no_physical_CDC",mode,total_good);
    $finish;
  end
  initial begin #20000000;$fatal(1,"Memory crossing watchdog");end
endmodule
