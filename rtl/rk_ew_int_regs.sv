// SPDX-License-Identifier: MIT
`timescale 1ns/1ps
// Fail-closed decoder for the captured RK3588 integer elementwise streams.
//
// Evidence: build/rk3588-example-captures/ew-int (15 READY bundles) and the
// source examples kernel_6_18/expt elementwise_int.py. docs/EW_INT.md maps
// every accepted register value and mode to captured vectors / source lines.
// Three captured stream shapes are accepted, and only those:
//   simple  : 18 QWORDs, one contiguous native-dtype tensor (no surface regs)
//   layout  : 44 QWORDs, expt prepared surface (C1WC2 16-byte surfaces, width 1)
//   regroup : 31 QWORDs, INT16 in / INT32 out 16-to-32 writeback
// The per-mode register set is matched exactly: unknown target/offset is E1,
// a register outside the inferred mode contract is E2, a missing one is E3.
// Unsupported ops/dtypes and non-captured fixed values are E2; geometry E6;
// address/alias E4; PC chain E7. Nothing is silently ignored or defaulted.
// This module is additive and does not replace or modify rtl/rk_ew_regs.sv.
module rk_ew_int_regs (
    input  logic        clk, rst_n,
    input  logic        cmd_valid,
    output logic        cmd_ready,
    input  logic [63:0] cmd_data,
    input  logic        engine_busy,
    input  logic        engine_error,
    output logic        cfg_valid,
    input  logic        cfg_ready,
    output logic [2:0]  cfg_op,        // 0 ADD, 1 MINUS, 2 MUL, 3 MAX, 4 MIN
    output logic [1:0]  cfg_dtype,     // ALU result dtype: 0 INT8, 1 INT16, 2 INT32
    output logic [1:0]  cfg_in_item,   // 0 -> 1 byte, 1 -> 2 bytes, 2 -> 4 bytes
    output logic [1:0]  cfg_out_item,
    output logic [15:0] cfg_count,     // logical lanes
    output logic [31:0] cfg_a, cfg_b, cfg_dst,
    output logic        error,
    output logic [7:0]  error_code
);
    // Captured register keys: (target << 16) | byte offset.
    localparam logic [31:0] K_S_POINTER           = 32'h1001_4004;
    localparam logic [31:0] K_FEATURE_MODE_CFG    = 32'h1001_400c;
    localparam logic [31:0] K_DATA_FORMAT         = 32'h1001_4010;
    localparam logic [31:0] K_DST_BASE_ADDR       = 32'h1001_4020;
    localparam logic [31:0] K_DST_SURF_STRIDE     = 32'h1001_4024;
    localparam logic [31:0] K_DATA_CUBE_WIDTH     = 32'h1001_4030;
    localparam logic [31:0] K_DATA_CUBE_HEIGHT    = 32'h1001_4034;
    localparam logic [31:0] K_DATA_CUBE_NOTCH     = 32'h1001_4038;
    localparam logic [31:0] K_DATA_CUBE_CHANNEL   = 32'h1001_403c;
    localparam logic [31:0] K_BS_CFG              = 32'h1001_4040;
    localparam logic [31:0] K_BS_ALU_CFG          = 32'h1001_4044;
    localparam logic [31:0] K_BS_MUL_CFG          = 32'h1001_4048;
    localparam logic [31:0] K_BS_OW_CFG           = 32'h1001_4050;
    localparam logic [31:0] K_WDMA_SIZE_0         = 32'h1001_4058;
    localparam logic [31:0] K_WDMA_SIZE_1         = 32'h1001_405c;
    localparam logic [31:0] K_BN_CFG              = 32'h1001_4060;
    localparam logic [31:0] K_BN_ALU_CFG          = 32'h1001_4064;
    localparam logic [31:0] K_BN_MUL_CFG          = 32'h1001_4068;
    localparam logic [31:0] K_EW_CFG              = 32'h1001_4070;
    localparam logic [31:0] K_EW_CVT_OFFSET       = 32'h1001_4074;
    localparam logic [31:0] K_EW_CVT_SCALE        = 32'h1001_4078;
    localparam logic [31:0] K_OUT_CVT_OFFSET      = 32'h1001_4080;
    localparam logic [31:0] K_OUT_CVT_SCALE       = 32'h1001_4084;
    localparam logic [31:0] K_OUT_CVT_SHIFT       = 32'h1001_4088;
    localparam logic [31:0] K_SURFACE_ADD         = 32'h1001_40c0;
    localparam logic [31:0] K_RDMA_S_POINTER      = 32'h2001_5004;
    localparam logic [31:0] K_RDMA_WIDTH          = 32'h2001_500c;
    localparam logic [31:0] K_RDMA_HEIGHT         = 32'h2001_5010;
    localparam logic [31:0] K_RDMA_CHANNEL        = 32'h2001_5014;
    localparam logic [31:0] K_RDMA_SRC_BASE       = 32'h2001_5018;
    localparam logic [31:0] K_RDMA_BRDMA_CFG      = 32'h2001_501c;
    localparam logic [31:0] K_RDMA_NRDMA_CFG      = 32'h2001_5028;
    localparam logic [31:0] K_RDMA_ERDMA_CFG      = 32'h2001_5034;
    localparam logic [31:0] K_RDMA_EW_BASE        = 32'h2001_5038;
    localparam logic [31:0] K_RDMA_EW_SURF_STRIDE = 32'h2001_5040;
    localparam logic [31:0] K_RDMA_FEATURE_MODE   = 32'h2001_5044;
    localparam logic [31:0] K_RDMA_SRC_DMA_CFG    = 32'h2001_5048;
    localparam logic [31:0] K_RDMA_SURF_NOTCH     = 32'h2001_504c;
    localparam logic [31:0] K_RDMA_WEIGHT         = 32'h2001_5068;
    localparam logic [31:0] K_RDMA_EW_SURF_NOTCH  = 32'h2001_506c;
    localparam logic [31:0] K_NEXT_ADDRESS        = 32'h0101_0010;
    localparam logic [31:0] K_NEXT_AMOUNT         = 32'h0101_0014;
    localparam logic [31:0] K_VERSION_MARKER      = 32'h0041_0000;
    localparam logic [31:0] K_OPERATION_ENABLE    = 32'h0081_0008;

    localparam int unsigned NK = 43;
    localparam logic [5:0] IDX_S_POINTER           = 6'd0;
    localparam logic [5:0] IDX_FEATURE_MODE_CFG    = 6'd1;
    localparam logic [5:0] IDX_DATA_FORMAT         = 6'd2;
    localparam logic [5:0] IDX_DST_BASE_ADDR       = 6'd3;
    localparam logic [5:0] IDX_DST_SURF_STRIDE     = 6'd4;
    localparam logic [5:0] IDX_DATA_CUBE_WIDTH     = 6'd5;
    localparam logic [5:0] IDX_DATA_CUBE_HEIGHT    = 6'd6;
    localparam logic [5:0] IDX_DATA_CUBE_NOTCH     = 6'd7;
    localparam logic [5:0] IDX_DATA_CUBE_CHANNEL   = 6'd8;
    localparam logic [5:0] IDX_BS_CFG              = 6'd9;
    localparam logic [5:0] IDX_BS_ALU_CFG          = 6'd10;
    localparam logic [5:0] IDX_BS_MUL_CFG          = 6'd11;
    localparam logic [5:0] IDX_BS_OW_CFG           = 6'd12;
    localparam logic [5:0] IDX_WDMA_SIZE_0         = 6'd13;
    localparam logic [5:0] IDX_WDMA_SIZE_1         = 6'd14;
    localparam logic [5:0] IDX_BN_CFG              = 6'd15;
    localparam logic [5:0] IDX_BN_ALU_CFG          = 6'd16;
    localparam logic [5:0] IDX_BN_MUL_CFG          = 6'd17;
    localparam logic [5:0] IDX_EW_CFG              = 6'd18;
    localparam logic [5:0] IDX_EW_CVT_OFFSET       = 6'd19;
    localparam logic [5:0] IDX_EW_CVT_SCALE        = 6'd20;
    localparam logic [5:0] IDX_OUT_CVT_OFFSET      = 6'd21;
    localparam logic [5:0] IDX_OUT_CVT_SCALE       = 6'd22;
    localparam logic [5:0] IDX_OUT_CVT_SHIFT       = 6'd23;
    localparam logic [5:0] IDX_SURFACE_ADD         = 6'd24;
    localparam logic [5:0] IDX_RDMA_S_POINTER      = 6'd25;
    localparam logic [5:0] IDX_RDMA_WIDTH          = 6'd26;
    localparam logic [5:0] IDX_RDMA_HEIGHT         = 6'd27;
    localparam logic [5:0] IDX_RDMA_CHANNEL        = 6'd28;
    localparam logic [5:0] IDX_RDMA_SRC_BASE       = 6'd29;
    localparam logic [5:0] IDX_RDMA_BRDMA_CFG      = 6'd30;
    localparam logic [5:0] IDX_RDMA_NRDMA_CFG      = 6'd31;
    localparam logic [5:0] IDX_RDMA_ERDMA_CFG      = 6'd32;
    localparam logic [5:0] IDX_RDMA_EW_BASE        = 6'd33;
    localparam logic [5:0] IDX_RDMA_EW_SURF_STRIDE = 6'd34;
    localparam logic [5:0] IDX_RDMA_FEATURE_MODE   = 6'd35;
    localparam logic [5:0] IDX_RDMA_SRC_DMA_CFG    = 6'd36;
    localparam logic [5:0] IDX_RDMA_SURF_NOTCH     = 6'd37;
    localparam logic [5:0] IDX_RDMA_WEIGHT         = 6'd38;
    localparam logic [5:0] IDX_RDMA_EW_SURF_NOTCH  = 6'd39;
    localparam logic [5:0] IDX_NEXT_ADDRESS        = 6'd40;
    localparam logic [5:0] IDX_NEXT_AMOUNT         = 6'd41;
    localparam logic [5:0] IDX_VERSION_MARKER      = 6'd42;

    localparam logic [42:0] SIMPLE_MASK =
        (43'd1 << IDX_FEATURE_MODE_CFG) | (43'd1 << IDX_DATA_FORMAT) |
        (43'd1 << IDX_DST_BASE_ADDR) | (43'd1 << IDX_DATA_CUBE_WIDTH) |
        (43'd1 << IDX_DATA_CUBE_CHANNEL) | (43'd1 << IDX_EW_CFG) |
        (43'd1 << IDX_EW_CVT_SCALE) | (43'd1 << IDX_RDMA_WIDTH) |
        (43'd1 << IDX_RDMA_HEIGHT) | (43'd1 << IDX_RDMA_CHANNEL) |
        (43'd1 << IDX_RDMA_SRC_BASE) | (43'd1 << IDX_RDMA_ERDMA_CFG) |
        (43'd1 << IDX_RDMA_EW_BASE) | (43'd1 << IDX_RDMA_FEATURE_MODE) |
        (43'd1 << IDX_NEXT_ADDRESS) | (43'd1 << IDX_NEXT_AMOUNT) |
        (43'd1 << IDX_VERSION_MARKER);
    localparam logic [42:0] LAYOUT_EXTRA =
        (43'd1 << IDX_S_POINTER) | (43'd1 << IDX_DST_SURF_STRIDE) |
        (43'd1 << IDX_DATA_CUBE_HEIGHT) | (43'd1 << IDX_DATA_CUBE_NOTCH) |
        (43'd1 << IDX_BS_CFG) | (43'd1 << IDX_BS_ALU_CFG) |
        (43'd1 << IDX_BS_MUL_CFG) | (43'd1 << IDX_BS_OW_CFG) |
        (43'd1 << IDX_WDMA_SIZE_0) | (43'd1 << IDX_WDMA_SIZE_1) |
        (43'd1 << IDX_BN_CFG) | (43'd1 << IDX_BN_ALU_CFG) |
        (43'd1 << IDX_BN_MUL_CFG) | (43'd1 << IDX_SURFACE_ADD) |
        (43'd1 << IDX_RDMA_S_POINTER) | (43'd1 << IDX_RDMA_BRDMA_CFG) |
        (43'd1 << IDX_RDMA_NRDMA_CFG) | (43'd1 << IDX_RDMA_EW_SURF_STRIDE) |
        (43'd1 << IDX_RDMA_SRC_DMA_CFG) | (43'd1 << IDX_RDMA_SURF_NOTCH) |
        (43'd1 << IDX_RDMA_WEIGHT) | (43'd1 << IDX_RDMA_EW_SURF_NOTCH);
    localparam logic [42:0] LAYOUT_MASK = SIMPLE_MASK | LAYOUT_EXTRA;
    localparam logic [42:0] REGROUP_MASK =
        (43'd1 << IDX_FEATURE_MODE_CFG) | (43'd1 << IDX_DATA_FORMAT) |
        (43'd1 << IDX_DST_BASE_ADDR) | (43'd1 << IDX_DST_SURF_STRIDE) |
        (43'd1 << IDX_DATA_CUBE_WIDTH) | (43'd1 << IDX_DATA_CUBE_HEIGHT) |
        (43'd1 << IDX_DATA_CUBE_NOTCH) | (43'd1 << IDX_DATA_CUBE_CHANNEL) |
        (43'd1 << IDX_BS_CFG) | (43'd1 << IDX_BS_OW_CFG) |
        (43'd1 << IDX_WDMA_SIZE_0) | (43'd1 << IDX_WDMA_SIZE_1) |
        (43'd1 << IDX_BN_CFG) | (43'd1 << IDX_EW_CFG) |
        (43'd1 << IDX_EW_CVT_OFFSET) | (43'd1 << IDX_EW_CVT_SCALE) |
        (43'd1 << IDX_OUT_CVT_OFFSET) | (43'd1 << IDX_OUT_CVT_SCALE) |
        (43'd1 << IDX_OUT_CVT_SHIFT) | (43'd1 << IDX_SURFACE_ADD) |
        (43'd1 << IDX_RDMA_WIDTH) | (43'd1 << IDX_RDMA_HEIGHT) |
        (43'd1 << IDX_RDMA_CHANNEL) | (43'd1 << IDX_RDMA_SRC_BASE) |
        (43'd1 << IDX_RDMA_ERDMA_CFG) | (43'd1 << IDX_RDMA_EW_BASE) |
        (43'd1 << IDX_RDMA_FEATURE_MODE) | (43'd1 << IDX_NEXT_ADDRESS) |
        (43'd1 << IDX_NEXT_AMOUNT) | (43'd1 << IDX_VERSION_MARKER);

    localparam logic [31:0] ENABLE_VALUE  = 32'h0000_0018;
    localparam logic [31:0] FEATURE_MODE  = 32'h0000_01e5;
    localparam logic [31:0] BS_CFG_VALUE  = 32'h0000_0053;
    localparam logic [31:0] BN_CFG_VALUE  = 32'h0000_0053;
    localparam logic [31:0] BS_OW_LAYOUT  = 32'h0000_0002;
    localparam logic [31:0] BS_OW_REGROUP = 32'h0000_0126;
    localparam logic [31:0] WEIGHT_VALUE  = 32'h0101_0101;
    localparam logic [31:0] REGROUP_STRIDE = 32'h0000_0010;
    localparam logic [31:0] REGROUP_ADD    = 32'h0000_0020;
    localparam logic [15:0] MAX_COUNT     = 16'd64000;

    logic [42:0] seen;
    logic [31:0] regval [0:NK-1];
    logic [5:0] key_index;
    logic [31:0] value, key;
    logic key_valid, enable_hit;
    logic [1:0] mode;                  // 0 simple, 1 layout, 2 regroup
    logic [42:0] mode_mask;
    logic set_extra, set_missing;
    logic dtype_ok, op_ok, ew_ok, basic_ok;
    logic channels_field_ok, channels_ok, width_ok, shape_ok, contract_ok;
    logic count_ok, addr_ok, next_ok;
    logic [2:0] out_prec, in_prec, proc_prec;
    logic [1:0] in_dtype, out_dtype;
    logic [2:0] op_code;
    logic [31:0] width_calc, channels_calc, channel_field;
    logic [15:0] count;
    logic [31:0] in_bytes, out_bytes;
    logic [4:0] in_shift, out_shift;
    logic [31:0] surfaces_in, surfaces_out, pad_in, pad_out;
    logic [31:0] ew_expected, erdma_expected, rdma_mode_expected;
    logic [31:0] a_base, b_base, dst_base, stride;
    logic [32:0] a_end, b_end, dst_end;
    integer i;

    assign value = cmd_data[47:16];
    assign key = {cmd_data[63:48], cmd_data[15:0]};
    assign cmd_ready = !cfg_valid && !engine_busy && !engine_error && !error;

    // Key index for the raw value store.
    always_comb begin
        key_valid = 1'b1;
        key_index = 6'd0;
        case (key)
            K_S_POINTER:           key_index = IDX_S_POINTER;
            K_FEATURE_MODE_CFG:    key_index = IDX_FEATURE_MODE_CFG;
            K_DATA_FORMAT:         key_index = IDX_DATA_FORMAT;
            K_DST_BASE_ADDR:       key_index = IDX_DST_BASE_ADDR;
            K_DST_SURF_STRIDE:     key_index = IDX_DST_SURF_STRIDE;
            K_DATA_CUBE_WIDTH:     key_index = IDX_DATA_CUBE_WIDTH;
            K_DATA_CUBE_HEIGHT:    key_index = IDX_DATA_CUBE_HEIGHT;
            K_DATA_CUBE_NOTCH:     key_index = IDX_DATA_CUBE_NOTCH;
            K_DATA_CUBE_CHANNEL:   key_index = IDX_DATA_CUBE_CHANNEL;
            K_BS_CFG:              key_index = IDX_BS_CFG;
            K_BS_ALU_CFG:          key_index = IDX_BS_ALU_CFG;
            K_BS_MUL_CFG:          key_index = IDX_BS_MUL_CFG;
            K_BS_OW_CFG:           key_index = IDX_BS_OW_CFG;
            K_WDMA_SIZE_0:         key_index = IDX_WDMA_SIZE_0;
            K_WDMA_SIZE_1:         key_index = IDX_WDMA_SIZE_1;
            K_BN_CFG:              key_index = IDX_BN_CFG;
            K_BN_ALU_CFG:          key_index = IDX_BN_ALU_CFG;
            K_BN_MUL_CFG:          key_index = IDX_BN_MUL_CFG;
            K_EW_CFG:              key_index = IDX_EW_CFG;
            K_EW_CVT_OFFSET:       key_index = IDX_EW_CVT_OFFSET;
            K_EW_CVT_SCALE:        key_index = IDX_EW_CVT_SCALE;
            K_OUT_CVT_OFFSET:      key_index = IDX_OUT_CVT_OFFSET;
            K_OUT_CVT_SCALE:       key_index = IDX_OUT_CVT_SCALE;
            K_OUT_CVT_SHIFT:       key_index = IDX_OUT_CVT_SHIFT;
            K_SURFACE_ADD:         key_index = IDX_SURFACE_ADD;
            K_RDMA_S_POINTER:      key_index = IDX_RDMA_S_POINTER;
            K_RDMA_WIDTH:          key_index = IDX_RDMA_WIDTH;
            K_RDMA_HEIGHT:         key_index = IDX_RDMA_HEIGHT;
            K_RDMA_CHANNEL:        key_index = IDX_RDMA_CHANNEL;
            K_RDMA_SRC_BASE:       key_index = IDX_RDMA_SRC_BASE;
            K_RDMA_BRDMA_CFG:      key_index = IDX_RDMA_BRDMA_CFG;
            K_RDMA_NRDMA_CFG:      key_index = IDX_RDMA_NRDMA_CFG;
            K_RDMA_ERDMA_CFG:      key_index = IDX_RDMA_ERDMA_CFG;
            K_RDMA_EW_BASE:        key_index = IDX_RDMA_EW_BASE;
            K_RDMA_EW_SURF_STRIDE: key_index = IDX_RDMA_EW_SURF_STRIDE;
            K_RDMA_FEATURE_MODE:   key_index = IDX_RDMA_FEATURE_MODE;
            K_RDMA_SRC_DMA_CFG:    key_index = IDX_RDMA_SRC_DMA_CFG;
            K_RDMA_SURF_NOTCH:     key_index = IDX_RDMA_SURF_NOTCH;
            K_RDMA_WEIGHT:         key_index = IDX_RDMA_WEIGHT;
            K_RDMA_EW_SURF_NOTCH:  key_index = IDX_RDMA_EW_SURF_NOTCH;
            K_NEXT_ADDRESS:        key_index = IDX_NEXT_ADDRESS;
            K_NEXT_AMOUNT:         key_index = IDX_NEXT_AMOUNT;
            K_VERSION_MARKER:      key_index = IDX_VERSION_MARKER;
            default:               key_valid = 1'b0;
        endcase
    end
    assign enable_hit = (key == K_OPERATION_ENABLE);

    // Exact captured EW_CFG reconstruction for a dtype x op pair.
    function automatic logic [31:0] ew_cfg_expected_value(
        input logic [1:0] dt, input logic [2:0] op, input logic bypass
    );
        logic [31:0] elem, v;
        begin
            elem = (dt == 2'd0) ? 32'd1 : (dt == 2'd1) ? 32'd2 : 32'd3;
            v = 32'h1000_0000 | (elem << 22) | 32'h0000_02c0;
            if (op == 3'd2) v = v | 32'h0000_0004;
            else begin
                v = v & ~32'h000f_0000;
                if (op == 3'd0) v = v | 32'h0002_0000;
                else if (op == 3'd1) v = v | 32'h0004_0000;
                else if (op == 3'd4) v = v | 32'h0001_0000;
            end
            if (op == 3'd3 || op == 3'd4) v = v | 32'h0020_0000;
            if (bypass) v = v | 32'h0000_0100;
            ew_cfg_expected_value = v;
        end
    endfunction

    function automatic logic [31:0] erdma_expected_value(input logic [1:0] dt);
        logic [31:0] elem;
        begin
            elem = (dt == 2'd0) ? 32'd1 : (dt == 2'd1) ? 32'd2 : 32'd3;
            erdma_expected_value = 32'h4000_0000 | (elem << 2);
        end
    endfunction

    function automatic logic [31:0] rdma_mode_expected_value(input logic [1:0] dt);
        logic [31:0] precision;
        begin
            precision = (dt == 2'd0) ? 32'd0 : (dt == 2'd1) ? 32'd1 : 32'd4;
            rdma_mode_expected_value = (precision << 15) | (32'd15 << 11) |
                                       (precision << 5) | 32'd1;
        end
    endfunction

    assign out_prec = regval[IDX_DATA_FORMAT][31:29];
    assign in_prec = regval[IDX_DATA_FORMAT][28:26];
    assign proc_prec = regval[IDX_DATA_FORMAT][2:0];

    always_comb begin : decode_fields
        in_dtype = 2'd0;
        out_dtype = 2'd0;
        dtype_ok = 1'b1;
        op_code = 3'd0;
        op_ok = 1'b1;
        mode = 2'd0;
        mode_mask = SIMPLE_MASK;
        ew_expected = 32'd0;
        erdma_expected = 32'd0;
        rdma_mode_expected = 32'd0;
        if (seen[IDX_EW_CVT_OFFSET]) begin
            mode = 2'd2;
            mode_mask = REGROUP_MASK;
        end else if (seen[IDX_DST_SURF_STRIDE]) begin
            mode = 2'd1;
            mode_mask = LAYOUT_MASK;
        end
        if (mode == 2'd2) begin
            in_dtype = 2'd1;
            out_dtype = 2'd2;
            dtype_ok = (in_prec == 3'd1) && (proc_prec == 3'd1) &&
                       (out_prec == 3'd4);
        end else begin
            dtype_ok = (in_prec == proc_prec) && (out_prec == in_prec);
            case (in_prec)
                3'd0: in_dtype = 2'd0;
                3'd1: in_dtype = 2'd1;
                3'd4: in_dtype = 2'd2;
                default: dtype_ok = 1'b0;
            endcase
            out_dtype = in_dtype;
        end
        if (regval[IDX_EW_CFG][2]) begin
            op_code = 3'd2;
            op_ok = (regval[IDX_EW_CFG][19:16] == 4'd0);
        end else begin
            case (regval[IDX_EW_CFG][19:16])
                4'd0: op_code = 3'd3;
                4'd1: op_code = 3'd4;
                4'd2: op_code = 3'd0;
                4'd4: op_code = 3'd1;
                default: op_ok = 1'b0;
            endcase
        end
        if (mode == 2'd2) op_ok = op_ok && (op_code == 3'd0);
        ew_expected = (mode == 2'd2)
            ? ew_cfg_expected_value(2'd1, 3'd0, 1'b0)
            : ew_cfg_expected_value(in_dtype, op_code, in_dtype == 2'd2);
        erdma_expected = erdma_expected_value(in_dtype);
        rdma_mode_expected = rdma_mode_expected_value(in_dtype);
        channel_field = regval[IDX_DATA_CUBE_CHANNEL];
        channels_field_ok = (channel_field[31:16] == channel_field[15:0]);
        channels_calc = {16'd0, channel_field[15:0]} + 32'd1;
        width_calc = regval[IDX_DATA_CUBE_WIDTH] + 32'd1;
        channels_ok = channels_field_ok &&
                      (regval[IDX_RDMA_CHANNEL] + 32'd1 == channels_calc) &&
                      (channels_calc >= 32'd1) && (channels_calc <= 32'd8191);
        width_ok = (regval[IDX_RDMA_WIDTH] + 32'd1 == width_calc) &&
                   (width_calc >= 32'd1) && (width_calc <= 32'd4096);
        stride = width_calc << 4;
        count = width_calc[15:0] * channels_calc[15:0];
        if (mode == 2'd2) count = 16'd8;
        count_ok = (count >= 16'd1) && (count <= MAX_COUNT);
        in_shift = (in_dtype == 2'd0) ? 5'd4 : (in_dtype == 2'd1) ? 5'd3 : 5'd2;
        out_shift = (out_dtype == 2'd0) ? 5'd4 : (out_dtype == 2'd1) ? 5'd3 : 5'd2;
        if (mode == 2'd2) begin
            in_bytes = {16'd0, count} * 32'd2;
            out_bytes = {16'd0, count} * 32'd4;
        end else if (mode == 2'd1) begin
            pad_in = channels_calc + ((32'd1 << in_shift) - 32'd1);
            pad_out = channels_calc + ((32'd1 << out_shift) - 32'd1);
            surfaces_in = pad_in >> in_shift;
            surfaces_out = pad_out >> out_shift;
            in_bytes = surfaces_in * stride;
            out_bytes = surfaces_out * stride;
        end else begin
            in_bytes = {16'd0, count} * (32'd16 >> in_shift);
            out_bytes = {16'd0, count} * (32'd16 >> out_shift);
        end
    end

    assign a_base = regval[IDX_RDMA_SRC_BASE];
    assign b_base = regval[IDX_RDMA_EW_BASE];
    assign dst_base = regval[IDX_DST_BASE_ADDR];
    assign a_end = {1'b0, a_base} + {1'b0, in_bytes};
    assign b_end = {1'b0, b_base} + {1'b0, in_bytes};
    assign dst_end = {1'b0, dst_base} + {1'b0, out_bytes};

    always_comb begin : validate
        set_extra = (seen & ~mode_mask) != 43'd0;
        set_missing = (mode_mask & ~seen) != 43'd0;
        basic_ok = (regval[IDX_FEATURE_MODE_CFG] == FEATURE_MODE) &&
                   (regval[IDX_RDMA_ERDMA_CFG] == erdma_expected) &&
                   (regval[IDX_RDMA_FEATURE_MODE] == rdma_mode_expected) &&
                   (regval[IDX_VERSION_MARKER] == 32'd0) &&
                   (regval[IDX_NEXT_ADDRESS] == 32'd0) &&
                   (regval[IDX_NEXT_AMOUNT] == 32'd0);
        ew_ok = (regval[IDX_EW_CFG] == ew_expected);
        if (mode == 2'd2) begin
            shape_ok = (width_calc == 32'd1) && (channels_calc == 32'd8);
            contract_ok = (regval[IDX_DST_SURF_STRIDE] == REGROUP_STRIDE) &&
                          (regval[IDX_DATA_CUBE_HEIGHT] == 32'd0) &&
                          (regval[IDX_DATA_CUBE_NOTCH] == 32'd0) &&
                          (regval[IDX_BS_CFG] == BS_CFG_VALUE) &&
                          (regval[IDX_BS_OW_CFG] == BS_OW_REGROUP) &&
                          (regval[IDX_WDMA_SIZE_0] == 32'd7) &&
                          (regval[IDX_WDMA_SIZE_1] == 32'd0) &&
                          (regval[IDX_BN_CFG] == BN_CFG_VALUE) &&
                          (regval[IDX_EW_CVT_OFFSET] == 32'd0) &&
                          (regval[IDX_EW_CVT_SCALE] == 32'd1) &&
                          (regval[IDX_OUT_CVT_OFFSET] == 32'd0) &&
                          (regval[IDX_OUT_CVT_SCALE] == 32'd1) &&
                          (regval[IDX_OUT_CVT_SHIFT] == 32'd0) &&
                          (regval[IDX_SURFACE_ADD] == REGROUP_ADD) &&
                          (regval[IDX_RDMA_HEIGHT] == 32'd0) &&
                          (regval[IDX_RDMA_CHANNEL] == 32'd7);
        end else if (mode == 2'd1) begin
            shape_ok = (width_calc == 32'd1);
            contract_ok = (regval[IDX_S_POINTER] == 32'h0000_000e) &&
                          (regval[IDX_RDMA_S_POINTER] == 32'h0000_000e) &&
                          (regval[IDX_RDMA_BRDMA_CFG] == 32'd1) &&
                          (regval[IDX_RDMA_NRDMA_CFG] == 32'd1) &&
                          (regval[IDX_DST_SURF_STRIDE] == stride) &&
                          (regval[IDX_DATA_CUBE_HEIGHT] == 32'd0) &&
                          (regval[IDX_DATA_CUBE_NOTCH] == 32'd0) &&
                          (regval[IDX_BS_CFG] == BS_CFG_VALUE) &&
                          (regval[IDX_BS_ALU_CFG] == 32'd0) &&
                          (regval[IDX_BS_MUL_CFG] == 32'd0) &&
                          (regval[IDX_BS_OW_CFG] == BS_OW_LAYOUT) &&
                          (regval[IDX_WDMA_SIZE_0] + 32'd1 == channels_calc) &&
                          (regval[IDX_WDMA_SIZE_1] + 32'd1 == width_calc) &&
                          (regval[IDX_BN_CFG] == BN_CFG_VALUE) &&
                          (regval[IDX_BN_ALU_CFG] == 32'd0) &&
                          (regval[IDX_BN_MUL_CFG] == 32'd0) &&
                          (regval[IDX_SURFACE_ADD] == stride) &&
                          (regval[IDX_RDMA_EW_SURF_STRIDE] == stride) &&
                          (regval[IDX_RDMA_SRC_DMA_CFG] == 32'd0) &&
                          (regval[IDX_RDMA_SURF_NOTCH] == 32'd0) &&
                          (regval[IDX_RDMA_EW_SURF_NOTCH] == 32'd0) &&
                          (regval[IDX_RDMA_WEIGHT] == WEIGHT_VALUE);
        end else begin
            shape_ok = (channels_calc == ((in_dtype == 2'd2) ? 32'd4 : 32'd8));
            contract_ok = (regval[IDX_EW_CVT_SCALE] == 32'd1) &&
                          (regval[IDX_RDMA_HEIGHT] == 32'd0);
        end
        addr_ok = (a_base[3:0] == 4'd0) && (b_base[3:0] == 4'd0) &&
                  (dst_base[3:0] == 4'd0) &&
                  (a_end <= 33'h1_0000_0000) && (b_end <= 33'h1_0000_0000) &&
                  (dst_end <= 33'h1_0000_0000) &&
                  ((a_base == dst_base) ||
                   !({1'b0, a_base} < dst_end && {1'b0, dst_base} < a_end)) &&
                  ((b_base == dst_base) ||
                   !({1'b0, b_base} < dst_end && {1'b0, dst_base} < b_end));
        next_ok = (regval[IDX_NEXT_ADDRESS] == 32'd0) &&
                  (regval[IDX_NEXT_AMOUNT] == 32'd0);
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            seen <= 43'd0;
            for (i = 0; i < NK; i = i + 1) regval[i] <= 32'd0;
            cfg_valid <= 1'b0;
            cfg_op <= 3'd0;
            cfg_dtype <= 2'd0;
            cfg_in_item <= 2'd0;
            cfg_out_item <= 2'd0;
            cfg_count <= 16'd0;
            cfg_a <= 32'd0;
            cfg_b <= 32'd0;
            cfg_dst <= 32'd0;
            error <= 1'b0;
            error_code <= 8'd0;
        end else begin
            if (cfg_valid && cfg_ready) cfg_valid <= 1'b0;
            if (cmd_valid && cmd_ready) begin
                if (enable_hit) begin
                    if (value != ENABLE_VALUE) begin
                        error <= 1'b1; error_code <= 8'd2;
                    end else if (set_extra) begin
                        error <= 1'b1; error_code <= 8'd2;
                    end else if (set_missing) begin
                        error <= 1'b1; error_code <= 8'd3;
                    end else if (!dtype_ok) begin
                        error <= 1'b1; error_code <= 8'd2;
                    end else if (!op_ok) begin
                        error <= 1'b1; error_code <= 8'd2;
                    end else if (!ew_ok) begin
                        error <= 1'b1; error_code <= 8'd2;
                    end else if (!basic_ok) begin
                        error <= 1'b1; error_code <= 8'd2;
                    end else if (!channels_field_ok) begin
                        error <= 1'b1; error_code <= 8'd2;
                    end else if (!channels_ok) begin
                        error <= 1'b1; error_code <= 8'd6;
                    end else if (!width_ok) begin
                        error <= 1'b1; error_code <= 8'd6;
                    end else if (!shape_ok) begin
                        error <= 1'b1; error_code <= 8'd6;
                    end else if (!contract_ok) begin
                        error <= 1'b1; error_code <= 8'd2;
                    end else if (!count_ok) begin
                        error <= 1'b1; error_code <= 8'd6;
                    end else if (!addr_ok) begin
                        error <= 1'b1; error_code <= 8'd4;
                    end else if (!next_ok) begin
                        error <= 1'b1; error_code <= 8'd7;
                    end else begin
                        cfg_valid <= 1'b1;
                        cfg_op <= op_code;
                        cfg_dtype <= out_dtype;
                        cfg_in_item <= in_dtype;
                        cfg_out_item <= out_dtype;
                        cfg_count <= count;
                        cfg_a <= a_base;
                        cfg_b <= b_base;
                        cfg_dst <= dst_base;
                    end
                end else if (!key_valid) begin
                    error <= 1'b1; error_code <= 8'd1;
                end else if (seen[key_index] && (regval[key_index] != value)) begin
                    error <= 1'b1; error_code <= 8'd2;
                end else begin
                    regval[key_index] <= value;
                    seen[key_index] <= 1'b1;
                end
            end
        end
    end
endmodule
