# Full512 capacity physical evidence archive

This archive preserves the source/text evidence for the exact retirement-capacity image and physical results. The accepted root review is `PASS_ROOT_PHYSICAL_FULL512_TWO_GIB_CAPACITY_AND_RECONFIGURED_RAW_JOBS` for bitstream SHA-256 `de982cd7e6c41d13de8e1f047c92fd515ab590e6958339a1dd37135642bef2a4` (source tag `2c8f17dd`). The index binds the exact171 selected hardware sources, six full scan traces, all60 report-listed physical artifacts, original CMAC K65/EW SUB9 upload/golden fixtures, route review, image-prep-v2 source/emission proof, and the raw-auditor 16-control source review.

Physical scope: two full 2 GiB capacity trials (33,554,432 64-byte lines each), with 67,108,864 writes and 67,108,864 reads; 245,760 complete normal BO bytes were checked before ACK across 4 jobs/6 tasks. The test used two deliberate volatile loads. The BIST compares internally; it does not dump the full DDR contents to USER2.

The archive does not claim physical ECC injection/recovery, PCIe, flash programming, live joint-reset testing, full TinyStories on this image, or RK numerical equivalence. The raw-auditor fix is an additional software control/re-audit record and does not replace or relabel the six original physical traces. Its strict replay refers to a prep-v1 CMAC trace; that older trace is hash-only excluded and is not presented as a current prep-v2 physical trace. `.bit`, `.dcp`, native tools, compiled objects and bytecode are excluded and hash-identified in `index.json`.

Payloads over 16 KiB use deterministic gzip level 9 with mtime zero; the index records each actual stored path, source hash/size and stored hash/size. No `SHA256SUMS` sidecar is included; `index.json` is the payload inventory.
