`timescale 1ns/1ps
// Page-level replay + contract bench for the Image-B ew-int page form.
//
// Instantiates the integer page (rk_ew_int_page_axi) and the sparse aperture
// (rk_ew_int_aperture) exactly as Image B wires them: the page's 16-bit memory
// master is the aperture engine port, page_busy gates host staging, and the
// aperture memory_ready gates the page's job-control submit.
//
// The TB stages the frozen BO images through the aperture AXI4-Lite staging
// port (no back door), submits the raw command BO through the frozen page ABI,
// waits for the result, reads the output BO back through the same AXI port and
// dumps it for the Python masked comparison. It also reads back the operand and
// command banks to prove the staging byte order and that the engine never
// rewrites its inputs or the command BO.
//
// Plusargs:
//   STIM=<prefix>       prefix for a_words.hex / b_words.hex / cmd_words.hex
//   CMD_WORDS=<n>       command QWORD count (18/31/44; negatives may differ)
//   AMOUNT=<n>          START_AMOUNT to submit (default CMD_WORDS)
//   ECASE=<n>           expected RESULT_CODE (default 0 = success)
//   NAME=<case>         tag for messages
//   OUT=<prefix>        prefix for out.hex / a_read.hex / b_read.hex /
//                       cmd_read.hex
//   SKIP_TAG=1          do not write JOB_TAG (expect submit refusal)
//   BAD_STROBE=1        use a partial write strobe for START_AMOUNT (refusal)
//   STIM2=<prefix>      second successful case in the same reset session
//                       (reset-per-job / clean back-to-back jobs)
//   CMD_WORDS2 / AMOUNT2 / NAME2 / OUT2  for the second case
module tb_ew_int_page;
    localparam logic [31:0] A_BANK = 32'h1100_1000;
    localparam logic [31:0] B_BANK = 32'h1100_2000;
    localparam logic [31:0] D_BANK = 32'h1100_3000;
    localparam logic [31:0] C_BANK = 32'h1100_4000;
    localparam integer BO_WORDS = 1024;    // 4096 bytes / 4
    localparam integer CMD_MAX_WORDS = 88; // 352 bytes / 4
    localparam logic [31:0] JOB_TAG = 32'h4b454949;

    logic clk;
    initial clk = 1'b0;
    always #5 clk = ~clk;
    logic rst_n = 1'b0;

    // ---- page AXI4-Lite master ------------------------------------------
    logic [15:0] p_awaddr = 16'd0;
    logic [2:0] p_awprot = 3'd0;
    logic p_awvalid = 1'b0, p_awready;
    logic [31:0] p_wdata = 32'd0;
    logic [3:0] p_wstrb = 4'd0;
    logic p_wvalid = 1'b0, p_wready;
    logic [1:0] p_bresp;
    logic p_bvalid, p_bready = 1'b0;
    logic [15:0] p_araddr = 16'd0;
    logic [2:0] p_arprot = 3'd0;
    logic p_arvalid = 1'b0, p_arready;
    logic [31:0] p_rdata;
    logic [1:0] p_rresp;
    logic p_rvalid, p_rready = 1'b0;

    // ---- aperture AXI4-Lite master --------------------------------------
    logic [31:0] ap_awaddr = 32'd0;
    logic [2:0] ap_awprot = 3'd0;
    logic ap_awvalid = 1'b0, ap_awready;
    logic [31:0] ap_wdata = 32'd0;
    logic [3:0] ap_wstrb = 4'd0;
    logic ap_wvalid = 1'b0, ap_wready;
    logic [1:0] ap_bresp;
    logic ap_bvalid, ap_bready = 1'b0;
    logic [31:0] ap_araddr = 32'd0;
    logic [2:0] ap_arprot = 3'd0;
    logic ap_arvalid = 1'b0, ap_arready;
    logic [31:0] ap_rdata;
    logic [1:0] ap_rresp;
    logic ap_rvalid, ap_rready = 1'b0;

    // ---- page <-> aperture engine port ----------------------------------
    wire page_mem_req_valid, page_mem_req_ready, page_mem_req_write;
    wire [31:0] page_mem_req_addr;
    wire [15:0] page_mem_req_wdata;
    wire page_mem_rsp_valid, page_mem_rsp_ready, page_mem_rsp_error;
    wire [15:0] page_mem_rsp_rdata;
    wire page_busy, page_done, page_error, page_irq, ap_memory_ready;
    wire [7:0] page_error_code;
    wire ap_busy, ap_irq;

    rk_ew_int_page_axi page (
        .clk(clk), .rst_n(rst_n), .memory_ready(ap_memory_ready),
        .page_cancel(1'b0),
        .s_axil_awaddr(p_awaddr), .s_axil_awprot(p_awprot),
        .s_axil_awvalid(p_awvalid), .s_axil_awready(p_awready),
        .s_axil_wdata(p_wdata), .s_axil_wstrb(p_wstrb),
        .s_axil_wvalid(p_wvalid), .s_axil_wready(p_wready),
        .s_axil_bresp(p_bresp), .s_axil_bvalid(p_bvalid),
        .s_axil_bready(p_bready),
        .s_axil_araddr(p_araddr), .s_axil_arprot(p_arprot),
        .s_axil_arvalid(p_arvalid), .s_axil_arready(p_arready),
        .s_axil_rdata(p_rdata), .s_axil_rresp(p_rresp),
        .s_axil_rvalid(p_rvalid), .s_axil_rready(p_rready),
        .mem_req_valid(page_mem_req_valid), .mem_req_ready(page_mem_req_ready),
        .mem_req_write(page_mem_req_write), .mem_req_addr(page_mem_req_addr),
        .mem_req_wdata(page_mem_req_wdata),
        .mem_rsp_valid(page_mem_rsp_valid), .mem_rsp_ready(page_mem_rsp_ready),
        .mem_rsp_rdata(page_mem_rsp_rdata), .mem_rsp_error(page_mem_rsp_error),
        .page_busy(page_busy), .page_done(page_done), .page_error(page_error),
        .page_error_code(page_error_code), .irq(page_irq)
    );

    rk_ew_int_aperture aperture (
        .clk(clk), .rst_n(rst_n), .page_busy(page_busy),
        .memory_ready(ap_memory_ready),
        .s_axil_awaddr(ap_awaddr), .s_axil_awprot(ap_awprot),
        .s_axil_awvalid(ap_awvalid), .s_axil_awready(ap_awready),
        .s_axil_wdata(ap_wdata), .s_axil_wstrb(ap_wstrb),
        .s_axil_wvalid(ap_wvalid), .s_axil_wready(ap_wready),
        .s_axil_bresp(ap_bresp), .s_axil_bvalid(ap_bvalid),
        .s_axil_bready(ap_bready),
        .s_axil_araddr(ap_araddr), .s_axil_arprot(ap_arprot),
        .s_axil_arvalid(ap_arvalid), .s_axil_arready(ap_arready),
        .s_axil_rdata(ap_rdata), .s_axil_rresp(ap_rresp),
        .s_axil_rvalid(ap_rvalid), .s_axil_rready(ap_rready),
        .engine_req_valid(page_mem_req_valid),
        .engine_req_ready(page_mem_req_ready),
        .engine_req_write(page_mem_req_write),
        .engine_req_addr(page_mem_req_addr),
        .engine_req_wdata(page_mem_req_wdata),
        .engine_rsp_valid(page_mem_rsp_valid),
        .engine_rsp_ready(page_mem_rsp_ready),
        .engine_rsp_rdata(page_mem_rsp_rdata),
        .engine_rsp_error(page_mem_rsp_error),
        .busy(ap_busy), .irq(ap_irq)
    );

    // ---- stimulus / result storage --------------------------------------
    logic [31:0] a_words [0:BO_WORDS-1];
    logic [31:0] b_words [0:BO_WORDS-1];
    logic [31:0] cmd_words [0:CMD_MAX_WORDS-1];
    logic [31:0] a_read [0:BO_WORDS-1];
    logic [31:0] b_read [0:BO_WORDS-1];
    logic [31:0] cmd_read [0:CMD_MAX_WORDS-1];
    logic [31:0] out_read [0:BO_WORDS-1];
    string stim_prefix, out_prefix, case_name;
    integer cmd_words_n, amount_n, expected_code;
    integer fd, i, errors;
    string stim2_prefix, out2_prefix, case2_name;
    integer cmd2_words_n, amount2_n, have_case2;
    logic skip_tag, bad_strobe;
    logic [31:0] start_addr_sel;

    // ---- race-free AXI4-Lite master tasks --------------------------------
    // Drive on negedge, sample ready mid-cycle (+1 ns, stable), complete the
    // handshake on the following posedge, deassert on the following negedge.
    task automatic page_write(input logic [15:0] addr, input logic [31:0] data,
                              input logic [3:0] strb, output logic [1:0] bresp);
        logic aw_done, w_done, aw_hs, w_hs;
        begin
            aw_done = 1'b0; w_done = 1'b0;
            @(negedge clk);
            p_awaddr = addr; p_awprot = 3'd0; p_awvalid = 1'b1;
            p_wdata = data; p_wstrb = strb; p_wvalid = 1'b1;
            while (!(aw_done && w_done)) begin
                #1;
                aw_hs = p_awvalid && p_awready;
                w_hs = p_wvalid && p_wready;
                @(posedge clk);
                if (aw_hs) aw_done = 1'b1;
                if (w_hs) w_done = 1'b1;
                @(negedge clk);
                if (aw_done) p_awvalid = 1'b0;
                if (w_done) p_wvalid = 1'b0;
            end
            p_awvalid = 1'b0; p_wvalid = 1'b0;
            while (!p_bvalid) @(negedge clk);
            bresp = p_bresp;
            p_bready = 1'b1;
            @(posedge clk);
            @(negedge clk);
            p_bready = 1'b0;
        end
    endtask

    task automatic page_read(input logic [15:0] addr, output logic [31:0] data);
        logic ar_done, ar_hs;
        begin
            ar_done = 1'b0;
            @(negedge clk);
            p_araddr = addr; p_arprot = 3'd0; p_arvalid = 1'b1;
            while (!ar_done) begin
                #1;
                ar_hs = p_arvalid && p_arready;
                @(posedge clk);
                if (ar_hs) ar_done = 1'b1;
                @(negedge clk);
                if (ar_done) p_arvalid = 1'b0;
            end
            p_arvalid = 1'b0;
            while (!p_rvalid) @(negedge clk);
            data = p_rdata;
            if (p_rresp != 2'b00) $fatal(1, "unexpected page read SLVERR");
            p_rready = 1'b1;
            @(posedge clk);
            @(negedge clk);
            p_rready = 1'b0;
        end
    endtask

    task automatic ap_write(input logic [31:0] addr, input logic [31:0] data,
                            output logic [1:0] bresp);
        logic aw_done, w_done, aw_hs, w_hs;
        begin
            aw_done = 1'b0; w_done = 1'b0;
            @(negedge clk);
            ap_awaddr = addr; ap_awprot = 3'd0; ap_awvalid = 1'b1;
            ap_wdata = data; ap_wstrb = 4'hf; ap_wvalid = 1'b1;
            while (!(aw_done && w_done)) begin
                #1;
                aw_hs = ap_awvalid && ap_awready;
                w_hs = ap_wvalid && ap_wready;
                @(posedge clk);
                if (aw_hs) aw_done = 1'b1;
                if (w_hs) w_done = 1'b1;
                @(negedge clk);
                if (aw_done) ap_awvalid = 1'b0;
                if (w_done) ap_wvalid = 1'b0;
            end
            ap_awvalid = 1'b0; ap_wvalid = 1'b0;
            while (!ap_bvalid) @(negedge clk);
            bresp = ap_bresp;
            ap_bready = 1'b1;
            @(posedge clk);
            @(negedge clk);
            ap_bready = 1'b0;
        end
    endtask

    logic [31:0] ap_read_value;
    task automatic ap_read(input logic [31:0] addr);
        logic [31:0] data;
        logic ar_done, ar_hs;
        begin
            ar_done = 1'b0;
            @(negedge clk);
            ap_araddr = addr; ap_arprot = 3'd0; ap_arvalid = 1'b1;
            while (!ar_done) begin
                #1;
                ar_hs = ap_arvalid && ap_arready;
                @(posedge clk);
                if (ar_hs) ar_done = 1'b1;
                @(negedge clk);
                if (ar_done) ap_arvalid = 1'b0;
            end
            ap_arvalid = 1'b0;
            i = 0;
            while ((ap_rvalid !== 1'b1) && (i < 200)) begin
                @(negedge clk);
                i = i + 1;
            end
            if (ap_rvalid !== 1'b1) begin
                $display("XREAD timeout addr=%08x st=%0d ar_have=%b ar_sent=%b arv=%b arr=%b bank_rv=%b rd_bank=%0d",
                         addr, aperture.host_state_q, aperture.ar_have,
                         aperture.ar_sent, aperture.bank_arvalid,
                         aperture.bank_arready, aperture.bank_rvalid,
                         aperture.read_bank);
                $fatal(1, "aperture read timeout");
            end
            data = ap_rdata;
            if (ap_rresp != 2'b00) $fatal(1, "unexpected aperture read SLVERR");
            ap_read_value = data;
            ap_rready = 1'b1;
            @(posedge clk);
            @(negedge clk);
            ap_rready = 1'b0;
        end
    endtask

    // ---- helpers ---------------------------------------------------------
    task automatic stage_words(input logic [31:0] bank, input integer words,
                               input integer which);
        logic [1:0] bresp;
        integer k;
        begin
            for (k = 0; k < words; k = k + 1) begin
                if (which == 0) ap_write(bank + 32'(k) * 4, a_words[k], bresp);
                else if (which == 1) ap_write(bank + 32'(k) * 4, b_words[k], bresp);
                else ap_write(bank + 32'(k) * 4, cmd_words[k], bresp);
                if (bresp != 2'b00) begin
                    $display("FAIL %s: staging write bresp=%b at word %0d",
                             case_name, bresp, k);
                    errors = errors + 1;
                end
            end
        end
    endtask

    task automatic readback_banks(input integer cmd_word32);
        integer k;
        begin
            for (k = 0; k < BO_WORDS; k = k + 1) begin
                ap_read(A_BANK + 32'(k) * 4);
                a_read[k] = ap_read_value;
            end
            for (k = 0; k < BO_WORDS; k = k + 1) begin
                ap_read(B_BANK + 32'(k) * 4);
                b_read[k] = ap_read_value;
            end
            for (k = 0; k < BO_WORDS; k = k + 1) begin
                ap_read(D_BANK + 32'(k) * 4);
                out_read[k] = ap_read_value;
            end
            for (k = 0; k < cmd_word32; k = k + 1) begin
                ap_read(C_BANK + 32'(k) * 4);
                cmd_read[k] = ap_read_value;
            end
        end
    endtask

    task automatic dump_results(input string prefix);
        begin
            fd = $fopen({prefix, "out.hex"}, "w");
            if (fd == 0) $fatal(1, "cannot open out.hex");
            for (i = 0; i < BO_WORDS; i = i + 1) $fdisplay(fd, "%08x", out_read[i]);
            $fclose(fd);
            fd = $fopen({prefix, "a_read.hex"}, "w");
            for (i = 0; i < BO_WORDS; i = i + 1) $fdisplay(fd, "%08x", a_read[i]);
            $fclose(fd);
            fd = $fopen({prefix, "b_read.hex"}, "w");
            for (i = 0; i < BO_WORDS; i = i + 1) $fdisplay(fd, "%08x", b_read[i]);
            $fclose(fd);
            fd = $fopen({prefix, "cmd_read.hex"}, "w");
            for (i = 0; i < CMD_MAX_WORDS; i = i + 1) $fdisplay(fd, "%08x", cmd_read[i]);
            $fclose(fd);
        end
    endtask

    task automatic run_case(input integer which);
        string outpref, name;
        integer words_n, word32_n, amount, ecode;
        logic [31:0] status, code, tasks, tag;
        logic [1:0] bresp;
        integer p;
        logic refusal;
        begin
            if (which == 0) begin
                outpref = out_prefix;
                name = case_name; words_n = cmd_words_n; amount = amount_n;
                ecode = expected_code; refusal = skip_tag || bad_strobe;
            end else begin
                outpref = out2_prefix;
                name = case2_name; words_n = cmd2_words_n; amount = amount2_n;
                ecode = 0; refusal = 1'b0;
            end
            word32_n = 2 * words_n;
            if (ap_busy) $fatal(1, "aperture busy before staging");
            if (ap_irq !== 1'b0) $fatal(1, "aperture irq must stay low");
            $display("INFO %s: staging banks (cmd_words=%0d)", name, words_n);
            stage_words(A_BANK, BO_WORDS, 0);
            stage_words(B_BANK, BO_WORDS, 1);
            stage_words(C_BANK, word32_n, 2);
            page_write(16'h10, start_addr_sel, 4'hf, bresp);
            if (bresp != 2'b00) $fatal(1, "START_ADDRESS write bresp=%b", bresp);
            if (bad_strobe && which == 0) begin
                page_write(16'h14, 32'(amount), 4'b0011, bresp);
                if (bresp != 2'b10) $fatal(1, "partial-strobe write must be SLVERR");
            end else begin
                page_write(16'h14, 32'(amount), 4'hf, bresp);
                if (bresp != 2'b00) $fatal(1, "START_AMOUNT write bresp=%b", bresp);
            end
            if (!(skip_tag && which == 0)) begin
                page_write(16'h18, JOB_TAG, 4'hf, bresp);
                if (bresp != 2'b00) $fatal(1, "JOB_TAG write bresp=%b", bresp);
            end
            if (refusal) begin
                // A submit without complete fields must be refused with SLVERR.
                page_write(16'h0c, 32'd1, 4'hf, bresp);
                if (bresp != 2'b10) $fatal(1, "incomplete submit must be SLVERR");
                $display("PASS %s: submit refused (bresp=%b)", name, bresp);
            end else begin
                status = 32'd0;
                for (p = 0; p < 200; p = p + 1) begin
                    page_read(16'h08, status);
                    if (status[0]) p = 200;
                end
                if (!status[0]) $fatal(1, "can_submit never asserted");
                page_write(16'h0c, 32'd1, 4'hf, bresp);
                if (bresp != 2'b00) $fatal(1, "submit bresp=%b", bresp);
                status = 32'd0;
                for (p = 0; p < 40000; p = p + 1) begin
                    page_read(16'h08, status);
                    if (status[2]) p = 40000;
                end
                if (!status[2]) $fatal(1, "result_valid never asserted");
                if (page_irq !== status[2]) $fatal(1, "page irq must track result_valid");
                page_read(16'h24, code);
                page_read(16'h20, tasks);
                page_read(16'h1c, tag);
                $display("INFO %s: status=%08x code=%08x tasks=%0d tag=%08x",
                         name, status, code, tasks, tag);
                if (status[3] != (ecode != 0))
                    $fatal(1, "result_error=%b expected %b", status[3], (ecode != 0));
                if (code[7:0] != 8'(ecode))
                    $fatal(1, "result_code=%0d expected %0d", code[7:0], ecode);
                if (ecode == 0) begin
                    if (!page_done) $fatal(1, "page_done missing after success");
                    if (page_error) $fatal(1, "page_error asserted on success");
                    if (tasks != 32'd1) $fatal(1, "RESULT_TASKS=%0d expected 1", tasks);
                    if (tag != JOB_TAG) $fatal(1, "RESULT_TAG mismatch");
                    page_write(16'h0c, 32'd2, 4'hf, bresp);
                    if (bresp != 2'b00) $fatal(1, "success ack bresp=%b", bresp);
                end else begin
                    if (!page_error) $fatal(1, "page_error missing after error");
                    if (page_error_code != 8'(ecode))
                        $fatal(1, "page_error_code=%0d expected %0d",
                               page_error_code, ecode);
                    // Sticky error contract: the frozen control rejects new jobs
                    // and register writes until fabric reset.
                    page_write(16'h14, 32'(amount), 4'hf, bresp);
                    if (bresp != 2'b10) $fatal(1, "post-error write must be SLVERR");
                    page_write(16'h0c, 32'd1, 4'hf, bresp);
                    if (bresp != 2'b10) $fatal(1, "post-error submit must be SLVERR");
                end
                readback_banks(word32_n);
                dump_results(outpref);
                $display("PASS %s: result_code=%0d result_error=%b tasks=%0d",
                         name, code[7:0], status[3], tasks);
            end
        end
    endtask

    initial begin
        errors = 0;
        if (!$value$plusargs("STIM=%s", stim_prefix)) $fatal(1, "missing STIM");
        if (!$value$plusargs("CMD_WORDS=%d", cmd_words_n)) $fatal(1, "missing CMD_WORDS");
        amount_n = cmd_words_n;
        if (!$value$plusargs("AMOUNT=%d", amount_n)) amount_n = cmd_words_n;
        if (!$value$plusargs("ECASE=%d", expected_code)) expected_code = 0;
        if (!$value$plusargs("NAME=%s", case_name)) case_name = "case";
        if (!$value$plusargs("OUT=%s", out_prefix)) $fatal(1, "missing OUT");
        if (!$value$plusargs("START_ADDR=%d", start_addr_sel))
            start_addr_sel = C_BANK;
        if (!$value$plusargs("SKIP_TAG=%d", skip_tag)) skip_tag = 1'b0;
        if (!$value$plusargs("BAD_STROBE=%d", bad_strobe)) bad_strobe = 1'b0;
        have_case2 = $value$plusargs("STIM2=%s", stim2_prefix);
        if (have_case2 != 0) begin
            if (!$value$plusargs("CMD_WORDS2=%d", cmd2_words_n)) $fatal(1, "missing CMD_WORDS2");
            amount2_n = cmd2_words_n;
            if (!$value$plusargs("AMOUNT2=%d", amount2_n)) amount2_n = cmd2_words_n;
            if (!$value$plusargs("NAME2=%s", case2_name)) case2_name = "case2";
            if (!$value$plusargs("OUT2=%s", out2_prefix)) $fatal(1, "missing OUT2");
            if (skip_tag || bad_strobe) $fatal(1, "STIM2 cannot be combined with refusal flags");
        end
        if ((cmd_words_n < 4) || (cmd_words_n > 2 * CMD_MAX_WORDS))
            $fatal(1, "invalid CMD_WORDS");
        if (expected_code < 0 || expected_code > 8) $fatal(1, "invalid ECASE");
        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (4) @(negedge clk);
        $readmemh({stim_prefix, "a_words.hex"}, a_words);
        $readmemh({stim_prefix, "b_words.hex"}, b_words);
        $readmemh({stim_prefix, "cmd_words.hex"}, cmd_words);
        run_case(0);
        if (have_case2 != 0) begin
            $display("INFO %s: second job in the same reset session", case2_name);
            $readmemh({stim2_prefix, "a_words.hex"}, a_words);
            $readmemh({stim2_prefix, "b_words.hex"}, b_words);
            $readmemh({stim2_prefix, "cmd_words.hex"}, cmd_words);
            run_case(1);
        end
        if (errors != 0) $fatal(1, "page replay errors: %0d", errors);
        $display("PASS %s: page replay complete", case_name);
        $finish;
    end
endmodule
