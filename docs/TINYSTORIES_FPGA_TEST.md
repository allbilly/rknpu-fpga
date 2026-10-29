# TinyStories FPGA inference and raw-wire evidence

The complete **32-position TinyStories-260K hybrid inference** now passes
[independent raw-wire audit](../build/tinystories-streaming-model-audit/full32-idle-wait-v1.json)
on the full512 FPGA image. All1,152 learned dense input/output pairs and all
16,384 logits match the fixed donor-policy oracle exactly. The28 generated
token IDs and text match the separate CPU reference:

> Once upon a time, there was a little girl named Lily. She loved to play outside in the park. One

| Complete32-position run | Accepted evidence |
|---|---|
| Physical execution | All1,152 learned projections;7,424 original raw jobs;11,136 completed tasks |
| Raw JTAG audit | 2,743,153 scans and914,383 complete mailbox commands, including retained sequence and wrap checks |
| Resident weights | All116 prepared tiles verified initially;3,712 weight-tile checks before use |
| Complete output readback | 30,408,704 bytes, including physical padding/guards, checked before each ACK |
| Numerical result | All16,384 logits bit-identical; SHA256 `c35b2be9a48e7fdc49c9b513ee1e0977766caf1ca442f9756aa2ec877a473e0c` |
| Model generation | All28 greedy IDs and text exact; prompt `Once upon a time`,32 forward positions |
| Target and image | DNA `004E544714C705C`, raw ID `23751093`, USR_ACCESS `1e01179c`; exact source/bitstream hashes below |
| Storage and cleanup | One audited volatile-SRAM load; worker/bridge exits0; owned server stopped and cable lease released; flash unchanged |

The [physical producer receipt](../build/fpga-bringup/tinystories-model-wait-20261027T035254Z/physical-tests/report.json)
and independent audit bind the exact image,277 reviewed inputs, target,
original commands/tasks, complete BOs, actual scans and final logits/tokens.
The parent finished at07:36:12UTC on2026-10-27 after a repeated complete BOS
control and the32-position workload. This is not a throughput benchmark.
Vivado Lab2026.1.1 used3MHz TCK. The worker made1,153 memory admission checks,
with a minimum4,454,208KiB available; it consumed none of the900-second idle
wait budget. All scan deadlines and the2GiB minimum remained unchanged.
The [331-file portable evidence archive](../verification/runs/2026-10-27-tinystories-full32-fpga/index.json)
preserves the complete raw trace, actual BO observations, reviewed local
sources, auditors and reference results. Its deterministic compressed/literal
copies total49,234,220bytes and decode to the recorded original hashes.
Compiled images/checkpoints and the external native tools are excluded and
remain identified by hash. This selected archive is not a complete binary DAG.

Embedding, RMSNorm, RoPE, attention, SwiGLU, residuals, KV storage and sampling
remain explicit CPU operators. Every learned dense projection uses the FPGA;
there is no learned-dense CPU fallback or runtime CPU layout/arithmetic repair.
This closes the selected TinyStories/JTAG milestone. Physical DDR, PCIe,
general framework support and RK3588 equivalence remain separate gates.
The failed earlier attempts below retain their original failed statuses.

## First complete model forward

The new shared image now passes **one complete BOS forward through all five
TinyStories-260K layers and the output head**. All 36 learned dense
projections execute on the full512 FPGA datapath. Every actual dense input
and output matches the fixed donor-policy oracle, all 512 logits are
bit-identical, and greedy sampling generates token 403, `Once`.

This is hybrid inference: embedding, RMSNorm, RoPE, attention, SwiGLU,
residuals, KV storage and sampling are explicit CPU host operators. There is
no CPU learned-dense fallback or runtime CPU layout repair. This earlier
one-position receipt retains its own scope; the later full32 result is above.

| First complete forward | Actual evidence |
|---|---|
| Learned projections | All 36, across five layers and the output head |
| Resident weights | All 116 prepared tiles, 557,056 bytes, uploaded and read back |
| Raw execution | 232 original raw jobs, 348 completed tasks |
| Mutable-output readback | 950,272 complete BO bytes observed before the respective ACKs |
| Independent actual-scan audit | 145,105 scans, 48,367 mailbox commands; exact original command/task BOs, resident weights and all 36 actual input/output pairs checked |
| Numerical comparison | All 512 FP32 host logits match the donor-policy reference byte-for-byte; SHA256 `da84021345aa0521e0ed1c37344b91e93ef077d964a56bd876fdd4326ae8a893` |
| Generated output | One token: 403, `Once` |
| Persistent storage | Flash unchanged |

The [closed first-forward receipt](../build/fpga-bringup/tinystories-model-20261026T215500Z/first-forward-snapshot.json)
and [independent audit](../build/fpga-bringup/tinystories-model-20261026T215500Z/independent-first-forward-audit-v2.json)
bind this result to the same source and bitstream hashes below. The actual
worker ran from 22:06:57 to 22:14:40 UTC on 2026-10-26, including model upload
and readback. This is 2026-10-27 local time. It is not a throughput benchmark.
The [41-file portable first-forward archive](../verification/runs/2026-10-27-tinystories-first-forward-fpga/index.json)
preserves the closed worker, actual scans/BO observations, host source and
independent auditors. Its deterministic compressed copies decode to the
original recorded hashes. The active 32-position run is excluded.

## Failed longer run and captured-prefix audit

The first 32-position attempt stopped after 738 complete projections, during
readback of raw job 4,738. That job had already reported tag 4,738, two tasks
and error code zero; only eight of its 64 output lines were fully read before
the native RPC timed out, so it was not ACKed. Its remote final read outcome
is uncertain. The [producer](../build/fpga-bringup/tinystories-model-20261026T215500Z/physical-tests/report.json)
and child remain failed; no software retry or fallback completed that workload.

The kernel reported global OOM at 00:22:53 UTC, four seconds before the worker
failure completed. The native bridge also recorded 10- and 15-second scans
with about 0.5 GB virtual headroom. This is evidence of host resource failure
coincident with the timeout, not new numerical or hardware signoff. Owned
worker, bridge and server processes were stopped and the shared lease released.
No unrelated process was stopped by this test controller.

A [streaming postmortem audit](../build/tinystories-long-failure-audit/v1/prefix-audit-v2.json)
checks 1,772,883 actual scans, 590,959 completed mailbox commands, all 4,737
fully recorded raw jobs and 19,402,752 complete output-BO bytes. All 738
complete dense input/output pairs match the donor-policy reference. Twenty
full positions are replayed through the unchanged CPU host operators using
only captured actual FPGA dense outputs; all corresponding logits and token
IDs match the fixed reference. Eighteen further projections of the next
position are also complete. This is a qualified captured prefix of a failed
run, not a passing 32-position execution.

That recorded-output host replay reconstructs:

> Once upon a time, there was a little girl named Lily. She loved to play

The [preservation receipt](../build/tinystories-long-failure-audit/v1/preservation.json)
binds the failed receipts, host OOM log and 29 pre-edit software sources.
Hardware image/source inputs were unchanged. Runtime repairs now flush each
completed position's logits, tokens and text bytes, plus every completed dense
receipt, and poison the model if recording fails. Six new controls pass;
the updated CPU oracle CLI reproduces all 32 prior reference rows byte-exactly.

Vivado Lab 2026.1.1 initializes the required native commands at a measured
501,408 KiB software-only peak. The fresh
[same-image attempt](../build/fpga-bringup/tinystories-model-lab-20261027T011411Z/image-review.json)
uses Lab, checks host headroom before admission, and gives the worker a
2 GiB availability gate between projections. It rechecks cable/DNA/raw ID and
performs a new volatile load before BOS/32-position tests. The original
30-second scan budget, numerical comparisons, raw commands and FPGA timing
remain unchanged. Its new BOS control passes, and the
[independent actual-scan audit](../build/fpga-bringup/tinystories-model-lab-20261027T011411Z/independent-first-forward-audit-v2.json)
again matches all 36 actual dense input/output pairs, all original command/task
BOs, resident weights and 512 logits. The Lab 32-position run subsequently
stopped at 02:57:01 UTC when its between-projection resource check found
2,065,748 KiB available against the unchanged 2,097,152 KiB minimum. Its producer
remains failed. The [independent raw-wire prefix audit](../build/tinystories-lab-resource-failure/v1/prefix-review.json)
passes 18 complete positions, 681 dense pairs, 4,360 acknowledged jobs,
6,540 tasks and 17,858,560 output BO bytes. All 9,216 recorded logits and the
token/text prefix match the donor reference. Every scan/request completes;
the next projection was not submitted. The final process cleanup remains
recorded separately; a quit ACK does not imply a passing full run.

The [preservation ledger](../build/tinystories-lab-resource-failure/v1/preservation.json)
rehashes the reviewed source/image and captured artifacts and preserves the
pre-edit runtime sources. The separate
[host snapshot](../build/host-pressure-failure/20261027T0325Z/resource-event-receipt.json)
records later severe memory pressure and a 03:25:11 UTC global OOM that killed
an unrelated Vivado worker. That later kernel event is distinct from this
producer's earlier memory-guard failure. The DDR repeat timeout is also a
separate failed run; none is relabeled as numerical success.

For the next reviewed attempt, `run_model.py` supports an explicit hardware-only
`--memory-wait-budget-seconds` while retaining the original memory threshold.
The default zero budget still fails immediately. A positive budget is cumulative
across the whole worker and permits waiting only before connection or between
fully completed projections, after their output readback and ACKs. It keeps the
same live model state; it does not replay/reconnect/retry a device job or perform
CPU dense work. No active transport deadline is extended. Exhaustion, malformed
host telemetry and recording failures remain explicit failures. Atomic resource
metadata and wait/resume events distinguish an idle wait from completed work.

The [55-method control and CPU-reference receipt](../build/tinystories-memory-wait-controls/v1/report.json)
passes six new policy controls and the complete CPU-only 32-position oracle:
1,152 dense records and all 65,536 logit bytes remain exact. The earlier full
default Make snapshot has49 TinyStories controls; the later
[full default regression](../build/production-model-auditors/current-v3/root-review.json)
also passes all55 controls in its1,035.709-second Make run. A new physical run
still needs fresh runtime/image/
target review, stable host headroom and exclusive cable ownership.

The [wait-enabled fresh session](../build/fpga-bringup/tinystories-model-wait-20261027T035254Z/image-review.json)
has now passed those preflights, a new volatile load and its complete BOS
control. DNA/raw ID, INIT/DONE, 3 MHz TCK and source-derived USR_ACCESS
`1e01179c` match. Its [independent actual-wire replay](../build/tinystories-streaming-model-audit/bos-idle-wait-v1.json)
passes all 36 projections, 232 jobs, 348 tasks and 512 logits on the same
full512 image. The 900-second cumulative idle-wait budget was unused in that
control. Its separate32-position worker subsequently completed successfully,
and the full actual-wire audit above now accepts that workload. Prior failed
prefixes and the BOS control retain their narrower scopes.

## Repeatable read-only application audits

`tools/tinystories/check_progress.py` compares only the positions/projections
counted in the worker's atomic report. It checks each counted logit row, token,
text prefix and dense input/output hash against the fixed donor reference.
Unmarked trailing writes are ignored while the producer runs or has failed;
a completed producer must have exact coverage and no extra bytes/rows. An
empty startup is reported without inventing progress. This checker always
retains the producer's status and reports `full_hardware_run_accepted=false`.

```sh
python3 tools/tinystories/check_progress.py \
  --worker build/fpga-bringup/tinystories-model-lab-20261027T011411Z/physical-tests/greedy32/jobs \
  --reference build/tinystories-full-oracle/v1 \
  --out build/new-prefix-check.json
```

`tools/tinystories/audit_model.py` supplies the independent final raw-wire audit.
Its streaming decoder checks target ID, framing, retained responses, sequence
wrap, request ownership and complete scan history without collecting the
entire trace in memory. The replay checks original command/task BOs, actual
resident weights before each CMAC use, EW unity constants, contiguous inputs
and outputs, guards, complete output readback and ACK ordering. All uploaded
lines must have actual successful readback before a submission. The final
32-position gate also requires the completed physical producer, cleanup,
exact image/load/source bindings, all token/logit/dense records and the fixed
reference. A running/failed parent cannot pass this gate.

```sh
python3 tools/tinystories/audit_model.py \
  --run build/fpga-bringup/tinystories-model-lab-20261027T011411Z \
  --package build/tinystories-preparation/260k-first-v2 \
  --catalog build/tinystories-programs/all-v1/report.json \
  --reference build/tinystories-full-oracle/v1 \
  --out build/new-complete-model-audit.json
```

The explicitly selected `--phase one-complete-forward-position` audits the
separate BOS control and always leaves full-generation acceptance false. Its
[final-source physical replay](../build/tinystories-streaming-model-audit/bos-v4.json)
passes 145,105 scans, 48,367 commands, 232 jobs, 348 tasks, 36 dense pairs,
116 weight checks and 950,272 output BO bytes. The
[49-method TinyStories control review](../build/tinystories-model-audit-controls/v2/root-review.json)
pass with Python 3.14.5, including corrupt/missing progress, sequence wrap,
failed scans, altered original BOs/constants, guard damage, missing output
lines and wrong ACK ownership. Generated checks and whitespace checks also
pass. These controls are separate from the earlier full production snapshot's
34 TinyStories methods. Artifact hashes also stream rather than loading an
entire trace into memory. The first final-source BOS command used the wrong
preparation package and was correctly rejected; its failure is preserved.
The linked final-source replay uses the worker's exact v2 package. No new
hardware action is performed by either auditor.

## Earlier trained-tile test

On 2026-10-27 local time, the new shared full512 CMAC/EW/USER2 image passed
its first physical trained-tile test on the YPCB XC7K480T. Two raw CMAC jobs
and two linked EW compactions passed, with all **360,448 owned BO bytes**
compared before their respective ACKs. An independent audit reconstructed
the actual numeric JTAG scans and matched the original raw descriptors,
uploads, completion registers and complete readbacks.

This result covers BOS token 1, layer 0 Wq outputs 0–31 of TinyStories-260K.
The complete first forward above is a separate result. The CPU reference
supplies test expectations only; it does not supply device results.

| Evidence | Observed result |
|---|---|
| Implementation | All 512 CMAC products, one EW engine, 1 MiB BRAM; 516 total DSPs |
| Routed 50 MHz checks | Setup +0.640 ns, hold +0.056 ns, pulse width +9.600 ns; zero failures and route errors |
| Reset and CDC | Actual registered reset cone and startup INITs, held-bus bounds, synchronizers and bus skew pass |
| DRC | 2,064 factory DSP pipelining advisories retain severity; no RAM async-control findings, zero waivers; bitstream DRC has zero errors |
| Volatile load | Exact cable/DNA/raw ID verified; INIT=1, DONE=1, USR_ACCESS=`1e01179c` |
| Raw CMAC | Original 45-word body/49 final QWORDs, 1×64 input and 32 outputs; repeated successfully after EW |
| FPGA compaction | Two original raw EW MUL-unity tasks per compaction; contiguous outputs and native holes/guards match |
| Complete memory checks | 90,112 bytes before every successful ACK, four jobs total |
| Independent wire audit | 25,894 scans, 8,630 mailbox commands; one TAP reset and one raw IDCODE check |
| Persistent storage | Flash unchanged |

The source SHA256 is
`1e01179cf730fdec0faa6644eae1f51dbeee4a5474f3734b327a0f8c7677b425`.
The 18,735,217-byte bitstream SHA256 is
`8039831e578923793bcb6c6b3a5423d90f333dd033667ac3631473649eac941d`.
The target is cable `80802026a77a01`, raw IDCODE `23751093`, with the audited
named DNA_PORT `004E544714C705C`. Programming and testing held the shared
YPCB JTAG lease; owned bridge/server processes were closed afterward.

The [portable physical archive](../verification/runs/2026-10-27-tinystories-trained-tile-fpga/index.json)
contains 85 selected files, including the emission checks, programming
receipt, actual scans, complete BO readbacks and independent audit. Large
text reports/scans use deterministic gzip; the index binds both original and
archived hashes and sizes. Images/checkpoints are excluded. The separate
[145-file source/native/route archive](../verification/runs/2026-10-27-tinystories-dual-route/index.json)
preserves the frozen implementation and corrected simulator runs.

Live local receipts are the [image review](../build/fpga-bringup/tinystories-dual-20261026T221500Z/image-review.json),
[physical producer](../build/fpga-bringup/tinystories-dual-20261026T221500Z/physical-tests/report.json)
and [independent audit](../build/fpga-bringup/tinystories-dual-20261026T221500Z/independent-physical-audit.json).
The new image has its own evidence; earlier autonomous/full512/EW logs are
not relabeled as this endpoint's results.

The completed32-position test and its independent audit compare every learned
projection, all logits and generated token IDs against the fixed same-policy
reference. General tinygrad integration,
DDR/PCIe, RK silicon equivalence and numerical special-value qualification
retain separate gates. IRQ/heartbeat LEDs are not PASS indicators.
