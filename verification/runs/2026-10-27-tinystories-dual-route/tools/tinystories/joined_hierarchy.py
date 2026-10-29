"""Strict reachable-instance census for the dual raw endpoint's elaborated JSON.

Verilator may emit $unit/std PACKAGE nodes for testbench strings. They are
accepted only through their explicit netlist system-package references; they
cannot substitute for a MODULE or a CELL target. Unknown nodes still fail.
"""
import json
from pathlib import Path

EXPECTED = {
    'rk_jtag_dual_bram':1, 'rk_jtag_backend':1, 'rk_job_control':2,
    'rk_shared_bram_regport':1, 'rk_ew_dma':1, 'rk_cmac_array_dma':1,
    'rk_cmac_success_rearm':1,
    'rk_cmac_fp16_array_dsp_prefix_pipe':1, 'rk_cmac_fp16_cell_dsp_prefix_pipe':16,
    'rk_cmac_fp16_lane_dsp_prefix':512, 'rk_cmac_fp16_discarded_carry':512,
}
FALLBACK = {'rk_cmac_fp16_cell','rk_cmac_fp16_cell_fixed','rk_cmac_fp16_array',
            'rk_cmac_fp16_array_fixed','rk_cmac_fp16_cell_dsp','rk_cmac_fp16_lane_dsp',
            'rk_cmac_fp16_array_dsp'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def census(tree):
    require(tree.get('type') == 'NETLIST' and type(tree.get('modulesp')) is list, 'Missing elaborated netlist')
    nodes = tree['modulesp']
    addresses = [n.get('addr') for n in nodes]
    require(all(isinstance(a,str) and a for a in addresses) and len(set(addresses)) == len(nodes),
            'Duplicate/missing elaborated node address')
    modules = {}
    for node in nodes:
        if node.get('type') == 'MODULE':
            modules[node['addr']] = node
        else:
            require(node.get('type') == 'PACKAGE' and node.get('inLibrary') is True, 'Unknown elaborated node')
            role = {'$unit':'dollarUnitPkgp','std':'stdPackagep'}.get(node.get('name'))
            require(role is not None and tree.get(role) == node['addr'], 'Unrecognized system package')
    roots = [m for m in modules.values() if m.get('origName') == 'tb_jtag_dual_bram']
    require(len(roots) == 1, 'Missing/duplicate dual endpoint test root')
    counts = {name:0 for name in EXPECTED}
    def cells(node):
        if isinstance(node,dict):
            require(node.get('type') not in ('GENFOR','GENIF'), 'Unelaborated generate is not an instance proof')
            if node.get('type') == 'CELL':
                yield node
                return
            for value in node.values():
                yield from cells(value)
        elif isinstance(node,list):
            for value in node:
                yield from cells(value)
    def visit(module, stack):
        address = module['addr']
        require(address not in stack, 'Recursive elaborated hierarchy')
        name = module.get('origName',module.get('name'))
        require(name not in FALLBACK, 'Non-prefix/reduced compute fallback')
        if name in counts:
            counts[name] += 1
        for cell in cells(module.get('stmtsp',[])):
            require(cell.get('modp') in modules, 'Unlinked/package/black-box cell target')
            visit(modules[cell['modp']], stack|{address})
    visit(roots[0],set())
    require(counts == EXPECTED, 'Changed dual endpoint/full512 instance census')
    return counts


def hierarchy_json(path):
    return census(json.loads(Path(path).read_text()))
