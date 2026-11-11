# BLOCKED: conv_depthwise_3x3_c3_oc3_h11w28

Reason code: `MULTITASK_ROCKET_JOB_UNSUPPORTED`

The source intentionally submits the same depthwise task twice. This original case encoded both submissions as two tasks in one Rocket job. The Rocket board path executes only the first task of a two-task job; the second task alone passes exactly. The runnable split cases are `conv_depthwise_3x3_c3_oc3_h11w28_task0` and `conv_depthwise_3x3_c3_oc3_h11w28_task1`, each with one 52-QWORD stream at offset 0.

## Preserved evidence

- `evidence/job.json`: original two-task job (`[0,52)` and `[52,104)`).
- `evidence/regcmd.bin`: original 104-QWORD stream; the two 52-QWORD halves are byte-identical.
- `evidence/input.bin`, `evidence/weight.bin`, `evidence/expected.bin`: original inputs and expected output.
- Source: `/home/fedora/rk3588/examples/conv_legacy.py` lines 861, 456-593, 648-828, 436-443.
