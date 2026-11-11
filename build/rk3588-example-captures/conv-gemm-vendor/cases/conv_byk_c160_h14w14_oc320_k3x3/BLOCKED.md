# BLOCKED: conv_byk_c160_h14w14_oc320_k3x3

Source: `/home/fedora/rk3588/examples/conv.py`

Shape: `b1_c160_h14_w14_oc320_wic160_k3x3_g1_s1_pvalid`

## Reason

Vendor BY_K conv path uses explicit multi-core task distribution and a multi-task PC chain. Rocket has no core_mask/subcore_task fields and no bundle patch kind for the runtime regcmd address in PC_BASE_ADDRESS.

## Exact evidence

- Source calls npu_submit(..., task_count=3, core_mask=0, subcores=((0,1),(0,1),(0,1),(0,0),(0,0))). `core_mask=0` is RKNPU_CORE_AUTO_MASK and the three subcore entries assign one task each to three physical cores.
- Rocket presents one drm_sched_entity per file and picks one core; there is no UAPI way to express the 1/1/1 split.
- The 11-row layout also writes PC_BASE_ADDRESS to the regcmd BO DMA address and PC_REGISTER_AMOUNTS to non-zero chain lengths; the bundle schema can patch only named buffer addresses, not a self-referential regcmd address.
