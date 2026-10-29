// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Serialized raw-mailbox control, not a concurrent generic AXI interconnect.
// EW page0, CMAC page1, layout page4. One owner through readback and ACK.
module rk_layout_job_control (
    input wire clk,rst_n,memory_ready,
    input wire [31:0] s_axil_awaddr,s_axil_wdata,s_axil_araddr,
    input wire [2:0] s_axil_awprot,s_axil_arprot,
    input wire [3:0] s_axil_wstrb,
    input wire s_axil_awvalid,s_axil_wvalid,s_axil_bready,s_axil_arvalid,s_axil_rready,
    output wire s_axil_awready,s_axil_wready,s_axil_bvalid,s_axil_arready,s_axil_rvalid,
    output wire [1:0] s_axil_bresp,s_axil_rresp,
    output wire [31:0] s_axil_rdata,
    output wire irq,scheduler_fault,control_owned,control_quiet,
    output wire [1:0] control_owner_kind,
    output wire core_start_valid,
    output wire [1:0] core_start_kind,
    output wire [31:0] core_start_address,core_start_amount,
    input wire core_ew_start_ready,core_cmac_start_ready,core_layout_start_ready,
    input wire core_busy,core_done,core_error,core_write_block,
    input wire [7:0] core_error_code,
    input wire [31:0] core_completed_tasks
);
    wire [2:0] bank_awready,bank_wready,bank_bvalid,bank_arready,bank_rvalid;
    wire [1:0] bank_bresp[0:2],bank_rresp[0:2];
    wire [31:0] bank_rdata[0:2],bank_address[0:2],bank_amount[0:2];
    wire [2:0] bank_irq,bank_start;
    logic owned,result_seen,local_fault;
    logic [1:0] owner_kind;
    function automatic [1:0] bank_for(input logic [23:0] page);
        if(page===24'h000001)bank_for=1;
        else if(page===24'h000004)bank_for=2;
        else bank_for=0;
    endfunction
    wire [1:0] write_bank=bank_for(s_axil_awaddr[31:8]),read_bank=bank_for(s_axil_araddr[31:8]);
    wire multiple_starts=(bank_start[0]&&bank_start[1])||(bank_start[0]&&bank_start[2])||
                         (bank_start[1]&&bank_start[2]);
    wire foreign_start=owned&&(|(bank_start&~(3'b001<<owner_kind)));
    wire bad_launch=multiple_starts||foreign_start;
    assign scheduler_fault=rst_n&&(local_fault||bad_launch);
    assign control_owned=owned;
    assign control_owner_kind=owner_kind;
    assign core_start_kind=owned ? owner_kind : bank_start[0] ? 2'd0 : bank_start[1] ? 2'd1 : 2'd2;
    assign core_start_valid=rst_n&&(owned ? bank_start[owner_kind] : |bank_start);
    assign core_start_address=bank_address[core_start_kind];
    assign core_start_amount=bank_amount[core_start_kind];
    assign irq=rst_n&&(|bank_irq);
    // Registered/public pending states only; admission blocking is deliberately
    // absent so this witness cannot form a cycle through a reset owner.
    assign control_quiet=rst_n&&!owned&&!(|bank_start)&&!(|bank_irq)&&!(|bank_bvalid)&&!(|bank_rvalid)&&
        (&bank_awready)&&(&bank_wready)&&(&bank_arready)&&
        !s_axil_awvalid&&!s_axil_wvalid&&!s_axil_arvalid&&!scheduler_fault;
    assign s_axil_awready=bank_awready[write_bank];
    assign s_axil_wready=bank_wready[write_bank];
    assign s_axil_bvalid=bank_bvalid[write_bank];
    assign s_axil_bresp=bank_bresp[write_bank];
    assign s_axil_arready=bank_arready[read_bank];
    assign s_axil_rvalid=bank_rvalid[read_bank];
    assign s_axil_rresp=bank_rresp[read_bank];
    assign s_axil_rdata=bank_rdata[read_bank];
    always @(posedge clk)begin
        if(!rst_n)begin owned<=0;owner_kind<=0;result_seen<=0;local_fault<=0;end
        else begin
            if(bad_launch)local_fault<=1;
            if(!owned&&!scheduler_fault)begin
                if(|bank_start)begin owned<=1;owner_kind<=core_start_kind;result_seen<=0;end
            end else if(owned)begin
                if(bank_irq[owner_kind])result_seen<=1;
                if(result_seen&&!bank_irq[owner_kind]&&!(|bank_start)&&
                   !core_busy&&!core_error&&!scheduler_fault)begin owned<=0;result_seen<=0;end
            end
        end
    end
    for(genvar g=0;g<3;g=g+1)begin: bank
        localparam logic [1:0] KIND=2'(g);
        localparam logic [31:0] ID=g==0 ? 32'h524b4144 : g==1 ? 32'h524b4344 : 32'h524b4c59;
        wire selected=!owned||owner_kind==KIND;
        wire other_start=|(bank_start&~(3'b001<<g));
        wire selected_ready=g==0 ? core_ew_start_ready : g==1 ? core_cmac_start_ready : core_layout_start_ready;
        wire own_ready=selected&&!other_start&&selected_ready;
        wire own_busy=core_busy||!selected||other_start;
        rk_job_control_admission #(.DEVICE_ID(ID)) control (
            .clk,.rst_n,.memory_ready(memory_ready&&selected&&!other_start&&!scheduler_fault),
            // Only the two explicit nonzero pages are rebased. All unknown
            // full addresses reach EW unchanged and retain DECERR behavior.
            .s_axil_awaddr(KIND==2'd0 ? s_axil_awaddr : {24'd0,s_axil_awaddr[7:0]}),
            .s_axil_awprot,.s_axil_awvalid(s_axil_awvalid&&write_bank==KIND),
            .s_axil_awready(bank_awready[g]),.s_axil_wdata,.s_axil_wstrb,
            .s_axil_wvalid(s_axil_wvalid&&write_bank==KIND),.s_axil_wready(bank_wready[g]),
            .s_axil_bresp(bank_bresp[g]),.s_axil_bvalid(bank_bvalid[g]),.s_axil_bready(s_axil_bready&&write_bank==KIND),
            .s_axil_araddr(KIND==2'd0 ? s_axil_araddr : {24'd0,s_axil_araddr[7:0]}),
            .s_axil_arprot,.s_axil_arvalid(s_axil_arvalid&&read_bank==KIND),.s_axil_arready(bank_arready[g]),
            .s_axil_rdata(bank_rdata[g]),.s_axil_rresp(bank_rresp[g]),.s_axil_rvalid(bank_rvalid[g]),
            .s_axil_rready(s_axil_rready&&read_bank==KIND),.irq(bank_irq[g]),
            .core_start_valid(bank_start[g]),.core_start_ready(own_ready||scheduler_fault),
            .core_start_address(bank_address[g]),.core_start_amount(bank_amount[g]),
            .core_write_block(core_write_block||!selected||other_start||scheduler_fault),
            .core_busy(own_busy),.core_done(owned&&owner_kind==KIND&&core_done),
            .core_error(core_error||scheduler_fault),.core_error_code(scheduler_fault ? 8'd6 : core_error_code),
            .core_completed_tasks(owned&&owner_kind==KIND ? core_completed_tasks : 32'd0)
        );
    end
endmodule
