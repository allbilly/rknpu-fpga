# RK EW capture handoff package

This archive contains the reviewed 18-case compiler/input preparation and the source-reviewed passive RK capture runner, observer, and 13 device-free tests. It preserves the original `build/rk-ew-silicon-case-prep-v1` and `build/rk-ew-silicon-runner-prep-v1` relative paths so the runner can use the prepared case tree after relocation.

The 18 cases cover ADD, SUB, and MUL at logical counts 7, 8, 9, 31, 32, and 33, with finite and special input sets. There are 126 prepared files; each argument image initializes the complete 4096-byte mapping. `program.bin` files are pinned compiler IR, not final device-address command streams. The package contains no RK outputs and does not establish arithmetic correctness on silicon.

## Verify without extracting

Run `python3 verify.py`. The verifier checks the archive hash, safe unique regular-file member paths, every member size/hash, and the expected file census. It never extracts files, imports tinygrad/backend code, unpickles artifacts, or accesses a device.

## Relocated source preflight

After manually extracting the archive into `DEST`, the offline source preflight can be run against the pinned backend checkout (commit `078eee94d8f1912bb63ce786c250d2c24984844a`):

```sh
python3 DEST/build/rk-ew-silicon-runner-prep-v1/run_capture.py \
  --backend /path/to/pinned/tinygrad \
  --cases DEST/build/rk-ew-silicon-case-prep-v1 \
  --case add_8 --input-set finite \
  --out /tmp/rk-ew-capture-preflight-add8-finite
```

This omits `--run`; it performs source/input validation only and creates a preflight receipt. Real capture uses an explicit `--run` and an audited `--device`; no hardware mode was run during this preparation.
