# Joined raw-frame DDR endpoint

`rtl/ddr/rk_jtag_ew_ddr.sv` joins the unchanged raw job controller, EW DMA and
memory adapter with the ECC monitor, reset coordinator, memory owner and
write-fence components. The incoming frame interface shares `c0_ui_clk` with
memory AXI and ECC control. The module is a logical endpoint; it supplies no
BSCANE2/TCK crossing, PCIe shell, physical constraints or hardware result.

The final backend QWORDs and complete physical BO bytes remain the compute
boundary. The software reference supplies test expectations only. This path
adds no CPU arithmetic, layout repair or fallback execution.

## Frame and control identity

The endpoint reuses `rk_jtag_backend` with its existing USER2 frame layout:
register read/write and 64-byte memory read/write operations. The backend's
16-bit memory requests are handled by the DDR owner. Packet framing, sequence
numbers, alignment and error responses remain explicit.

Its transport identity is **RKED**, `0x524b4544`, ABI `0x00010000`. This is
distinct from the BRAM RKEW candidate, so an existing client cannot silently
accept a different initialization/recovery contract. The register offsets in
[HOST_CONTROL.md](HOST_CONTROL.md) remain: descriptor address/amount/tag,
SUBMIT, result tag/task count/code, IRQ and successful-result ACK.

The DDR status/error reads overlay platform failure at the AR handshake,
including a later fault invalidating a pending logical success. An already
held AXI-Lite read response remains stable. During monitor-cause classification,
fault status can precede a nonzero code; new work, done and ACK are blocked.
The known first cause is retained: raw decoder errors keep their existing
codes; transport timeouts map to E8; other platform memory faults map to E5.

## Hardware initialization and ownership

The default window is the full channel-0 range, BASE 0 and BYTES 2 GiB. Both
address extent and alignment are checked before use. A parameterized smaller
test window is separate from the default target. It does not authorize accesses
outside the range actually initialized by that instance.

After the synchronized reset barrier, calibration and ECC configuration checks,
the owner writes zero to every 64-byte beat with all 64 strobes enabled. Full
writes establish data/ECC without first reading uninitialized memory through
masked RMW. Initialization completes only after the final actual write response,
an exact-last-address readback fence and a fresh ECC snapshot. It does not
follow from calibration or a caller-provided readiness flag.

Host access starts after initialization. Each host write receives a successful
response only after its own write/fence/ECC sequence. Host packets exclude job
admission for their entire lifetime, including gaps between backend halfwords.
Job admission claims the memory owner before DMA launches. A queued descriptor
that encounters a fault is accepted into the error path without launching DMA;
its completed-task count is zero rather than a prior job's stale count.

The job epoch records real AW, W, B, AR and R handshakes and the actual final
acknowledged AW address. On raw DMA completion, the owner seals producer
traffic, checks pending history and runs the fence. Only qualified retirement
can publish the controller's successful completion. Pending result ownership
permits readback while rejecting writes. The actual IRQ falling edge after a
successful ACK releases the epoch for the next job.

The held-reset/release barrier covers the owned SYS/UI0/UI1 components.
Independent TCK, PCIe or other masters require their own audited crossing,
reset and ownership integration. No original-BD/global-drain coverage is inferred.

## Faults and reset

Faults stop new admission and keep accepted memory requests owned. Existing
AW/W/AR payloads remain stable until handshake; late B/R and adapter-local
responses drain even when a faulted DMA no longer accepts responses. Errors
can leave partial writes; no rollback is supplied. Calibration returning or a
later healthy response does not clear quarantine.

The ECC monitor's live health indication can fall before its registered cause
appears. The owner reserves that first-cause slot and suppresses done/ACK while
classification is pending. It must not convert an earlier timeout into a later
generic relay error. Same-edge fault wins over successful completion.

An explicit coordinated reset invalidates all prior BO contents and reruns
hardware initialization. Callers must upload the original complete BOs again.
Reset sequencing, an initialized window and a source-qualified fence are
separate conditions; this source design supplies no board or RK silicon proof.

## Current verification boundary

The [full-span fabric run](../build/luna-ddr-full-span-20261026T1430Z/report.json)
passes with Verilator 5.048: 33,554,432 full-strobe writes cover the default
2,147,483,648-byte aperture, with final address `0x7fffffc0`, 32 progress rows
and the required initialization fence. The simulation completes in 132.695
seconds under its 300-second limit; all eight runner controls pass. The
current source manifest is
`9456d4770659a43438d4e3bafde5c89c0b5b1eeb48a1be4b6f087e4001edc5b0`.
This test uses an AXI stream sink. It validates the generated write sequence
and ownership protocol, without storing or checking 2 GiB of DDR contents,
executing the generated MIG/PHY, or establishing physical memory behavior.

Earlier structured-bench verification used Verilator 5.048 and a one-job build;
the [build report](../build/luna-ddr-structured-20261026/build-report.json)
binds bench hash
`cff6dfac731ca1ce8d4015d1cfdd90c9348526218ecea50cf069a97f6e836f3b` and all 82
inputs. All four cases reuse
that same binary. The [host-timeout case](../build/luna-ddr-structured-20261026/negative-9/report.json)
passes with one `negative=9` marker and performs no numerical job. The
[uncorrectable-ECC case](../build/luna-ddr-structured-20261026/negative-2/report.json)
passes with one `negative=2` marker and retains the bench's fault, quarantine
and no-success assertions. The [positive `capture_add_8` case](../build/luna-ddr-structured-20261026/positive/report.json)
passes and its [1,472-row readback](../build/luna-ddr-structured-20261026/positive/observed.txt)
matches the complete 203,136-byte ASCII dump exactly. Those rows represent
94,208 physical BO bytes; dump size is not a physical-memory byte count.

The [reset-recovery case's original report](../build/luna-ddr-structured-20261026/reset-recovery-retry/report.json)
retains its `PASS_OR_READBACK_FAILED` producer status. A separate
[corrected read-only review](../build/luna-ddr-structured-20261026/reset-recovery-retry/corrected-readonly-review.json)
binds that report and its raw log, verifies exactly one marker with
`jobs=2 negative=2 recovered=1 lines=1472 uploaded_nonzero=72 rawtasks=1 phy_user_returns=51910`,
and checks the same 203,136-byte dump against the expected image. The
producer's marker predicate added an extra `=` to its field checks; its report
was preserved unchanged. These runs use the logical MIG controller/PHY model.
They establish no FPGA-board DDR behavior, physical DDR result or RK silicon
equivalence.

## Repeatable current-source runner

`tools/ddr/run_endpoint.py` now freezes the actual local sources, archived
logical AXI/UI/MC/ECC sources, explicit source variants, complete raw BO
vectors and diagnostic policy before compiling once with Verilator. It never
starts Vivado or accesses hardware. The source preparation retains the
archive's separate identity and its simulation-only generate-attribute patch;
it does not qualify that electrical profile for hardware.

The [fresh native build](../build/ddr-endpoint-current/native-v1/report.json)
passes with Verilator 5.048, 173 frozen input hashes and the exact 574 admitted
diagnostics. Its current bench also checks both UI reset-release branches and
explicit model array/queue bounds. The earlier tested bench/model/controller
sources were preserved and checked against the original ledger in a
[separate source snapshot](../build/ddr-structured-original-source-snapshot/report.json).
Earlier logs do not qualify the modified sources.

The complete matrix contains nine captured ADD/SUB/MUL workloads, repeated
SUB(9), nine explicit fault controls and joint-reset recovery. The original
[positive shard](../build/ddr-endpoint-current/positives-v1/report.json) and
[fault/recovery shard](../build/ddr-endpoint-current/faults-v1/report.json)
are preserved: ADD(8) and seven fault controls passed; ADD(9) and the ECC-control
timeout case hit their unchanged 1,800/300-second wall limits, stopping the
remaining cases. ADD(8)'s complete 94,208 physical BO bytes and exact 52,006
modeled PHY returns were independently checked. The timed-out ADD(9) partial
dump is not accepted.

The [optimized simulator build](../build/ddr-endpoint-current/native-o3-v1/report.json)
compiles the same frozen RTL with GCC `-O3` rather than its default `-Os`,
retaining assertions, all original stimuli/goldens and the same deadlines.
Its exact 574-diagnostic inventory passes. The
[failed-case regressions](../build/ddr-endpoint-current/o3-regressions-v1/report.json)
pass: ECC-control timeout completes in 268.663 seconds under its unchanged
300-second limit, and ADD(9) completes in 1,240.561 seconds with its entire
94,208-byte physical BO image matching. Earlier failures remain failures.
The new [O3 fault/recovery matrix](../build/ddr-endpoint-current/faults-o3-v1/report.json)
passes all ten selected cases and its independent receipt verifier. The
[O3 positive matrix](../build/ddr-endpoint-current/positives-o3-v1/report.json)
completed nine captures but failed its final repeated SUB(9) case at the
unchanged 1,800-second limit during the later host-pressure interval. Its
[preservation review](../build/ddr-endpoint-current/repeat-timeout-review-v1/preservation.json)
retains the failed report, run log and 61,440-byte partial output. That partial
image is not accepted. Nineteen of twenty logical cases have passed across the
two shards; the whole positive shard remains failed. After three stable
headroom samples, a [same-binary repeat-only retry](../build/ddr-endpoint-current/repeat-o3-v2-admission.json)
uses the original case, goldens and deadline. It passes in 1,697.873 seconds,
with both jobs, four raw tasks and all 102,400 physical BO bytes checked.
The [independent twenty-case union](../build/ddr-endpoint-current/independent-all20-o3-union-v2.json)
now passes: nine captured positives from the failed shard, all ten fault/
recovery cases and the separately verified repeat use exactly the same frozen
ELF and execution inputs. The original failed shard remains failed. Thirteen
successful jobs compare 1,282,048 physical BO bytes; the persisted final images
represent 1,179,648 bytes because repeated comparisons overwrite the prior dump.
This completes the logical twenty-case gate for that source/binary, with no
new FPGA, PHY training, physical DDR, PCIe or RK claim. The
[130-entry selected archive](../verification/runs/2026-10-27-ddr-all20-logical/index.json)
preserves frozen local sources, commands, logs, readbacks and the earlier
failure; external vendor sources and the native binary are excluded.

Each successful case must
match its entire original BO image, including command/task BOs and guards.
The checker derives positive/recovery PHY-return counts from the scalar AXI
and host-line contracts, rejects malformed/duplicate completion markers, and
retains the 300-second fault and 1,800-second numerical/recovery bounds.
Unknown task descriptor fields fail before simulation.

```sh
make ddr-endpoint-controls
python3 tools/ddr/run_endpoint.py build --archive /path/XC7K480T_XDMA_Test.zip \
  --primitive-library /path/Vivado/data/verilog/src/xeclib --out build/ddr-model
python3 tools/ddr/run_endpoint.py run --package build/ddr-model --out build/ddr-all20
python3 tools/ddr/run_endpoint.py verify-run --report build/ddr-all20/report.json
```

`run --case NAME` can select cases explicitly; its receipt claims only that
subset. Eight portable result/diagnostic/descriptor controls and three actual
Icarus/Verilator image-reader controls also run under the default `make test`.
The joined MC numerical run is specifically a Verilator model; neither those
controls nor an encoded PHY memory model validate actual DDR pads/training,
the full default 2 GiB contents, a TCK crossing or physical PCIe.

Separate [original-profile MIG generation](DDR_ORIGINAL_MIG.md) now supplies
actual regenerated controller sources with the original RZQ/7 drive settings.
Its wrapper/PHY identity and physical integration are separate from the
archive-based logical model above.

The next [SYS50/UI133 source profile](DDR_ASYNC_ENDPOINT.md) connects the
separately tested engine crossings to this owner under the new RKAD identity.
It requires fresh compilation and the same logical matrix; the twenty-case
result above remains limited to its original single-UI-clock source.
