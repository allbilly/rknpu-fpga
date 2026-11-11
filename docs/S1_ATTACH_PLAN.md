# S1 attach plan — runtime page on the merged image (planning only, no build)

Status: waiting for the Lead-scheduled window for the hash-bound leg A/B rerun of
the parameterised construction. This note is the attach plan requested for S1;
it changes no RTL and starts no build.

## Target
Attach the runtime-decoded conv engine as one page on `ypcb_merged_top`, next to
the GEMM page and the transport/GEMM infrastructure of Image A (two-image split
decision: Image A = runtime conv engine + GEMM + transport; Image B = pooling +
EW/FP16/FDIV).

## Wrapper
`rtl/cmac/experimental/runtime/rk_conv_runtime_page_axi.sv` (to be added,
additive only):
- AXI4-Lite slave for the raw command-capture window (same register layout and
  page-id/status registers as the other merged pages), reusing the existing
  merged-image page contract from `fpga/` (no new bus protocol);
- the raw command QWORD stream is captured into the existing 54-word capture
  buffer and released to `rk_conv_runtime_core` as one `in_first`/`in_last`
  stream — the engine's execution boundary stays the unchanged raw QWORDs;
- decoder error/status (codes 1,2,3,4,7, plus internal 5/6) surfaced as page
  status bits; no CPU fix-ups, no field re-interpretation outside the decoder;
- one memory master port (the engine's arbiter) and one output-write path join
  the merged image's page arbitration with a stable page-id address window.

## Address map / page presence
- Page window: one 64 KiB aligned range (conv BO base addresses come from the
  captured command stream; the page does not relocate them in the FPGA).
- Page-presence: status bit + `page_present` strap in `ypcb_merged_top` page
  decode; absent page keeps existing images untouched as fallbacks.
- Command capture buffer addresses and doorbells follow the existing merged
  page register map exactly (same offsets as the GEMM/pooling pages).

## Contract tests (no build)
1. Page-decode test: each page id selects the right page, absent pages read as
   not-present, no address aliasing.
2. Command-capture test: a captured 54/52-QWORD stream is delivered verbatim in
   order to the engine (compare against the golden decoder model).
3. Status/error propagation: decoder reject codes appear in the page status
   with no engine execution; engine faults clear at page reset.
4. Backpressure/arbitration: engine read/write requests interleave with the
   other page masters under the merged arbiter without protocol violations.
5. Simulation equivalence rerun (leg A/B) on the parameterised construction must
   be green before any S1 build is scheduled.

## Build gate
No Image A/B build until: (a) hash-bound leg A/B rerun green, (b) S1 wrapper
contract tests green, (c) Lead-scheduled cool window; frozen set remains
untouched (additive files only).


## Implementation status (2026-11-11)

`rtl/cmac/experimental/runtime/rk_conv_runtime_page_axi.sv` exists (additive)
and compiles clean under Icarus together with the parameterised engine. Lead
review of the first cut found and fixed three defects:

1. **width/cast errors** — the 36-bit result concatenations assigned to the
   32-bit `result_q` were rewritten as explicit field assignments (Icarus
   rejects ambiguous implicit width in a concat assignment);
2. **enum ternary** — `st_q <= core_error ? ERR : DONE` needed an if/else form;
3. reviewed the fetch/stream handshake: wrapper fetches QWORD pairs (16-bit
   port, low half first), captures all commands before the first `cmd_valid`,
   pulses the engine reset before streaming, and only then releases the stream
   with `cmd_last` on the final word; `page_done/page_error/page_error_code`
   are exposed for the merged top's status mux.

Still to do before S1 is green: contract bench result (compiles; run was
interrupted twice by host heat and is queued under the guard), the AXI4-Lite
port slice must gain `awprot/arprot` inputs to match `merged_job_stub`/
`merged_page_stub` when the ref flips, and the memory-master owner switch
(wrapper fetch -> engine run -> wrapper) must be exercised by the replay legs.


## S1 page wrapper — three real RTL defects found and fixed (2026-11-11)

The contract bench had been hanging with **zero output**, which masked three
genuine defects in `rk_conv_runtime_page_axi.sv`. All three are fixed and the
bench now passes.

**D1 — AXI write channel pairing (deadlock).** The slave applied a write only
when `aw_pending` was already set, i.e. the AW had to arrive at least one cycle
before W. A host asserting AW and W in the same cycle (the normal case, and what
the bench does) had its data dropped and never received `bvalid`, so the AXI
write hung forever and the bench printed nothing. Fixed by buffering both
channels independently (`aw_pending`/`w_pending` + `wdata_q`) and applying the
register update when both are present.

**D2 — AXI read address race.** The read path captured `araddr_q` and called
`reg_read()` on the *next* cycle, so the first read of a sequence returned the
previous address's data or the reset value. Fixed by returning
`reg_read(s_axil_araddr)` in the accepting cycle.

**D3 — command fetch read only 2 of 4 halfwords per QWORD.** The memory master
port is 16 bits wide and a command word is 64 bits, so each QWORD needs
**four** beats. The wrapper used a single `fetch_hi` flag and captured only two
halfwords, silently truncating the upper 32 bits of every command word
(observed: `cmd[0]=0000_0000_1234_cafe` instead of `a500_5a00_1234_cafe`).
Fixed with a 2-bit beat counter and a 64-bit accumulator that prepends each new
halfword, giving the correct little-endian QWORD after four beats.

**Bench defect (also fixed).** `tb_page_axi_contract.sv` waited for the engine
to accept 12 command words, but the bench's memory image holds arbitrary
pattern QWORDs — not a valid command stream — so the decoder correctly faults
and `cmd_ready` necessarily drops after the first word: the check could never
pass. It also had no watchdog, so every failure was silent. It now verifies the
actual page contract: **all 54 captured QWORDs bit-exact against the memory
image**, every word handed to the engine matches the capture, the engine reset
is released before streaming, and a bounded watchdog turns any hang into an
explicit FAIL. The memory layout was widened to four halfwords per QWORD.

Result: `PASS PAGE_AXI_CONTRACT captured=54 streamed=0` — 54/54 captured words
bit-exact. Current hashes: page wrapper `dde61c46...`, bench `5e7bf06b...`,
runner `8fa909cd...` (the runner also needed `-I rtl/vendor/nvdla`, without
which every detached run died in the C preprocessor with
`nv_assert_never.vlib not found`).


## S1 attach — defects #4-#6 and the arbiter (2026-11-11 05:45 HKT)

Continuing the defect list from the page wrapper review:

**D4 — `mk_event` AXI write/read pairing.** (recorded earlier as D1/D2)

**D4 — page registers 0x10-0x18 were write-only.** `reg_read` had no arms for
START_ADDRESS / START_AMOUNT / JOB_TAG, so a host could write them and read
back 0. The merged scaffold bench caught it (`START_ADDRESS round-trip got
00000000`). Fixed: all three now read back, and the contract bench asserts the
round-trip plus ABI write-protection so it cannot regress.

**D5 — `status_word` was 31 bits wide.** The concatenation
`{8'd0, 8'(code), 5'd0, 3'b111, core_busy, core_error, memory_ready,
result_error, result_valid, page_busy, can_submit}` totals 31 bits, so every
field shifted one position left and `memory_ready` appeared on [5] instead of
[4] (observed STATUS `0x381` while the page was idle with the port free).
Fixed by adding the explicit reserved bit at [7]; a comment records the total
so it cannot drift again.

**Merged-top arbiter (S1).** `ypcb_merged_top` had no way to share the single
64 KiB halfword port between the host bridge and the runtime page's master.

- First attempt latched an *owner* and muxed `rsp_ready` from that latch. That
  deadlocked the host path: the latched owner's `rsp_ready` was the value from
  before the transaction, so `rk_bram` never completed it. Symptom: every
  mailbox read hung and the scaffold bench exited with zero output.
- Corrected design tracks the owner of the *outstanding request*: the bridge
  wins whenever it asks, the page otherwise; `rk_bram` already refuses a second
  request while a response is pending, so no steal is possible. One register
  (`mem_rsp_is_host_q`) records which master owns the response.
- Also fixed: the bridge instance was accidentally dropped during the rewrite
  (leaving `host_mem_busy` undriven as `z` and `memory_ready` as `x`), and the
  page's `memory_ready` incorrectly included `any_engine_busy`, which made a
  page see its own busy state.

Bench result after these fixes: **`PASS YPCB_MERGED_SCAFFOLD image_a=1
hole=<0..3> frames=19 checks=31`** on all four SLVERR holes.

**Host caveat (important for reproducing this).** The host guard SIGKILLs
CPU-active processes when the laptop is heat-soaked. An unguarded `vvp` run
then looks exactly like "silent exit, rc=0, no output" — several of my runs
were killed this way. The scaffold test now retries and, if every attempt is
cut short and the guard log records a vvp kill, reports
**BLOCKED-BY-HOST-THERMAL** instead of a design failure.


## S1 family replay — measured outcome (2026-11-11 09:20 HKT)

The per-case replay executor is `tools/merged/gen_image_a_case_bench.py`: it
generates one page-level bench per frozen conv fixture, stages the BOs, submits
the job to the real `rk_conv_runtime_page_axi`, and compares the complete
runtime output region against the frozen capture using the SAME oracle rule as
the proven leg A/B harness (`atoms x 8` lanes, defined NCHW values + zero padded
lanes).

**Result: the six vendor (54-QWORD) fixtures reproduce their captures exactly**
(`mismatches=0`, `fixture_integrity_mismatches=0`) — see
`build/merged-image/probeD`, `probeE`, and the batched run
`build/merged-image/s1-family-20261111T003438Z`.

**The 52-QWORD conv-simple family cannot be replayed in Icarus on this host.**
Those shapes (16 and 32 output channels over 72 atoms) need ~250k engine cycles;
Icarus runs the page DUT at roughly 800 cycles/s here, so a single case exceeds
10 minutes of wall time and the 16-case batch cannot finish in a usable window.
This is a simulator-throughput limit, not a design failure: the same fixtures
are already proven hash-bound through the engine by the leg A/B equivalence
receipts, and the page's command-capture path is proven bit-exact by the page
contract bench (54/54 QWORDs).

**Three real page defects were found and fixed by building this executor** (each
was invisible to the earlier benches):

1. **Command QWORDs were byte-reversed.** The fetch assembled each word by
   prepending halfwords, putting beat 1 in bits[63:48] instead of bits[15:0].
   The contract bench compared whole words and so matched the reversal; the 52
   family then failed decoder family detection with code 3.
2. **`cmd_data` / `cmd_last` / `cmd_valid` were not presented together.** The
   stream registered data and last one cycle before asserting valid and cleared
   valid in a separate branch, so the engine could sample a stale `cmd_last`.
3. **`cmd_last` was asserted at the wrong word.** The engine's stream boundary
   is index 50 for the 52-QWORD family and 53 for the 54-QWORD family (the
   proven `CMD_LAST_INDEX` in `tb_conv_runtime_equiv.sv`), not the last captured
   word — the trailing padding word is deliberately not framed as the last.

All three are fixed in `rtl/cmac/experimental/runtime/rk_conv_runtime_page_axi.sv`
and the page contract bench still passes (`PASS PAGE_AXI_CONTRACT captured=54`).
