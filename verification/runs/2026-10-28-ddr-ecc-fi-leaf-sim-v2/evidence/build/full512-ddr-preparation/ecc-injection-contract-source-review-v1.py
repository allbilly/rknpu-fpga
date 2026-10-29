#!/usr/bin/env python3
"""Record source-derived injection obligations; no controller or hardware test."""
import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path('/home/fedora/rknpu-fpga')
source = ROOT / 'build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl'
specs = {
    'generated_profile': ('099/top_mig_7series_0_0_mig.v', [
        'parameter C1_ECC_TEST              = "OFF"',
        '(C1_ECC_TEST == "OFF") ? C1_DATA_WIDTH : C1_DQ_WIDTH']),
    'control_permissions': ('004/mig_7series_v4_2_axi_ctrl_top.v', [
        "P_REG_FI_ECC_RDAC = 1'b0", "P_REG_FI_D_31_00_RDAC = 1'b0",
        'P_REG_FI_D_63_32_RDAC = 1\'b0', 'P_REG_FI_ECC_WRAC = (C_ECC_TEST == "ON")',
        "P_REG_FI_ECC_ADDR = 32'h0000_0380", "P_REG_FI_D_31_00_ADDR = 32'h0000_0300",
        "P_REG_FI_D_63_32_ADDR = 32'h0000_0304"]),
    'control_fi_bus': ('002/mig_7series_v4_2_axi_ctrl_reg_bank.v', [
        'assign fi_xor_we     = fi_xor_we_r & {C_DQ_WIDTH/8{ecc_on_off_r}}',
        'fi_xor_we_r[0*C_DATA_WIDTH/8+:C_DATA_WIDTH/8]',
        'fi_xor_we_r[1*C_DATA_WIDTH/8+:C_DATA_WIDTH/8]']),
    'one_shot_mask': ('056/mig_7series_v4_2_fi_xor.v', [
        "reg [DQ_WIDTH-1:0]              fi_xor_data = {DQ_WIDTH{1'b0}}",
        'if (wrdata_en) begin', 'else if (fi_xor_we[i]) begin',
        'assign wrdata_out[0+:DQ_WIDTH] = wrdata_in[0+:DQ_WIDTH] ^ fi_xor_data[0+:DQ_WIDTH]',
        'assign wrdata_out[DQ_WIDTH+:(2*nCK_PER_CLK-1)*DQ_WIDTH] = wrdata_in[DQ_WIDTH+:(2*nCK_PER_CLK-1)*DQ_WIDTH]']),
    'mc_placement': ('048/mig_7series_v4_2_mc.v', [
        'mc_wrdata_en_r <= mc_wrdata_en', '.wrdata_in (mc_wrdata_i)',
        '.wrdata_out (mc_wrdata)', '.wrdata_en (mc_wrdata_en_i)']),
    'ui_width_adaptation': ('058/mig_7series_v4_2_memc_ui_top_axi.v', [
        'if(ECC_TEST == "ON") begin',
        'assign app_wdf_data[o*72+:72] = {app_wdf_data_axi_o[o*64+:8],app_wdf_data_axi_o[o*64+:64]}',
        "assign app_raw_not_ecc = {2*nCK_PER_CLK{1'b0}}"]),
}
files = {}
for name, (relative, anchors) in specs.items():
    path = source / relative
    data = path.read_bytes()
    lines = data.decode().splitlines()
    hits = []
    for anchor in anchors:
        found = [n for n, line in enumerate(lines, 1) if anchor in line]
        assert found, (name, anchor)
        hits.append({'anchor': anchor, 'lines': found})
    if name == 'one_shot_mask':
        ports = data.decode().split('Port Declarations', 1)[1].split('Local parameters', 1)[0]
        assert 'rst' not in ports and 'reset' not in ports
    files[name] = {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'evidence': hits}
result = {
    'schema': 'ecc-injection-source-obligations-v1',
    'status': 'SOURCE_REVIEW_ONLY_NOT_INJECTION_QUALIFICATION',
    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'reviewer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'files': files,
    'findings': {
        'active_image_injection_available': False,
        'fi_register_readback_available': False,
        'fi_mask_applies_to': 'Only first 72-bit codeword of each 576-bit controller write datum',
        'mask_lifetime': 'Held until wrdata_en; write event clears all bytes and wins over simultaneous arm',
        'mask_reset_port_present': False,
        'joint_reset_alone_establishes_mask_disarmed': False,
        'ecc_test_enable_changes_generated_payload_width': True,
    },
    'required_future_profile_work': [
        'Enable ECC_TEST in a separately source-bound generated/controller profile; retain normal 64-bit payload semantics',
        'Qualify the complete controller/AXI width adaptation and fresh full numerical regression',
        'Exclusive data/control ownership must prevent unrelated writes or maintenance/RMW writes consuming the armed mask',
        'Explicitly write zero to all nine FI mask bytes before startup/recovery admission; FI registers cannot be read back',
        'Do not arm concurrently with wrdata_en; bind observed intended MC write and auto-clear to the target line',
        'Observe valid-qualified controller ECC events and exact corrected/uncorrectable read behavior',
        'Keep the normal monitor strict; diagnostic expected-fault receipts are separate from normal job success',
        'Prove fault quarantine, pending AXI drain and source-bound whole-domain recovery before resuming raw jobs',
    ],
    'hardware_accessed': False, 'vivado_executed': False,
    'physical_ecc_injection_qualified': False, 'recovery_qualified': False,
}
output = ROOT / 'build/full512-ddr-preparation/ecc-injection-contract-source-review-v1.json'
with output.open('x') as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps({k:v for k,v in result.items() if k!='files'}, sort_keys=True))
