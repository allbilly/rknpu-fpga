# Current factored-image TinyStories evidence

This archive preserves the accepted full32 TinyStories-260K run on source tag
`60e7abbb`, bitstream SHA256 `1ca5ae19a0d95a13899a2e13fd3664668d26643cd2ae733f8f5936f6b380523a`.
The complete 32-position phase executes 1,152 learned projections on FPGA,
matches 16,384 logits and 28 generated token IDs, and checks 30,408,704 output
BO bytes before ACK through 2,984,893 actual JTAG scans. First/repeated BOS
controls are also included. CPU embedding, normalization, RoPE, attention,
SwiGLU, residual, KV and sampling remain explicit host operations.

The archive contains 1,357 source/evidence payloads totaling 1,086,699,649
uncompressed bytes, including all three actual scan traces, original reports,
fresh independent phase replays, model preparation, oracle and source closure.
Native executables/libraries, bitstreams, checkpoints and installed tools are
27 hash-only exclusions. Original paths inside receipts describe the producing
workspace; the archive does not install those paths or provide a ready image.
Licenses and original source notices are retained with their source payloads.

Run from any checkout, using Python 3.11 or newer:

```sh
python3 verification/runs/2026-10-30-framework-factored-full32-fpga/verify_archive.py
```

The verifier reads adjacent files, checks the compressed archive identity,
streams every selected payload and checks the saved acceptance/image identity.
It never extracts files, imports archived code, executes inference or touches
hardware. This is portable evidence integrity, not a fresh numerical or raw-wire
audit. Replaying those audits requires the archived sources, their recorded
dependencies and a deliberate path mapping; rebuilding/programming an image
requires separate source, tool, timing, target and hardware review.

The [index](index.json) records scope and hashes. The independent byte review
is [preserved separately](independent-byte-review.json). Full capacity, physical
ECC/warm recovery, PCIe, cold boot and RK equivalence are not qualified by this
run. Flash was unchanged. Staging and archive verification add no hardware claim.
