"""Literal structural export for the mapped board, including BRAM string modes.

The earlier binary-only array exporter is intentionally left unchanged while
its independently source-bound simulation may still be running. No synthesis,
arithmetic substitution, parameter defaulting or silent pruning occurs here.
Every actual export must pass the independent real-Yosys circuit-signature gate.
"""
import json
import re


# These literal string parameters are declared by the installed Yosys XC7
# cells_sim.v RAMB18E1/RAMB36E1 definitions. INIT_FILE is deliberately NONE:
# file-backed initialization is not an established part of this board contract.
BRAM_STRINGS = {
    'INIT_FILE': {'NONE'},
    'RAM_MODE': {'TDP', 'SDP'},
    'RAM_EXTENSION_A': {'NONE', 'UPPER', 'LOWER'},
    'RAM_EXTENSION_B': {'NONE', 'UPPER', 'LOWER'},
    'RDADDR_COLLISION_HWCONFIG': {'DELAYED_WRITE', 'PERFORMANCE'},
    'RSTREG_PRIORITY_A': {'RSTREG', 'REGCE'},
    'RSTREG_PRIORITY_B': {'RSTREG', 'REGCE'},
    'SIM_COLLISION_CHECK': {'ALL', 'WARNING_ONLY', 'GENERATE_X_ONLY', 'NONE'},
    'SIM_DEVICE': {'VIRTEX6', '7SERIES'},
    'WRITE_MODE_A': {'WRITE_FIRST', 'READ_FIRST', 'NO_CHANGE'},
    'WRITE_MODE_B': {'WRITE_FIRST', 'READ_FIRST', 'NO_CHANGE'},
}


def literal(value, primitive=None, parameter=None):
    assert isinstance(value, str), 'Nonstring RTLIL parameter encoding'
    if re.fullmatch('[01xz]+', value):
        return str(len(value))+"'b"+value
    assert primitive in ('RAMB18E1', 'RAMB36E1'), 'Unsupported string primitive parameter'
    assert parameter in BRAM_STRINGS and value in BRAM_STRINGS[parameter], (
        'Unsupported BRAM string parameter', primitive, parameter, value)
    return json.dumps(value)


def structural_board_verilog(design):
    def ident(value):
        assert value and not re.search(r'\s', value), 'Invalid structural identifier'
        return '\\'+value+' '

    def bit_name(bit):
        if type(bit) is int:
            return 'n_'+str(bit)
        assert bit in ('0', '1', 'x', 'z'), 'Unknown netlist bit encoding'
        return "1'b"+bit

    def vector(bits):
        assert bits
        names = [bit_name(b) for b in reversed(bits)]
        return names[0] if len(names)==1 else '{'+', '.join(names)+'}'

    lines = ['// Literal mapped board export: no arithmetic or layout substitution.']
    for name, module in sorted(design['modules'].items()):
        ports = module['ports']
        defaults = ['parameter '+ident(key)+'= '+literal(value)
                    for key, value in sorted(module.get('parameter_default_values', {}).items())]
        settings = '#('+', '.join(defaults)+') ' if defaults else ''
        lines.append('module '+ident(name)+settings+'('+', '.join(ident(p) for p in ports)+');')
        for port, value in ports.items():
            assert value['direction'] in ('input', 'output'), 'Unsupported inout'
            width = len(value['bits'])
            assert width > 0
            shape = '' if width==1 else '['+str(width-1)+':0] '
            lines.append('  '+value['direction']+' wire '+shape+ident(port)+';')
        bits = {b for value in ports.values() for b in value['bits'] if type(b) is int}
        hardware = {n:c for n,c in module.get('cells', {}).items() if c['type']!='$scopeinfo'}
        for cell in hardware.values():
            bits.update(b for conn in cell['connections'].values() for b in conn if type(b) is int)
        lines.extend('  wire n_'+str(b)+';' for b in sorted(bits))
        for port, value in ports.items():
            if value['direction']=='input':
                assert all(type(b) is int for b in value['bits']), 'Constant implementation input'
            lhs, rhs = (vector(value['bits']), ident(port)) if value['direction']=='input' else (ident(port), vector(value['bits']))
            lines.append('  assign '+lhs+' = '+rhs+';')
        for name, cell in sorted(hardware.items()):
            parameters = ['.'+ident(key)+'('+literal(value, cell['type'], key)+')'
                          for key, value in sorted(cell.get('parameters', {}).items())]
            settings = ' #('+', '.join(parameters)+')' if parameters else ''
            connections = ', '.join('.'+ident(pin)+'('+vector(wires)+')'
                                    for pin, wires in sorted(cell['connections'].items()))
            lines.append('  '+ident(cell['type'])+settings+' '+ident(name)+'('+connections+');')
        lines.append('endmodule')
    return '\n'.join(lines)+'\n'
