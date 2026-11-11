# BLOCKED: conv_h40_c160_h40w40_oc320_k3x3

Source: `/home/fedora/rk3588/examples/conv.py`

Shape: `b1_c160_h40_w40_oc320_wic160_k3x3_g1_s1_pvalid`

## Reason

Vendor H40 spatial BY_Y conv path distributes six tasks over three cores and uses 17 PC-chain rows. Rocket cannot express the vendor core_mask/subcore_task split, and the PC_BASE_ADDRESS rows require runtime regcmd-address patching that the bundle schema does not have.

## Exact evidence

- Source calls npu_submit(..., task_count=6, core_mask=0, subcores=((0,2),(0,2),(0,2),(0,0),(0,0))). Two tasks are assigned to each of cores 0, 1 and 2.
- The 17-row layout writes per-row PC_BASE_ADDRESS/PC_REGISTER_AMOUNTS links and masks 0x0d/0x60.
- Rocket's drm_rocket_task has only regcmd and regcmd_count; the vendor task fields op_idx/enable_mask/int_mask/int_clear and submit core_mask/subcore_task are absent.
