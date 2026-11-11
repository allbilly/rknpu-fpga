// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
module tb_ppu_c3_job_control;
    localparam logic [31:0] PPU_PAGE = 32'h00000300;
    localparam logic [31:0] COMMAND_BASE = 32'h00003000;
    localparam logic [31:0] JOB_TAG = 32'hc3000001;

    logic clk;
    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    logic rst_n = 1'b0;
    logic memory_ready = 1'b1;
    logic [31:0] s_axil_awaddr = 0, s_axil_wdata = 0, s_axil_araddr = 0;
    logic [2:0] s_axil_awprot = 0, s_axil_arprot = 0;
    logic [3:0] s_axil_wstrb = 4'hf;
    logic s_axil_awvalid = 0, s_axil_wvalid = 0, s_axil_bready = 0;
    logic s_axil_arvalid = 0, s_axil_rready = 0;
    wire s_axil_awready, s_axil_wready, s_axil_bvalid;
    wire s_axil_arready, s_axil_rvalid;
    wire [1:0] s_axil_bresp, s_axil_rresp;
    wire [31:0] s_axil_rdata;
    wire irq, scheduler_fault, control_owned, control_quiet;
    wire [1:0] control_owner_kind, core_start_kind;
    wire core_start_valid;
    wire [31:0] core_start_address, core_start_amount;
    logic core_ew_start_ready = 1'b1;
    logic core_cmac_start_ready = 1'b1;
    logic core_layout_start_ready = 1'b0;
    logic core_busy;
    logic core_done = 1'b0;
    logic core_error = 1'b0;
    logic [7:0] core_error_code = 0;
    logic [31:0] core_completed_tasks = 0;
    integer start_count;
    logic [1:0] last_start_kind;
    logic [31:0] last_start_address, last_start_amount;

    rk_layout_job_control #(.ENABLE_PPU(1'b1)) dut (
        .clk, .rst_n, .memory_ready,
        .s_axil_awaddr, .s_axil_wdata, .s_axil_araddr,
        .s_axil_awprot, .s_axil_arprot, .s_axil_wstrb,
        .s_axil_awvalid, .s_axil_wvalid, .s_axil_bready,
        .s_axil_arvalid, .s_axil_rready,
        .s_axil_awready, .s_axil_wready, .s_axil_bvalid,
        .s_axil_arready, .s_axil_rvalid, .s_axil_bresp, .s_axil_rresp,
        .s_axil_rdata, .irq, .scheduler_fault, .control_owned, .control_quiet,
        .control_owner_kind, .core_start_valid, .core_start_kind,
        .core_start_address, .core_start_amount,
        .core_ew_start_ready, .core_cmac_start_ready, .core_layout_start_ready,
        .core_busy, .core_done, .core_error, .core_write_block(1'b0),
        .core_error_code, .core_completed_tasks
    );

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            start_count <= 0;
            last_start_kind <= 0;
            last_start_address <= 0;
            last_start_amount <= 0;
            core_busy <= 0;
        end else begin
            if (core_start_valid && core_layout_start_ready) begin
                start_count <= start_count + 1;
                last_start_kind <= core_start_kind;
                last_start_address <= core_start_address;
                last_start_amount <= core_start_amount;
                core_busy <= 1;
            end
            if (core_done || core_error)
                core_busy <= 0;
        end
    end

    task automatic write_reg(input logic [31:0] address,
                             input logic [31:0] data,
                             input logic [1:0] expected_response);
        logic aw_seen, w_seen;
        begin
            @(negedge clk);
            s_axil_awaddr = address;
            s_axil_wdata = data;
            s_axil_awvalid = 1'b1;
            s_axil_wvalid = 1'b1;
            aw_seen = 0;
            w_seen = 0;
            while (!aw_seen || !w_seen) begin
                @(posedge clk);
                if (s_axil_awready) aw_seen = 1;
                if (s_axil_wready) w_seen = 1;
            end
            @(negedge clk);
            s_axil_awvalid = 1'b0;
            s_axil_wvalid = 1'b0;
            while (s_axil_bvalid !== 1'b1) @(negedge clk);
            if (s_axil_bresp !== expected_response)
                $fatal(1, "write %08x=%08x BRESP=%b expected=%b",
                       address, data, s_axil_bresp, expected_response);
            s_axil_bready = 1'b1;
            @(posedge clk);
            @(negedge clk);
            s_axil_bready = 1'b0;
            s_axil_awaddr = 0;
        end
    endtask

    task automatic read_reg(input logic [31:0] address,
                            input logic [31:0] expected_data,
                            input logic [1:0] expected_response);
        begin
            @(negedge clk);
            s_axil_araddr = address;
            s_axil_arvalid = 1'b1;
            @(posedge clk);
            if (s_axil_arready !== 1'b1) $fatal(1, "AR not ready at %08x", address);
            @(negedge clk);
            s_axil_arvalid = 1'b0;
            while (s_axil_rvalid !== 1'b1) @(negedge clk);
            if (s_axil_rresp !== expected_response ||
                (expected_response == 2'b00 && s_axil_rdata !== expected_data))
                $fatal(1, "read %08x RDATA=%08x RRESP=%b expected=%08x/%b",
                       address, s_axil_rdata, s_axil_rresp, expected_data, expected_response);
            s_axil_rready = 1'b1;
            @(posedge clk);
            @(negedge clk);
            s_axil_rready = 1'b0;
            s_axil_araddr = 0;
        end
    endtask

    task automatic program_job;
        begin
            write_reg(PPU_PAGE + 32'h10, COMMAND_BASE, 2'b00);
            write_reg(PPU_PAGE + 32'h14, 32'd26, 2'b00);
            write_reg(PPU_PAGE + 32'h18, JOB_TAG, 2'b00);
        end
    endtask

    initial begin : TEST
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        read_reg(PPU_PAGE + 32'h00, 32'h524b5050, 2'b00);
        read_reg(PPU_PAGE + 32'h04, 32'h00010000, 2'b00);
        read_reg(32'h00000400, 32'h524b4c59, 2'b00);

        program_job();
        write_reg(PPU_PAGE + 32'h0c, 32'd1, 2'b10);
        if (core_start_valid || control_owned || scheduler_fault)
            $fatal(1, "PPU SUBMIT without auxiliary-slot readiness was not rejected");

        core_layout_start_ready = 1'b1;
        write_reg(PPU_PAGE + 32'h0c, 32'd1, 2'b00);
        wait (start_count == 1);
        if (last_start_kind !== 2'd3 || last_start_address !== COMMAND_BASE ||
            last_start_amount !== 32'd26 || control_owner_kind !== 2'd3 || !control_owned)
            $fatal(1, "RKPP page did not own the distinct PPU dispatch kind");
        repeat (3) @(negedge clk);
        core_completed_tasks = 32'd1;
        core_done = 1'b1;
        @(negedge clk);
        core_done = 1'b0;
        wait (irq === 1'b1);
        read_reg(PPU_PAGE + 32'h1c, JOB_TAG, 2'b00);
        read_reg(PPU_PAGE + 32'h20, 32'd1, 2'b00);
        read_reg(PPU_PAGE + 32'h24, 32'd0, 2'b00);
        if (scheduler_fault) $fatal(1, "successful PPU result raised scheduler fault");
        write_reg(PPU_PAGE + 32'h0c, 32'd2, 2'b00);
        wait (control_owned === 1'b0);
        if (irq || !control_quiet) $fatal(1, "successful RKPP ACK did not retire ownership");

        program_job();
        write_reg(PPU_PAGE + 32'h0c, 32'd1, 2'b00);
        wait (start_count == 2);
        core_error_code = 8'd5;
        core_error = 1'b1;
        wait (irq === 1'b1);
        read_reg(PPU_PAGE + 32'h24, 32'd5, 2'b00);
        write_reg(PPU_PAGE + 32'h0c, 32'd2, 2'b10);
        if (!control_owned || !irq || !core_error || scheduler_fault)
            $fatal(1, "faulted PPU result was ACKed or released");

        $display("PASS ppu_c3_job_control RKPP=0x300 kind=3 ready-gate=SLVERR success-ACK=fault-held");
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "PPU job-control testbench timeout");
    end
endmodule
