# Independent RK3588 capture bundle audit

**Audit status: PASS**

- Parser: `team/audit/audit.py` version `independent-bundle-audit/1.3.0`
- Parser source SHA-256: `9929d4c1cb9cae4538a0597fcb478f0be59191ce049679b988463636c48aa1ee`
- Generated (UTC): 2026-11-05T22:09:59.599746Z
- Snapshot window (UTC): 2026-11-05T22:09:59.354195Z .. 2026-11-05T22:09:59.399692Z
- Snapshot tree SHA-256: `21166d0cbbc4efb52b1ec16e2a29c8897caf3feeab79438d37bd62bd98d584dc`
- Python: 3.14.5 (main, May 10 2026, 10:21:34) [GCC 12.3.0]
- Platform: linux
- rknpu-fpga revision at audit: `f9b00d8f9a48ab4dea20cb30148890cd9f1443ee`
- rk3588 revision at audit: `273d015e08af40c81d2cd9ab84198486b03a17f1`
- CAPTURE_FORMAT.md: `c7704fb240d7c760a327ca9d4cd5bb5798659ba732f64434d979dc6860936719` (4766 bytes)

## Commands used

```
cd /home/fedora/rknpu-fpga
python3 -m py_compile /home/fedora/rknpu-fpga/build/rk3588-example-captures/team/audit/audit.py
python3 /home/fedora/rknpu-fpga/build/rk3588-example-captures/team/audit/audit.py --root /home/fedora/rknpu-fpga/build/rk3588-example-captures --out-json /home/fedora/rknpu-fpga/build/rk3588-example-captures/team/audit/AUDIT.json --out-md /home/fedora/rknpu-fpga/build/rk3588-example-captures/team/audit/AUDIT.md
python3 --version  # 3.14.5 (main, May 10 2026, 10:21:34) [GCC 12.3.0]
git -C /home/fedora/rknpu-fpga rev-parse HEAD  # f9b00d8f9a48ab4dea20cb30148890cd9f1443ee
git -C /home/fedora/rk3588 rev-parse HEAD  # 273d015e08af40c81d2cd9ab84198486b03a17f1
```

No `ssh`, `scp`, board access, device submit, FPGA programming or flash operation was performed.
This audit did not modify any family bundle, tracked source, test or documentation file.

## Declared determinism / seeds

- conv-fp16: `{'provenance_seeds': [42]}`
- conv-simple: `{'seeds': {'fp16': 42, 'int8': 1234, 'note': 'FP16 seed matches expt/conv_simple.py::run_shape.  INT8 seed is a preparation choice; each case also records its seed.'}, 'parity_padding': {'reason': 'Rocket PC fetch amount is expressed in QWORD pairs; an odd declared count fetches one extra QWORD.', 'applied_to': 'all READY cases', 'qwords': 1, 'value': 0, 'executed': False, 'declared_words_field': 'job.json tasks[].regcmd_words', 'file_words_fields': ['manifest.cases[].regcmd_file_words', 'manifest.cases[].regcmd_fetch_words', 'manifest.cases[].regcmd_size_bytes']}}`
- ew-fp16: `{'input_generation': 'closed-form deterministic patterns; no RNG and no seed'}`
- pooling: `{'input_generation': 'closed-form source arrays and constants; no RNG and no seed'}`

The audit itself uses no RNG and no seed.

## Per-family results

| Family | Manifest entries | Bundle dirs | READY | BLOCKED | INVALID | Verdict |
|---|---:|---:|---:|---:|---:|---|
| conv-fp16 | 14 | 11 | 9 | 5 | 0 | PASS |
| conv-gemm-vendor | 13 | 13 | 10 | 3 | 0 | PASS |
| conv-simple | 12 | 12 | 7 | 5 | 0 | PASS |
| ew-fp16 | 54 | 54 | 54 | 0 | 0 | PASS |
| ew-int | 18 | 15 | 15 | 3 | 0 | PASS |
| fdiv-systematic | 8 | 8 | 8 | 0 | 0 | PASS |
| pooling | 21 | 21 | 19 | 2 | 0 | PASS |
| **TOTAL** | **140** | **134** | **122** | **18** | **0** | **PASS** |

Counts are over the union of manifest entries and bundles present under `cases/`. A manifest `BLOCKED` case is counted BLOCKED only when its probe/bundle structure is valid; structural errors make the case INVALID.

**Case status: PASS** (122 READY / 18 BLOCKED / 0 INVALID). **Provenance/cross-family status: PASS** (0 family-level errors, 0 cross-family errors, 0 live-tree changes).

Checked 126 jobs, 364 buffers, 128 task descriptors, 365 patches, and 814 per-case hashes (814 verified).
Manifest-level 64-hex hash strings: 840; unverified by audit: 0.

## Errors

No errors.

## Case warnings

- `conv-gemm-vendor/conv_depthwise_3x3_c3_oc3_h11w28` `files.blocked_evidence_dir`: BLOCKED case carries a nested evidence directory: evidence
- `conv-gemm-vendor/conv_depthwise_3x3_c3_oc3_h11w28` `oracle.blocked_evidence_path`: oracle/expected file 'expected.bin' resolved under blocked-case evidence/: 'evidence/expected.bin'

## Cross-family findings

- No cross-family errors.
- WARNING `cross.schema_fields`: families use different schema/format field names: conv-fp16={'schema': None, 'format': 'rk3588-example-captures/1', 'format_doc': None}, conv-gemm-vendor={'schema': 'rk3588-example-capture-manifest-v1', 'format': None, 'format_doc': None}, conv-simple={'schema': None, 'format': 'build/rk3588-example-captures/CAPTURE_FORMAT.md', 'format_doc': None}, ew-fp16={'schema': 'rk3588-example-captures/v1', 'format': None, 'format_doc': '/home/fedora/rknpu-fpga/build/rk3588-example-captures/CAPTURE_FORMAT.md'}, ew-int={'schema': 'build/rk3588-example-captures/CAPTURE_FORMAT.md', 'format': None, 'format_doc': None}, fdiv-systematic={'schema': 'rk3588-example-captures/v1', 'format': None, 'format_doc': '/home/fedora/rknpu-fpga/build/rk3588-example-captures/CAPTURE_FORMAT.md'}, pooling={'schema': 'rk3588-example-capture-manifest-v1', 'format': None, 'format_doc': None}
- WARNING `cross.schema_label`: schema labels differ across families: schema=['build/rk3588-example-captures/CAPTURE_FORMAT.md', 'rk3588-example-capture-manifest-v1', 'rk3588-example-captures/v1'], format=['build/rk3588-example-captures/CAPTURE_FORMAT.md', 'rk3588-example-captures/1']
- WARNING `cross.rknpu_fpga_revision`: manifests bind different rknpu-fpga revisions: {'conv-gemm-vendor': 'f9b00d8f9a48ab4dea20cb30148890cd9f1443ee', 'ew-fp16': 'd54d33bc8f910059b6237d54d77e173737282869', 'fdiv-systematic': 'd54d33bc8f910059b6237d54d77e173737282869'}

- Job schema top-level keys consistent: True ([{'keys': ['buffers', 'case', 'description', 'patches', 'source_example', 'tasks', 'timeout_ns'], 'count': 126}])
- Patch kinds: {'value32': 365}; all value32: True
- EW encoding: `(target << 48) | ((value & 0xffffffff) << 16) | offset`; FDIV overlap cases compared: 17
  - FDIV signature is identical across ew-fp16 and fdiv-systematic; case-variable width/output-scale QWORDs are excluded from this comparison
  - FDIV uses EW_CFG 0x108303c0; docs/INTERFACE.md does not admit FDIV in the local RTL whitelist. This is a device-capture configuration, not an RTL-supported operation.
  - conv-fp16: [{'role': 'out', 'target': '0x1001', 'offset': '0x4020', 'kind': 'value32', 'count': 5}, {'role': 'a', 'target': '0x0201', 'offset': '0x1070', 'kind': 'value32', 'count': 5}]
  - conv-simple: [{'role': 'out', 'target': '0x1001', 'offset': '0x4020', 'kind': 'value32', 'count': 7}]
  - ew-fp16: [{'role': 'out', 'target': '0x1001', 'offset': '0x4020', 'kind': 'value32', 'count': 54}, {'role': 'a', 'target': '0x2001', 'offset': '0x5018', 'kind': 'value32', 'count': 54}, {'role': 'b', 'target': '0x2001', 'offset': '0x5038', 'kind': 'value32', 'count': 54}]
  - ew-int: [{'role': 'out', 'target': '0x1001', 'offset': '0x4020', 'kind': 'value32', 'count': 15}, {'role': 'a', 'target': '0x2001', 'offset': '0x5018', 'kind': 'value32', 'count': 15}, {'role': 'b', 'target': '0x2001', 'offset': '0x5038', 'kind': 'value32', 'count': 15}]
  - fdiv-systematic: [{'role': 'out', 'target': '0x1001', 'offset': '0x4020', 'kind': 'value32', 'count': 8}, {'role': 'a', 'target': '0x2001', 'offset': '0x5018', 'kind': 'value32', 'count': 8}, {'role': 'b', 'target': '0x2001', 'offset': '0x5038', 'kind': 'value32', 'count': 8}]
  - pooling: [{'role': 'out', 'target': '0x4001', 'offset': '0x6070', 'kind': 'value32', 'count': 21}]
  - op ADD: [{'ew_cfg': '0x108202c0', 'out_convert': '0x00010001', 'rdma_mode': '0x00017849', 'count': 9}]
  - op SUB: [{'ew_cfg': '0x108402c0', 'out_convert': '0x00010001', 'rdma_mode': '0x00017849', 'count': 9}]
  - op MUL: [{'ew_cfg': '0x108003c4', 'out_convert': '0x00010001', 'rdma_mode': '0x00017849', 'count': 9}]
  - op MAX: [{'ew_cfg': '0x108002c0', 'out_convert': '0x00010001', 'rdma_mode': '0x00017849', 'count': 9}]
  - op NEG: [{'ew_cfg': '0x108003c4', 'out_convert': '0x00010001', 'rdma_mode': '0x00017849', 'count': 9}]
  - op FDIV: [{'ew_cfg': '0x108303c0', 'out_convert': '0x00000001', 'rdma_mode': '0x00017841', 'count': 17}]

Schema/format labels:
  - conv-fp16: {'schema': None, 'format': 'rk3588-example-captures/1', 'format_doc': None}
  - conv-gemm-vendor: {'schema': 'rk3588-example-capture-manifest-v1', 'format': None, 'format_doc': None}
  - conv-simple: {'schema': None, 'format': 'build/rk3588-example-captures/CAPTURE_FORMAT.md', 'format_doc': None}
  - ew-fp16: {'schema': 'rk3588-example-captures/v1', 'format': None, 'format_doc': '/home/fedora/rknpu-fpga/build/rk3588-example-captures/CAPTURE_FORMAT.md'}
  - ew-int: {'schema': 'build/rk3588-example-captures/CAPTURE_FORMAT.md', 'format': None, 'format_doc': None}
  - fdiv-systematic: {'schema': 'rk3588-example-captures/v1', 'format': None, 'format_doc': '/home/fedora/rknpu-fpga/build/rk3588-example-captures/CAPTURE_FORMAT.md'}
  - pooling: {'schema': 'rk3588-example-capture-manifest-v1', 'format': None, 'format_doc': None}
Declared source revisions:
  - conv-fp16: {'rknpu_fpga': None, 'rk3588': '273d015e08af40c81d2cd9ab84198486b03a17f1'}
  - conv-gemm-vendor: {'rknpu_fpga': 'f9b00d8f9a48ab4dea20cb30148890cd9f1443ee', 'rk3588': '273d015e08af40c81d2cd9ab84198486b03a17f1'}
  - ew-fp16: {'rknpu_fpga': 'd54d33bc8f910059b6237d54d77e173737282869', 'rk3588': '273d015e08af40c81d2cd9ab84198486b03a17f1'}
  - ew-int: {'rk3588': '273d015e08af40c81d2cd9ab84198486b03a17f1'}
  - fdiv-systematic: {'rknpu_fpga': 'd54d33bc8f910059b6237d54d77e173737282869', 'rk3588': '273d015e08af40c81d2cd9ab84198486b03a17f1'}

## Format observations not applied to case status

- `format.rocket_job_boundary`: The current CAPTURE_FORMAT.md contains a 'Rocket job boundary' paragraph stating that multiple sequential RK submissions must not share one tasks array. This audit rerun was scoped to the fetch-parity padding rule; the multi-task cases below were not reclassified under that newer paragraph and need separate review.
  - `conv-fp16/conv_grouped_3x3_c4_h5_w5_oc8_g2`: 2 tasks
  - `conv-fp16/conv_splitoc_3x3_c16_h9_w9_oc16`: 2 tasks

## Accepted Rocket fetch parity padding

CAPTURE_FORMAT permits exactly one zero QWORD of fetch-only padding when the declared task extent is odd. The task descriptor keeps the declared count; the case must record `regcmd_padding_words=1` and `regcmd_file_words=declared+1`. These cases were accepted after verifying the odd task extent, the exact one-QWORD trailing zero, and both fields.

- `conv-simple/conv_simple_fp16_1x1_c4_h8_w8_oc16`: task words 51, file words 52, padding 1 x 0x0
- `conv-simple/conv_simple_fp16_3x3_c4_h8_w8_oc16`: task words 51, file words 52, padding 1 x 0x0
- `conv-simple/conv_simple_fp16_5x5_c4_h8_w8_oc16`: task words 51, file words 52, padding 1 x 0x0
- `conv-simple/conv_simple_fp16_1x1_c32_h8_w8_oc32`: task words 51, file words 52, padding 1 x 0x0
- `conv-simple/conv_simple_fp16_3x3_c16_h8_w8_oc32`: task words 51, file words 52, padding 1 x 0x0
- `conv-simple/simple_conv_int8_5x5_c8_h8_w8_oc32`: task words 69, file words 70, padding 1 x 0x0
- `conv-simple/simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64`: task words 69, file words 70, padding 1 x 0x0

## Blocked cases

### conv-fp16 (5)

- `conv_grouped_3x3_c4_h5_w5_oc8_g2`: MULTITASK_ROCKET_JOB_UNSUPPORTED: the RK3588 Rocket v6.18 board path executed only task 0 of a two-task job. The original run's task 0 output matched exactly while task 1's output BO remained all zero. The four derived one-task bundles (including both task-1 streams) matched their expected_out0/expected_out1 oracles exactly as single-task jobs. This two-task job is retained as BLOCKED evidence and must not be submitted; use the promoted one-task cases.
- `conv_splitoc_3x3_c16_h9_w9_oc16`: MULTITASK_ROCKET_JOB_UNSUPPORTED: the RK3588 Rocket v6.18 board path executed only task 0 of a two-task job. The original run's task 0 output matched exactly while task 1's output BO remained all zero. The four derived one-task bundles (including both task-1 streams) matched their expected_out0/expected_out1 oracles exactly as single-task jobs. This two-task job is retained as BLOCKED evidence and must not be submitted; use the promoted one-task cases.
- `conv_tiles_vendor_abi_blocked`: Vendor-only ABI: conv_tiles.py opens /dev/dri/card1 and submits through DRM_IOCTL_RKNPU_MEM_CREATE/MEM_MAP/MEM_SYNC/ACTION/SUBMIT with struct rknpu_submit and RKNPU_JOB_PC. It has no rocket_runtime or drm_rocket_task path. Re-hosting its register builder would require a new BO/submission adapter and fresh verification; producing a READY bundle would imply an unverified Rocket ABI. No registers were invented.
- `conv_3x3_pad_register_fp16_blocked`: No Rocket-capable FP16 builder emits and validates CNA_PAD_CON0. conv_new_clean.py comments the pad register out (lines 547-550) and computes valid-only geometry. conv_mesa_fp16.py does emit CNA_PAD_CON0, but its register path is the Mesa uint8 zero-point semantics (for example BS_OW_OP uses 0x80 - weights_zero_point and OUT_CVT/EW scales are quantized), so using it would change the numerical contract. A true pad-register FP16 case is therefore blocked pending source evidence and tests. The READY padded case uses an explicit zero frame instead.
- `conv_split_k_reduction_blocked`: Split-K reduction requires accumulation of partial products across tiles. Neither inspected Rocket path provides an accumulator or a second reduction pass: conv_0522._execute_conv_tiles clears the output BO before every tile and _tile_to_desc leaves all tile offsets at zero; conv_new_clean has no K-split for spatial conv. Only split-OC is encoded as READY. Adding split-K would require a new accumulation contract, not just more tasks.

### conv-gemm-vendor (3)

- `conv_depthwise_3x3_c3_oc3_h11w28`: MULTITASK_ROCKET_JOB_UNSUPPORTED: Rocket board execution completes only the first task of a two-task job; task 1 alone passes exactly. The source double submit is split into _task0 and _task1 one-task cases.
- `conv_byk_c160_h14w14_oc320_k3x3`: Vendor BY_K conv path uses explicit multi-core task distribution and a multi-task PC chain. Rocket has no core_mask/subcore_task fields and no bundle patch kind for the runtime regcmd address in PC_BASE_ADDRESS.
- `conv_h40_c160_h40w40_oc320_k3x3`: Vendor H40 spatial BY_Y conv path distributes six tasks over three cores and uses 17 PC-chain rows. Rocket cannot express the vendor core_mask/subcore_task split, and the PC_BASE_ADDRESS rows require runtime regcmd-address patching that the bundle schema does not have.

### conv-simple (5)

- `conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2`: No source path encodes a convolution stride.  The FP16 shape parser accepts an sN field (expt/conv_simple.py:228-238), but _conv_params ignores it (lines 297-311) and make_regs always writes CNA_CONV_CON3 = (1<<3)|1 = 0x9, i.e. stride 1 (expt/conv_simple.py:408).  kernel_6_18/simple_conv.py hardcodes the same value at line 557.  Emitting a stride-2 case would require a new CNA_CONV_CON3 encoding that these sources do not provide.
- `conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad`: No SAME-padding path exists in the named sources.  The FP16 make_regs() never writes CNA_PAD_CON0 or CNA_PAD_CON1 (expt/conv_simple.py:383-440) and _conv_params computes out_h/out_w = in_h/in_w - k + 1, i.e. valid-only (expt/conv_simple.py:301).  The INT8 builder writes CNA_PAD_CON0 = 0 (kernel_6_18/simple_conv.py:575), sets CNA_PAD_CON1 only to a zero-point fill value (line 584), and also computes valid-only output geometry (lines 81-82).  A SAME case would require new pad-register evidence and an output-with-halo contract that the sources do not provide.
- `conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack`: This C8 shape cannot be packed safely with the FP16 builder.  For in_c=8, _conv_align_c returns 16 (expt/conv_simple.py:283-286), but _conv_input_pack_c2 returns 8 (lines 289-294).  pack_input() then writes c1*c2 = 8 channels per pixel (lines 364-374), while make_regs sets CNA_DATA_SIZE1 = ((in_c-1)<<16) | data_in_channel_aligned = 0x00070010, i.e. a 16-channel aligned field (lines 393,410).  The source's own known-supported table has no C8 entry (lines 207-217), and its validated small-channel path is the <=4-channel NHWC case (C3/C4, where use_nhwc is true and the CVT fields carry the real channel count).  There is no source-supported padding contract that fills the missing 8 channels for C8 (the same gap affects 5 <= in_c <= 8).  The READY small cases therefore use C4, and the larger cases use C16/C32 where the packed channel count equals the aligned count.
- `conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2`: The grouped path cannot be expressed safely from these sources.  The FP16 make_regs() has no group-count register and its known-supported table has no grouped entry (expt/conv_simple.py:207-217,383-440).  The only grouped implementation is kernel_6_18/simple_conv.py::run_conv2d_grouped (lines 729-759), which slices input/weight/bias and calls run_conv2d_shape once per group; each call overwrites the shared BOs in write_buffers (lines 675-691) and does its own npu_submit (lines 871-872).  A single bundle would therefore need per-group BOs plus a multi-task PC chain, and the chain's PC_BASE_ADDRESS would have to be regcmd_addr + task_offset.  The bundle patch schema can only bind named buffer addresses, not the regcmd self-address, so the chain cannot be encoded without leaving an unpatched address.
- `simple_conv_int8_addition_c8_h8_w8_oc32`: The source's addition-input knobs are not a usable ABI.  use_shape() reads addition_input/add_tensor (kernel_6_18/simple_conv.py:83-84), but build_conv_regs() uses them only to change CNA_PAD_CON1 and the single-channel CVT scale (lines 523-531); add_tensor is never written to an address register.  write_buffers() allocates and packs only input/weight/bias/output (lines 675-691), and npu_submit() submits no addition tensor BO (lines 298-305).  A residual case would require a vendor-only addition-input stream and a second feature buffer, which these sources do not construct.

### ew-int (3)

- `int32_div_c8_w2`: The source proves DIV/FLOOR/CEIL use floating-point semantics and are not integer operations (OPERATIONS[...]['integer_supported'] = False). There is no trustworthy integer oracle; bundling them as integer EW would mislabel the result. FLOOR and CEIL share this blocker.
- `fp16_four_input_sum_c8_w1`: The only multi-input sum in either source is FP16, with FP32 BRDMA/NRDMA operands. This family is integer-only (ew-int); an FP16/FP32 mixed case needs its own oracle and belongs in an ew-fp16 family. It is not an INT8/INT16/INT32 case and was deliberately not materialized here.
- `fp16_bs_bn_relu_prelu_c8_w1`: ReLU-X and PReLU are emitted only in the FP16 BS/BN auxiliary stages. No integer ReLU path exists in either source, and ReLU6 and batchnorm are never emitted at all. Not an integer elementwise case.

### pooling (2)

- `fp32_max_k2s2_zero_write_c4_h2w2`: Source expt/pooling.py docstring lines 17-18 and the case flag expect_unsupported=True (lines 937-962) report that this PROC_PRECISION configuration submits successfully (submit_ret==0) but writes all zero, while the expected maximum is nonzero. That disproves the format on this PPU path; there is no valid output to compare. The exact probe stream is retained, but it must not be scored as a READY numerical case.
- `int32_max_k2s2_zero_write_c4_h2w2`: Source expt/pooling.py docstring lines 17-18 and the case flag expect_unsupported=True (lines 937-962) report that this PROC_PRECISION configuration submits successfully (submit_ret==0) but writes all zero, while the expected maximum is nonzero. That disproves the format on this PPU path; there is no valid output to compare. The exact probe stream is retained, but it must not be scored as a READY numerical case.

## What was checked

- `job.json` keys/types against CAPTURE_FORMAT.md; duplicate JSON keys rejected.
- Unique case names, buffer names, input names and output names.
- Buffer sizes exactly equal input file lengths; output files absent.
- `regcmd.bin` length multiple of 8; task ranges in bounds, in declared order, non-overlapping, and covering the command extent. Exactly one documented zero QWORD of Rocket QWORD-pair fetch padding is accepted only when the task extent is odd and both `regcmd_padding_words=1` and `regcmd_file_words=declared+1` are recorded; any other trailing data is rejected.
- Every patch index in range, inside a declared task range, kind supported, referenced buffer present; no duplicate patch index.
- Expected/oracle files never used as device inputs or outputs.
- Manifest and per-case hashes, declared sizes, aggregate hashes, source hashes and artifact hashes recomputed from actual bytes.
- `source_example`/`source_refs`/`source_lines` paths exist.
- Cross-family: job/buffer schema, patch convention, EW patch fields and EW_CFG/out_convert/RDMA encoding, FDIV overlap, task-range consistency, buffer-size declarations.
- No device was accessed; no output was fabricated; no bundle was repaired.

## Evidence limits

This audit verifies bundle structure and byte-level provenance only. It does not validate RK3588 silicon numerics, Rocket execution, FPGA RTL, or the correctness of any oracle formula. It also does not re-run the family generators or validators.

Snapshot hashes cover 764 files / 2803959 bytes. If the live tree changed after the snapshot, the audit remains a statement about the snapshot; see `snapshot.live_changes`.

