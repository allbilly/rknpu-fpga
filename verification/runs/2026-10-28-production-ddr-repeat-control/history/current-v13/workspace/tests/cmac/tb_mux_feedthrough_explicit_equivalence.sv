`timescale 1ps/1ps
// Same exhaustive equivalence contract as the retained failed generated bench.
// Explicit vendor mux instances avoid generated output-index elaboration.
module tb_mux_feedthrough_equivalence;
  reg [3:0] data;
  reg [2:0] select;
  wire [3:0] lut;
  wire left, right, original, buffered_left, buffered_right;
  wire [1:0] wrapped_left, wrapped_right, candidate;
  integer vector, digit, k, unused_mode, comparisons;
  reg negative;

  function automatic four_state(input integer value);
    case (value)
      0: four_state = 1'b0;
      1: four_state = 1'b1;
      2: four_state = 1'bx;
      3: four_state = 1'bz;
    endcase
  endfunction

  for (genvar i = 0; i < 4; i = i + 1) begin : sources
    LUT1 #(.INIT(2'b10)) source (.I0(data[i]), .O(lut[i]));
  end
  MUXF7 source_left (.I0(lut[0]), .I1(lut[1]), .S(select[0]), .O(left));
  MUXF7 source_right (.I0(lut[2]), .I1(lut[3]), .S(select[1]), .O(right));
  MUXF8 source_root (.I0(left), .I1(right), .S(select[2]), .O(original));
  LUT1 #(.INIT(2'b10)) identity_left (.I0(left), .O(buffered_left));
  LUT1 #(.INIT(2'b10)) identity_right (.I0(right), .O(buffered_right));
  MUXF7 wrapper_left_floating (.I0(buffered_left), .I1(1'bz), .S(1'b0), .O(wrapped_left[0]));
  MUXF7 wrapper_right_floating (.I0(buffered_right), .I1(1'bz), .S(1'b0), .O(wrapped_right[0]));
  MUXF8 candidate_root_floating (.I0(wrapped_left[0]), .I1(wrapped_right[0]),
                                  .S(select[2]), .O(candidate[0]));
  MUXF7 wrapper_left_ground (.I0(buffered_left), .I1(1'b0), .S(1'b0), .O(wrapped_left[1]));
  MUXF7 wrapper_right_ground (.I0(buffered_right), .I1(1'b0), .S(1'b0), .O(wrapped_right[1]));
  MUXF8 candidate_root_ground (.I0(wrapped_left[1]), .I1(wrapped_right[1]),
                                .S(select[2]), .O(candidate[1]));

  initial begin
    negative = $test$plusargs("NEGATIVE");
    comparisons = 0;
    for (vector = 0; vector < 16384; vector = vector + 1) begin
      digit = vector;
      for (k = 0; k < 4; k = k + 1) begin
        data[k] = four_state(digit % 4);
        digit = digit / 4;
      end
      for (k = 0; k < 3; k = k + 1) begin
        select[k] = four_state(digit % 4);
        digit = digit / 4;
      end
      #10;
      for (unused_mode = 0; unused_mode < 2; unused_mode = unused_mode + 1) begin
        if ((negative && vector == 0 ? ~candidate[unused_mode] : candidate[unused_mode]) !== original)
          $fatal(1, "MUX_EQ_MISMATCH vector=%0d inactive=%0d", vector, unused_mode);
        if (wrapped_left[unused_mode] !== left || wrapped_right[unused_mode] !== right)
          $fatal(1, "MUX_EQ_SHARED_OUTPUT_MISMATCH vector=%0d", vector);
        comparisons = comparisons + 1;
      end
    end
    if (negative || comparisons != 32768) $fatal(1, "MUX_EQ_BAD_COMPLETION");
    $display("PASS_MUX_FEEDTHROUGH_FOUR_STATE vectors=16384 comparisons=32768");
    $finish;
  end
endmodule
