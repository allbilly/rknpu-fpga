// SPDX-License-Identifier: MIT
// ADDITIVE EXPERIMENTAL COPY for the runtime engine (task-13).
// The FINAL-frozen rtl/cmac/rk_cmac_fp16_cell.sv is NOT modified. This copy is
// construction-identical to the frozen leaf except that C=16 is in the
// supported set (corpus-verified C16 jobs); C=8/32/64 remain supported.
`timescale 1ns/1ps
// Parallel FP16 dot-product cell. NVIDIA nvdlav1 partial-row arithmetic;
// ATOMIC_C changes the group, not the format of the FP44 output to CACC.
//
// MEASURED PIPELINE. The six-page image failed the 20 ns gate with this cell as
// a single combinational cloud (build/jtag-dual-image/20261109T180000Z,
// WNS -1.549 ns, 52 logic levels between the frame stage and out_groups). The
// cloud is now three registered legs, split where the data naturally rests:
//
//   leg 1: lane decode -- pair_nz, normalised mantissas, exponent add, the
//          32-entry maximum and the NaN priority scan;
//   leg 2: the donor NV_NVDLA_CMAC_CORE_MAC_mul Booth/CSA tree, its
//          sign-compensation shift and the per-lane row sum;
//   leg 3: the sign-extended 32-way accumulate and the NaN result mux.
//
// EXACTNESS. The arithmetic is bit-identical to the single-cloud form for every
// input, and no approximation is taken:
//   * `maximum` is the maximum over every lane exponent; maximum is
//     associative, so a balanced tree is the same value as the original
//     serial compare chain;
//   * the 32-way accumulate is modulo-2^38 addition of sign-extended 32-bit
//     lane sums; integer addition is associative, so a balanced adder tree is
//     the same 38-bit residue as the original serial loop (the original also
//     truncated each partial sum to 38 bits);
//   * the NaN scan keeps the donor's weight-before-data, lowest-channel
//     priority: an isolate-lowest-set-bit select on the same predicate vector;
//   * the donor Booth/CSA row decomposition (row_a/row_b) is untouched and is
//     the only place a lane product is formed.
// The pipeline enables are supplied by the enclosing array; a low enable holds
// the leg and the array's valid pipeline prevents a bubble from being emitted.
module rk_runtime_fp16_cell #(parameter int unsigned ATOMIC_C=16) (
    input wire clk,rst_n,
    input wire [ATOMIC_C*16-1:0] data,weight,
    input wire [ATOMIC_C-1:0] data_mask,weight_mask,
    input wire stage1_en,stage2_en,
    output logic [43:0] result,
    output logic invalid
);
    initial if (ATOMIC_C!=8&&ATOMIC_C!=16&&ATOMIC_C!=32&&ATOMIC_C!=64)
        $fatal(1,"unsupported atomic C");

    localparam int unsigned LEVELS = (ATOMIC_C<=1) ? 0 : $clog2(ATOMIC_C);

    wire [15:0] a[ATOMIC_C],b[ATOMIC_C];
    wire [14:0] am[ATOMIC_C],bm[ATOMIC_C];
    wire pair_nz[ATOMIC_C];
    wire [3:0] exponent[ATOMIC_C];

    //---------------------------------------------------------------
    // Leg 1 input cone: every value that depends only on the operands.
    //---------------------------------------------------------------
    for (genvar i=0;i<ATOMIC_C;i=i+1) begin: lanes
        assign a[i] = data[i*16+:16];
        assign b[i] = weight[i*16+:16];
        assign pair_nz[i] = data_mask[i] && weight_mask[i] &&
                            (a[i][14:0]!=0) && (b[i][14:0]!=0);
        // Same width and shift expression as the original cell: the shift
        // result is truncated to 15 bits before the donor sees it.
        assign am[i] = {4'd0,(a[i][14:10]!=0),a[i][9:0]} <<
                       (a[i][14:10]==0 ? 2'd1 : a[i][11:10]);
        assign bm[i] = {4'd0,(b[i][14:10]!=0),b[i][9:0]} <<
                       (b[i][14:10]==0 ? 2'd1 : b[i][11:10]);
        // 4-bit modulo addition, exactly like the original assignment.
        assign exponent[i] = pair_nz[i] ?
                             {1'b0,a[i][14:12]}+{1'b0,b[i][14:12]} : 4'd0;
    end

    // Balanced maximum tree. The serial original is numerically identical
    // because maximum is associative and every exponent is unsigned.
    function automatic [3:0] max4 (input [3:0] x, input [3:0] y);
        max4 = (x>y) ? x : y;
    endfunction
    // A single packed vector holds every tree level; a node reads only the
    // previous level's slice, so the netlist is acyclic by construction.
    // Level l occupies 8*(A - (A>>l)) bits onward and stores (A>>l) values.
    localparam int unsigned MAX_BITS = 8*ATOMIC_C-4;
    wire [MAX_BITS-1:0] max_all;
    for (genvar i=0;i<ATOMIC_C;i=i+1) begin: max_seed
        assign max_all[4*i+:4] = exponent[i];
    end
    for (genvar l=0;l<LEVELS;l=l+1) begin: max_stage
        localparam int unsigned IN_COUNT = ATOMIC_C >> l;
        localparam int unsigned OUT_COUNT = (IN_COUNT+1)/2;
        localparam int unsigned BASE = 8*(ATOMIC_C-(ATOMIC_C>>l));
        localparam int unsigned NEXT_BASE = 8*(ATOMIC_C-(ATOMIC_C>>(l+1)));
        for (genvar j=0;j<OUT_COUNT;j=j+1) begin: max_node
            if ((2*j+1)<IN_COUNT) begin: pair
                assign max_all[NEXT_BASE+4*j+:4] =
                    max4(max_all[BASE+8*j+:4],
                         max_all[BASE+8*j+4+:4]);
            end else begin: single
                assign max_all[NEXT_BASE+4*j+:4] =
                    max_all[BASE+8*j+:4];
            end
        end
    end
    wire [3:0] maximum;
    assign maximum = max_all[8*(ATOMIC_C-1)+:4];

    // NaN priority: weight halfwords win over data halfwords and the lowest
    // lane wins within a scan, which is the donor's documented priority. The
    // isolate-lowest-set-bit form is exactly that priority, without a serial
    // 32-deep override chain.
    wire [ATOMIC_C-1:0] weight_nan,data_nan;
    for (genvar i=0;i<ATOMIC_C;i=i+1) begin: nan_lanes
        assign weight_nan[i] = weight_mask[i] && (b[i][14:10]==5'd31) &&
                               (b[i][9:0]!=0);
        assign data_nan[i] = data_mask[i] && (a[i][14:10]==5'd31) &&
                             (a[i][9:0]!=0);
    end
    wire [ATOMIC_C-1:0] weight_low,data_low;
    assign weight_low = weight_nan & ~(weight_nan - 1'b1);
    assign data_low = data_nan & ~(data_nan - 1'b1);
    // The selects are one-hot, so the OR reduction is a plain function of the
    // two inputs; a function keeps it a combinational expression instead of an
    // always-block over unpacked arrays (which Icarus flags as over-sensitive).
    function automatic [10:0] or_payload (input [11*ATOMIC_C-1:0] v);
        integer i;
        or_payload = 11'd0;
        for (i=0;i<ATOMIC_C;i=i+1) or_payload = or_payload | v[11*i+:11];
    endfunction
    wire [11*ATOMIC_C-1:0] weight_payload_vec,data_payload_vec;
    for (genvar i=0;i<ATOMIC_C;i=i+1) begin: payload_lanes
        assign weight_payload_vec[11*i+:11] =
            {11{weight_low[i]}} & {b[i][15],b[i][9:0]};
        assign data_payload_vec[11*i+:11] =
            {11{data_low[i]}} & {a[i][15],a[i][9:0]};
    end
    wire [10:0] weight_payload,data_payload;
    assign weight_payload = or_payload(weight_payload_vec);
    assign data_payload = or_payload(data_payload_vec);
    wire nan_found;
    wire [10:0] nan_payload;
    assign nan_found = (|weight_nan) || (|data_nan);
    assign nan_payload = (|weight_nan) ? weight_payload : data_payload;

    //---------------------------------------------------------------
    // Leg 1 register: donor operands and the frame's exponent/max/NaN state.
    //---------------------------------------------------------------
    logic [ATOMIC_C*16-1:0] op_a_q,op_b_q;
    logic [ATOMIC_C-1:0] pair_nz_q;
    logic [ATOMIC_C*4-1:0] exp_sft_q;
    logic [3:0] maximum_q;
    logic nan_found_q;
    logic [10:0] nan_payload_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            op_a_q <= '0;
            op_b_q <= '0;
            pair_nz_q <= '0;
            exp_sft_q <= '0;
            maximum_q <= '0;
            nan_found_q <= 1'b0;
            nan_payload_q <= '0;
        end else if (stage1_en) begin
            for (integer i=0;i<ATOMIC_C;i=i+1) begin
                op_a_q[i*16+:16] <= {b[i][15],bm[i]};
                op_b_q[i*16+:16] <= {a[i][15],am[i]};
                pair_nz_q[i] <= pair_nz[i];
                // exp_sft has always been the donor's alignment input:
                // maximum - exponent, 4-bit modulo (never negative in range).
                exp_sft_q[i*4+:4] <= maximum - exponent[i];
            end
            maximum_q <= maximum;
            nan_found_q <= nan_found;
            nan_payload_q <= nan_payload;
        end
    end

    //---------------------------------------------------------------
    // Leg 2: donor Booth/CSA multiply and sign-shift, then the per-lane sum.
    // The donor module is instantiated unchanged; only its inputs are now
    // registered.
    //---------------------------------------------------------------
    wire [ATOMIC_C*32-1:0] lane_sum;
    wire [ATOMIC_C-1:0] lane_invalid;
    for (genvar i=0;i<ATOMIC_C;i=i+1) begin: lanes2
        wire [31:0] row_a,row_b;
        wire [7:0] row_tag;
        logic [31:0] compensation;
        logic bad_tag;
        NV_NVDLA_CMAC_CORE_MAC_mul donor(
            .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),.cfg_is_fp16(1'b1),
            .cfg_is_int8(1'b0),.cfg_reg_en(1'b1),.exp_sft(exp_sft_q[i*4+:4]),
            .op_a_dat(op_a_q[i*16+:16]),.op_a_nz({2{pair_nz_q[i]}}),
            .op_a_pvld(1'b1),
            .op_b_dat(op_b_q[i*16+:16]),.op_b_nz({2{pair_nz_q[i]}}),
            .op_b_pvld(1'b1),
            .res_a(row_a),.res_b(row_b),.res_tag(row_tag));
        // The nine legal row tags and their exact NVIDIA compensation
        // constants; any other tag is an arithmetic error (the original
        // single-cloud case did the same).
        always @* begin
            compensation = 32'd0;
            bad_tag = 1'b0;
            case (row_tag)
                8'hf0: compensation = 32'haaab0000;
                8'h78: compensation = 32'hfaaab000;
                8'h3c: compensation = 32'hffaaab00;
                8'h1e: compensation = 32'hfffaaab0;
                8'h0f: compensation = 32'hffffaaab;
                8'h07: compensation = 32'hfffffaab;
                8'h03: compensation = 32'hffffffab;
                8'h01: compensation = 32'hfffffffb;
                8'h00: compensation = 32'd0;
                default: begin compensation = 32'd0; bad_tag = 1'b1; end
            endcase
        end
        // 32-bit modulo addition, exactly like the original lane_sum.
        assign lane_sum[i*32+:32] = row_a + row_b + compensation;
        assign lane_invalid[i] = bad_tag;
    end

    //---------------------------------------------------------------
    // Leg 2 register: per-lane sum plus the frame state needed by leg 3.
    //---------------------------------------------------------------
    logic [ATOMIC_C*32-1:0] lane_sum_q;
    logic [ATOMIC_C-1:0] lane_invalid_q;
    logic [3:0] maximum_q2;
    logic nan_found_q2;
    logic [10:0] nan_payload_q2;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lane_sum_q <= '0;
            lane_invalid_q <= '0;
            maximum_q2 <= '0;
            nan_found_q2 <= 1'b0;
            nan_payload_q2 <= '0;
        end else if (stage2_en) begin
            lane_sum_q <= lane_sum;
            lane_invalid_q <= lane_invalid;
            maximum_q2 <= maximum_q;
            nan_found_q2 <= nan_found_q;
            nan_payload_q2 <= nan_payload_q;
        end
    end
    assign invalid = |lane_invalid_q;

    //---------------------------------------------------------------
    // Leg 3: balanced 32-way accumulate of the sign-extended lane sums.
    // Every partial sum is 38 bits, which is the original `sum` width, so the
    // result is the same modulo-2^38 residue.
    //---------------------------------------------------------------
    // Level l occupies 76*(A - (A>>l)) bits onward and stores (A>>l) values.
    localparam int unsigned SUM_BITS = 76*ATOMIC_C-38;
    wire [SUM_BITS-1:0] sum_all;
    for (genvar i=0;i<ATOMIC_C;i=i+1) begin: sum_seed
        assign sum_all[38*i+:38] =
            {{6{lane_sum_q[32*i+31]}},lane_sum_q[32*i+:32]};
    end
    for (genvar l=0;l<LEVELS;l=l+1) begin: sum_stage
        localparam int unsigned IN_COUNT = ATOMIC_C >> l;
        localparam int unsigned OUT_COUNT = (IN_COUNT+1)/2;
        localparam int unsigned BASE = 76*(ATOMIC_C-(ATOMIC_C>>l));
        localparam int unsigned NEXT_BASE = 76*(ATOMIC_C-(ATOMIC_C>>(l+1)));
        for (genvar j=0;j<OUT_COUNT;j=j+1) begin: sum_node
            if ((2*j+1)<IN_COUNT) begin: pair
                assign sum_all[NEXT_BASE+38*j+:38] =
                    sum_all[BASE+76*j+:38] +
                    sum_all[BASE+76*j+38+:38];
            end else begin: single
                assign sum_all[NEXT_BASE+38*j+:38] =
                    sum_all[BASE+76*j+:38];
            end
        end
    end
    wire [37:0] sum_final;
    assign sum_final = sum_all[76*(ATOMIC_C-1)+:38];

    // NaN wins over the accumulated value; otherwise the packed FP44 word is
    // {maximum, 2'b0, sum}, identical to the original result expression.
    assign result = nan_found_q2 ? {6'h3f,nan_payload_q2,27'd0}
                                 : {maximum_q2,2'b0,sum_final};
endmodule
