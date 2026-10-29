// SPDX-License-Identifier: Apache-2.0
// USER2 transport for the standalone openXC7 image. One outstanding command.
// 640-bit DR, LSB first: data[511:0], byte address[543:512], register strobes
// [547:544], opcode[555:548], sequence[571:556], magic 0x4f54504a[603:572].
// Opcodes: 1 register read, 2 register write, 3 64-byte read, 4 64-byte write.
// An all-zero frame polls. Response: data[511:0], status[519:512], sequence
// [535:520], magic[567:536]. The host must await its sequence before submitting
// another command. The held payloads cross with toggle synchronizers; payload
// bits must not be individually synchronized or changed during a transaction.
module otpu_jtag_mailbox (
  input logic clk, rst,
  input logic tck, capture, shift, update, sel, tdi,
  output wire tdo,
  output logic req_valid,
  input logic req_ready,
  output logic [603:0] req,
  input logic rsp_valid,
  input logic [511:0] rsp_data,
  input logic [7:0] rsp_status,
  input logic [15:0] rsp_seq
);
  localparam logic [31:0] MAGIC = 32'h4f54504a;
  logic [639:0] sr = '0;
  logic [603:0] held = '0;
  logic req_toggle = 0;
  logic [567:0] response = {MAGIC, 16'b0, 8'b0, 512'b0};
  logic rsp_toggle = 0;
  (* ASYNC_REG = "TRUE" *) logic [2:0] rq_sync = '0, rs_sync = '0;
  logic rq_seen = 0, rs_seen = 0;
  logic [567:0] response_tck = {MAGIC, 16'b0, 8'b0, 512'b0};
  assign tdo = sr[0];
  always_ff @(posedge tck) begin
    rs_sync <= {rs_sync[1:0], rsp_toggle};
    if (rs_sync[2] != rs_seen) begin
      response_tck <= response;
      rs_seen <= rs_sync[2];
    end
    if (sel && capture) sr <= {72'b0, response_tck};
    else if (sel && shift) sr <= {tdi, sr[639:1]};
    if (sel && update && sr[603:572] == MAGIC && sr[555:548] != 0) begin
      held <= sr[603:0];
      req_toggle <= !req_toggle;
    end
  end
  always_ff @(posedge clk) begin
    rq_sync <= {rq_sync[1:0], req_toggle};
    if (rst) begin
      rq_seen <= rq_sync[2];
      req_valid <= 0;
    end else begin
      if (req_valid && req_ready) req_valid <= 0;
      if (!req_valid && rq_sync[2] != rq_seen) begin
        req <= held;
        req_valid <= 1;
        rq_seen <= rq_sync[2];
      end
      if (rsp_valid) begin
        response <= {MAGIC, rsp_seq, rsp_status, rsp_data};
        rsp_toggle <= !rsp_toggle;
      end
    end
  end
endmodule
