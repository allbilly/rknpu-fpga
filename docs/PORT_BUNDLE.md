# rknpu-fpga port bundle

Everything needed to keep working on a better-cooled machine.

**Updated 2026-11-12: the port now travels as a git commit, not an archive.**
Commit `39c6957` on `main` (31 commits ahead of `origin/main`, **not yet pushed**)
carries the whole source tree, the frozen capture corpus and the emitted Image-A
bitstream - 2,152+ files, 32.6 MB. See `handoff.md` §16 for current state. The old 17 MB zip/tar.gz were deleted because
they were a redundant copy and were already stale the moment the tree moved on.

## What is in here — and why the original folder is 205 GB

The working tree is 205 GB, but **197 GB of that is disposable build output**:

| Path | Size | Needed on the new machine? |
|---|---:|---|
| `build/` | 197 G | **No** — regenerable (`.dcp` 40 G, `.vvp` 15 G, `.o` 2.2 G, `.a` 1.8 G, `packed.json`/`yosys_flat.json` dumps) |
| `.Xil/` | 2.6 G | **No** — Vivado's own scratch cache |
| `verification/` | 4.7 G | **No** — old run tarballs |
| `.git/` | 326 M | Optional — only if you want branch history |
| `a.out` | 78 M | **No** — stray binary |
| `rtl/ fpga/ tools/ tests/ model/ docs/` | **39 M** | **Yes** — the actual source of truth |

So the port bundle keeps the 39 M of sources, the 13 M of frozen capture corpus,
the 18 M Image-A bitstream, and every text receipt — and drops 197 G of
regenerable junk.

## Contents

* **All sources**: `rtl/`, `fpga/` (tops + XDC + source manifests), `tools/`
  (generators, renderers, replay runners), `tests/`, `model/`, `docs/`,
  `taproot`/`README.md`/`SHA256SUMS`/`Makefile`.
* **`build/rk3588-example-captures/`** — the frozen capture corpus. Every replay
  runner reads this; without it nothing is reproducible.
* **`build/merged-image/image-a-emit-20261111T041526Z/host-merged.bit`** — the
  18,735,212-byte Image A bitstream,
  SHA-256 `5b03e7388ea0d0a95462dcd7d9279277c6264085d8a801f484ea928a12ac2bfb`,
  USR_ACCESS `396e6429`, timing-clean (sys_clk WNS **+1.525 ns**, 0 failing
  endpoints), **never programmed**.
* **Receipts** (`build/verif/`, `build/merged-image/*.md`, `build/runtime-conv-lab/`,
  `build/ppu-pooling/`, `build/pooling-image/`) — every `*.md`, `*.json`, `*.csv`
  evidence file, including
  `build/verif/freeze-exceptions/FREEZE_EXCEPTION_001_global_avg_leaf.md`.

Deliberately **excluded**: `*.dcp`, `*.bit` (except Image A), `*.vvp`, `*.o`,
`*.a`, `*.so`, `*.bba`, `*.bin`, `packed.json`, `pack_input.json`,
`literal_flat.json`, `yosys_flat.json`, `__pycache__`, `*.pyc`, `.git`,
`.Xil`, `verification/`, `a.out`.

## Getting back to work on the new machine

```sh
cd ~ && mkdir -p rknpu-fpga && cd rknpu-fpga
unzip ~/rknpu-port.zip          # or: tar -xf rknpu-port.tar.gz

# 1. toolchain: Vivado 2026.1 (xc7k480tffg1156-2), Icarus Verilog, Verilator,
#    python3. Reference install on the old box: /home/fedora/vivado/2026.1
# 2. sanity-check the tree
python3 tools/merged/vivado_merged_image.py --profile image-a check
python3 -m unittest discover -s tests/merged        # expect 79/79
python3 -m unittest discover -s tests/ppu_pooling   # expect 129/129
```

Nothing in `tools/` hardcodes `/home/fedora/rknpu-fpga` in code — paths are
derived from `Path(__file__).resolve()`, so the tree relocates cleanly. Only
`__pycache__` blobs referenced the old absolute path, and those are excluded.

## What still needs doing (state at hand-off)

* **Image A** — built, timing-clean, bitstream emitted. Ready to load. **Still
  blocked on the DLC10 cable + explicit volatile-load authorisation.**
  `lsusb -d 03fd:` was empty on the old host.
* **Image B** — all six pages attached (pooling band, EW page, six-bank EW
  aperture, ew-int page + aperture), DRC clean, merged suite 79/79 — but it
  **failed timing** at sys_clk WNS −92.008 ns on the pooling leaf adder tree.
  That leaf has now been fixed (freeze exception #1): the combinational
  `/15`, `%15` and variable-divisor 64-bit divide were replaced by an
  algebraically identical serialised form. It needs an **Image-B rebuild** to
  confirm the Design Timing Summary is clean before any bitstream.
* Read `handoff.md` §15 first — it is the authoritative state summary.
  Then `progress.md` and `build/merged-image/IMAGE_B_TIMING_FAILURE_20261111.md`.

## Rebuilding from scratch (takes the 197 G back)

```sh
python3 tools/merged/vivado_merged_image.py render --profile image-a --out build/ours
# export RK_MERGED_SOURCE_SHA from the rendered inputs.json, then:
RK_CONFIRM_BOARD=YPCB_00338_1P1 RK_CONFIG_VOLTAGE=1.8 RK_CFGBVS=GND \
  python3 tools/merged/vivado_merged_image.py synth --execute --profile image-a \
  --out build/ours
```

A single Image-A build is ~2 h and peaks near 100 °C Tctl on the old
heat-throttled laptop — which is precisely why porting to better cooling is
worth doing.

## How to move it

```sh
# on the old machine
cd ~/rknpu-fpga && git push origin main        # or scp the repo, see below

# on the new machine
git clone https://github.com/allbilly/rknpu-fpga
# the corpus and the Image-A bitstream come with the clone (they are tracked)
```

If you would rather not push to GitHub yet, copy the repository directly - a
clone of this repo is ~360 MB including the 30 local commits, and the tracked
tree is only 60 MB:

```sh
cd ~/rknpu-fpga && git bundle create ~/rknpu.bundle main
# on the new machine: git clone ~/rknpu.bundle rknpu-fpga
```

## What is NOT in git (and why)

`build/` is 197 GB of regenerable output - Vivado `.dcp` checkpoints (40 GB),
Icarus `.vvp` binaries (15 GB), object files (4 GB), and multi-GB
`packed.json`/`yosys_flat.json` dumps. None of it is needed on the new machine;
it all reappears when you rebuild. `.Xil/` (2.6 GB Vivado scratch) and
`verification/` (4.7 GB of historical evidence tarballs) are excluded too.

The only `build/` content that IS tracked:

* `build/rk3588-example-captures/` - 803 frozen capture fixtures. Every replay
  runner reads this path and **102 tools hardcode it**, so it cannot move.
* `build/merged-image/image-a-emit-*/host-merged.bit` - the deliverable (18 MB).
  The repo already tracks emitted bitstreams, so this follows existing convention.
