# Service-admission cofactor source candidate

This directory is a durable, byte-exact, **unselected** owner/service source pair. It is not a default source selection. `rtl/ddr/dual_host_maintenance_fi/sources.json` remains unchanged and currently selects `rtl/ddr/capacity/rk_ddr_capacity_owner.sv` (SHA-256 `c97a6f…`) plus `rtl/ddr/maintenance_fi/rk_ddr_capacity_service.sv` (SHA-256 `6ed1fc…`). The immediate owner comparison baseline for this cofactor is the separate published, explicitly unselected `rtl/ddr/capacity/admission_health_cofactor/rk_ddr_capacity_owner.sv` (SHA-256 `320a98…`); the component receipts below do not qualify the profile's default `c97a6f…` owner.

## Candidate pair

The owner candidate adds one internal `normal_service_admission_enable` output. The existing free-input `normal_admission_enable`, fault encoder and registered state remain. The service candidate routes that qualified output to service admission and retains the old free-input admission as an internal `ASSERT_ON` witness. The external service interface is unchanged. No arithmetic, command words, response encoding, state, latency or clocks are changed.

A future full-source trial must replace HDL orders 154 (owner) and 157 (service) together. These map to project indices 53 and 56 in the warm/controller source profiles. Do not compile the candidate module alongside its baseline definition. The candidate pair is absent from the current public `sources.json`.

## Evidence boundary

The binary composition proof is conditional on the service diagnostic/BIST reset contract; it is not four-state or full-system equivalence. Paired native evidence covers four owner-pair results and sixteen service-profile results. The independent review limits that evidence to component profiles and notes the `other_diagnostic_pending=0` fixture tie-off.

The saved matched-component mapping audit reports 32-to-0 CTRL-RDATA admission fan-in, 1,999 FFs/66 owner FFs for both variants, and LUTs 2,718-to-2,719. Its raw OOC producer remains failed because the parser counted `clk` while Tcl intentionally omitted it from the input-fanin table. A separate saved-artifact audit/review reparses those existing outputs with that one in-memory clock-census correction; it does not rerun Vivado or promote the failed raw producer.

A separate saved-image component replay has an independent review: 20 runtime commands over 20 distinct frozen simulator images, with 50 source hashes, 6 tool hashes and 76 total input bindings unchanged. This is component-only evidence and involved no recompilation.

**Status snapshot — 2026-11-03, 04:25 HKT:** the full synthesis was still running. Root reported both warm/controller codegen commands active after their Verilator version checks returned rc0; terminal codegen and warning reviews were still pending. No routed timing, new image, FPGA execution, physical MIG/PHY behavior or RK hardware qualification is claimed. Exact paths, hashes and receipt limits are recorded in [`source-candidate.json`](source-candidate.json).
