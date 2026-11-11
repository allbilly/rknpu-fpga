# Analysis notes and offline probe sources

This directory preserves working analysis that used to live only under
`/tmp/opencode/`. Nothing here is device evidence or a qualification record;
the authoritative contracts remain the `docs/*.md` files they support.

## Documents

| File | What it is |
|---|---|
| `conv_support_matrix.md` | Generated matrix of the captured convolution corpus: per family READY/BLOCKED counts, geometry, QWORD counts and whether a pinned fixture exists. Regenerate logic is described in the header. |
| `conv_support_matrix_detail.md` | Companion detail pass: BLOCKED reasons with source evidence, per-case packed input/weight/output layouts, and which parameter tuples the 3×3 front needs. |
| `nvdla_param_notes.md` | Survey of `/home/fedora/hw` (nvdla/hw) atom/bank/stride parameterization and how it maps to our `ATOMIC_C=32`, `ATOMIC_K=16`, `PACK_C2=8`, `ALIGN_C=16` naming. Marks unverified items explicitly. |
| `k8_changed_table.md` | The K8 core-parameter change table from the C32/K8 increment. |
| `conv-simple-analysis.json` | Per-case divergence analysis for the `conv-simple` family captures. |
| `conv-first-case-layout-check.json` | Layout audit for the first 1×1 C8 capture case. |

These documents deliberately cite repository paths and NVDLA
`file:line` references rather than `/tmp` locations, so they stay useful after
the temporary workspace is cleaned.

## Probe sources

`tools/analysis/` holds the standalone RK3588 probe and comparison scripts that
were developed alongside the notes:

- `analyze_conv_simple.py`, `compare_pooling.py` — capture-vs-oracle comparisons.
- `rk3588_rocket_add.py`, `rk3588_rocket_fdiv.py`,
  `rk3588_rocket_max_special.py`, `rk3588_rocket_special_matrix.py`,
  `rk3588_rocket_infinity_matrix.py`, `rk3588_fdiv_matrices.py` — read-only
  Rocket probes used for the EW differential work.

They are diagnostic tools that may submit work to an explicitly authorized
RK3588 target; they are not part of the FPGA execution path and must not be
used as a CPU fallback for accelerator results.
