# Shared full512 and EW DDR candidate

`rtl/ddr/rk_jtag_dual_ddr_async.sv` joins the existing raw EW and full512 CMAC
clock bridges to one DDR owner. It is a staged source candidate. The passing
[first physical CH1 result](DDR_FPGA_TEST.md) belongs to the EW-only image;
it does not qualify this new numerical composition, CDC, routing or hardware.

The new source retains the 512-product C32/K16 arithmetic selected by the
passing BRAM TinyStories image, including its generated CACC wrapper and
pipelined DSP-prefix implementation. It passes original command addresses,
amounts and halfword memory traffic. There is no tensor-level execution port,
CPU arithmetic fallback or runtime layout repair. Original command-field
validation, donor numerical policy and explicit failures remain in the engines.

## Control and memory ownership

| Namespace | Identity | Descriptor convention |
|---|---|---|
| EW CSR `0x000..0x0ff` | RKAD `0x524b4144`, ABI 1.0 | Original linked raw EW task stream |
| CMAC CSR `0x100..0x1ff` | RKCD `0x524b4344`, ABI 1.0 | Original terminal CMAC amount 45, all 49 QWORDs |

`rk_dual_job_control` wraps two unchanged register controllers. They retain
separate staged fields and result registers; one global owner serializes
execution and remains selected through successful output readback and ACK.
The other namespace cannot stage or submit a competing job while that owner
is held. A wrong-bank ACK fails without releasing ownership. Unsupported
namespaces reach the original decoder and return DECERR; invalid protection,
strobe and read-only writes retain their explicit access errors.

The AXI-Lite routing uses `rk_jtag_backend`'s private serial source contract:
one register transaction at a time, with its address held through the
response. Split address/data handshakes and response backpressure are tested.
The containing platform uses the same UI clock for this register path and
the DDR/ECC owner. Each numerical engine has its own descriptor and opposite-
direction halfword-memory crossing to SYS50.

`rk_dual_async_dispatch` selects the numerical child until its terminal result
is consumed. The containing endpoint then retains global job ownership through
the exact-address write fence, fresh ECC monitor check, result publication,
complete BO readback and ACK. Numerical completion alone cannot publish a
successful DDR result. A fault preserves the selected owner and outstanding
memory transfers; coordinated whole-domain reset remains the recovery boundary.

CMAC child rearming uses a healthy-platform permit that remains asserted
during a healthy owned job. General memory-ready falls during ownership and
therefore cannot supply that permit. The fabric immediately blocks new jobs,
memory admission and successful completion on its own fault. Its cause is
latched on the next UI edge, revoking the registered cross-clock child permit.
This keeps the fabric's combinational fault out of its own READY/admission
feedback path. Child rearming does not establish global DDR recovery.

The new endpoint keeps the successful-result fault overlay at both status
addresses `0x008`/`0x108` and error-code addresses `0x024`/`0x124`. A later
platform fault invalidates a new status read and prevents ACK even if a
successful numerical result had already been observed.

The existing `DdrJtagTransport` admits RKAD only. The separate
`DualDdrRawTransport` checks RKAD and RKCD plus both ABI versions before any
write. It switches profiles only when both banks are healthy, idle and
unstaged, and retains DDR result ownership through ACK. Descriptor writes
are refused locally while a job is owned. Its ten wire-mock controls pass;
they do not qualify a physical link or image. A caller waits for initialized
DDR before using the unchanged raw TinyStories dense device. No identity
bypass or CPU fallback is supplied.

TinyStories workers select their memory transport explicitly with
`--memory-profile bram` or `--memory-profile ddr`; BRAM remains the default.
DDR mode is accepted only with `--backend jtag` and constructs
`DualDdrRawTransport` directly. It requires an already initialized, healthy
DDR image and caller-owned image/cable lease; it does not detect the image,
retry with BRAM, or qualify physical DDR. Bridge ports default to 3741 for
BRAM and 3721 for DDR, with `--port` available for an explicit override.

## Current verification and build boundary

Run the ordinary, portable controls with:

```sh
make generated-check
make ddr-host-controls
make ddr-dual-controls
```

The dual-control runner executes the real register-bank wrapper in Icarus
and Verilator, and the dispatcher in Icarus with explicitly nonnumeric child
models. Its source-bound report records exact commands, versions, markers and
input hashes. These controls cover ownership, readiness, readback/ACK ordering,
fault retention, reset and invalid access. They do not execute FP16 arithmetic
or DDR. The duplicate-offer regression passes the corrected dispatcher and
fails the preserved old source when READY is low.

The default channel-profile controls use a checked-in, source-derived port
and binding contract and reproduce the exact frozen CH1 interconnect hash.
The full 122-HDL package audit remains separately available:

```sh
make ddr-channel-frozen-controls
```

That command requires the actual frozen CH1 package and all of its inputs.
The earlier private production regression failed because the old default
test required an ignored build directory. The failed receipt is preserved;
the portable controls now also pass in a source-only copy with no `build/`.

The [combined source preparation](../build/full512-ddr-preparation/combined-source-v6/preparation.json)
freezes 151 real HDL files, both original MIG controllers and unchanged XDC
bytes, with logical UI0 bound to physical CH1. The donor CACC requires the
same `DESIGNWARE_NOEXIST` define as the passing full512 build. Icarus
elaboration passes. Strict Verilator lint remains failed on 55 inherited
warnings; a separate [source/diagnostic review](../build/full512-ddr-preparation/combined-source-v6/frontend-root-review-v1.json)
confirms their unchanged parent sources and zero combinational-loop warnings.
It permits early resource synthesis only. No warning severity was changed.

The complete numerical/fault composition, new CMAC CDC constraints and mapped
audits, resource/timing fit and fresh physical TinyStories/DDR tests retain
separate gates. The [first joined controller-model executions](DDR_FULL512_MODEL.md)
have their own independent CMAC/EW reviews; their reset epochs are separate.
The original nine-mode CMAC
component suite remains bound to its direct-bridge source. Its new
dispatcher composition now passes all nine modes in both simulators with
[independent source/log/counter review](../build/full512-ddr-preparation/dual-dispatch-numerical-v1/both-simulators-root-review-v1.json)
and a [portable logical archive](../verification/runs/2026-10-27-full512-dispatch-logical/index.json).
The actual elaborated model retains sixteen C32 kernels and all 512 product
lanes. Repeat mode checks 98 original command words, 13,056 operand reads,
128 writes, 13,576 responses and two safe rearms. All fault/reset modes retain
their original expectations and seed. That bench uses halfword memory; its
results do not qualify the DDR controller or physical execution. Separate
[trained controller-model reuse](DDR_FULL512_MODEL.md#trained-tile-reuse-in-one-epoch)
now passes CMAC/EW/CMAC in one reset epoch with the original RTL. The later
shared-data area candidate now has its own passing cell/dispatcher suites and
trained controller replay; see [its source-bound results and remaining gates](DDR_AREA_CANDIDATE.md).

The read-only `tools/ddr/audit_trained_tile.py` prepares the independent wire
check for the explicit DDR trained-tile worker. It requires an externally
reviewed vector-report digest, both RKAD/RKCD identities, all four original
raw descriptors, complete expected BO bytes before each ACK and restored
memory readiness after ACK. Eleven portable controls exercise synthetic
wire commands and fail-closed artifact admission; they do not qualify a
physical trace. The audit deliberately requires separate exact-image,
target, routed-timing and DDR admission receipts. For a completed future
trial, use a fresh output path:

```sh
python3 tools/ddr/audit_trained_tile.py --worker "$DDR_TILE_WORKER" \
  --vectors "$TRAINED_VECTORS" --vectors-sha256 "$REVIEWED_VECTOR_SHA256" \
  --out build/ddr-trained-tile-wire-audit/result.json
```

The separate [full512 image renderer](../tools/ddr/full512_image_template.py)
and [emission template](../fpga/ddr/emit_full512_ch1.tcl.in) now prepare the
post-route emission gate. They bind the routed checkpoint, all six helpers,
renderer/template hashes and the exact 242-port property snapshot. The gate
rechecks both controllers, 512 products/516 total DSPs, USER2, timing and the
reviewed DRC inventory; only the source-tag metadata changes before writing
an image. Fourteen portable controls pass, including helper-call compatibility,
pre-open hash failures and rejection of a failing later period/pulse row.
They are included in default DDR host controls. The separate
[reviewed image emission](../build/full512-ddr-preparation/full512-image-prep-v12/root-emission-review.json)
passes 30 offline controls and binds the strict checkpoint requalification,
completed logical qualifications and a 163-file hardware fingerprint. It
binds the repaired route, independent timing review and the fresh
242-port/eight-property snapshot. All 1,936 values match the physical pin
specification. The native query returned zero; its outer parser failure on
Vivado's checkpoint container name remains preserved beside corrected offline
postprocessing and independent review. The first image-emission attempt
timed out at its 1,200-second workflow limit during bitmap generation and
produced no bitfile. That receipt is preserved. Fresh emission completed in
1,256.917 seconds within its prospective 2,400-second workflow budget, with
identical design/checks. The `d627b715` image passes independent bitfile review
and the [physical trained-tile trial](DDR_FULL512_FPGA_TEST.md).
The separate [bitfile-audit preparation](../build/full512-ddr-preparation/full512-bitfile-audit-v2/offline-controls.json)
passes 11 packet/DRC controls. It rejects old source tags, wrong IDCODE,
IPROG, malformed NOP/READ count tricks and Type-2 writes without the reviewed
FDRI context. The historical image is only a parser fixture; no new bitstream
is qualified by these controls alone, and software CRC validation remains unchecked.
The separate actual image/physical receipts qualify the finite trained workload
and the [complete32-position DDR model](DDR_FULL512_FPGA_TEST.md): all 1,152
learned FPGA projections and 16,384 logits pass independent actual-wire review.
Full memory capacity, injected ECC/recovery, PCIe and RK equivalence remain open.

The model wire auditor now has an explicit `--memory-profile ddr` mode.
It requires the separate full512 CH1 DDR image review, DDR-tagged producer
and worker receipts, and the RKAD/RKCD identities on the actual trace. Pending
results may have general memory-ready low: complete BO reads require the
validated owned result, and ACK must restore healthy initialized memory.
Seventeen synthetic controls pass, including rejected BRAM identities, early
readback/ACK, missing initialization, unknown commands and relabelled image
receipts. DDR model qualification now requires the ordered phases
`one-complete-forward-position`, `repeated-complete-forward-position`, then
`greedy32`. Both BOS trials remain one-position controls; failed, omitted,
duplicated or reordered controls cannot qualify the 32-position result.
BRAM remains the default audit mode. The completed DDR three-phase session
now [passes independent root acceptance](../build/fpga-bringup/full512-ddr-model-prep-v5/root-full32-review.json),
including 2,984,893 actual scans and 30,408,704 complete output-BO bytes before ACK.
