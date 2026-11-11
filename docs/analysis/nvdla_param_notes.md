# NVDLA convolution data-movement / atom parameterization — reference note

Scope: `/home/fedora/hw` (nvdla/hw checkout) plus `/home/fedora/ZYNQ-NVDLA`
(generated upstream copy) and the local `/home/fedora/rknpu-fpga` parameters.
Read-only survey; no repository file was modified. Gaps are marked **UNVERIFIED**.

## 1. Spec-side atom/bank definitions

`/home/fedora/hw/spec/defs/nv_full.spec:16-22`
```
#define MAC_ATOMIC_C_SIZE_64
#define MAC_ATOMIC_K_SIZE_32
#define MEMORY_ATOMIC_SIZE_32
#define CBUF_BANK_NUMBER_16
#define CBUF_BANK_WIDTH_64
#define CBUF_BANK_DEPTH_512
```

`/home/fedora/hw/spec/defs/projects.spec:99-105,107-113,115-121,130-150`
```
#if defined(MAC_ATOMIC_C_SIZE_64)
    %define NVDLA_MAC_ATOMIC_C_SIZE 64
#elif defined(MAC_ATOMIC_C_SIZE_8)
    %define NVDLA_MAC_ATOMIC_C_SIZE 8
...
#if defined(MAC_ATOMIC_K_SIZE_32)
    %define NVDLA_MAC_ATOMIC_K_SIZE 32
#elif defined(MAC_ATOMIC_K_SIZE_8)
    %define NVDLA_MAC_ATOMIC_K_SIZE 8
...
#if defined(MEMORY_ATOMIC_SIZE_32)
    %define NVDLA_MEMORY_ATOMIC_SIZE 32
#elif defined(MEMORY_ATOMIC_SIZE_8)
    %define NVDLA_MEMORY_ATOMIC_SIZE 8
...
#if defined(CBUF_BANK_NUMBER_16) ... NVDLA_CBUF_BANK_NUMBER 16 / 32
#if defined(CBUF_BANK_WIDTH_64)  ... NVDLA_CBUF_BANK_WIDTH  64 / 8
#if defined(CBUF_BANK_DEPTH_512) ... NVDLA_CBUF_BANK_DEPTH  512 (only value allowed)
```

Semantics:
- **atomC** = `NVDLA_MAC_ATOMIC_C_SIZE` = channels (reduction lanes) per MAC atom. Full profile 64, small profile 8.
- **atomK** = `NVDLA_MAC_ATOMIC_K_SIZE` = output kernels per MAC transaction. Full profile 32 (INT8), small 8.
- **entry size** = one CBUF entry = `NVDLA_MAC_ATOMIC_C_SIZE * NVDLA_BPE` bits (`NVDLA_CBUF_ENTRY_WIDTH`). With BPE=8 that is 64*8 = 512 bits = 64 B for the large profile; the generated RTL/C model actually reads **128 B per entry** because a bank entry is two 512-bit columns (see §3). Derived macro list (from the generated upstream copy):
  `/home/fedora/ZYNQ-NVDLA/build/ypcb/nv-large-generation-v1/upstream/outdir/nv_large/spec/defs/project.def:55-66`
  ```
  NVDLA_MAC_ATOMIC_C_SIZE_LOG2 log2(NVDLA_MAC_ATOMIC_C_SIZE)
  NVDLA_MAC_ATOMIC_K_SIZE_LOG2 log2(NVDLA_MAC_ATOMIC_K_SIZE)
  NVDLA_CBUF_BANK_NUMBER_LOG2 / BANK_WIDTH_LOG2 / BANK_DEPTH_LOG2
  NVDLA_CBUF_DEPTH_LOG2 = log2(BANK_NUMBER)+log2(BANK_DEPTH)
  NVDLA_CBUF_ENTRY_WIDTH = NVDLA_MAC_ATOMIC_C_SIZE*NVDLA_BPE
  NVDLA_CBUF_WIDTH_LOG2 / NVDLA_CBUF_WIDTH_MUL2_LOG2
  NVDLA_BPE_LOG2
  NVDLA_MAC_RESULT_WIDTH = NVDLA_BPE*2+NVDLA_MAC_ATOMIC_C_SIZE_LOG2
  NVDLA_CC_ATOMC_DIV_ATOMK = int(NVDLA_MAC_ATOMIC_C_SIZE/NVDLA_MAC_ATOMIC_K_SIZE)
  ```
  Generated values for the large profile (`project.h`): BPE 8, C64, K32, MEM32,
  BANK_NUMBER 16, BANK_WIDTH 64, BANK_DEPTH 512, CBUF_ENTRY_WIDTH 512,
  MAC_RESULT_WIDTH 22, CC_ATOMC_DIV_ATOMK 2.
  Small-256 profile (`nv_small_256.../outdir/nv_small_256/spec/defs/project.h:8-50`):
  C32, K8, MEM8, BANK_NUMBER 32, BANK_WIDTH 32, BANK_DEPTH 128,
  CBUF_ENTRY_WIDTH 256, MAC_RESULT_WIDTH 21, CC_ATOMC_DIV_ATOMK 4.
- **bank size** = `CBUF_BANK_WIDTH * CBUF_BANK_DEPTH` bits (64*512 = 32 Kib = 4 KiB
  per bank for the large profile); total CBUF = 16 banks x 4 KiB = 64 KiB by
  these literals. **UNVERIFIED**: the RTL instantiates 16 banks x 2 columns of
  `nv_ram_rws_256x512` (see §3), i.e. 16 x 256 x 128 B = 512 KiB, so the
  BANKS_WIDTH/DEPTH literals are not the RAM geometry of the checked-in
  `NV_NVDLA_cbuf.v`. Do not treat them as an RTL memory map without regenerating.
- **memory atom** = `NVDLA_MEMORY_ATOMIC_SIZE * NVDLA_BPE` bits = 32 B.
  The C model names the same 32 B granularity `ATOM_CUBE_SIZE`
  (`/home/fedora/hw/cmod/csc/NV_NVDLA_csc.h:68`, `cmod/cbuf/NV_NVDLA_cbuf.h`,
  `cmod/cacc/NV_NVDLA_cacc.h:100`).
- **BPE** is selected in the newly generated projects.spec
  (`/home/fedora/ZYNQ-NVDLA/build/ypcb/nv-large-generation-v1/upstream/spec/defs/projects.spec:1-7`):
  INT8 feature type -> BPE 8; INT16/FP16 feature type -> BPE 16.
  **UNVERIFIED / gap**: the `/home/fedora/hw` checkout's `projects.spec` is only
  234 lines and has no BPE selection nor the `NVDLA_CBUF_ENTRY_WIDTH` derivations;
  those were read from the ZYNQ-NVDLA generated copy.

## 2. CSC naming and semantics (sequence generator / datapath / weight loader)

`NV_NVDLA_CSC_sg.v` packet layouts:
- data packet `sg2dl_pd[30:0]` (`/home/fedora/hw/vmod/nvdla/csc/NV_NVDLA_CSC_sg.v:6826-6836`):
  ```
  dat_pkg_pd[4:0]   = w_offset
  dat_pkg_pd[9:5]   = h_offset
  dat_pkg_pd[16:10] = channel_size[6:0]
  dat_pkg_pd[23:17] = stripe_length[6:0]
  dat_pkg_pd[25:24] = cur_sub_h[1:0]
  dat_pkg_pd[26]    = block_end; [27]=channel_end; [28]=group_end; [29]=layer_end; [30]=dat_release
  ```
- weight packet `sg2wl_pd[17:0]` (`...CSC_sg.v:7091-7097`):
  ```
  wt_pkg_pd[6:0]   = weight_size[6:0]   // aligned channel count for this block
  wt_pkg_pd[12:7]  = kernel_size[5:0]   // taps in this stripe / group
  wt_pkg_pd[14:13] = cur_sub_h[1:0]
  wt_pkg_pd[15]    = channel_end; [16]=group_end; [17]=wt_release
  ```
- FIFO widths: data 33 b (idx+pd), weight 20 b
  (`NV_NVDLA_CSC_SG_dat_fifo.v:32-35`, `NV_NVDLA_CSC_SG_wt_fifo.v:32-35`);
  each is a 4-deep flop-RAM (`...dat_fifo.v:175`, `...wt_fifo.v:175`).

Channel alignment (the de-facto "align_c"):
`...CSC_sg.v:2954-2958` and `:5324-5357`
```
c_fetch_size = is_winograd ? 7'h4 : 7'h40;     // 64 for direct conv, 4 for WG
{channel_up_cnt_inc} = channel_up_cnt + c_fetch_size;
is_last_channel = (channel_up_cnt_inc >= weight_channel);
cur_channel = (is_winograd_d1 | ~is_last_channel) ? c_fetch_size :
              (reg2dp_weight_channel_ext[5:0] + 1'b1);
```
So **channel blocks are 64-element atoms** (equals `PARALLEL_CHANNEL_NUM=64`,
`cmod/csc/NV_NVDLA_csc.h:49`); a partial last block is `1..64`. The C model
lifts packed partial blocks into fewer CBUF entries:
`/home/fedora/hw/cmod/csc/NV_NVDLA_csc.cpp:633-644`
```
super_channel_num = (cube_in_channel + PARALLEL_CHANNEL_NUM - 1)/PARALLEL_CHANNEL_NUM;
last_super_channel_element_num = ... cube_in_channel % 64 ...;
atom_per_channel = (cube_in_channel*element_size + ATOM_CUBE_SIZE - 1)/ATOM_CUBE_SIZE;
cbuf_entry_per_slice = (atom_per_channel/4)*cube_in_width;
  + cube_in_width if remainder 3; +(cube_in_width+1)/2 if remainder 2;
  + (cube_in_width+3)/4 if remainder 1;
```
and the packing select (FP16 branch, `...csc.cpp:855-867`):
```
if (last_super_channel_element_num > 32)  packed_channel_iter = channel_iter;
else if (<=16)  packed_channel_iter = (input_atom_coor_width%4)*16 + channel_iter;
else            packed_channel_iter = (input_atom_coor_width%2)*32 + channel_iter;
```
**There is no identifier `align_c`/`ALIGN_C` anywhere in `/home/fedora/hw` or
`/home/fedora/ZYNQ-NVDLA`** (full-repo grep found no source hits). "align_c" is
donor/RK naming; the NVDLA equivalent is the 64-channel super-atom
(`c_fetch_size=0x40`, `PARALLEL_CHANNEL_NUM`) with a masked partial tail.
**UNVERIFIED**: exact packing for INT16/INT8 shares the same shape but different
element widths; only the FP16/INT16 path was excerpted.

Weight kernel groups (OC blocking):
`...CSC_sg.v:2885-2891`
```
weight_groups_w = is_int8 ? (reg2dp_weight_kernel[12:5] + 1'b1) :
                            (reg2dp_weight_kernel[12:4] + 1'b1);
```
`...CSC_sg.v:4727-4735`
```
cur_kernel = ~is_last_group ? (is_int8_d1 ? 6'h20 : 6'h10) :
             is_int8_d1 ? (reg2dp_weight_kernel[4:0] + 1'b1) :
                          (reg2dp_weight_kernel[3:0] + 1'b1);
```
=> **weight kernel group = 32 kernels for INT8, 16 kernels for FP16**
(`KERNEL_PER_GROUP_INT8=32`, `_INT16=16`, `_FP16=16`,
`cmod/csc/NV_NVDLA_csc.h:32-34`). The C model's group stride:
`...csc.cpp:1059-1066`
```
byte_per_kernel     = kernel_width * kernel_height * kernel_channel * element_size;
kernel_group_stride = byte_per_kernel * kernel_per_group_ideal;
kernel_group_num    = (kernel_num + kernel_per_group_ideal - 1)/kernel_per_group_ideal;
```

Kernel tap sequencing (r/s raster + optional y-extension):
`...CSC_sg.v:2893-2907`
```
{weight_r_add_w, mon_weight_r_add_w} = (6'h9 << reg2dp_y_extension);   // 9 taps * 2^yext
weight_r_last_w = weight_r_add_w[0] ? 2'b0 :
                  weight_r_add_w[1] ? {1'b0, reg2dp_weight_height_ext[0]} :
                  reg2dp_weight_height_ext[1:0];
```
`...CSC_sg.v:5583-5627`
```
is_last_s = (weight_s_up_cnt == weight_width_cmp);          // s = kernel width
is_last_r = (weight_r_up_cnt_inc > {1'b0, weight_height_cmp}); // r = kernel height
cur_r     = is_last_r ? weight_r_last : weight_r_add[2]?2'h3 : weight_r_add[1]?2'h1 : 2'h0;
is_last_block = is_last_s & is_last_r;
weight_s_up_cnt_w = layer_st?0 : is_last_s?0 : weight_s_up_cnt+1;
weight_r_up_cnt_w = layer_st?0 : is_last_r?0 : weight_r_up_cnt_inc[4:0];
```
Semantics: `s` (width) is the inner tap loop, `r` (height) is the outer one.
`y_extension` (0/1/2 -> 1/2/4) packs 2 or 4 kernel rows into one "super atom"
(`sub_h`), so `r` advances by `weight_r_add` per step. For image input,
`weight_width_cmp`/`weight_height_cmp` are forced to 0
(`...CSC_sg.v:2864-2877`), i.e. image mode relies on the outer pixel loop.
C-model equivalent: `kernel_atom_num = kernel_height*kernel_width`,
`stripe_operation_per_block_operation = (kw*kh + post_y_ext - 1)/post_y_ext`
(`...csc.cpp:631,1074`) and the tap coordinate mapping
`...csc.cpp:682-683,736-737`:
```
kernel_atom_coor_height = kernel_atom_iter/kernel_width;
kernel_atom_coor_width  = kernel_atom_iter%kernel_width;
input_atom_coor_width   = output_atom_coor_width*stride_w + kx*dilation - pad_left;
input_atom_coor_height  = output_atom_coor_height*stride_h + ky*dilation - pad_top;
```

Stripes (output-pixel runs that hold one weight set):
`...CSC_sg.v:2853-2862`
```
data_out_atomic_w = is_img ? reg2dp_dataout_width + 1 :
                    is_winograd ? ({2'b0, reg2dp_atomics[20:2]} + 1) :
                    reg2dp_atomics + 1;
```
`...CSC_sg.v:2926-2952`
```
lower_limit_w = is_img ? 7'h40 : is_winograd ? 7'h10 : (batches==0)?0x10:
                batches<=2?8: batches<=6?4: batches<=14?2:1;
upper_limit_w = is_img ? 7'h40 : is_winograd ? 7'h20 : (batches==0)?0x20:
                batches<=2?0x10: batches<=6?8: batches<=14?4:1;
```
`...CSC_sg.v:5072-5116`
```
stripe_up_cnt_inc = stripe_up_cnt + upper_limit;
is_last_stripe = (stripe_up_cnt_inc >= data_out_atomic);
cur_stripe = is_last_stripe ? (data_out_atomic[6:0]-stripe_up_cnt[6:0]) : lower_limit;
```
So a **stripe** is the number of output atoms (pixels) over which weights remain
resident; max 64 atoms for image mode, 32 for Winograd, 1..32 for batched
feature mode. The C model uses `ideal_stripe_length` 64 (image) or
`stripe_length[batch_num]` (16,8,4,...,1) (`...csc.cpp:578-579,1074-1079`).

CBUF entry reads / output address generation in CSC:
`...CSC_sg.v:6110-6116`, `:7171-7182`
```
pkg_weight_size_w = is_winograd_d1 ? 7'h40 : cur_channel;
stripe_length_w   = cur_stripe;
sg2dat_channel_size = dat_pop_pd[16:10];  sg2dat_stripe_length = dat_pop_pd[23:17];
sg2wt_weight_size   = wt_pop_pd[6:0];     sg2wt_kernel_size   = wt_pop_pd[12:7];
```
Weight source address in the C model (byte-major, modulo weight bank capacity):
`...csc.cpp:1176-1184`
```
kernel_atom_size_index = (weight_layer_start_byte_idx_
    + kernel_iter * current_super_atom_size
    + stripe_operation_iter * stripe_operation_stride
    + block_operation_iter  * block_operation_stride
    + kernel_group_iter     * kernel_group_stride) % (cbuf_entry_for_weight*CBUF_ENTRY_SIZE);
cbuf_entry_addr = cbuf_entry_for_data + kernel_atom_size_index/CBUF_ENTRY_SIZE;
begin_byte_within_one_entry = kernel_atom_size_index % CBUF_ENTRY_SIZE;
```
with `current_super_atom_size = cripple_channel_num * element_size * post_y_extension`
(`...csc.cpp:1153-1173`). This is the exact "weight halfwords per tap / group
stride" arithmetic.

Data movement/credit: CSC-SG stalls data/weight packets on CACC credit:
`...CSC_sg.v:8053-8086` (`credit_req_size = dat_impact_cnt + batch_delta;
credit_ready = ~sg2dat_channel_end | (credit_cnt >= credit_req_size)`).
It also handshakes CBUF/CDMA readiness via `cdma2sc_dat_entries/slices`,
`cdma2sc_wt_entries/kernels`, pending req/ack (`...CSC_sg.v:71-101`) and CACC
credit `accu2sc_credit_vld/size` (`...CSC_sg.v:86-87`).

`NV_NVDLA_CSC_WL_dec.v` is a **weight-expression decompressor**, not a spatial
unit: 1024-bit (128 B) packed weight word + 128-bit mask + 10-bit mask-enable ->
128 x 8-bit lanes, with 3 pipeline stages (`...NV_NVDLA_CSC_WL_dec.v:157-163`,
`:984` `input_mask_gated = ~input_mask_en[8] ? 128'b0 : input_mask;`).
The nibble/byte decompression select is `input_sel[15:0]` (`:161`), output
`output_sel[15:0]` (`:294`); it is reused by CSC_wl for compressed weights.

`NV_NVDLA_CSC_dl.v` (data loader) same packet fields:
`...CSC_dl.v:8646-8655`
```
dl_w_offset[4:0]=dl_pd[4:0]; dl_h_offset[9:5]=dl_pd[5..9];
dl_channel_size[6:0]=dl_pd[16:10]; dl_stripe_length[6:0]=dl_pd[23:17];
dl_cur_sub_h[1:0]=dl_pd[25:24]; dl_block_end[26], dl_channel_end[27],
dl_group_end[28], dl_layer_end[29], dl_dat_release[30];
```
and pixel coordinate arithmetic `...CSC_dl.v:9891-9902`, `:10461-10473`:
```
dl_w_offset_ext = dl_w_offset * x_dilate;
datain_w_cur    = datain_w_cnt + dl_w_offset_ext;
dl_h_offset_ext = dl_h_offset * y_dilate;
datain_h_cur    = datain_h_cnt + dl_h_offset_ext + sub_h_cnt;
```
This is the exact equivalent of our hand-built `input_pixel = (oy*STRIDE+ty)*W +
ox*STRIDE+tx` gather, done by NVDLA in `CSC_dl`.

## 3. CBUF and atom usage in CMAC

`/home/fedora/hw/vmod/nvdla/cbuf/NV_NVDLA_cbuf.v`
- Ports: 12-bit read addr `sc2buf_dat_rd_addr` / `sc2buf_wt_rd_addr`, 8-bit
  `sc2buf_wmb_rd_addr`; data out 1024 b (`:44-72`). Two write ports: data
  1024 b with `hsel[1:0]` (2 halves), weight 512 b with single `hsel`.
- Address split, `...NV_NVDLA_cbuf.v:887-888`, `:3492-3499`
  ```
  cbuf_p0_wr_bank = cbuf_p0_wr_addr[12-1:8];   // addr[11:8] = bank
  cbuf_p1_wr_bank = cbuf_p1_wr_addr[12-1:8];
  cbuf_p0_rd_addr = sc2buf_dat_rd_addr[11:0];
  cbuf_p0_rd_bank = cbuf_p0_rd_addr[12-1:8];
  ```
  Low 8 bits = entry index within bank. Writes are **half-entry** addressed:
  `(addr*2 + hsel)*64 B` in the C model (`cmod/cbuf/NV_NVDLA_cbuf.cpp:55,74`).
- RAM geometry is literal in RTL: 32 x `nv_ram_rws_256x512` = 16 banks x 2
  512-bit columns (`...NV_NVDLA_cbuf.v:3098-3480`). One bank entry therefore
  carries 2x512 b = 128 B; a bank has 256 entries. Total 512 KiB.
- `cmod/cbuf/NV_NVDLA_cbuf.h:25-33`: `CBUF_BANK_NUM 16`,
  `CBUF_ENTRY_PER_BANK 256`, `CBUF_ENTRY_SIZE 128`,
  `CBUF_DATA_BASE_BANK 0`, `CBUF_DATA_HEAD_BANK 14`,
  `CBUF_WEIGHT_BASE_BANK 1`, `CBUF_WEIGHT_HEAD_BANK 15`,
  `CBUF_HALF_ENTRY_SIZE 64`. WMB (compressed-weight mask) lives in bank 15,
  data in banks 0..14.

CMAC frames (`sc2mac` interface in `NV_NVDLA_CMAC_core.v:305,437,438...,566`):
- data: `[127:0] mask`, 128 x 8-bit lanes = 128 B, duplicated for A and B.
- weight: `[127:0] mask` + 128 x 8-bit lanes = 128 B + `[7:0] sel`.
- C-model interpretation (`cmod/cmac/NV_NVDLA_cmac.h:41-45`,
  `PARALLEL_CHANNEL_NUM 64`, `MAC_CELL_NUM 8`, `DATA_ELEMENT_NUM 2*64`,
  `WEIGHT_ELEMENT_NUM 8*128`, `RESULT_NUM_PER_MACELL 8`):
  - one feature payload = 64 channels x 16 b = 128 B (FP16/INT16), with the
    lower 64 B duplicated into the second half for INT8;
  - one weight payload = exactly one kernel's 64 aligned channels (128 B);
  - `sel` (`1<<kernel_iter`, or `1<<(kernel_iter/2)` for INT8 pairs) picks which
    of the 8 MAC cells' weight scratch buffers receives it
    (`cmod/csc/NV_NVDLA_csc.cpp:1417-1448`).
- Multiplier/atom count: `NV_NVDLA_CMAC_core.v` instantiates **8**
  `NV_NVDLA_CMAC_CORE_mac`, each with **64** `..._MAC_mul`
  (`...CORE_mac.v:49-63` inputs 1024 b data, 191-b exponent/mask). C model says
  `PARALLEL_KERNEL_NUM_INT8 16 / INT16 8` per CMAC (`cmod/cmac/NV_NVDLA_cmac.h:37-40`).
  So CMAC_A alone = C64 x K16(INT8)/K8(FP16); A+B = C64 x K32(INT8)/K16(FP16)
  = the spec C64/K32 for INT8, and FP16 K16.
- MAC result to CACC: 8 x 176 b + mask/mode/pd (`...CORE_rt_out.v:60-71`);
  CACC joins A+B into `MAC_CELL_NUM 16`, `RESULT_NUM_PER_MACELL 8`
  (`cmod/cacc/NV_NVDLA_cacc.h:61-66,96-97`) and emits 16-element atoms
  (`ATOM_ELEMENT_NUM_INT8 32 / INT16 16 / FP16 16`, `...cacc.h:69-74`).
- ACC output atom geometry/stride (`cmod/cacc/NV_NVDLA_cacc.cpp:354-408`):
  ```
  base_addr   = cacc_dataout_addr << 5;
  line_stride = cacc_line_stride << 5;
  atom_num    = cube_width*cube_height*((cube_channel+element_per_atom-1)/element_per_atom);
  atom_num_batch_2sdp = 1 / batch_num / 2*batch_num (64B-aligned line, width>1)
  ```
  => NVDLA **output atom = 16 FP16 elements = 32 B**, and addresses/line/surf
  strides are in **32-byte units** in the registers.

CDMA feature/weight strides (`NV_NVDLA_CDMA_regfile.v`, `NV_NVDLA_CDMA_dual_reg.v`):
- `NVDLA_CDMA_D_LINE_STRIDE_0`, `SURF_STRIDE_0`, `BATCH_STRIDE_0` are bits
  `[31:5]` => **32-byte units** (`...CDMA_dual_reg.v:394-395,414-415,432`,
  assignment at `:773-775,907-914,1031-1033`).
- `NVDLA_CDMA_D_ENTRY_PER_SLICE_0` bits `[11:0]` (`...CDMA_dual_reg.v:410,893-895`)
  is the number of 128 B CBUF entries per input line/slice; CSC checks it equals
  its own `cbuf_entry_per_slice` (`...csc.cpp:646-648`).
- `NVDLA_CDMA_D_CONV_STRIDE_0` x/y `[2:0]` each (`...CDMA_dual_reg.v:395,778-785`).
- Weight side: `NVDLA_CDMA_D_WEIGHT_ADDR_LOW_0` bits `[31:5]` (32 B units),
  `WEIGHT_BYTES_0` bits `[31:7]` (128 B units), `byte_per_kernel` size reg
  (`...CDMA_dual_reg.v:433-439`). Weight total is 128-B aligned
  (`cmod/cdma/NV_NVDLA_cdma.cpp:1605`).
- Feature fetch formula (`cmod/cdma/NV_NVDLA_cdma.cpp:1110,1390`):
  ```
  payload_addr = base + batch*batch_stride + slice*fetch_grain*line_stride
               + (super_surface*2 + surface)*surface_stride
  ```
  with `line_stride = cdma_line_stride << 5`, `surface_stride = cdma_surf_stride << 5`
  (`...cdma.cpp:1013-1014,1206-1207`). Feature atom = 32 B; a "super surface"
  = 2 atoms = 64 B (`super_normal_ratio=2`, `...cdma.cpp:1238-1244`).

## 4. Mapping to the local rknpu-fpga parameters

Local source anchors:
- `/home/fedora/rknpu-fpga/rtl/cmac/rk_conv_3x3_valid_c4_front.sv:8-23,55-59`
  ```systemverilog
  parameter int unsigned INPUT_CHANNELS = 4,
  parameter int unsigned KERNELS = 4,
  parameter int unsigned ALIGN_C = 16,
  parameter int unsigned PACK_C2 = 8,
  ...
  localparam int unsigned TAPS = 9;
  localparam int unsigned PIXEL_BYTES = PACK_C2 * 2;        // 16
  localparam int unsigned WEIGHT_LANES = KERNELS * ALIGN_C; // 64
  localparam int unsigned WEIGHT_HALFWORDS = TAPS * WEIGHT_LANES; // 576
  ```
- `...rk_conv_3x3_valid_c4_front.sv:123-135`
  ```systemverilog
  frame_weight_mask[kernel_lane*32 +: 32] = REAL_MASK;
  frame_weight[(kernel_lane*32 + input_lane)*16 +: 16] =
      weight_store[tap_index*WEIGHT_LANES + kernel_lane*ALIGN_C + input_lane];
  frame_data[input_lane*16 +: 16] = input_store[input_pixel][input_lane];
  frame_output_address = output_base + {21'd0, output_atom, 4'b0000};
  ```
- `...rk_conv_3x3_valid_c4_front.sv:114-117`: `tap_y = tap_index/3`,
  `tap_x = tap_index%3`, `input_pixel = (oy*STRIDE+ty)*W + ox*STRIDE+tx`.
- `rtl/cmac/rk_conv_3x3_valid_c4_core.sv:89-97` instantiates `.KERNELS(4),
  .ALIGN_C(16), .PACK_C2(8)`, and `:111` `.ATOMIC_C(32), .ATOMIC_K(16)`.
- `rtl/cmac/rk_conv_output_atom.sv:34` uses `.ATOMIC_K(8)` and writes
  `in_values[255:0]` (8 FP16 = 16 B).

Mapping table:

| Local parameter | Local value | Nearest NVDLA concept | Notes |
|---|---|---|---|
| `ATOMIC_C` | 32 | `NVDLA_MAC_ATOMIC_C_SIZE` | NVDLA full profile is 64; generated small_256 is 32. Our C32/K16 is a sliced, locally defined variant, not an NVDLA `nv_full` config. |
| `ATOMIC_K` | 16 | `NVDLA_MAC_ATOMIC_K_SIZE` | Equals the FP16 kernel group (16) and half the INT8 K32. `KERNEL_PER_GROUP_FP16=16`. |
| `PACK_C2` | 8 | (none) | **No NVDLA equivalent.** NVDLA has no C2 packing; its CBUF packs only partial 64-channel tails (4x4 or 2x2 rows per 128 B entry). C2=8 is the RK/donor NC1HWC2 layout. |
| `ALIGN_C` | 16 | `PARALLEL_CHANNEL_NUM`/`c_fetch_size` is 64, not 16 | **`align_c` is not an NVDLA identifier.** NVDLA's alignment is 64 elements (`c_fetch_size=0x40`), masked per partial block. Our 16 is a donor BO row alignment. |
| `REAL_C` | 1..4 | `last_super_channel_element_num` / mask width | NVDLA expresses real channels only via mask bits + zero fill of the 64-lane atom; it does not have a "real C" parameter. |
| `REAL_K` | 1..4 | `cur_kernel` remainder (`weight_kernel[3:0]+1`) | NVDLA expresses real kernels via `weight_kernel` remainder and `weight_groups`; the last group is short. |
| `TAP_COUNT` | 9 (3x3) | `kernel_height*kernel_width`; `weight_r_add = 9 << y_extension` | NVDLA iterates taps r-major/s-inner; 9 is derived, not a constant. |
| pixel plane stride | `PIXEL_BYTES=16` B (`PACK_C2*2`) | CBUF atom stride is 128 B / feature super-surface 64 B; CDMA `line_stride` is register x32 B | Our 16 B is donor pixel stride; NVDLA's is `line_stride<<5` with atoms 32 B. |
| weight halfwords per tap | `WEIGHT_LANES=64` (128 B) | one `sc2mac_wt` payload = 64 halfwords = 128 B = one kernel, one 64-channel block | Matches NVDLA exactly for FP16; NVDLA adds mask + `sel`. |
| output atom bytes | 16 B (8 FP16 lanes) | `ATOM_ELEMENT_NUM_FP16=16` -> **32 B** | Our atom is half an NVDLA output atom. NVDLA CACC would produce 16 lanes/32 B and C2 packing is ours only. |
| frame data mask | 32 b (`REAL_MASK`) | `sc2mac_dat_mask[127:0]`, 2 bits per 64 lanes | NVDLA uses 128-mask (2 bits/lane, nonzero/NaN-ish) vs our 1 bit/lane. |
| `frame_first/frame_last` | tap 0 / tap 8 | `stripe_st`/`stripe_end`/`channel_end`/`layer_end` | NVDLA has four end flags per packet (`sg2dl_pd[26:29]`); ours encodes first/last tap and final output separately. |

Derived local numbers (C4/K4, ALIGN_C16):
- weight BO = `TAPS * KERNELS * ALIGN_C` halfwords = 9*4*16 = 576 H = **1152 B**.
  Per tap = 4*16 = 64 H = **128 B**.
- input BO = pixels x `PACK_C2` x 2 B; C4/H9/W9 = 81*16 = **1296 B per C1
  plane**, 2 planes = 2592 B; grouped C2 = 25*16 = 400 B/plane, 800 B total.
  (`rtl/cmac/rk_conv_3x3_valid_c4_front.sv:219-220` advances pixel by
  `PIXEL_BYTES`, plane only by base).
- output atom index stride = 16 B (`{..., 4'b0000}`); RK plane stride is
  52 atoms = 832 B with four C1 planes = 3328 B for the C4 case
  (`docs/CONV_SPATIAL_3X3_C4.md:49-51`).

## 5. Which NVDLA modules could replace the hand-built spatial gather

If the goal is a general schedule instead of the capture-bounded front:

1. **`NV_NVDLA_CDMA_img` + `NV_NVDLA_CDMA_shared_buffer` + `cdma_mux`
   (+ `CDMA_cvt` for precision/scale)**
   `/home/fedora/hw/vmod/nvdla/cdma/...`
   Generates pixel/window reads from base/line/surface/batch strides plus
   `conv_x_stride`/`conv_y_stride`, `entries`, `grains`, `line_packed`,
   `surf_packed`. This is NVDLA's real spatial gather. Needs the CDMA regfile
   (`NV_NVDLA_CDMA_regfile.v`, CSB slave) plus the status/credit handshakes
   (`cdma2sc_dat_entries/slices`, `wt_entries/kernels`, pending req/ack).
2. **`NV_NVDLA_cbuf`**
   Stores gathered 128 B entries with 12-bit address = `[11:8] bank`,
   `[7:0] entry`; two write ports (data with `hsel`, weight 512 b), three read
   ports (data/weight/wmb 1024 b). Requires the SRAM macros
   (`nv_ram_rws_256x512`) or inferred equivalents and the bank split
   (data banks 0..14, weight 1..15, wmb 15). No parameters; fixed 16-bank layout.
3. **`NV_NVDLA_csc` / `NV_NVDLA_CSC_sg` / `CSC_dl` / `CSC_wl` (+ `CSC_WL_dec`)**
   Converts entries into `sc2mac` data/weight payloads with the exact
   `w_offset/h_offset/channel_size/stripe_length/sub_h/end` packets and the
   r/s tap loop. Requires the **CSC regfile**
   (`NV_NVDLA_CSC_regfile.v`, CSB slave, dual producer/consumer groups) with
   `reg2dp`: `atomics`, `data_bank`, `weight_bank`, `entries`, `datain_format`,
   `conv_mode`, `batches`, `y_extension`, `weight_width_ext`,
   `weight_height_ext`, `weight_channel_ext`, `weight_kernel`, `weight_bytes`,
   `weight_format`, `rls_slices`, `data_reuse`, `weight_reuse`,
   `skip_data_rls`, `skip_weight_rls`, `proc_precision`, `op_en`; status
   `dp2reg_done`, `sc_state`. It additionally needs the **CACC credit**
   (`accu2sc_credit_vld/size`) and **CDC to `nvdla_core_ng_clk`** (the CSC SG
   uses `nvdla_core_ng_clk`, `...CSC_sg.v:103`; CDMA/CSC updates cross through
   the `cdma2sc_*` handshakes).
4. **`NV_NVDLA_cmac` (`CMAC_CORE_active`/`CORE_cfg`/`CORE_mac`) + `NV_NVDLA_cacc`**
   Arithmetic and atom assembly. Needs the `sc2mac` 128 B + mask + `sel` streams
   and the `mac2accu` 8x176 b + mask/mode/pd interface, the CMAC and CACC
   regfiles, and the CACC->SDP delivery/atom writer. CACC's `MAC_CELL_NUM=16`
   yields 16-element (32 B) FP16 output atoms, not our 8-lane 16 B atoms.
5. **Lowest-effort pieces** reusable without the full cluster:
   - `CSC_SG_dat_fifo` / `CSC_SG_wt_fifo` as 4-deep skid buffers (33 b / 20 b).
   - `CSC_WL_dec` as the 128 B compressed-weight decompressor.
   - `CMAC_CORE_active` as a 64-lane feature formatter (2-bit-per-lane mask,
     1024 b data, duplicated halves for INT8).
   These still assume 64-lane/128 B payloads, so they would force ALIGN_C=64
   and PACK payload 128 B, or need a local width adapter.

Requirements summary to adopt the general path:
- **CBUF**: 512 KiB SRAM (16 banks x 256 entries x 128 B) with the three read
  and two write ports; data/weight bank split; WMB bank.
- **CSC regfile + CSB/APB bridge**: 64-bit-ish CSB request/resp (the regfile
  expects `csb2csc_req_pd`/`pvld`, returns `csc2csb_resp_pd[33:0]`); NSB/NVDLA
  CSB protocol, not our raw QWORD command stream. Our 54-QWORD task words would
  need a CSB adapter or a local register alias bank.
- **Status/CDC**: `nvdla_core_clk` vs `nvdla_core_ng_clk`; `sc_state[1:0]`,
  `dp2reg_done`, `cdma2sc_*_pending_ack`, `sc2cdma_*_pending_req`,
  `accu2sc_credit_*`; plus SLCG clock gating or tie-offs
  (`tmc2slcg_disable_clock_gating`, `dla_clk_ovr_on_sync`).
- **Regeneration, not parameter override**: every checked-in NVDLA vmod module
  has **zero `parameter` declarations** (grep counts 0 in
  `cbuf/NV_NVDLA_cbuf.v`, `csc/NV_NVDLA_csc.v`, `CSC_sg.v`, `CSC_dl.v`,
  `CSC_wl.v`, `cmac/NV_NVDLA_cmac.v`, `CMAC_core.v`). C/K/bank widths are baked
  by the Perl `#define` generator from `spec/defs/*.spec`; changing C32/K16 or
  bank geometry requires regenerating sources (and re-running
  `make generated-check` per repo rules) rather than overriding at instantiation.

## 6. Gaps / UNVERIFIED

- `align_c` / `ALIGN_C` literal: **not found** in `/home/fedora/hw` or
  `/home/fedora/ZYNQ-NVDLA`; it is donor/RK terminology. NVDLA's equivalent is
  64-element `PARALLEL_CHANNEL_NUM` / `c_fetch_size=0x40` plus masked tails.
- **C2 packing**: no NVDLA identifier or module. Closest is CBUF partial-tail
  packing (4x4 or 2x2 rows per 128 B entry) and CDMA image `pixel_format`/
  `packed_format` for raw pixel input. Do not present C2=8 as NVDLA behavior.
- `/home/fedora/hw/spec/defs/projects.spec` is 234 lines and lacks BPE and
  `NVDLA_CBUF_ENTRY_WIDTH` derivations; those were read from the ZYNQ-NVDLA
  generated upstream copy. Treat the hw checkout's derived-macro coverage as
  incomplete.
- `CBUF_BANK_WIDTH=64` / `CBUF_BANK_DEPTH=512` vs the literal RTL
  `nv_ram_rws_256x512` pairs was not fully reconciled. The RTL/C-model entry is
  128 B with 256 entries per bank; 512 KiB total was inferred, not confirmed by
  a generated memory map.
- Exact partial-tail packing for INT8/INT16 was not excerpted; only the
  FP16/INT16 branch of `cmod/csc/NV_NVDLA_csc.cpp:855-867` was read.
- `NV_NVDLA_partition_c` CMA/CBUF/CSC/CACC instantiation names were not confirmed
  (the grep of `vmod/nvdla/top/NV_NVDLA_partition_c.v` returned no `NV_NVDLA_cmac
  u_`/`NV_NVDLA_cacc u_` hits in the time available); the cluster wiring claim
  rests on the individual module ports and the cmod reference model.
- No numerical-equivalence or RTL-simulation evidence was produced here. This
  note is a source-reading reference only.
