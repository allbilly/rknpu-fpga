# Public factored full512 framework source profile

This explicit 68-file order publishes the byte-qualified full512 FP16 C32/K16
framework used by the accepted readiness-factor parent and six-case USER2
physical run. The publication introduces nine qualified source copies under
this new directory; the other 59 files reuse their existing public paths and
bytes. `sources.json` carries the ordered paths and SHA-256 values.

Use `python3 tools/ddr/framework_factored_profile.py --check` to validate the
manifest and every source file. Compile the returned ordered path list. Do not
combine this list with historical framework alternatives by recursively
globbing `rtl/ddr`: several old and selected files define the same module names,
so the manifest explicitly chooses the selected implementation.

The source bytes and order match the accepted private P50 source order. The
publication crosswalk is
`build/framework-factored-publication-prep-v1/publication-proof.json`. This is
a byte/order publication record, not a new compile, simulation or hardware
qualification. The physical acceptance covers the selected six ordinary
FP16 layouts/CMAC/reset cases on one volatile image; broader RK, PCIe, full
capacity, ECC injection and full-model claims remain separate.
