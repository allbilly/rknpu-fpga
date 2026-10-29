// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Private raw-mailbox AXI-Lite source only: rk_jtag_backend serializes reads
// and writes and holds its address through the response. This is not a generic
// concurrent AXI interconnect. EW CSR0x000, terminal CMAC CSR0x100. One global
// job owner remains selected through successful result readback and ACK.
module rk_dual_job_control (
    input wire clk,rst_n,memory_ready,
    input wire [31:0] s_axil_awaddr,s_axil_wdata,s_axil_araddr,
    input wire [2:0] s_axil_awprot,s_axil_arprot,
    input wire [3:0] s_axil_wstrb,
    input wire s_axil_awvalid,s_axil_wvalid,s_axil_bready,s_axil_arvalid,s_axil_rready,
    output wire s_axil_awready,s_axil_wready,s_axil_bvalid,s_axil_arready,s_axil_rvalid,
    output wire [1:0] s_axil_bresp,s_axil_rresp,
    output wire [31:0] s_axil_rdata,
    output wire irq,scheduler_fault,control_owned,control_owner_cmac,
    output wire core_start_valid,core_start_cmac,
    output wire [31:0] core_start_address,core_start_amount,
    input wire core_ew_start_ready,core_cmac_start_ready,
    input wire core_busy,core_done,core_error,
    input wire [7:0] core_error_code,
    input wire [31:0] core_completed_tasks
);
    wire [1:0] bank_awready,bank_wready,bank_bvalid,bank_arready,bank_rvalid;
    wire [1:0] bank_bresp[0:1],bank_rresp[0:1];
    wire [31:0] bank_rdata[0:1],bank_address[0:1],bank_amount[0:1];
    wire [1:0] bank_irq,bank_start;
    logic owned,owner_cmac,result_seen,local_fault;
    // An out-of-range address is forwarded unchanged to EW, whose register
    // decoder returns DECERR. Never truncate unknown or unsupported namespaces.
    wire write_cmac=s_axil_awaddr[31:8]===24'h000001;
    wire read_cmac=s_axil_araddr[31:8]===24'h000001;
    wire bad_launch=(bank_start[0]&&bank_start[1])||
        (owned&&(owner_cmac ? bank_start[0] : bank_start[1]));
    assign scheduler_fault=rst_n&&(local_fault||bad_launch);
    assign control_owned=owned;
    assign control_owner_cmac=owner_cmac;
    assign core_start_cmac=owned ? owner_cmac : (!bank_start[0]&&bank_start[1]);
    assign core_start_valid=rst_n&&(owned ? bank_start[owner_cmac] : |bank_start);
    assign core_start_address=core_start_cmac ? bank_address[1] : bank_address[0];
    assign core_start_amount=core_start_cmac ? bank_amount[1] : bank_amount[0];
    assign irq=rst_n&&(|bank_irq);
    assign s_axil_awready=bank_awready[write_cmac];
    assign s_axil_wready=bank_wready[write_cmac];
    assign s_axil_bvalid=bank_bvalid[write_cmac];
    assign s_axil_bresp=bank_bresp[write_cmac];
    assign s_axil_arready=bank_arready[read_cmac];
    assign s_axil_rvalid=bank_rvalid[read_cmac];
    assign s_axil_rresp=bank_rresp[read_cmac];
    assign s_axil_rdata=bank_rdata[read_cmac];

    always_ff @(posedge clk) begin
        if(!rst_n)begin owned<=0;owner_cmac<=0;result_seen<=0;local_fault<=0;end
        else begin
            if(bad_launch)local_fault<=1;
            if(!owned&&!scheduler_fault)begin
                if(|bank_start)begin
                    owned<=1;owner_cmac<=bank_start[1];result_seen<=0;
                end
            end else if(owned)begin
                if(bank_irq[owner_cmac])result_seen<=1;
                // Only the selected controller's successful ACK drops IRQ.
                // Platform faults and failed results cannot release this slot.
                if(result_seen&&!bank_irq[owner_cmac]&&!(|bank_start)&&
                   !core_busy&&!core_error&&!scheduler_fault)begin
                    owned<=0;result_seen<=0;
                end
            end
        end
    end

    for(genvar g=0;g<2;g=g+1)begin: bank
        localparam bit CMAC=(g==1);
        wire selected=!owned||(owner_cmac==CMAC);
        wire other_start=bank_start[1-g];
        wire selected_ready=CMAC ? core_cmac_start_ready : core_ew_start_ready;
        wire own_ready=selected&&!other_start&&selected_ready;
        wire own_busy=core_busy||!selected||other_start;
        rk_job_control #(.DEVICE_ID(CMAC ? 32'h524b4344 : 32'h524b4144)) control (
            .clk,.rst_n,
            .memory_ready(memory_ready&&selected&&!other_start&&!scheduler_fault),
            .s_axil_awaddr(CMAC ? {24'b0,s_axil_awaddr[7:0]} : s_axil_awaddr),
            .s_axil_awprot,.s_axil_awvalid(s_axil_awvalid&&(write_cmac==CMAC)),
            .s_axil_awready(bank_awready[g]),.s_axil_wdata,.s_axil_wstrb,
            .s_axil_wvalid(s_axil_wvalid&&(write_cmac==CMAC)),.s_axil_wready(bank_wready[g]),
            .s_axil_bresp(bank_bresp[g]),.s_axil_bvalid(bank_bvalid[g]),
            .s_axil_bready(s_axil_bready&&(write_cmac==CMAC)),
            .s_axil_araddr(CMAC ? {24'b0,s_axil_araddr[7:0]} : s_axil_araddr),
            .s_axil_arprot,.s_axil_arvalid(s_axil_arvalid&&(read_cmac==CMAC)),
            .s_axil_arready(bank_arready[g]),.s_axil_rdata(bank_rdata[g]),
            .s_axil_rresp(bank_rresp[g]),.s_axil_rvalid(bank_rvalid[g]),
            .s_axil_rready(s_axil_rready&&(read_cmac==CMAC)),.irq(bank_irq[g]),
            .core_start_valid(bank_start[g]),.core_start_ready(own_ready||scheduler_fault),
            .core_start_address(bank_address[g]),.core_start_amount(bank_amount[g]),
            .core_busy(own_busy),.core_done(owned&&owner_cmac==CMAC&&core_done),
            .core_error(core_error||scheduler_fault),
            .core_error_code(scheduler_fault ? 8'd6 : core_error_code),
            .core_completed_tasks(owned&&owner_cmac==CMAC ? core_completed_tasks : 32'b0)
        );
    end
endmodule
