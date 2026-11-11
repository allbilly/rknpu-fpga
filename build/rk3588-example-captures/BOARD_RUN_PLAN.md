# Board queue execution plan

The board must have exactly one capture owner. Preparation agents never access
it. When all family manifests validate, run this plan once.

## Preconditions

- Every `READY` bundle passes `runner/validate_bundle.py`.
- The queue is copied to one fresh board directory:
  `/home/opencode-agent/rk3588-example-captures/queue-<utc>/`.
- Record board identity before any submit: hostname, kernel, Python version,
  `ls -l /dev/accel/accel0`, and any existing capture process.
- No other capture/submit process may be running. If one exists, stop and
  report rather than racing it.

## Mandatory serialization

Every execution step runs under one advisory lock:

```
flock -x -w 900 /home/opencode-agent/rk3588-npu.lock \
  python3 rocket_run.py --queue <case-root> --out <output-root>
```

`rocket_run.py` processes cases sequentially. Do not launch parallel copies.
Do not reset or reprogram the device between cases. A case failure is recorded
and the worker moves to the next case; it never fabricates output.

## Per-case acceptance

- `submit_ret == 0`;
- every declared output file exists with the declared size;
- `capture.json` records the real BO addresses, hashes, duration and errors;
- the output is stored unchanged; any oracle comparison is separate and
  labelled.

## Post-run

- Copy the entire output tree back to
  `build/rk3588-example-captures/results/<utc>/`.
- Re-hash every `capture.json` and output file on both sides.
- Summarize READY/PASS/FAIL/BLOCKED counts by family.
- Do not commit device outputs to tracked source; keep them under `build/`.
- Program/flash the FPGA only under a separate explicit request and audited
  target. NPU capture does not authorize that.
