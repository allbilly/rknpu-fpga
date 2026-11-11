# fdiv-systematic: device-free FDIV operand-class truth-table bundles

This directory contains **prepared, device-free** RK3588 Rocket capture bundles
for a systematic FP16 FDIV operand-class matrix.  Nothing here has been run on
the Orange Pi, RK3588 silicon or the FPGA.  No `ssh`, `scp`, board command,
submit, program or flash was executed.  No numerical oracle is supplied: every
case is `READY` with `oracle: none` and the later worker captures the real
device output.

The matrix is the complete Cartesian product of 16 raw FP16 classes for A and
16 raw FP16 classes for B: **256 pairs**, packed as **8 cases of 32 lanes**.
Each case is one FDIV task with `width=3` (32 physical lanes).  A is the outer
(row) class and B is the inner (column) class, so the pair order is row-major.

## Status

| Item | Value |
|---|---|
| Family | `fdiv-systematic` |
| READY cases | **8** |
| BLOCKED cases | **0** |
| Operand pairs | **256** (16 A classes x 16 B classes) |
| Lanes per case | **32** (`width=3`) |
| Oracle | **none** for every case |
| Manifest | `manifest.json` |
| Local validator | `tools/validate.py` |
| Local validation | `validation/local_validation.txt` (PASS, 2150 checks) |

## Raw FP16 operand classes

The class order below is exact and must not be reordered.  The bit patterns are
written to the buffers verbatim, including the quiet/signaling NaN payloads.

| Index | Name | Bits | Meaning |
|---:|---|---|---|
| 0 | `zero_p` | `0x0000` | `+0` |
| 1 | `zero_n` | `0x8000` | `-0` |
| 2 | `inf_p` | `0x7c00` | `+inf` |
| 3 | `inf_n` | `0xfc00` | `-inf` |
| 4 | `qnan` | `0x7e00` | quiet NaN, payload `0x200` |
| 5 | `snan` | `0x7c01` | signaling NaN, payload `0x001` |
| 6 | `sub_min` | `0x0001` | minimum positive subnormal |
| 7 | `sub_max` | `0x03ff` | maximum positive subnormal |
| 8 | `norm_min` | `0x0400` | minimum positive normal |
| 9 | `fin_max` | `0x7bff` | maximum positive finite |
| 10 | `one_p` | `0x3c00` | `+1.0` |
| 11 | `one_n` | `0xbc00` | `-1.0` |
| 12 | `half_p` | `0x3800` | `+0.5` |
| 13 | `half_n` | `0xb800` | `-0.5` |
| 14 | `two_p` | `0x4000` | `+2.0` |
| 15 | `two_n` | `0xc000` | `-2.0` |

## Pair grid and case-to-row mapping

Each cell is the **global pair index** `16 * A_index + B_index`.  Row A00 is
the first A class (`0x0000`), row A15 is the last (`0xc000`).  Column B00 is
the first B class (`0x0000`), column B15 is the last (`0xc000`).

```text
        B00 B01 B02 B03 B04 B05 B06 B07 B08 B09 B10 B11 B12 B13 B14 B15
A00      000 001 002 003 004 005 006 007 008 009 010 011 012 013 014 015
A01      016 017 018 019 020 021 022 023 024 025 026 027 028 029 030 031
A02      032 033 034 035 036 037 038 039 040 041 042 043 044 045 046 047
A03      048 049 050 051 052 053 054 055 056 057 058 059 060 061 062 063
A04      064 065 066 067 068 069 070 071 072 073 074 075 076 077 078 079
A05      080 081 082 083 084 085 086 087 088 089 090 091 092 093 094 095
A06      096 097 098 099 100 101 102 103 104 105 106 107 108 109 110 111
A07      112 113 114 115 116 117 118 119 120 121 122 123 124 125 126 127
A08      128 129 130 131 132 133 134 135 136 137 138 139 140 141 142 143
A09      144 145 146 147 148 149 150 151 152 153 154 155 156 157 158 159
A10      160 161 162 163 164 165 166 167 168 169 170 171 172 173 174 175
A11      176 177 178 179 180 181 182 183 184 185 186 187 188 189 190 191
A12      192 193 194 195 196 197 198 199 200 201 202 203 204 205 206 207
A13      208 209 210 211 212 213 214 215 216 217 218 219 220 221 222 223
A14      224 225 226 227 228 229 230 231 232 233 234 235 236 237 238 239
A15      240 241 242 243 244 245 246 247 248 249 250 251 252 253 254 255
```

Case `c` (0..7) covers A rows `2c` and `2c+1`, i.e. global pair indices
`32c .. 32c+31`:

| # | Case | A rows | A class, lanes 0-15 | A class, lanes 16-31 | B classes per half | Global pairs |
|---:|---|---|---|---|---|---|
| 0 | `fdiv_class_rows_00_01` | A00, A01 | `0x0000` (+0) | `0x8000` (-0) | B00..B15 | 0..31 |
| 1 | `fdiv_class_rows_02_03` | A02, A03 | `0x7c00` (+inf) | `0xfc00` (-inf) | B00..B15 | 32..63 |
| 2 | `fdiv_class_rows_04_05` | A04, A05 | `0x7e00` (qNaN) | `0x7c01` (sNaN) | B00..B15 | 64..95 |
| 3 | `fdiv_class_rows_06_07` | A06, A07 | `0x0001` (min subnormal) | `0x03ff` (max subnormal) | B00..B15 | 96..127 |
| 4 | `fdiv_class_rows_08_09` | A08, A09 | `0x0400` (min normal) | `0x7bff` (max finite) | B00..B15 | 128..159 |
| 5 | `fdiv_class_rows_10_11` | A10, A11 | `0x3c00` (+1.0) | `0xbc00` (-1.0) | B00..B15 | 160..191 |
| 6 | `fdiv_class_rows_12_13` | A12, A13 | `0x3800` (+0.5) | `0xb800` (-0.5) | B00..B15 | 192..223 |
| 7 | `fdiv_class_rows_14_15` | A14, A15 | `0x4000` (+2.0) | `0xc000` (-2.0) | B00..B15 | 224..255 |

## Lane order and alignment

For case `c` and local lane `i` in `0..31`:

```text
A_index = 2*c + i // 16
B_index = i % 16
global_pair = 16*A_index + B_index = 32*c + i
```

Thus lanes 0-15 are the first A row against B00..B15, and lanes 16-31 are the
second A row against B00..B15.  Input files are raw little-endian FP16
halfwords in exactly this lane order:

- `input-a.bin`: 32 halfwords, exactly 64 bytes, one A class per lane;
- `input-b.bin`: 32 halfwords, exactly 64 bytes, one B class per lane;
- `output.bin` (worker-created): 32 halfwords, exactly 64 bytes.

The manifest repeats this order in each case's `pairs` array.  Each entry has
`lane`, `pair_index`, and the raw `a`/`b` class index, name and bits.  A later
worker should align output halfword `i` with `pairs[i]`; no lane is padding.

## Register stream

Every `regcmd.bin` is 22 little-endian 64-bit QWORDs (176 bytes), encoded as
`target << 48 | value32 << 16 | offset`.  This is the terminal single-task
donor layout: the **17 non-padding command entries** requested for FDIV, plus
**five zero-valued donor fields** retained as padding so the stream has the
same 22-QWORD shape as the other capture families.

| Index | Target | Offset | Value | Field | Role |
|---:|---|---|---|---|---|
| 0 | `0x1001` DPU | `0x4004` | `0x0000000e` | `dpu_s_pointer` | command |
| 1 | `0x1001` DPU | `0x400c` | `0x000001e5` | `dpu_feature_mode_cfg` | command |
| 2 | `0x1001` DPU | `0x4010` | `0x48000002` | `dpu_data_format` | command |
| 3 | `0x1001` DPU | `0x4030` | `0x00000003` | `dpu_data_cube_width` (`width=3`) | command |
| 4 | `0x1001` DPU | `0x4034` | `0x00000000` | `dpu_data_cube_height` | padding |
| 5 | `0x1001` DPU | `0x4038` | `0x00000000` | `dpu_data_cube_notch` | padding |
| 6 | `0x1001` DPU | `0x403c` | `0x00070007` | `dpu_data_cube_channel` | command |
| 7 | `0x1001` DPU | `0x4070` | `0x108303c0` | `dpu_ew_cfg` (FDIV) | command |
| 8 | `0x1001` DPU | `0x4084` | `0x00000001` | `dpu_out_cvt_scale` | command |
| 9 | `0x2001` RDMA | `0x5004` | `0x0000000e` | `rdma_s_pointer` | command |
| 10 | `0x2001` RDMA | `0x500c` | `0x00000003` | `rdma_data_cube_width` | command |
| 11 | `0x2001` RDMA | `0x5010` | `0x00000000` | `rdma_data_cube_height` | command |
| 12 | `0x2001` RDMA | `0x5014` | `0x00000007` | `rdma_data_cube_channel` | command |
| 13 | `0x2001` RDMA | `0x5034` | `0x40000008` | `rdma_erdma_cfg` | command |
| 14 | `0x1001` DPU | `0x4020` | `0x00000000` | `dst_base_addr` | command, **placeholder** |
| 15 | `0x2001` RDMA | `0x5018` | `0x00000000` | `src_a_base_addr` | command, **placeholder** |
| 16 | `0x2001` RDMA | `0x5038` | `0x00000000` | `src_b_base_addr` | command, **placeholder** |
| 17 | `0x2001` RDMA | `0x5044` | `0x00017841` | `rdma_feature_mode_cfg` | command |
| 18 | `0x0101` PC_REG | `0x0010` | `0x00000000` | `pc_base_address` | padding |
| 19 | `0x0101` PC_REG | `0x0014` | `0x00000000` | `pc_register_amounts` | padding |
| 20 | `0x0041` VERSION | `0x0000` | `0x00000000` | `version_marker` | padding |
| 21 | `0x0081` PC | `0x0008` | `0x00000018` | `pc_operation_enable` | command |

The five padding entries are indices 4, 5, 18, 19 and 20.  Removing them leaves
the 17 requested command entries: indices 0, 1, 2, 3, 6, 7, 8, 9, 10, 11, 12,
13, 14, 15, 16, 17 and 21.

### Address patches

The three address fields are zero placeholders.  `job.json` declares exactly
three CAPTURE_FORMAT.md `value32` patches, which replace command bits
`[47:16]` with the buffer's 32-bit DMA address while preserving the target in
bits `[63:48]` and the register offset in bits `[15:0]`:

| QWORD | Buffer | Target/offset | Field |
|---:|---|---|---|
| 14 | `out` | `0x1001`/`0x4020` | `dst_base_addr` |
| 15 | `a` | `0x2001`/`0x5018` | `src_a_base_addr` (A) |
| 16 | `b` | `0x2001`/`0x5038` | `src_b_base_addr` (B / RDMA EW) |

All three patches must be applied before submit.  An unpatched stream addresses
zero and must not be treated as a valid capture.

## Bundle layout

```text
fdiv-systematic/
  README.md
  manifest.json
  tools/generate.py
  tools/validate.py
  validation/local_validation.{json,txt}
  cases/
    fdiv_class_rows_00_01/
      job.json           CAPTURE_FORMAT.md job description
      regcmd.bin         22 QWORDs = 176 bytes
      input-a.bin        32 FP16 halfwords = 64 bytes
      input-b.bin        32 FP16 halfwords = 64 bytes
      # output.bin is created by the later board worker; it is not bundled
    ...                  seven more cases, rows 02_03 .. 14_15
```

`job.json` declares one task at `regcmd_offset_words: 0` with
`regcmd_words: 22`, and exactly three buffers:

| Buffer | Size | Direction | File |
|---|---:|---|---|
| `a` | 64 | in | `input-a.bin` |
| `b` | 64 | in | `input-b.bin` |
| `out` | 64 | out | worker writes `output.bin` |

There is deliberately no `expected.bin`, no `output.bin` and no CPU-computed
result in any bundle.  `oracle: none` means the raw device output is the
characterization record; a CPU division result must not be substituted.

## Local validation

`tools/validate.py` is a local parser only.  It checks JSON shape, exactly 64
bytes for every input/output declaration, the exact 22-QWORD register template,
patch indices and zero placeholders, task bounds, bundle hashes and all 256
row-major pairs/lane bits.  It does not create a device output.

Run it from the repository root:

```sh
python3 build/rk3588-example-captures/fdiv-systematic/tools/validate.py
```

Current result (`validation/local_validation.txt`):

```text
status: PASS
checks: 2150
cases: 8 declared, 8 manifest entries, status READY required
buffers: 16 input files x 64 bytes, output declared 64 bytes
regcmd: 8 files x 22 QWORDs (176 bytes), exact template matched
patches: 24 value32 patches, indices 14/15/16, placeholders zero
task bounds: offset 0 + 22 QWORDs within each 22-QWORD stream
pair order: 256/256 unique row-major pairs, A outer, B inner; 32 lanes per case
```

This is structural preparation evidence, not SystemVerilog, FPGA or RK3588
silicon validation.  The later worker runs the cases under the board lock and
records actual addresses, `submit_ret`, durations, hashes and the board/tool
identity in its capture record.
