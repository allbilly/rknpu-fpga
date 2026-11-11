# EW aperture audit: do the frozen EW families fit the merged sparse aperture?

Status: **offline audit, PASS.** Resolves ambiguity #1 of
`docs/MERGED_INTEGRATION_NOTES.md` before Image-B stage S4. After the Lead's D1/D4
two-image split decision the EW endpoint (and therefore this aperture) lives in
**Image B** (`fpga/ypcb_image_b_top.sv`); the numbers and verdict below are
unchanged and are mapped to the Image-B decode literals there. Read-only over
the frozen bundles under `build/rk3588-example-captures/`; no device, no Vivado,
no hardware. Reproduce with:

```sh
python3 tools/merged/ew_aperture_audit.py            # human summary
python3 tools/merged/ew_aperture_audit.py --json     # machine summary
python3 -m unittest tests.merged.test_ew_aperture_audit -v
```

## 1. Question and method

The merged image keeps a **1 MiB decoded EW memory aperture** at
`0x1000_0000..0x100f_ffff` (the frozen production command BOs contain absolute
device addresses and are uploaded verbatim), but only maps **six physical banks
totalling 100 KiB** (measured from the nine production captures,
`docs/MERGED_IMAGE_PLAN.md` §3.5):

| Bank | Address | Bytes | Role |
|---|---|---:|---|
| A | `0x1000_1000` | 4096 | operand A (RDMA src_a) |
| B | `0x1002_0000` | 4096 | operand B (RDMA src_b) |
| D | `0x1004_0000` | 4096 | output (DPU dst) |
| scratch | `0x1006_0000` | 8192 | production backend scratch |
| command | `0x100e_0000` | 65536 | raw command BO |
| task | `0x100f_0000` | 16384 | production task BO |

The audit reads only frozen files: each family's `manifest.json`, and per case
`job.json` + `regcmd.bin`. For every case it:

1. decodes all command QWORDs with the reviewed `model.profile.decode`
   (target/offset/value grammar);
2. identifies every **address-bearing register field** by target:offset
   (`dpu_dst` `1001:4020`, `rdma_src_a` `2001:5018`, `rdma_src_b` `2001:5038`,
   terminal `pc_next_address` `0101:0010`, `pc_next_amount` `0101:0014`);
3. proves each data pointer is in the case's `job.json` **patch list** (the host
   fills it at staging time) and that the terminal PC chain is zero — i.e. no
   captured absolute heap address is ever executed unpatched;
4. computes the staging requirement: buffer set/sizes, command-BO bytes, number
   of distinct regions, and whether the chosen staging inside the six banks
   covers it.

Staging plan audited (same family grammar as the production layout): `a -> A`,
`b -> B`, `out -> D`, command BO -> command bank; the task/scratch banks stay
available for the production backend cases but are not needed by these bundles.

## 2. Per-family region map and measured bounds

All 54 `ew-fp16` cases are identical in shape (22 QWORD command BO, three
patch indices, three 4096-byte buffers), independent of op:

| Family | Cases | Buffer set / sizes | Command BO | Patched pointer fields | Regions per case | Union of staged bases |
|---|---:|---|---:|---:|---:|---|
| `ew-fp16` (ADD 9, SUB 9, MUL 9, MAX 9, NEG 9, FDIV 9) | 54 | a/b/out, 4096 B each | 176 B (22 QW), 0 padding | `out`,`a`,`b` (value32) | 4 (A, B, D, command) | `0x1000_1000`, `0x1002_0000`, `0x1004_0000`, `0x100e_0000` |
| `fdiv-systematic` (16x16 class-grid rows) | 8 | a/b/out, 64 B each | 176 B (22 QW), 0 padding | `out`,`a`,`b` (value32) | 4 (A, B, D, command) | same four bases |
| `simple_add` | — | no separate bundle family | — | — | — | — |
| production backend (baseline the six banks were measured from) | 9 | a/b/out 4096 B + scratch 8192 B + command 65536 B + task 16384 B | 22 QW body + task BO | backend layout | 6 | `0x10001000..0x100f4000` (972 KiB span) |

`simple_add`: there is **no separate `simple_add` capture family** in the frozen
capture tree. The `ew-fp16` manifest cites
`/home/fedora/rk3588/examples/simple_add.py` (lines 196-203, 215-236: EW_CFG and
8-lane width) as the cross-check for every case (54/54), so `simple_add.py`'s
supported command grammar and buffer layout are covered by the audited
`ew-fp16` family; nothing additional has to be staged. If a future capture adds
a distinct simple_add bundle with a different buffer set, re-run this audit.

Other measured maxima:

* maximum command-BO size: **176 B** (22 QWORDs; no padding words in any audited
  case) — 0.27 % of the 64 KiB command bank;
* maximum buffers per case: **3** (no case has a fourth buffer, a second output,
  or an in-place alias that would need another bank);
* maximum distinct regions per case: **4** of the 6 banks;
* maximum buffer size per family: 4096 B (ew-fp16), 64 B (fdiv-systematic) —
  i.e. ≤ one 4 KiB bank each;
* union of staged bases: four banks; the full physical footprint of a bundle
  case is **12 KiB + 176 B**, versus 100 KiB for the production baseline;
* every audited case's terminal PC QWORDs are **zero** (single task, no linked
  PC chain) and `pc_next_amount == 0`.

## 3. Verdict

**PASS.** The one-MiB-decode / six-bank-sparse-aperture layout is safe for the
full audited set: the 54 `ew-fp16` cases (including the FDIV cases and the
`simple_add`-cited grammar) and the 8 `fdiv-systematic` cases all stage into
banks A/B/D + the command bank, with no new region, no size overflow, and no
unpatched absolute address. The two extra banks (scratch, task) remain mapped
for the nine production backend cases, which are the only ones that need them.

Provenance: the audit reads only frozen capture files, and the bundle README
states these are **device-free prepared** bundles (`expected.bin` is the donor
CPU oracle, never a device output). The verdict is therefore about *merged-image
staging feasibility*, not about device behaviour; the live RK3588 differential
for these families is tracked separately (P2).

## 4. Requirements on the S4 EW integration (host side)

For the bundle families the merged/EW runner must (no RTL change):

1. allocate `a`/`b`/`out` inside banks A/B (`0x1000_1000`, `0x1002_0000`) and D
   (`0x1004_0000`, the DPU destination), sized to the job's buffers;
2. copy the bundle's `regcmd.bin` into the command bank starting at
   `0x100e_0000`, patch QWORDs 14/15/16 with the staged `out`/`a`/`b` addresses
   (`value32` patches exactly as the frozen `job.json` declares), keep the tail
   QWORDs zero;
3. submit the command-BO address and the declared 22-word amount through the EW
   job control, then compare the **complete** staged output BO before ACK;
4. keep the production path unchanged: the nine production captures are uploaded
   verbatim at their captured addresses (no patching), with scratch/task banks
   used. The two paths share the same aperture and are distinguished by the
   command BO contents, not by map changes.

## 5. Fallbacks and residual risks

* **Spare banks**: the 8 KiB scratch bank is unused by the audited bundle
  families; it can absorb one extra 4 KiB operand/output region (or two 4 KiB
  halves) without touching the decode if a future bundle adds a buffer.
* **256-tile window**: BRAM budget allows restoring the standalone EW image's
  full 1 MiB physical window if a capture ever uses an address outside the six
  banks; that costs ~231 more RAMB36 tiles but no decode change.
* **EW as its own image**: the already-emitted standalone EW image remains the
  fallback if the merged EW integration cannot be equivalence-proven at S4.
* **Residual risk**: the audit saw only single-task, three-buffer, zero-PC-chain
  bundles. A future bundle with a linked PC chain (`pc_next_address != 0`), a
  second output, or an address outside the measured layout is *not* covered and
  must be re-audited (the tool fails such cases with an explicit problem, it does
  not silently pass them).
* **Out-of-scope families**: `ew-int` (INT8/16/32) was not part of this audit.

## 6. Reproducibility

* Tool: `tools/merged/ew_aperture_audit.py` (`--json` emits the full per-case
  record: decoded address fields, patch list, buffer list, staged regions).
* Test: `tests/merged/test_ew_aperture_audit.py` pins the verdict (PASS), the
  per-family bounds above and the six-bank capacity (100 KiB).
* Inputs are frozen capture files; the tool writes nothing and never invokes
  Vivado or hardware. Any change of the frozen bundles changes the audit output
  and must re-run both the tool and the test.
