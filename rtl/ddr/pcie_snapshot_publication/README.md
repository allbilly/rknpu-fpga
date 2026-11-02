# Snapshot publication RTL source candidate

This is a reviewable source candidate for the 201 selected records in `build/snapshot-scope-cofactor-full-synth-v1/source-manifest.json` (SHA-256 `68cea9679fcb1140e5c1db61027993c0f335fee11386db91921cd4d5a27e322d`). It is not the default design source set. No `files.f`, Makefile, or RTL default selection was changed.

`source-index.json` preserves all 201 manifest records in order and is pinned by the preparer to SHA-256 `68463e168f10524f543bf0a823e49239a410b2f1d67358be0d15e4d5b9bfcc6b`. A changed index is rejected even if it retains the selected full-manifest SHA field. For 177 records, `repository_path` points to an existing tracked file byte-identical to the selected source (the inventory preferred `rtl/` and then shortest path). The 23 new public copies are the 22 HDL files and one header listed in the index. The unchanged 9,075,034-byte XDMA component checkpoint remains external and is bound to its required SHA-256; it is not copied into this candidate. Each record's `relative_path` is the layout expected by the portable resource-census recipe after rendering.

The copied `synth.tcl` is byte-identical to the separately prepared portable resource-census recipe (SHA-256 `51a0dd1cdac2a71323e0ed37edc592dc9b7fc2553670e8889d1927681b8c713d`). It expects a rendered `sources/hdl`, `sources/headers`, `sources/xdc`, and `components/xdma_ooc.dcp` tree; this candidate is not directly runnable as-is. Vivado has not been run from this public source profile.

## Prepare a source tree

From the repository root, validate the indexed sources and supplied unchanged
component without writing an output tree:

```sh
python3 tools/prepare_pcie_snapshot_publication.py \
  --xdma-component /path/to/xdma_ooc.dcp
```

Add `--out /path/to/fresh-source-tree` to copy all 201 exact inputs and the
relocated resource-census recipe. The output directory must not exist. The
command records input hashes before and after copying and runs no model,
Vivado, image-generation or hardware command. An optional `--source-index PATH`
may point to another copy, but only the exact pinned index SHA is accepted; a
changed index is rejected before output creation. The receipt records its path
and hash. Validate the resulting tree
from any directory with `python3 /path/to/fresh-source-tree/validate_bundle.py`.
The standalone validator checks consistency against its manifest; retain the
repository source index and preparation receipt to identify the selected source.

## Evidence scope

The source manifest's current synthesis review is resource-census-only. The warm model replay and strict stage are separately reviewed within their stated scopes. The controller replay now passes all twelve original model cases. Placement passes structural review but its unrouted setup/hold estimates fail; the guarded route completed all 450,895 routable nets and passed hold, but setup failed at −1.208 ns. Its cleanup/protection checks pass; it has no accepted routed-timing result. The full public default regression also passes, and those default targets remain separate from this candidate full-system profile. This candidate does not establish timing closure, electrical signoff, routed-image validity, FPGA qualification, or hardware execution.
