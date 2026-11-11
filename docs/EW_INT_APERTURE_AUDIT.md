# ew-int aperture audit for Image B page-form integration

Status: **offline audit, PASS.** Produced by task-23 (ewint) for the Image-B
S4 integration of the integer elementwise family; analogous to
`docs/EW_APERTURE_AUDIT.md` for the FP16 EW endpoint. Read-only over the frozen
bundles under `build/rk3588-example-captures/ew-int/` and over the reviewed
integer RTL; no device, no Vivado, no hardware, no build.

Reproduce:

```sh
python3 tools/merged/ew_int_aperture_audit.py            # human summary
python3 tools/merged/ew_int_aperture_audit.py --json     # machine summary
python3 -m unittest tests.merged.test_ew_int_aperture_audit -v
```

## 1. Question and method

The Lead decision form is **page-form** in Image B: the ew-int endpoint is an
AXI4-Lite control page (`RKEI` = `0x524b4549` at `0x0002_4000`) plus a memory
aperture for the captured operand/output buffers. The Image-B scaffold decodes a
**1 MiB ew-int aperture placeholder** at `0x1100_0000..0x110f_ffff`; the
physical sparse-bank map was left to this audit.

For every READY case the audit reads only frozen files (`manifest.json`,
`job.json`, `regcmd.bin`, `a.bin`, `b.bin`, `expected.bin`,
`expected.mask.bin`) and:

1. decodes every command QWORD with the reviewed raw-command grammar
   (`model.profile.decode`), and proves every decoded register key is part of
   the reviewed integer register map (`model.int_profile.KNOWN_KEYS` plus the
   terminal `PC.OPERATION_ENABLE` word);
2. identifies the **address-bearing** register fields and proves each data
   pointer is host-patched (`job.json` `patches`, `value32` only) to the buffer
   the staging plan expects, while the terminal PC chain is exactly zero and is
   never patched;
3. proves the unpatched command words still contain the documented distinct
   placeholders (`out=0x2000_0000`, `a=0x1000_0000`, `b=0x1001_0000`), so a
   missed patch is visible rather than silently executing a stale address;
4. decodes the stream with the integer decoder (after patching the three
   pointers to the page-form aperture bases) to obtain the mode, element count
   and byte geometry, and verifies the captured command shape
   (18 / 31 / 44 QWORDs);
5. computes the staged buffers (three 4096-byte BOs plus the raw command BO),
   their banks, the union span and any overlap, and checks that every case fits
   the four-bank physical plan;
6. states the BLOCKED cases explicitly: they have no oracle and no staged
   expectation, so they require no aperture.

## 2. Address-bearing fields (the layout-mode question)

Across all three captured stream shapes the **only** registers that carry a
device memory address are:

| register | QWORD role | capture handling |
|---|---|---|
| `DPU.DST_BASE_ADDR` `0x1001:4020` | output BO pointer | patched to bank D (`out`) |
| `RDMA.SRC_BASE_ADDR` `0x2001:5018` | operand-A BO pointer | patched to bank A (`a`) |
| `RDMA.EW_BASE_ADDR` `0x2001:5038` | operand-B BO pointer | patched to bank B (`b`) |
| `PC_REG.BASE_ADDRESS` `0x0101:0010` | terminal PC chain | must be `0`, never patched |
| `PC_REG.REGISTER_AMOUNTS` `0x0101:0014` | terminal PC amount (a count, not a pointer) | must be `0`, never patched |

The layout-mode surface registers that the integration flagged as a possible
hidden address source — `DPU.DST_SURF_STRIDE` `0x1001:4024`, `SURFACE_ADD`
`0x1001:40c0`, `RDMA.EW_SURF_STRIDE` `0x2001:5040` — are **geometry only**:
each captured layout stream carries `0x10` (`width << 4`, width = 1), and the
decoder treats them as stride validation, never as a base pointer. No layout
case carries an unpatched operand/surface base address. Regroup-only registers
(`BS_OW_CFG=0x126`, `OUT_CVT_*`) are likewise configuration values.

Consequence: a missed host patch cannot execute an arbitrary captured heap
address for the data buffers; it is either caught as the visible placeholder
(decoder address range/alignment checks against the aperture) or explicitly
patched. This is the same no-unpatched-address property `docs/EW_APERTURE_AUDIT.md`
proved for the FP16 EW family.

## 3. Per-case staged footprint

All 15 READY cases use the same buffer set: `a`, `b`, `out`, 4096 B each
(`direction in/in/out`). The command BO is 18 QWORDs (144 B), 31 QWORDs (248 B)
or 44 QWORDs (352 B); there is no padding-word field in any bundle and no case
needs a task BO or a second output.

| shape | dtype/op coverage | command BO | patch QWORD indices (a,b,out order per job.json) | regions |
|---|---|---:|---|---:|
| `simple` (18 QW) | INT8/INT16 ADD/MINUS/MUL/MAX/MIN; INT32 ADD/MUL/MAX | 144 B | `{10, 11, 12}` | 4 |
| `layout` (44 QW) | INT8/INT16/INT32 ADD; INT16 MINUS | 352 B | `{23, 24, 25}` | 4 |
| `regroup` (31 QW) | INT16→INT32 ADD | 248 B | `{35, 36, 37}` | 4 |

Measured maxima:

* maximum command BO: **352 B** (0.1 % of a 4 KiB command bank);
* maximum buffers per case: **3**, all 4096 B;
* maximum distinct regions per case: **4** (A, B, D, command bank);
* union span of the required bytes: `0x1100_1000..0x1100_4160` = **12,640 B**
  (12.34 KiB) — versus ≈12.6 KiB predicted from the frozen job files;
* buffer footprint equals one 4 KiB bank exactly for `a`/`b`/`out`, so the bank
  bases must stay 4 KiB-aligned and a buffer may not be split across banks.

## 4. Bank map and holes (the pinned Image-B literals)

The 1 MiB decoded aperture is kept (verbatim staged addresses / fallback
safety), but only four 4 KiB banks are physical:

| bank | absolute range | bytes | role | physical |
|---|---|---:|---|---|
| A | `0x1100_1000..0x1100_1fff` | 4096 | operand a (`RDMA.SRC_BASE_ADDR`) | 1 BRAM36 (2048×16b) |
| B | `0x1100_2000..0x1100_2fff` | 4096 | operand b (`RDMA.EW_BASE_ADDR`) | 1 BRAM36 |
| D | `0x1100_3000..0x1100_3fff` | 4096 | output (`DPU.DST_BASE_ADDR`) | 1 BRAM36 |
| C | `0x1100_4000..0x1100_4fff` | 4096 | raw command BO (page `START_ADDRESS`) | 1 BRAM36 |

Physical total: **16 KiB / 4 BRAM36 tiles**, versus 256 tiles for the dense
1 MiB decode — **252 tiles saved**. Everything else in the decoded aperture is
an explicit hole: `0x1100_0000..0x1100_0fff` and
`0x1100_5000..0x110f_ffff` return SLVERR to the host and a memory-response error
to the engine; they never alias a bank. The top-level decode still maps only
`0x1100_xxxx`/`0x110f_xxxx` to this endpoint; any other address remains a
top-level explicit SLVERR.

Command-BO placement decision: the raw command BO lives in **bank C**, so the
page needs exactly **one** 16-bit serialized memory master (capture phase and
engine phase both target the aperture). This avoids adding a page-master
arbiter to the shared 64 KiB host window and keeps ew-int jobs from contending
with the pooling/EW pages. `START_ADDRESS = 0x1100_4000`, `START_AMOUNT ∈
{18, 31, 44}`; the 352 B maximum fits one bank with no fragmentation.

## 5. Verdict

**PASS.** The four-bank 16 KiB sparse aperture (A/B/D/command) covers all 15
READY integer elementwise cases: every case has exactly three host-patched data
pointers plus the zero terminal PC tail, no hidden address source in the
layout/regroup configuration registers, at most four 4 KiB regions, and a
12.34 KiB union span inside the 16 KiB physical map. The 1 MiB decode is safe
to keep because the sparse map is an explicit hole/SLVERR decode, not an
aliasing scheme.

The three BLOCKED cases (`int32_div_c8_w2`,
`fp16_four_input_sum_c8_w1`, `fp16_bs_bn_relu_prelu_c8_w1`) have no oracle, are
not implemented by the integer endpoint, and therefore have no aperture
requirement. They stay excluded; nothing was materialised or invented for them.

This verdict concerns *Image-B staging feasibility and address containment*,
not device behaviour. Numerical correctness of the integer arithmetic is
covered by the source-hash-bound RTL replay receipts under `build/ew-int/`
(15/15 READY, both simulators) and the page-level contract replay.

## 6. Requirements on the S4 page integration

1. `rk_ew_int_page_axi` (page at `0x0002_4000`, `DEVICE_ID=0x524b4549`,
   `ABI_VERSION=0x00010000`): frozen `rk_job_control` register ABI
   (`STATUS/COMMAND/START_ADDRESS/START_AMOUNT/JOB_TAG/RESULT_*`), single
   terminal task, `RESULT_TASKS=1` on success, raw QWORD capture from
   `START_ADDRESS` and byte-order-preserving issue into the integer decoder
   (no field rewrite, no CPU fix-ups), fail-closed page errors.
**Frozen STATUS bit layout (authoritative; LSB-anchored in the frozen
`rtl/rk_job_control.sv`):** `[0] can_submit`, `[1] active`, `[2] result_valid`,
`[3] result_error`, `[4] memory_ready`, `[5] core_error`, `[6] core_busy`,
`[10:8] fields_valid`, remaining bits zero. The page and its replay bench poll
exactly these positions; do not use the `[16] core_busy / [20:18] fields_valid`
sketch that appeared in early coordination text — the frozen RTL concatenation
is `{21'b0, fields_valid, 1'b0, core_busy, core_error, memory_ready,
result_error, result_valid, active, can_submit}`.

2. `rk_ew_int_aperture` (at `0x1100_0000`): the four `rk_bram` banks above, one
   AXI4-Lite 32-bit host staging slave (all four byte strobes required, partial
   or protected access SLVERR), one 16-bit engine master port with absolute
   addressing, `memory_ready` (host staging idle) wired to the page's
   `rk_job_control`, and host access refused with SLVERR while the page is busy.
   Bank contents must be byte-identical to the staged BO files.
3. Host staging: write `a`/`b`/`out`/`regcmd` into banks A/B/D/C, patch the three
   data pointers to `0x1100_1000`/`0x1100_2000`/`0x1100_3000` (`value32` on the
   QWORD indices the bundle's `job.json` declares), write
   `START_ADDRESS=0x1100_4000`, `START_AMOUNT=word count`, `JOB_TAG`,
   `COMMAND=1`; poll `STATUS.result_valid`; read `RESULT_CODE`; read the `out`
   bank and compare the complete 4096-byte buffer under `expected.mask.bin`
   before acknowledging (`COMMAND=2` on success only).
4. Error behaviour is sticky until fabric reset (frozen `rk_job_control` has no
   error-ack); engine/decoder state is reset per job, so clean jobs can run
   back-to-back without a fabric reset. Aperture holes are memory-bus errors
   (code 5), and wrong command shapes/amounts are invalid page commands
   (code 6) — never silent fallbacks.

## 7. Fallbacks and residual risks

* **Fallback:** the standalone mailbox-direct ew-int image
  (`fpga/ewint/ypcb_jtag_ew_int_top.sv`, prepared package
  `build/ew-int-image-prep/`) remains the fallback if Image B integration is
  delayed; it needs no aperture audit (1 MiB dense BRAM window).
* If a future capture family adds a second output, a task BO, or an in-place
  alias, the four-bank/12.34 KiB bound no longer holds; re-run this audit (the
  tool fails closed on extra buffers, unknown patches and unknown registers).
* The audit cannot prove device behaviour; it proves staging containment only.
