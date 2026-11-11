# Public factored full512 framework source profile

This explicit 81-file order selects the full512 FP16 C32/K16 framework derived
from the readiness-factor parent, with separate capture-bounded C3, valid-C8,
padded-C8, minimum-C8, average-C8 and MAX-with-index PPU profiles enabled.
The original profile had 68 source slots; this candidate substitutes the PPU
dispatch in the existing dispatch slot and appends six strict gates, six
pooling leaves and their shared DMA. The initial publication introduced nine source copies in this directory
and reused 59 existing public paths. `sources.json` carries the ordered paths
and SHA-256 values.

Use `python3 tools/ddr/framework_factored_profile.py --check` to validate the
manifest and every source file. Compile the returned ordered path list. Do not
combine this list with historical framework alternatives by recursively
globbing `rtl/ddr`: several old and selected files define the same module names,
so the manifest explicitly chooses the selected implementation.

The initial source bytes and order matched the accepted private P50 selection.
Its publication crosswalk is
`build/framework-factored-publication-prep-v1/publication-proof.json`. This is
a byte/order publication record, not a new compile, simulation or hardware
qualification. The physical acceptance covers the selected six ordinary
FP16 layouts/CMAC/reset cases on one volatile image; broader RK, PCIe, full
capacity, ECC injection and full-model claims remain separate.

The current layout metadata-enable correction changes `rk_layout_dma.sv` while
preserving the profile order and architecture. Its
[paired native](../../../build/layout-metadata-enable-native-results-review-v2/review.json)
and [mapping](../../../build/layout-metadata-enable-mapped-results-review-v2/review.json)
checks pass; the [current 82-source integration](../dual_host_maintenance_fi/README.md)
has a fresh warm replay. Historical FPGA receipts qualify their exact source
snapshots and image tags; they do not establish a new physical result for this
changed 81-source selection. The C3/C8/padded-C8/minimum/average/indexed PPU addition remains simulation-only and is
not qualified by those earlier physical receipts.
