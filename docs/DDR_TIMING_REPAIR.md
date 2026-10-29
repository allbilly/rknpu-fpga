# Full512 DDR routed setup repair

The first constrained shared-data implementation routes completely but fails
setup timing. Its checkpoint is preserved and is not admitted for image emission.

| Measurement | Actual result |
|---|---|
| Setup WNS / TNS | -0.551 ns / -287.348 ns |
| Setup failing endpoints | 1,194 |
| Hold slack / failing endpoints | +0.048 ns / 0 |
| Pulse slack / failing endpoints | +0.264 ns / 0 |
| Product / total DSPs | 512 / 516 |
| Source optimized LUTs | 293,826 |

The [actual route receipt](../build/full512-ddr-preparation/shared-data-route-prep-v6/report.json)
remains failed. Its unchanged source and fully routed checkpoint are preserved;
the later strict global setup gate prevents image generation.

The worst reported path starts at the physical CH1 MIG control-address
register `addr_reg[3]` and ends at backend `rsp_data_reg[488]/CE`, under the
unchanged 7.5 ns UI clock. It passes through ECC monitor health, memory/compute
admission, job-claim arbitration and host readiness. The path has 20 LUT
levels and 7.746 ns data delay: 1.083 ns logic and 6.663 ns routing. Its final
response-enable net drives 517 pins. This diagnosis concerns response control,
not the FP16 multiplication or accumulation policy.

The read-only inventory identifies 1,130 failing CE paths and 64 failing D
paths. Thirteen selected LUT-driver nets cover 1,106 of those CE paths. The
first [targeted repair attempt](../build/full512-ddr-preparation/postroute-repair-v2/report.json)
failed before optimization: Vivado 2026.1 rejects
`-force_replication_on_nets` in post-route mode. Its failed receipt and
unchanged routed parent are preserved.

A fresh [supported post-route attempt](../build/full512-ddr-preparation/postroute-repair-v3/root-launch-review.json)
was launched on 2026-10-28 with `phys_opt_design -directive AggressiveExplore`,
then `route_design -directive MoreGlobalIterations -tns_cleanup`. It revalidates
the selected driver identities and retains all clocks, electrical properties,
project crossing/reset checks and source identities. Its pulse gate checks
every recognized period/pulse row, including Max Period rows when present.
The [native receipt](../build/full512-ddr-preparation/postroute-repair-v3/report.json)
must reach terminal success and pass independent review before image admission;
launch alone supplies no timing result. No false path, multicycle exception or
DRC severity change is permitted.

The completed native repair now passes setup/hold/pulse at
**+0.004/+0.048/+0.264 ns**, with zero failing endpoints and all 232 reported
period/pulse rows accepted. Its [independent native facts](../build/full512-ddr-preparation/postroute-repair-v3/root-native-facts.json)
retain native rc0 and the unique strict-gate PASS marker. The wrapper remains
**FAIL** because the public emitter template, recorded only as the origin of
the copied pulse checker, changed while implementation ran. RTL, XDC, helpers
and the executed repair Tcl remained unchanged. The failing receipt is preserved.

The [fresh strict requalification](../build/full512-ddr-preparation/strict-route-requalification-v1/root-review.json)
therefore reopens the actual repaired checkpoint, reruns every original
structural/CDC/reset/DRC/timing gate and exports a new checkpoint. It performs
no synthesis, placement, physical optimization, routing or constraint changes.
Its independently bound input closure contains the old/current template
snapshots and preserves the original provenance failure. A terminal native
pass and independent checkpoint review have now completed: native rc0 in
804.674 seconds, all 343 inputs unchanged, 422,138 fully routed nets and zero
route errors. The [independent checkpoint review](../build/full512-ddr-preparation/strict-route-requalification-v1/root-route-review.json)
passes all global timing and 232 pulse rows, both controllers, 512 product DSPs,
516 total DSPs, 242 ports and the original factory-warning inventory.
The [portable timing archive](../verification/runs/2026-10-28-full512-ddr-timing/index.json)
preserves 406 source/evidence payloads in 3,965,773 stored bytes, with independent
root rehash of every payload and all 343 input references. Checkpoints/tools
are hash-identified exclusions. The [independent IO review](../build/full512-ddr-preparation/full512-image-prep-v11/root-io-review.json)
also passes all 1,936 properties across 242 ports with zero pin-spec mismatches.
Native IO query rc0 and its outer container-name parser failure remain separate;
corrected offline processing does not rerun or relabel that native attempt.
The first [offline emission receipt](../build/full512-ddr-preparation/full512-image-prep-v11/emission-report.json)
remains TIMEOUT: its 1,200-second workflow budget expired during bitmap
generation, after checkpoint serialization, without a bitfile. The
[fresh reviewed emission](../build/full512-ddr-preparation/full512-image-prep-v12/root-emission-review.json)
used a prospective 2,400-second workflow budget, the same qualified checkpoint
and unchanged RTL, clocks, constraints, DRC gates and numerical expectations.
It completed natively in 1,256.917 seconds. The independently reviewed bitfile
and [first physical trained workload](DDR_FULL512_FPGA_TEST.md) now pass. The
full model and broader capacity/ECC/recovery/PCIe gates remain.

An unpromoted RTL fallback is also prepared privately. It retains the request
validation/admission edge and completed memory side effects, captures response
data locally, and publishes the result one UI clock later using a registered
narrow pending record. It is not part of the routed design and does not inherit
its qualification. Native host tests must validate snapshots, final READ64
halfwords, error replies, outstanding-request quarantine and joint reset before
any integration; modified RTL would need fresh full-design implementation and
controller evidence. Its [independently reviewed private qualification](../build/full512-ddr-preparation/backend-response-pipeline-v3/root-review.json)
now passes strict directed snapshot/admission checks and all 15 original host
scenarios in both Icarus 13.0 and Verilator 5.048. Only the private backend
differs across the 1,095 copied source files. The public backend and current
DDR implementation remain unchanged; these host tests do not qualify the
fallback's complete DDR composition or timing.

The separate [same-executable controller union](../build/full512-ddr-preparation/shared-data-fault-model-v1/root-full33-union.json)
passes all 12 CMAC and 21 EW numerical/fault/recovery cases. Those logical
results do not close this timing gate or establish physical DDR inference.
