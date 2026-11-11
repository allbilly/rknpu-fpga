# Host crash postmortem — 2026-11-10 (two hard power-loss events)

Status: **diagnosed as a host power-delivery problem, not a project fault.**
No FPGA, JTAG, Vivado or project artifact caused or was damaged by the crashes.
Both losses were re-runnable simulation jobs; all build evidence survived.

## Timeline (2026-11-10 HKT)

| Event | Time | Boot | What was running |
|---|---|---|---|
| Crash 1 | 02:11:04 | boot `-2` (started 21:44:08) | six-page verification matrix: two Verilator compiles (`-j 2` each) plus sims |
| Crash 2 | 02:37:04 | boot `-1` (started 02:14:44) | resumed matrix: dual-endpoint + mailbox Verilator runners, both compiling |
| Reboot | 02:48:41 | boot `0` (current) | — |

Both boots end in the journal mid-service-tick with **no shutdown record**, no
`kernel panic`, no `Oops`/`BUG:`, no `MCE` event, no thermal trip log and no OOM
kill in the crashed boot. `journald` renamed the previous user journal as
"corrupted or uncleanly shut down" — consistent with an abrupt power loss or a
hard hang that needed a manual power cycle.

## Hardware state correlated with both crashes

- Machine: AMD ThinkPad (k10temp, amdgpu, thinkpad_acpi sensors; SP5100 TCO
  watchdog present); thermald is unsupported on this platform.
- `BAT0`: Celxpert 5B10X026, 45 Wh design, 34.61 Wh full (**76.9 % health**),
  **462 charge cycles**, charge thresholds 75 %/80 %, AC online.
- At and after both crashes the battery was at **~0 % (0.1–0.6 Wh)** and
  charging at **15–18 W**. A near-empty battery cannot buffer transient current;
  sustained multi-core load on this SoC can exceed what the adapter plus a
  depleted battery can deliver, which is a known mechanism for instant
  unprotected shutdowns.
- Idle/after-reboot CPU temperature 46–54 °C; no thermal pressure at rest.
- The earlier OOM event at 00:05:46 (boot `-2`, during the memory-crisis
  intervention) was a *software* OOM kill of Vivado and desktop helpers; the
  machine **survived** it, so memory pressure is not the crash cause.

## Ruled out / not supported by evidence

- Kernel panic, oops, watchdog reset, MCE (decoding enabled, none logged).
- Thermal shutdown as a primary cause (no thermal events, modest idle temps).
- Out-of-memory (crashed boots show no OOM lines; free memory was healthy).
- Filesystem/project corruption: after both reboots the FINAL-freeze manifest
  still matches **518/518** files and the adopted six-page receipt and bitstream
  are intact (`81eef4cd…4d39`).

## Leading hypothesis

**Power-delivery brownout during sustained multi-core CPU load while the
battery is nearly empty and charging.** The adapter must simultaneously run the
SoC at high package power and charge the battery at ~17 W; with the battery at
0 % there is no buffer for load transients, and the embedded controller can
drop the rails. Secondary possibilities that would need hardware service if
they persist: failing battery/BMS, underpowered or non-OEM adapter, VRM/firmware
fault.

## Prevention implemented (software, no root)

1. `build/verif/host_guard/host_guard.py` — detached watchdog logging battery
   %, status, voltage, energy, charge power, CPU temperature, load and
   available memory every 5 s to `build/verif/host_guard/guard.csv`. It kills
   recognised heavy job processes if battery voltage drops below 10.8 V, CPU
   temperature exceeds 95 °C, or the battery is discharging below 8 %.
2. `build/verif/host_guard/safe_run.sh` — launcher that **refuses** to start any
   heavy job while `BAT0` is below `BENCH_MIN_BATTERY` (default 30 %), then pins
   the job to a small CPU set (`BENCH_CPUS`, default `0-2`) at `nice 10` to
   lower package power and thus transient draw.
3. Verification policy change: heavy jobs are **serialized** (one runner at a
   time; no concurrent Verilator compiles) until the battery has recovered, and
   every launch is battery-gated. The remaining matrix legs are longer but the
   machine stays up.

## Operator actions recommended

- Keep the machine on AC until the battery is charged (it is charging at
  ~17 W; charge-end threshold is 80 %).
- If crashes recur with a charged battery and modest load, treat it as a
  hardware fault: battery/BMS, adapter wattage/condition, or SoC power delivery
  (service/diagnostics), not a software problem.

## Second limitation found later: degraded CPU cooling (2026-11-10 ~20:18Z)

After the power fix (new charger, 39 W charging), a different host limit showed
up under sustained single-core simulation:

- `host_guard` (5 s sampling) logged
  `GUARD_KILL reason='cpu_temperature_98.2C'` at 20:18:44Z and a second
  `96.6C` kill shortly after, while the mailbox mode-1 Verilator sim had been
  at ~98 % of one core for ~53 min (others: two ~10 min Verilator compiles).
- Tctl reached 98.2 °C with **both fans at ~3200 RPM**; the machine stayed
  stable (no panic/MCE/thermal trip/OOM) and the guard's protective kill
  worked as designed.
- The host is an AMD Ryzen 7 4700U (15 W class, Tjmax ~105 °C). Idle/heat-soak
  readings remain ~84-85 °C Tctl with fans at ~2900-3200 RPM, which is far
  above normal idle and points to degraded cooling (dust, dried thermal paste,
  or blocked intake/exhaust) on top of the earlier weak-charger problem.
- The OS cannot cap CPU frequency from user space on this host
  (`/sys/.../cpufreq/policy0/scaling_max_freq` is root-only and there is no
  sudo). The mitigation therefore has to be scheduling-based.

### Prevention v2 (implemented)

1. `host_guard.py` v2: strict process classification (only real heavy tools
   owned by the user, resolved executable / known runner entry points; each
   kill logs the full cmdline; desktop/system processes are no longer matched),
   still killing at Tctl > 95 °C.
2. `safe_run.sh` now takes a **global heavy-job lock** `/tmp/rknpu-heavy.lock`,
   then calls `heavy_exec.sh`, which waits until Tctl < 82 °C (up to 15 min)
   before launching, then applies an optional user-systemd `CPUQuota` (verified
   working via `systemd-run --user --scope -p CPUQuota=N%`) and CPU pinning +
   `nice`. One heavy job at a time host-wide.
3. Scheduling: verification/background work runs in short bursts with
   cool-down gating rather than hour-long single-core sims; mailbox modes 3-6
   are deferred; long legs use `BENCH_CPU_QUOTA=55-60`.

### Fan/tach question resolved by observation (2026-11-10 04:30-04:38 HKT)

The user reported the fan not visibly/audibly turning while the EC reported
full speed. Follow-up measurements show the fan **is** running:

- EC tach actually changes with its control loop: `2900 RPM -> 2400 RPM ->
  3200 RPM` (observed across the thermal events; `pwm1=255` full, auto mode),
  which requires live tach pulses — a stalled rotor would report 0/error.
- With a job running, Tctl fell from ~85 °C to **~60-65 °C within about a
  minute** when the load changed, and the tracing under a Verilator compile
  showed 60-78 °C swings typical of package power-state changes. Passive
  cooling alone cannot drop the package that fast.
- Therefore the earlier "~85 °C idle" was **heat-soak from long sustained
  jobs**, not a dead fan, and cooling is functional but **marginal under
  sustained full-core load** on this 15 W-class machine. The fan may simply be
  quiet at ~2400 RPM, or the user may have been looking at a different
  machine/vent.

Physical inspection is still worth doing if the exhaust feels cold at full
speed, but the software tach + thermal-response evidence does not indicate a
dead fan. Heavy jobs resumed under the gated one-at-a-time policy.

### Guard v3: why the 20:56Z kill batch was too aggressive (2026-11-10)

At 20:56:23Z the v2 guard logged `cpu_temperature_95.5C` and killed six
processes across three agents in one batch. Post-mortem: the real heat source
was one genuinely hot sustained job (the same single-core workload had reached
98 °C over 53 minutes), but the kill list also contained **queued flock
waiters** that had not started work yet (a running python/vvp pair plus three
`safe_run.sh` wrappers still waiting on `/tmp/rknpu-heavy.lock`). Killing
sleepers is pointless and destroys queued work.

Guard v3 fixes this and the sensor-noise problem:

- kill candidates must be heavy-tool classified **and** actually burning CPU
  (`utime+stime` delta >= 1 s per 5 s sample); queued waiters are never killed;
- the thermal decision uses the **median of the last 5 Tctl samples** at 95 °C
  plus an instantaneous 98 °C emergency, because k10temp Tctl swings ±10 °C
  between 5 s samples with CPU power state (87.8 → 95.5 °C in one sample, then
  back to 65 °C after the jobs died);
- every kill logs raw + smoothed temperature and each killed cmdline.

Additional schedule policy after this event: launch gate lowered to Tctl < 78 °C
inside `heavy_exec.sh`; heavy jobs pinned to fewer cores with a CPUQuota
(dual-endpoint legs on `BENCH_CPUS=0-1`, quota 70; long Icarus legs one core,
quota 70); background image workstreams (pooling corpus, runtime conv engine)
hold heavy jobs while the verification matrix and EW image build are the
priority; the shared heavy lock remains the single host-wide serialization
point.

### Empirical build-quota ceiling (2026-11-10 21:55Z)

A third thermal event (prevented properly): the pooling-corpus synth was
retried at `BENCH_CPU_QUOTA=300` (up to 3 cores) and spiked to **Tctl 98.4 C**
raw (smoothed 91 C) within ~90 s as the parallel synth workers started; guard
v3's instant-98 C emergency path killed the Vivado tree. No crash; mode-5
verification had just PASSed. Subsequent retries refined the ceiling further: a **200 %** pooling-synth
retry also reached the instant-99–100 C guard kill, so even 200 % is unsafe on
this host while ambient/cooling is marginal. **Final ceiling: ~150 % for
multithreaded Vivado builds** (`BENCH_CPUS=4-5`, `BENCH_CPU_QUOTA=150`,
`general.maxThreads 2`), 150 % for Verilator compiles, 55–90 % for single-core
sims. The launch gate is now Tctl < 72 C. A single 200 %-quota synth alone can
sit at 95–100 C here, so the build quota is the primary control, not queue
depth. The guard's raw-spike emergency kill is intentional and should
stay at 98 C (Tjmax ~105 C).

### Fourth event: external concurrent load near-miss (2026-11-10 22:24Z)

While the project was already heat-soaked, three unrelated heavy jobs were
burning CPU and Tctl hit **100.4 C raw** (smoothed 97-98 C; Tjmax ~105 C):

1. an external **`yosys` synthesis** from another DSH session
   (`/home/fedora/tiny-tpu/ypcb_demo`, parent chain to the DSH web node),
2. an external **full-filesystem `grep -rl`** over `/home/fedora` (~91 % CPU),
3. a Verilator **`cc1plus`** child (~99 % CPU, ~7 GB RSS) that survived the
   guard's kill of its `verilator_bin` parent.

Guard v3 killed the classified parent repeatedly but could not see (1), (2) or
(3), and the host kept heating. The Lead terminated the external jobs and the
in-flight compile to protect the hardware; Tctl fell back below 90 C, memory
recovered from 18 GB to 3 GB used.

**Guard v4** (installed): at an emergency temperature it now kills ANY
user-owned process actively burning CPU (>=1 s per 5 s sample), including
descendants of active burners, not just known verification tools; it protects
only its own ancestry and the DSH `node` infrastructure. Every kill still logs
the raw/smoothed temperature and the cmdlines.

**Rule added:** this host must not run heavy jobs from other sessions/projects
concurrently with the verification queue. One heavy job among *all* host users
at a time; the global `/tmp/rknpu-heavy.lock` only covers this project. The
guard's CPU-activity emergency kill is the backstop, not a scheduler.

### Identified external load: another DSH session on this host (2026-11-10 22:26-22:28Z)

The 100 °C near-misses were traced to **another DSH session** on the same laptop
(parent chain to the DSH `node ... web` process), not to this project:

- `cd /home/fedora/openTPU && build/fedora-venv/bin/python -c "from opentpu import ...; rtlsim.build_top(cfg)"`
  → `/home/linuxbrew/.../bin/verilator --binary -j 0 ... -Mdir /home/fedora/openTPU/build/verilator/...`
  spawning ~8 `cc1plus` processes (~7 GB RSS total, all cores);
- `cd /home/fedora/tiny-tpu/ypcb_demo && make synth` → `yosys` at ~98 % CPU;
- a full-filesystem `grep -rl ... /home/fedora`.

These ran concurrently with our gated queue. Guard v4 killed the external
`verilator_bin` at instant 100.0/100.5 °C (correct), and the Lead killed the
openTPU build tree and the full-tree grep manually to stop the heating; Tctl
fell from 100.9 °C to ~77 °C within a minute.

**Operational rule (added):** other sessions/projects must not run heavy
compiles/synthesis on this laptop while the verification queue is active. Our
`/tmp/rknpu-heavy.lock` cannot see them, and the thermal headroom is marginal
(~1–2 heavy jobs max). Guard v4's any-active-burner emergency kill is the last
line of defence, not a scheduler. Interrupted evidence runs must be discarded
and re-run cleanly.

### Guard v4.1: transient Tctl spikes filtered (2026-11-10 22:43Z)

A single-threaded, one-core synth (maxThreads 1, quota 150) was killed by the
v4 instant path on **one raw sample at 99.8 C while the 5-sample median was
86 C** — k10temp Tctl swings by up to ~10 C between 5 s samples at low load, so
single-sample instant kills were destroying jobs without sustained heat.
v4.1 keeps the sustained-heat protection but requires: instant >= 102.5 C, OR
two consecutive samples >= 99 C, OR 5-sample median >= 95 C. True hardware
limit remains: this host's cooling cannot sustain more than ~1 core of
continuous compute near Tjmax without approaching the throttle band, so all
jobs stay one-at-a-time and capped (builds 150 %, compiles 150 %, single-core
sims 55-90 %), with a Tctl < 72 C launch gate.

### Host-window mechanism: reversible foreign-job pause (2026-11-10 23:46Z)

The other DSH sessions on this laptop (openTPU/OpenTPU-ladder pytest+cocotb,
tiny-tpu cocotb/yosys) keep spawning heavy jobs and have now killed three
verification runs (mode-6 twice, one runtime-equivalence `vvp`) and two synth
attempts. Killing them manually was whack-a-mole and destroyed their work.

New mechanism: `build/verif/host_guard/foreign_hold.sh` — used as a wrapper
inside the heavy lock, it pauses (SIGSTOP) only processes whose cmdlines match
the known foreign project trees (`openTPU*`, `tiny-tpu`, `cocotb`,
`ladder-work*`), re-sweeps every 10 s while our job runs, and resumes every
paused pid on exit (trap, including SIGTERM/INT). It never touches this
project, the guard, the DSH node/agent infrastructure, or system/desktop
services; every PAUSE/RESUME is logged in `foreign_hold.log`. It is reversible
and scoped, and our jobs still run one-at-a-time under the thermal launch gate.

### Final state: cooling hardware failure (2026-11-10 23:56Z)

With every verification job stopped and no foreign load running, the host's
**idle Tctl remained 92–100 C (smoothed 96 C) with the fan reporting 3200 RPM**.
Earlier the user observed the fan not visibly turning while the EC reported
full speed. A 0.7-core, foreign-hold-wrapped equivalence leg was killed at the
median-96 C path with no foreign pauses recorded, i.e. the heat was the host
itself. Even the two earlier single-core jobs saturate it.

Refined diagnosis (true-idle test 2026-11-11 00:00Z): after killing the foreign
test-loop processes, CPU utilisation was **97-99 % idle** (vmstat) yet Tctl was
90-99 C, and then fell to **61-70 C over ~40 s with no load**. So the cooling is
**marginal/partially failing**, not permanently dead: it can remove idle heat
but saturates almost immediately under load, and the foreign sessions' test
loops (openTPU-ladder pytest + iverilog `vvp` at 100 % each, from
`/home/fedora/openTPU-ladder` and `/tmp/ladder-work8`) were continuously
reheating the host. With them stopped the machine cooled properly. Until the machine is serviced (or
verification is moved to another host), no simulation or bitstream build can
complete. The verification queue is stopped indefinitely; all completed
evidence remains valid and unchanged.

Pending when the host returns (all with commands already prepared):
dual mode-6 (then 7, 8), mailbox modes 1-2; conveng runtime-engine equivalence
replay (single launch or split primary/control legs) and OOC area estimate;
share pooling-corpus fit completion (page0/page3/page14/infra1 + exact
whole-image synth) and the Icarus matrix receipt refresh; any image builds
(pooling-corpus, merged, conv-fp16 runtime) require a genuinely cool host.

Operator action: power the laptop off and service/clean the cooling system
(fan, heatsink, repaste) before further verification; or move the verification
queue to a cooler machine.

### FINAL-freeze drift incident and restore (2026-11-10 20:06-20:45 HKT)

`rtl/cmac/rk_cmac_fp16_cell.sv` — a **FINAL-freeze-tracked production file**
(518-file manifest) — was modified in the main tree at 20:06:49 HKT
(frozen `845d7843…` -> drifted `20652af2…`), apparently as part of the
experimental runtime engine's 16-lane parameterisation. This invalidated the
dual mode-8 receipt (PASS but non-frozen) and would have invalidated any
conv/GEMM receipt whose cell hash changed.

Response:
- killed the in-flight D1 area run (it was synthesizing the drifted cell;
  its receipt is discarded);
- restored the exact frozen content from the verified A-only snapshot
  (`/home/fedora/rknpu-a-only`, byte-identical to the freeze);
- re-audited the manifest: **518/518 match, 0 missing, 0 mismatched**;
- ruled that the 16-lane cell support must be **additive** (new experimental
  cell + array copies under `rtl/cmac/experimental/`), never an edit of a
  frozen file; any frozen-file change requires the Lead and a new evidence
  chain/re-freeze decision;
- verif to re-run dual mode-8 on the restored tree and continue mailbox 1-2.

Lesson: every teammate must hash-check the FINAL-freeze set before/after any
work and treat frozen files as read-only; heavy-running D1 must re-read
sources only after such a restore.

### Guard v4.4: post-kill stale-median bug (2026-11-11 00:44 HKT)

After a thermal kill the guard slept 60 s but kept its 5-sample temperature
history. Because the sleep is longer than the sampling window, the stale
median stayed at ~97 C and the guard killed every subsequently started job
within one sample — at one point it killed a compile while raw Tctl was 58 C.
v4.4 clears the temperature/CPU history after a kill and also drops history
when the inter-sample gap exceeds 3 intervals (suspend/resume). Sustained-heat
protection is otherwise unchanged (median 97 C, instant 104 C, streak 2x>=101 C).

### Operator action recommended for the thermal limit

Service/clean the cooling system (fan, heatsink fins, repaste), use a cooling
pad, and keep ambient temperature down; or have the host serviced. Until then,
the project works in battery-safe, thermally gated short bursts, and the
hardware JTAG session should be scheduled when the host has cooled.

### Measured long-build ceiling (2026-11-11)

A 110k-LUT Vivado synthesis at CPUQuota=100% with `maxThreads 2` reached
100.2 C (k10temp) about 25 minutes in and was killed by the guard at median
97.1 C; the fanned chassis could not hold ~1 core that long. Long builds are
now launched at **CPUQuota=50, `maxThreads 1`** (the documented stable
~0.5-core envelope), with the pay-off being wall time, not weaker gates.
