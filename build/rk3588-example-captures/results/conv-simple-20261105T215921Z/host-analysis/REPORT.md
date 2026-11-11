# conv-simple RK3588 Rocket capture — 20261105T215921Z

## Identity and paths

- Board: `orangepi5`, Linux `6.18.24-current-rockchip64` #2 SMP PREEMPT
  (Wed Apr 22 11:22:34 UTC 2026), aarch64, Python 3.14.4.
- Device: `/dev/accel/accel0`, char `261,0`, `root:render`, driver modalias
  `platform:rknn`, compatible `xunlong,orangepi-5`, `rockchip,rk3588s`.
- Runner: `build/rk3588-example-captures/runner/rocket_run.py`,
  sha256 `a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd`
  (the `runner/pinned/` directory was empty; the fallback hash equals the
  required pin and was re-hashed identically on the board).
- Board tools: `/home/opencode-agent/rk3588-example-captures/tools/20261105T215921Z/`
- Board queue: `/home/opencode-agent/rk3588-example-captures/queue-20261105T215921Z/conv-simple/`
  (only the 7 READY cases; 5 BLOCKED cases were not staged).
- Board run: `/home/opencode-agent/rk3588-example-captures/runs/20261105T215921Z/conv-simple/`
- Host copy: `build/rk3588-example-captures/results/conv-simple-20261105T215921Z/`

## Preflight

- `conv-simple/validate.py`: PASS, 7 READY / 5 BLOCKED.
- `runner/validate_bundle.py` run per READY case: all 7 OK.
- No other capture/submit process before or after the run (only
  `supervisord` Python was present). The board lock file
  `/home/opencode-agent/rk3588-npu.lock` was used.

## Locked invocation

```
flock -x -w 900 /home/opencode-agent/rk3588-npu.lock \
  python3 .../tools/20261105T215921Z/rocket_run.py \
    --device /dev/accel/accel0 \
    --out .../runs/20261105T215921Z/conv-simple \
    .../queue-20261105T215921Z/conv-simple
```

One runner process, strictly sequential, no retries, no reset. Lock held
`2026-11-05T22:00:34Z` → `2026-11-05T22:00:35Z`; runner exit 0.

## Per-case results

| case | submit_ret | output BO | expected | comparison | exact-byte result |
| --- | --- | --- | --- | --- | --- |
| conv_simple_fp16_1x1_c4_h8_w8_oc16 | 0 | 4096 | 4096 | exact full | 0/4096 differ |
| conv_simple_fp16_3x3_c4_h8_w8_oc16 | 0 | 1152 | 1152 | exact full | 0/1152 differ |
| conv_simple_fp16_5x5_c4_h8_w8_oc16 | 0 | 512 | 512 | exact full | 0/512 differ |
| conv_simple_fp16_1x1_c32_h8_w8_oc32 | 0 | 8192 | 8192 | exact full | 5941/8192 differ |
| conv_simple_fp16_3x3_c16_h8_w8_oc32 | 0 | 2304 | 2304 | exact full | 0/2304 differ |
| simple_conv_int8_5x5_c8_h8_w8_oc32 | 0 | 1024 | 512 prefix | prefix | 7/512 differ, all +1 LSB |
| simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64 | 0 | 4608 | 2304 prefix | prefix | 13/2304 differ, all +1 LSB |

All 7 captures had `status: OK`, `submit_ret: 0`, empty `errors` and
`cleanup_errors`, and declared output size equal to the complete readback size.
Total output BO bytes read: **21888**.

### FP16 exact matches

Four cases are byte-identical to `expected.bin`:

- `conv_simple_fp16_1x1_c4_h8_w8_oc16` — 4096 B, sha256
  `c589ac10efaf190daa14dbe11c70db04b94b355d933ab1c035037a689433c6eb`
- `conv_simple_fp16_3x3_c4_h8_w8_oc16` — 1152 B, sha256
  `1f002aea6e9431152a316265fe8a36462c0172bea5c54e65f27f3783b2c610b9`
- `conv_simple_fp16_5x5_c4_h8_w8_oc16` — 512 B, sha256
  `1431b3f51a330880189417a1ec7b352203adcf737eace81819b8d1f00d96b986`
- `conv_simple_fp16_3x3_c16_h8_w8_oc32` — 2304 B, sha256
  `8cc5cddb7755ad67fcbc913e50195a10be97fabf2bf40b1b4c4c1b401b036441`

### FP32-output 1×1 C32 mismatch

`conv_simple_fp16_1x1_c32_h8_w8_oc32` used the declared FP32-output policy
(4 B/element) and the full 8192-byte BO was read. It is **not** an exact match:

- bytes 0..2047 (first 512 float32) are exact; first difference at byte 2048
  (element 512): expected `3.248020648956299` (`404fdf92`, LE `92df4f40`),
  actual `-3.9733774662017822` (`c07e4bd1`, LE `d14b7ec0`).
- 1024-byte chunk mapping (actual <- expected): 0<-0, 1<-1, 2<-4, 3<-5,
  4<-6, 5<-7, 6<-zero-fill, 7<-zero-fill. Expected chunks 2 and 3
  (bytes 2048..4095) are absent.
- byte 4096 (element 1024): expected `-3.9733774662017822`, actual
  `6.11406135559082`; byte 6144 (element 1536): expected `6.11406135559082`,
  actual `0.0`.
- 5941/8192 bytes differ, 1536/2048 float elements differ, max abs diff
  `32.64073085784912`, exceeding the manifest atol 0.1. This is a structural
  placement/zero-fill mismatch, not numerical rounding. The manifest already
  records that mainline-Rocket execution of this FP32-output stream is not
  separately evidenced by the source.

### INT8 prefix comparisons

Both INT8 BOs are larger than `expected.bin`; only the first
`len(expected.bin)` bytes are compared, and the remainder is reported
separately. All tails are entirely zero.

- `simple_conv_int8_5x5_c8_h8_w8_oc32`: 512/512 prefix bytes compared,
  7 mismatches, every one actual = expected + 1:
  `117 0x31->0x32`, `144 0x47->0x48`, `388 0x44->0x45`,
  `408 0x40->0x41`, `434 0x37->0x38`, `478 0x2d->0x2e`,
  `510 0x2c->0x2d`. Tail: 512 bytes, all zero.
- `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64`: 2304/2304 prefix bytes
  compared, 13 mismatches, every one actual = expected + 1:
  `423 0xd3->0xd4`, `438 0xca->0xcb`, `460 0xd2->0xd3`,
  `518 0xbe->0xbf`, `630 0xb8->0xb9`, `646 0xcd->0xce`,
  `740 0xe2->0xe3`, `1154 0xcf->0xd0`, `1182 0xcf->0xd0`,
  `1392 0xca->0xcb`, `1496 0xb7->0xb8`, `1561 0x11->0x12`,
  `1949 0xc4->0xc5`. Tail: 2304 bytes, all zero.

## Hash verification

- Staged runner and all 37 staged case files matched host sha256 values.
- Board-side and host-side sha256 for every `capture.json` and every `out.bin`
  (14 files) match exactly.
- Each `capture.json` output sha256 equals the corresponding `out.bin`, and
  each recorded job/regcmd/input hash equals the manifest and staged files.

## Scope

This was a mainline Rocket NPU capture only. No FPGA programming, flashing,
bitstream, vendor RKNPU path, or FPGA execution is claimed. Other families and
the 5 BLOCKED conv-simple cases were untouched.
