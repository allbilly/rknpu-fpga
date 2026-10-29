"""Full-circuit comparison-only support for declared empty plain-LUT outputs.

The pinned frontend omits any zero-width vector port; the full native packed
input includes disconnected XORCY-to-LUT2 output declarations. Preserve only
an absent [] O5/O6 declaration with its unchanged logical-O annotation, plain
LUT kind and literal INIT. No input or connected output is reconstructed, no
existing port is repaired, and no comparison view is an execution input.
The complete original circuit proof and physical-footprint checks are separate
mandatory callers' gates. Existing carry/empty-input gates stay unchanged.
"""
import re

from compare_imported_carry_export import carry_export_view


def comparison_port_source(module):
    """Retain full non-LUT contracts and only LUT empty-output contracts.

    Every original LUT INIT/input/output endpoint still belongs in the separate
    complete logical proof. This is merely the memory-bounded port-declaration
    source needed alongside that proof, not an alternative circuit.
    """
    cells = {}
    for name, cell in module['cells'].items():
        if cell['type'] != 'SLICE_LUTX':
            cells[name] = cell
            continue
        outputs = {p: bits for p, bits in cell['connections'].items()
                   if cell['port_directions'][p] == 'output' and bits == []}
        if outputs:
            cells[name] = dict(cell, connections=outputs, port_directions={p: 'output' for p in outputs})
        else:
            cells[name] = dict(type='SLICE_LUTX', connections={}, port_directions={})
    return dict(cells=cells)


def full_export_view(original, exported):
    view, metadata = carry_export_view(original, exported, include_luts=False)
    cells = dict(view['cells']); restored = 0
    for name, source in original['cells'].items():
        if source['type'] != 'SLICE_LUTX': continue
        declared = {p: bits for p, bits in source['connections'].items()
                    if source['port_directions'][p] == 'output' and bits == []}
        if not declared: continue
        assert len(declared) == 1, 'Unsupported multiple logical LUT outputs'
        assert re.fullmatch(r'LUT[1-6]', source['attributes']['X_ORIG_TYPE']), 'Unsupported empty-output LUT kind'
        assert set(source['parameters']) == {'INIT'} and re.fullmatch(r'[01]{1,64}', source['parameters']['INIT']), 'Unsupported LUT INIT'
        cell = cells[name]
        assert not any(k in c['attributes'] for c in (source, cell) for k in ('X_LUT_AS_DRAM', 'X_LUT_AS_SRL')), 'Memory/SRL LUT output contract unsupported'
        for pin in declared:
            assert pin in ('O5', 'O6'), 'Unsupported empty LUT output pin'
            key = 'X_ORIG_PORT_' + pin
            assert source['attributes'][key] == cell['attributes'][key] == 'O', 'Changed empty logical LUT output mapping'
            assert cell['parameters'] == source['parameters'] and cell['attributes']['X_ORIG_TYPE'] == source['attributes']['X_ORIG_TYPE'], 'Changed empty-output LUT function'
            if pin in cell['connections']: continue  # Never overwrite an existing port.
            connections, directions = dict(cell['connections']), dict(cell['port_directions'])
            connections[pin], directions[pin] = [], 'output'
            cell = dict(cell, connections=connections, port_directions=directions); restored += 1
        cells[name] = cell
    metadata.update(restored_empty_plain_LUT_outputs=restored,
        empty_LUT_output_contract='PLAIN_LUT1_TO_6_UNCHANGED_INIT_AND_LOGICAL_O_MAPPING_EMPTY_VECTOR_ONLY',
        connected_LUT_outputs_reconstructed=False, existing_LUT_ports_rewritten=False,
        complete_original_LUT_logic_proof_required=True, physical_resource_footprint_check_required=True)
    return dict(view, cells=cells), metadata
