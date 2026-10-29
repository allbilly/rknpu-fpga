# Read-only review: raw case status audit fix

Reviewed `tools/ddr/audit_raw_case.py`, `tests/ddr/capacity_parent/test_raw_case_wire.py`, `tools/ddr/run_capacity_parent.py`, `rtl/ddr/capacity/rk_job_control_admission.sv`, and the frozen CMAC epoch-1 scan trace. No source changes or hardware/native runs were made. The scan file was decoded offline by consuming `tools.tinystories.audit_scans.commands()` through EOF.

## Confirmed

- The auditor derives the staged valid mask from observed descriptor writes and requires exact equality: `expected_fields = (1 << staged) - 1`, then `(response >> 8) & 7 == expected_fields` (`audit_raw_case.py:65-70`). It rejects reserved status bits via `response & ~0x77f` and the result-error/core-error bits via `response & (8 | 32)` (`:57-60`). These checks do not erase unexpected status bits.
- The 14 `test_` methods in `test_raw_case_wire.py` include exact partial/full staged-field checks, peer-status rejection, completion regression, full readback ordering/content, ACK gating, final-idle health, unknown operation/CSR, reserved status, and failed command rejection. `run_capacity_parent.py` expects `tests: 14` for this suite (`:256-257`).
- The frozen `epoch-1-cmac/native-scans.jsonl` decodes completely: 4,873 scans, 1,623 commands, one IDCODE, one TAP reset. The raw-case replay accepts the actual CMAC upload/expected fixtures, descriptor `0x100e0000 / 45 / 0x35880001`, all 320 64-byte uploads and 320 readbacks, and ACK only after readback (20,480 bytes). Status observations are: idle `0x10` (647 reads total across both banks), staged `0x711` (one), and completed `0x714` (321). The exact field-valid bits therefore appear in the actual staged and readback statuses.

## Confirmed auditor gap

During an owned job with no result yet, the status branch only performs completion checks when bit 2 (`result_valid`) is set; it does not require bit 1 (`active`) to remain set or bit 0 (`can_submit`) to remain clear (`audit_raw_case.py:71-80`). The RTL status word puts `active` at bit 1 and `status_can_submit` at bit 0, and its completion transition clears `active` while setting `result_valid` on the same edge (`rk_job_control_admission.sv:56-57, 128-131`).

A synthetic copy of the existing valid CMAC fixture with the precompletion `0x742` status changed to `0x710` (descriptor flags and memory-ready retained, but neither active nor result-valid set) is currently accepted as `PASS_INDEPENDENT_SINGLE_RAW_JOB_WIRE_ONLY`. The corresponding `0x730` mutation (adding the RTL `core_error` bit 5) is rejected. This indicates a status-transition false-acceptance case: while local audit state says active and completion is not yet observed, require the RTL active bit and reject can-submit. The real trace does not contain a precompletion status poll, so it does not exercise this case.

## Narrow test-coverage note

The status-error predicate rejects both result-error bit 3 and core-error bit 5, but the existing `unknown/fault status` control injects `0x80` (reserved bit 7) rather than either defined error bit (`test_raw_case_wire.py:253-256`). The parser behavior is correct for the checked branches; adding separate mutations for `0x08` and `0x20` would directly lock those predicates.
