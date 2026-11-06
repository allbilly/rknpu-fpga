# K16 FDIV/MAX control-path timing repair candidate

This note records a source-level timing repair for the failed K16 FDIV/MAX
routed image. It is not a timing signoff: no full-top K16 or K8
synthesis/placement/route, bitstream or hardware run is claimed here.

## Observed failure

The fresh K16 image at source commit `58c0e7f5` routed but failed setup under
the unchanged 7.500 ns `clk_pll_i_1` constraint.

| Measurement | Value |
|---|---|
| Setup WNS / TNS | -0.121 ns / -5.982 ns |
| Setup failing endpoints | 132 |
| Worst path | CH1 MIG control `addr_reg[2]` -> `compute_reset/saved_code_reg[0]/CE` |
| Worst data path | 7.287 ns = 1.083 ns logic + 6.204 ns route, 20 levels |
| Hold / pulse | +0.047 ns / +0.264 ns, zero failing |

The failing families split into two independent combinational cones:

1. `c1_u_memc_ui_top_axi/.../addr_reg[2]` through the MIG control read data
   into `monitor/monitor_healthy` and `check_ready`, then into
   `compute_reset/saved_code_reg[*]/CE`, `ui_stable_reg[*]/CE`,
   `ui_release_reg/D`, `engine/numerical/cmac/job_crossing/descriptor_held_reg[*]/CE`
   and `control/bank[1].control/result_tasks_reg[26]/D`.
2. `reset_router/read_pending_reg` through the AXI-Lite read-address/response
   mux, `capacity/owner/logical_quiet`, capacity admission and `memory_ready`
   into `control/bank[*].control/{command_address,job_tag,result_tag}_reg[*]/CE`
   and `backend/rsp_data_reg[*]/CE` / `rsp_status_reg[7]/CE`.

Both cones are status/admission paths, not the numerical or command encoder.

## Repair

Two endpoint-local pipeline registers, no constraints, false paths or
multicycle exceptions:

### ECC monitor readback sample

`rtl/ddr/rk_mig_ecc_monitor.sv`

- Capture `m_axi_ctrl_rdata` on the actual read handshake into
  `read_sample_data`.
- Perform the expected-mask/onoff/status comparisons, the matching FSM state
  advance, and the snapshot capture from that registered copy on the following
  UI clock.
- Keep IRQ, calibration loss, AXI handshake/protocol, B/R response-code and
  timeout faults immediate and unchanged.

Latency/protocol impact: one extra UI clock per control read (three extra clocks
for the three-read startup and for each three-read check); healthy assertion and
snapshot publication move by those accumulated extra read clocks; data-mismatch
fault codes 6/7/8 are detected one UI clock after their response. The monitor
still owns one outstanding AXI-Lite transaction, consumes the response on the
same handshake, and issues no new request during the sample cycle. A bad read
cannot make health true because the `READ_STATUS` success edge now waits for the
sampled check. Immediate IRQ/calibration/protocol faults still drop
`monitor_healthy` in the same cycle.

### Capacity-owner diagnostic quiet witness

`rtl/ddr/capacity/rk_ddr_capacity_owner.sv`

- Add `logical_quiet_fault`, a registered copy of `logical_quiet`.
- Use it only for diagnostic fault code 4 (`diagnostic_owned &&
  !logical_quiet_fault`).
- Keep immediate `logical_quiet` for `quiet_now` and the two-cycle QUIESCE
  counter.

Latency/protocol impact: normal admission, normal completion, physical-quiet
counting and AXI handshakes are unchanged. The owner already requires two
consecutive quiet cycles before `diagnostic_owned`; the registered witness is
settled by then. A normal response that appears while a diagnostic session is
already owned faults one UI clock later. Normal admission is already disabled
in that state, so no new normal work can enter.

## Validation performed

- Verilator 5.048 `--lint-only -Wall` on both changed modules: clean.
- Portable ECC monitor, Icarus 13.0 and Verilator 5.048: PASS (30/24 cases,
  including the new late-readback-change regression).
- Archived vendor control-leaf ECC monitor, Icarus 13.0 and Verilator 5.048:
  PASS (21 scenarios, 16 raw event vectors, 2 held snapshots).
- Capacity service owner/router/control suites, Icarus 13.0 and Verilator
  5.048: PASS.
- Bounded capacity BIST/fence suites, Icarus 13.0 and Verilator 5.048: PASS.
- Public dual-host NPU/JTAG/PCIe replay, Verilator 5.048:
  `PASS_ACTUAL_NPU_DUAL_HOST_NATIVE_ONLY`, 2 jobs / 4 tasks / 2 BO images /
  204,800 BO bytes / 3,203 modeled READ64 reads, with zero new structural
  warnings.
- Framework source-profile hash checks and generated-source check: PASS.
- Small Vivado 2026.1 OOC synthesis of each changed module, 7.500 ns clock:
  the baseline frozen sources show one combinational path from
  `m_axi_ctrl_rdata` to `monitor_healthy` and one from
  `normal_pending_response` to `normal_admission_enable`; the repaired sources
  show zero such paths, with the 32-bit sample register and the one-bit quiet
  witness present.

The OOC checks are structural only. They do not estimate routed slack, and the
testbenches do not validate SystemVerilog placement/routing or silicon.

## Remaining qualification

A full-top K8 build must replace the two source files in its bound source
snapshot (or use the updated repository profile manifests) and run the guarded
synthesis/placement/route with unchanged clocks, DRC, electrical and CDC
checks. That build must show the K16 worst families and the 132 endpoints
cleared at 133.33 MHz, with no new failing paths from the two new registers,
and then pass the existing image/bitstream gates. The frozen K16 checkpoint
remains failed and is not admitted by this repair.
