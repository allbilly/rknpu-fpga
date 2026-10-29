"""Read-only v2 pair/carry contracts for literal declared empty LUT outputs.

Preserve the frozen v1 auditors. Derive two source-shaped functions with exact,
reversible output-contract replacements only; all other guards stay literal.
The native v2 reader distinguishes [] from absent/unknown output declarations,
and native tags count only connected outputs. A null output has no OUTMUX/carry
feed. These Python audits do not establish native legality or modify any input.
"""
import inspect

import audit_postplace_lut_pairs as old_pairs
import build_imported_carry_checker as old_roles
from empty_output_candidate import literal_outputs
from route_prefix_board import logical_lut

LOWER = "        assert first['connections'].get('O5') and not first['connections'].get('O6'), 'Changed 5LUT output role'\n"
UPPER = "        assert second['connections'].get('O6') and not second['connections'].get('O5'), 'Changed 6LUT output role'\n"
NEW_LOWER = "        check_output_role(first, 'O5', 'O6')\n"
NEW_UPPER = "        check_output_role(second, 'O6', 'O5')\n"
PAIR_PREFIX = "    cells = module['cells']\n"
ROLE_PREFIX = "    cells = module['cells']; by_bel = {}; users = {}\n"
DECLARATIONS = """    # Match the native v2 reader's complete plain-LUT output declarations
    # before original logical-pin/user iteration; malformed data fails here.
    for declared_cell in cells.values():
        if declared_cell['type'] == 'SLICE_LUTX':
            literal_outputs(declared_cell)
"""
ROLE = "        assert len(bits) == 1 and isinstance(bits[0], int)\n"
NEW_ROLE = """        # The v2 native predicate skips a null DI feed; only an exact
        # declared logical [] output can use that case in this read-only model.
        logical_lut(cell)
        literal_outputs(cell)
        assert 'O5' in cell['connections'] and cell['attributes']['X_ORIG_PORT_O5'] == 'O'
        assert cell['port_directions']['O5'] == 'output'
        if bits == []:
            continue
        assert len(bits) == 1 and isinstance(bits[0], int)
"""


def check_output_role(cell, expected, opposite):
    literal_outputs(cell)  # Missing/unknown/malformed declarations remain errors.
    assert expected in cell['connections'], 'Missing declared output role'
    assert cell['attributes'].get('X_ORIG_PORT_' + expected) == 'O', 'Changed logical output role'
    assert cell['port_directions'].get(expected) == 'output', 'Changed output direction'
    assert not cell['connections'].get(opposite), 'Connected opposite output role'


def source_shaped(original, replacements):
    result = original
    for old, new in replacements:
        assert result.count(old) == 1, 'Unpinned original output-contract guard'
        result = result.replace(old, new)
    restored = result
    for old, new in replacements:
        assert restored.count(new) == 1
        restored = restored.replace(new, old)
    assert restored == original
    return result


def _derive(function, replacements, module):
    source = source_shaped(inspect.getsource(function), replacements)
    namespace = dict(module.__dict__, check_output_role=check_output_role,
                     logical_lut=logical_lut, literal_outputs=literal_outputs)
    # Compile only the bounded known source above, never a netlist/input string.
    exec(compile(source, __file__ + ':source-shaped-' + function.__name__, 'exec'), namespace)
    return namespace[function.__name__], source


audit_pairs, PAIR_SOURCE = _derive(old_pairs.audit_pairs,
    ((PAIR_PREFIX, PAIR_PREFIX + DECLARATIONS), (LOWER, NEW_LOWER), (UPPER, NEW_UPPER)), old_pairs)
local_carry_roles, ROLE_SOURCE = _derive(old_roles.local_carry_roles,
    ((ROLE_PREFIX, ROLE_PREFIX + DECLARATIONS), (ROLE, NEW_ROLE)), old_roles)
