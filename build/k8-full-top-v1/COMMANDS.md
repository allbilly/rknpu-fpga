# C32/K8 full-top profile commands

All commands run from the worktree root unless noted. The profile is build-local
and does not change any tracked K16 default. No command here places/routes,
emits a bitstream, opens the board or programs anything.

## Source profile

```sh
python3 build/k8-full-top-v1/make_profile.py
python3 build/k8-full-top-v1/check_profile.py
```

`make_profile.py` rewrites `source-manifest.json` and `source-profile.json` from
the accepted 185-file snapshot plus the tracked K8/timing bytes and the three
build-local top/platform/endpoint patches. `check_profile.py` verifies all 185
hashes, the 14-file delta, the tracked K16 defaults and the synthesis source
list.

## Static and profile checks

```sh
make generated-check
python3 - <<'PY'
from tools.ddr.framework_profile import source_paths
print('framework', len(source_paths()))
from tools.ddr.dual_host_profile import core_source_paths
print('dual_host', len(core_source_paths()))
PY
python3 -m tools.ddr.framework_factored_profile --check
python3 -m tools.ddr.dual_host_factored_profile --check
python3 -m tools.ddr.dual_host_shared_cacc_profile --check
python3 -m tools.ddr.maintenance_fi_profile --check
python3 -m tools.ddr.dual_host_maintenance_fi_profile --check
```

## K8 core/DMA replay

The original K16/OC16 weight BO is read directly; no repacked weight is used.

```sh
python3 tools/cmac/test_array_core_k8_original_weight.py --tool iverilog --suite protocol
python3 tools/cmac/test_array_core_k8_original_weight.py --tool verilator --suite protocol
```

Reports are written under `build/rknpu-array-core-k8-original/`.

## K8 endpoint elaboration

```sh
python3 - <<'PY' > /tmp/k8_sources.txt
from tools.ddr.framework_factored_profile import source_paths
for p in source_paths(): print(p)
PY
verilator --lint-only -Wall -Wno-fatal --top-module rk_jtag_dual_ddr_async \
  -GATOMIC_K=8 -DDESIGNWARE_NOEXIST -DASSERT_ON $(cat /tmp/k8_sources.txt)
```

## Synthesis (post-opt resource gate only)

```sh
cd build/k8-full-top-v1/impl-synth
RK_SHARED_DATA_CONSTRAINED_ROOT_REVIEW=APPROVED \
  vivado -mode batch -source ../synth.tcl -log synth.log -journal synth.jou
cd -
python3 build/k8-full-top-v1/make_synth_report.py
```

The recipe is the accepted `synth.tcl` with only the source prefix rewritten
and the profile-specific 8-kernel/256-product-DSP census. Clocks, XDC, CDC,
reset, DRC and the 298,600-LUT gate are unchanged. No place/route or bitstream
step is part of this profile.
