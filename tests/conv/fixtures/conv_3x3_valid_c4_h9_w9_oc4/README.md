# Frozen capture fixture: `conv_3x3_valid_c4_h9_w9_oc4`

Source: one successful 54-QWORD FP16 valid 3×3 task from the
`conv-fp16-20261105T222300Z` Rocket run, captured on Orange Pi 5 / RK3588S,
kernel `6.18.24-current-rockchip64`, `/dev/accel/accel0`. The case contract and
hashes are pinned in `manifest.json`; the capture, donor job, and provenance
records are retained alongside the packed operands.

`regcmd.bin` is the donor template with zero address placeholders. Replaying
the job's declared value32 relocations at QWORDs 21, 27 and 35 to `0x1000`,
`0x2000` and `0x3000` reproduces the captured command stream hash. No command
body or task tail is synthesized by the RTL runner.

`a.bin` and `w.bin` are the donor-packed BO contents; `source_input_nchw.bin`
and `source_weight_nchw.bin` bind the pack-layout checks. `expected.bin` is the
source FP64 accumulation/FP16 output oracle. `device_out.bin` is the complete
3,328-byte device BO. Only the 196 logical C0–C3 values are a numerical oracle;
the device's padded channels and BO tail are retained as capture evidence, not
as stable results.
