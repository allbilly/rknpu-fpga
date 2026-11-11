# RK3588 example capture queue format

This directory collects **device-free preparation** for real RK3588 Rocket
captures. Preparation agents must not access the Orange Pi. A single later
worker owns the board and runs the queue under one exclusive lock.

## Rules

- Do not edit tracked source, tests or docs; write only under
  `build/rk3588-example-captures/<family>/`.
- Do not run `ssh`, `scp` or any command against `192.168.192.18`.
- Do not program or flash the FPGA.
- Record blockers explicitly; never fabricate an output or substitute a CPU
  oracle for a device capture.
- Keep each case self-contained and deterministic.

## Layout

```
build/rk3588-example-captures/
  <family>/
    manifest.json
    README.md
    cases/
      <case>/
        job.json
        regcmd.bin
        <input>.bin
```

`manifest.json` lists every case with `status` (`READY` or `BLOCKED`), the
source example path and line references, a short description, and the oracle
used to check the expected output. Blocked cases need a concrete reason.

## job.json

```json
{
  "case": "conv_simple_c8_h8_w8_oc8_k3",
  "source_example": "/home/fedora/rk3588/examples/conv_simple.py",
  "description": "FP16 3x3 valid conv, C8/H8/W8 -> OC8",
  "timeout_ns": 6000000000,
  "tasks": [
    {"regcmd_offset_words": 0, "regcmd_words": 22}
  ],
  "buffers": [
    {"name": "a", "size": 4096, "input": "a.bin", "direction": "in"},
    {"name": "b", "size": 4096, "input": "b.bin", "direction": "in"},
    {"name": "out", "size": 4096, "direction": "out", "output": "out.bin"}
  ],
  "patches": [
    {"regcmd_index": 14, "buffer": "out", "kind": "value32"}
  ]
}
```

- `regcmd.bin` is the concatenation of little-endian 64-bit command QWORDs.
- `tasks` become Rocket task descriptors pointing at
  `regcmd_addr + 8 * regcmd_offset_words`, with `regcmd_words` each.

### Rocket job boundary

The mainline Rocket v6.18 path used here does not reliably execute a second
task in one job. A two-task control returned `submit_ret=0` but left task 1's
output BO all zero; the same task 1 command stream submitted alone matched
exactly. Therefore each RK submission must be its own one-task job/case in a
capture bundle. Do not encode multiple sequential RK submissions in one
`tasks` array for this board path.

### Rocket fetch parity padding

Rocket fetches PC commands in QWORD pairs. When the declared task extent is
odd, exactly one zero QWORD may be appended as fetch-only padding. The task
descriptors keep the original declared count; the padding is never executed.
A case using this must record `regcmd_padding_words` (1) and
`regcmd_file_words` (declared + 1) in `job.json`/`manifest.json`. Validators
accept only that documented zero QWORD and reject any other trailing words.
- `buffers[].input` files are copied into a freshly allocated Rocket BO of
  `size` bytes at offset zero.
- `buffers[].direction` is `in`, `out`, or `inout`. Every buffer is passed to
  the Rocket job; `out`/`inout` buffers are read back after completion.
- `patches[].kind`:
  - `value32`: replace command bits `[47:16]` with the buffer's 32-bit DMA
    address. This matches the RK register value layout.
  - `all32`: replace command bits `[31:0]`.
  - `low32`: replace only the low 32 bits of the QWORD.
  - `high32`: replace only the high 32 bits of the QWORD.
- `patches[].regcmd_index` is the QWORD index in `regcmd.bin`.
- `output` is the relative filename the worker writes after the job.
- The worker records actual addresses, `submit_ret`, durations, hashes and the
  board/tool identity in `capture.json`.

## Deriving a case

The source examples allocate BOs, fill inputs, build command QWORDs with real
DMA addresses, submit, and read outputs. Preparation must separate that into:

1. the command QWORD stream with placeholder address fields;
2. deterministic input byte files;
3. the patch list mapping placeholders to named buffers; and
4. the expected output (oracle) for later comparison.

Host-side NumPy is allowed for preparing inputs and the oracle. The board-side
worker has no NumPy, so all generated bundle files must be raw bytes.

## Expected output

Do not put a CPU result into `output`. The worker reads the real device output.
The oracle belongs in `manifest.json` or a separate `expected.bin` with a
clearly labelled source (e.g. donor CPU function, SciPy, or an explicit
formula). If no trustworthy oracle exists, mark the case `READY` but
`oracle: none`; the raw BO is still useful.

## Board execution

The later worker runs one case at a time under
`flock -x /home/opencode-agent/rk3588-npu.lock`. No preparation agent may
assume it can submit. If a case needs several linked jobs, express the exact
ordering in `manifest.json` and keep the case directory self-contained.
