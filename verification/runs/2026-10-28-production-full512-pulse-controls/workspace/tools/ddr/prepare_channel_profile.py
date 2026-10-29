"""Prepare an explicit physical DDR-channel profile from frozen real sources.

Preserves both original MIG controllers, all pad/electrical settings, raw
addresses and the logical endpoint. Never runs FPGA tools or accesses hardware.
"""
from pathlib import Path
import argparse
import copy
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr.interface import require, load_json
from tools.ddr.original_binding import binding_map, ports, sha, WRAPPER_SHA, XDC_SHA
from tools.ddr.original_platform import render


def select_physical_channel(canonical, channel):
    """Logical channel0 is active; physical pads keep their original names.

    Internal c0/c1 endpoint and diagnostic names are logical roles. For CH1,
    swapping only non-pad MIG bindings also swaps clock/reset roles together.
    No address/data conversion or runtime channel selector is introduced.
    """
    require(type(channel) is int and channel in (0, 1), 'Unsupported physical DDR channel')
    result = copy.deepcopy(canonical)
    if channel == 0:
        return result
    for name, item in canonical.items():
        if name == 'sys_rst' or item['binding']['kind'] in ('physical_pad', 'external_clock'):
            continue
        require(name.startswith(('c0_', 'c1_')), 'Unmodeled channel-dependent MIG port')
        partner = ('c1_' if name.startswith('c0_') else 'c0_') + name[3:]
        require(partner in canonical, 'Missing paired MIG port: ' + name)
        other = canonical[partner]
        require((item['direction'], item['width']) == (other['direction'], other['width']),
                'Physical channel interfaces differ: ' + name)
        require(other['binding']['kind'] not in ('physical_pad', 'external_clock'),
                'Cannot exchange a physical pin or reference clock')
        result[name]['binding'] = copy.deepcopy(other['binding'])
    # Preserve every source binding exactly once, including all inactive VALID/
    # READY literals and explicit unqualified diagnostics. Never drop a port.
    require(len(result) == 169 and set(result) == set(canonical), 'Incomplete channel profile')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--platform', type=Path, required=True)
    ap.add_argument('--board', type=Path, required=True)
    ap.add_argument('--physical-channel', type=int, choices=(0, 1), required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    platform, board, out = args.platform.resolve(), args.board.resolve(), args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Fresh preparation directory required')
    pr, br = load_json(platform/'report.json'), load_json(board/'report.json')
    require(pr['status'] == 'PREPARED_ORIGINAL_MIG_ASYNC_EW_PLATFORM_WIRING_ONLY' and
            br['status'] == 'PREPARED_BOOT_ONLY_USER2_DDR_SNAPSHOT_SHELL_REQUIRES_QUALIFICATION',
            'Require the frozen original-MIG/read-snapshot source profiles')
    require(pr['stub_selected_for_real_design'] is False and
            br['stub_selected_for_real_design'] is False and br['logical_contract_schema'] == 3,
            'Actual source-only snapshot profile required')
    inputs = dict(pr['source_inputs']) | dict(br['source_inputs'])
    for directory, record in ((platform, pr), (board, br)):
        inputs[str(directory/'report.json')] = sha(directory/'report.json')
        for name, value in record['artifacts'].items():
            path = directory/name
            require(sha(path) == value, 'Changed parent artifact: ' + str(path))
            inputs[str(path)] = value
    require(all(sha(p) == value for p, value in inputs.items()), 'Frozen parent source changed')
    real = [Path(p).resolve() for p in br['real_hdl_sources']]
    require(len(real) == len(set(real)) == 122 and
            all('interface-only' not in str(p) for p in real), '122 real HDL files required')
    require(all(str(p) in inputs and sha(p) == inputs[str(p)] for p in real),
            'Unbound real HDL source')
    wrapper, = [p for p in real if p.name == 'top_mig_7series_0_0.v']
    endpoint, = [p for p in real if p.name == 'rk_jtag_ew_ddr_async.sv']
    require(sha(wrapper) == WRAPPER_SHA, 'Changed original MIG wrapper')
    ep = ports(endpoint.read_text(), 'rk_jtag_ew_ddr_async')
    canonical = binding_map(ports(wrapper.read_text(), 'top_mig_7series_0_0'), ep)
    original_source, _, original_top = render(ep, canonical)
    require(original_source == (platform/'platform.sv').read_text(),
            'Parent platform differs from the canonical source bindings')
    selected = select_physical_channel(canonical, args.physical_channel)
    source, _, selected_top = render(ep, selected)
    require(selected_top == original_top, 'Channel selection changed board-wrapper interface')
    # The reusable board shell connects logical frame_clk/frame_rst_n. Its
    # source is unchanged; the selected platform binds these to the active UI.
    require('assign frame_clk=c0_ui_clk;' in source and
            'assign frame_rst_n=c0_clients_rst_n;' in source, 'Changed logical mailbox clock/reset')
    require(sha(board/'mig-original.xdc') == XDC_SHA, 'Original MIG constraints changed')
    out.mkdir(parents=True)
    (out/'platform.sv').write_text(source)
    shutil.copyfile(board/'top.sv', out/'top.sv')
    for name in ('mig-original.xdc', 'board.xdc'):
        shutil.copyfile(board/name, out/name)
    (out/'constraint-helpers').mkdir()
    helper = Path(br['constraint_helpers']['mailbox_ui'])
    shutil.copyfile(helper, out/'constraint-helpers/mailbox_ui_cdc.tcl')
    selected_real = [out/'platform.sv' if p == platform/'platform.sv' else
                     out/'top.sv' if p == board/'top.sv' else p for p in real]
    require(len(set(selected_real)) == 122, 'Duplicate selected real HDL source')
    for path in (Path(__file__).resolve(), ROOT/'tools/ddr/original_platform.py',
                 ROOT/'tools/ddr/original_binding.py', ROOT/'tools/ddr/interface.py'):
        inputs[str(path)] = sha(path)
    record = dict(status='PREPARED_EXPLICIT_PHYSICAL_CHANNEL_SNAPSHOT_SOURCE_ONLY',
        top=br['top'], part=br['part'], source_inputs=inputs,
        real_hdl_sources=[str(p) for p in selected_real],
        artifacts={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()},
        constraint_sources=[str(out/'mig-original.xdc'), str(out/'board.xdc')],
        constraint_helpers={'mailbox_ui':str(out/'constraint-helpers/mailbox_ui_cdc.tcl')},
        selected_physical_channel=args.physical_channel,
        logical_ui0_physical_channel=args.physical_channel,
        logical_ui1_physical_channel=1-args.physical_channel,
        endpoint_and_diagnostic_names_are_logical_roles=True,
        all_mig_bindings=selected, board_ports=br['board_ports'],
        original_mig_pinmap=br['original_mig_pinmap'], logical_contract_schema=3,
        logical_address_window=dict(base=0, bytes=2147483648, host_address_bits=31),
        address_or_data_conversion=False, original_electrical_constraints_unchanged=True,
        transport_id='0x524b4144', abi='0x00010000', jtag_chain=2,
        both_mig_controllers_retained=True, physical_ecc_data_bits_per_channel=72,
        stub_selected_for_real_design=False, full512_integrated=False, pcie_present=False,
        recovery='Audited whole-card volatile SRAM reconfiguration only',
        source_clock_ns=20.0, selected_ui_period_ns=7.5,
        hardware_accessed=False, vivado_executed=False, bitstream_emitted=False,
        physical_integration_ready=False,
        remaining_gates=['Fresh selected-channel source synthesis',
            'Source-bound mapped clocks/reset/mailbox and complete routed checks',
            'Vendor CDC/IO/electrical and exact-image review',
            'Audited target and physical DDR/ECC/raw-BO tests'])
    (out/'report.json').write_text(json.dumps(record, indent=2)+'\n')
    print(record['status'], 'physical_channel='+str(args.physical_channel))


if __name__ == '__main__':
    main()
