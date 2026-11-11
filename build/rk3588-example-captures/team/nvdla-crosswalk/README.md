# RKNPU <-> NVDLA field crosswalk

Device-free, read-only analysis of the hypothesis that the RKNPU RTL is the NVDLA RTL with
different register names/offsets. No board access, no ssh/scp, no FPGA programming, no tracked
source changes.

## Files

- `FIELD_CROSSWALK.md` - readable report: method, cases, offset-alias tests, per-block field
  tables, verdicts, strongest evidence and caveats.
- `FIELD_CROSSWALK.json` - machine-readable version: decoded QWORDs, per-field RK value, NVDLA
  register/field/shift/mask, expected encoding, literal-copy decode, classification, source
  lines and arithmetic.
- `build_crosswalk.py` - generator; decodes the captured `regcmd.bin` files and parses the
  NVDLA headers. Re-run with `python3 build_crosswalk.py`.
- `specdump.py`, `fieldlines.py` - small read-only helpers used to dump NVDLA field tables and
  citation lines.

## Method

1. Decode each RK command QWORD as `(target << 48) | (value << 16) | reg_addr`.
2. Parse the generated NVDLA `nv_small_256` headers for register offsets, field shifts and
   masks (`build/ypcb/.../spec/manual/NVDLA_*.h`).
3. Resolve ambiguous value conventions from the NVDLA RTL: counts are last-index (value-1),
   strides are byte-addressed, the CDMA CVT is integer-only.
4. For each row, extract the RK semantic field, compute the NVDLA expected encoding, and also
   show what a literal copy of the RK value would decode to in the NVDLA field.
5. Classify only from a decoded capture value or a source definition. Offset similarity alone is
   never accepted as proof.

## Cases used

- `conv-simple/cases/conv_simple_fp16_3x3_c16_h8_w8_oc32` (required 3x3 FP16)
- `conv-simple/cases/simple_conv_int8_5x5_c8_h8_w8_oc32` (required INT8)
- `conv-fp16/cases/conv_3x3_valid_c4_h9_w9_oc4` (required conv-fp16 3x3)
- `ew-fp16/cases/{add,sub,mul,max}_p1_n8` (required EW cases)
- Supporting: `conv-fp16/cases/conv_depthwise_3x3_c3_h11_w28_oc3` (asymmetric H/W, to prove the
  RK width/height swap) and `conv-simple/cases/conv_simple_fp16_1x1_c4_h8_w8_oc16` (RK-only
  CONV_CON1 bits and FP32 output).

## Verdicts

| Block | NVDLA reference | Verdict |
|---|---|---|
| CNA | CSC + CDMA | reusable with adapter + specific datapath changes |
| CORE | CACC | reusable with a pure register adapter (accumulator/output-size subset) |
| DPU | SDP | reusable with adapter + specific datapath changes (EW stage is compile-time disabled in nv_small_256) |
| RDMA | SDP_RDMA | adapter + datapath change for the captured FP16 EW cases (ERDMA is not instantiated in nv_small_256); adapter + config addition for the INT8 BRDMA bias path; pure adapter only for MRDMA cube/source fields |

Strict hypothesis ("different register names/offsets") is **disproved**: only four fields are
identical aliases (RDMA cube W/H/C and SRC_BASE low). The block decomposition and many field
semantics are NVDLA-family, so a weaker hypothesis (NVDLA-derived blocks with a rewritten
register file) remains plausible, but register streams cannot prove RTL identity.

## Strongest evidence

- CNA `DATA_SIZE0=0x00080008` vs NVDLA `0x00070007`; the asymmetric C5 capture
  `0x001c000b` (H=11, W=28) vs `0x000a001b` proves the width/height swap and the +1.
- CNA `WEIGHT_SIZE2=0x03030020` packs kw/kh/kernels that NVDLA splits across
  `D_WEIGHT_SIZE_EXT_0=0x00020002` and `D_WEIGHT_SIZE_EXT_1` kernel=31.
- CNA `DMA_CON1/2` are 32-byte-unit strides (`conv_new_clean.py:274-276`); NVDLA line/surface
  strides are byte-addressed (`cdma.v:829-830`).
- CORE `MISC_CFG=0x201` for a direct 3x3 conv would be CACC `conv_mode=1` (Winograd) and
  `proc_precision=0` if copied literally; CLIP at `0x301c` vs CACC `0x702c` disproves a single
  fixed offset shift.
- DPU `FEATURE_MODE_CFG=0x1E5` decodes in SDP as flying=1, winograd=1, batch=1;
  `EW_CFG=0x108402C0` for SUB has ALU_ALGO=4 in a 3-bit field at [18:16], while SDP's ALU_ALGO
  is 2 bits at [3:2] and has no SUB enum; `DATA_FORMAT=0xA8000002` uses OUT_PRECISION=5 (FP32),
  which SDP cannot represent.
- The `nv_small_256` reference build has `NVDLA_SDP_EW_THROUGHPUT=0`; the SDP core ties
  `cfg_ew_en=0` and has no `reg2dp_ew_*` ports (`NV_NVDLA_SDP_core.v:329,334`; `project.vh:16`).
  The EW registers are defined in the header but the EW datapath is not usable in this build.
- The same build does not instantiate ERDMA: `NV_NVDLA_SDP_rdma.v` hardwires `erdma_disable=1`
  and has only `u_brdma`/`u_nrdma` (lines 216,258,350). The captured FP16 EW cases fetch their B
  operand via ERDMA, so that path is not usable without enabling/instantiating ERDMA.
- RDMA `FEATURE_MODE_CFG=0x17849` copies into SDP_RDMA as proc_precision=0 and batch_number=24;
  `ERDMA_CFG=0x40000008` copies as data_use=MUL and data_mode=0; `RDMA_WEIGHT=0x01010101` has no
  SDP_RDMA counterpart.

## Caveats

- Register writes prove the programming model, not RTL internals. "Reusable" here means the
  field-level contract can be adapted, not that any RK RTL file is or is not copied from NVDLA.
- The NVDLA reference is `nv_small_256`; other configurations may differ in CBUF/atom geometry.
- DMA address fields in the captured streams are zero placeholders patched at run time; address
  rows cite the job patch, not a device address.
- The required conv cases are square. The width/height swap conclusion uses the supporting C5
  depthwise 28x11 case; the required cases alone cannot distinguish the two orderings.
- Padding is only evidenced at zero. No non-zero padding or SAME-padding capture exists (the
  SAME-padding case is BLOCKED).
- No non-identity CVT capture exists; the four-lane CVT conclusion is source-level plus the
  captured identity values.
- SUB/FDIV conclusions are based on the NVDLA SDP ALU opcode set and the absence of a divider,
  not on a device differential test.
- Builder comments are not authoritative. `CVT_CON5` and CORE `MISC_CFG` bit0 are two examples
  where the comment and the decoded value disagree.

## Relation to `team/nvdla-reference/REFERENCE_MAPPING.md`

This work confirms the block-level direction (CNA~CSC+CDMA, CORE~CACC, DPU~SDP, RDMA~SDP_RDMA)
but refines it:

- CORE is a compacted CACC subset, not a uniform "+4 shift": the +4 relation holds for
  MISC/DATAOUT_SIZE_0/1, but CLIP is at `0x301c` vs CACC `0x702c`, and `0x3030` is a read-only
  CACC status offset.
- CNA is a merged, **reduced** CSC+CDMA register surface with a new packing, not a simple merge
  of the two NVDLA register maps.
- DPU/RDMA need more than a field rename: FEATURE_MODE_CFG, DATA_FORMAT and EW_CFG are repacked,
  and several RK-only fields have no NVDLA counterpart.

## Artifact note

All outputs here are text/JSON and small; no build or simulator byproducts are retained. The
analysis is reproducible from the referenced capture bundles and header files.
