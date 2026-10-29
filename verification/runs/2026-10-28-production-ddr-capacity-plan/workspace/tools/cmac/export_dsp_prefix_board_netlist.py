"""Literal DSP-prefix board export; preserve original exporter fail-closed.

Only the five string settings actually used by all 32 prefix-kernel DSPs
and the three shell DSPs are added. No defaulting, numerical replacement,
constant repair or pruning. Each actual export still needs a real Yosys
roundtrip circuit-signature comparison before any numerical acceptance.
"""
import re
import export_board_netlist as original

DSP_STRINGS = {'A_INPUT': 'DIRECT', 'B_INPUT': 'DIRECT', 'USE_DPORT': 'FALSE',
               'USE_MULT': 'MULTIPLY', 'USE_SIMD': 'ONE48'}


def literal(value, primitive=None, parameter=None):
    if primitive == 'DSP48E1' and parameter in DSP_STRINGS:
        assert value == DSP_STRINGS[parameter], ('Unsupported DSP string setting', parameter, value)
        return '"' + value + '"'
    return original.literal(value, primitive, parameter)


def structural_board_verilog(design):
    def ident(value):
        assert value and not re.search(r'\s', value), 'Invalid structural identifier'
        return '\\' + value + ' '
    def bit_name(bit):
        if type(bit) is int:
            return 'n_' + str(bit)
        assert bit in ('0', '1', 'x', 'z'), 'Unknown netlist bit encoding'
        return "1'b" + bit
    def vector(bits):
        assert bits
        names = [bit_name(bit) for bit in reversed(bits)]
        return names[0] if len(names) == 1 else '{' + ', '.join(names) + '}'

    lines = ['// Literal mapped board export: no arithmetic or layout substitution.']
    for name, module in sorted(design['modules'].items()):
        ports = module['ports']
        defaults = ['parameter ' + ident(key) + '= ' + literal(value)
                    for key, value in sorted(module.get('parameter_default_values', {}).items())]
        settings = '#(' + ', '.join(defaults) + ') ' if defaults else ''
        lines.append('module ' + ident(name) + settings + '(' + ', '.join(ident(port) for port in ports) + ');')
        for port, value in ports.items():
            assert value['direction'] in ('input', 'output'), 'Unsupported inout'
            width = len(value['bits'])
            assert width > 0
            shape = '' if width == 1 else '[' + str(width - 1) + ':0] '
            lines.append('  ' + value['direction'] + ' wire ' + shape + ident(port) + ';')
        bits = {bit for value in ports.values() for bit in value['bits'] if type(bit) is int}
        hardware = {name: cell for name, cell in module.get('cells', {}).items() if cell['type'] != '$scopeinfo'}
        for cell in hardware.values():
            bits.update(bit for connection in cell['connections'].values() for bit in connection if type(bit) is int)
        lines.extend('  wire n_' + str(bit) + ';' for bit in sorted(bits))
        for port, value in ports.items():
            if value['direction'] == 'input':
                assert all(type(bit) is int for bit in value['bits']), 'Constant implementation input'
            lhs, rhs = (vector(value['bits']), ident(port)) if value['direction'] == 'input' else (ident(port), vector(value['bits']))
            lines.append('  assign ' + lhs + ' = ' + rhs + ';')
        for name, cell in sorted(hardware.items()):
            parameters = ['.' + ident(key) + '(' + literal(value, cell['type'], key) + ')'
                          for key, value in sorted(cell.get('parameters', {}).items())]
            settings = ' #(' + ', '.join(parameters) + ')' if parameters else ''
            connections = ', '.join('.' + ident(pin) + '(' + vector(wires) + ')'
                                    for pin, wires in sorted(cell['connections'].items()))
            lines.append('  ' + ident(cell['type']) + settings + ' ' + ident(name) + '(' + connections + ');')
        lines.append('endmodule')
    return '\n'.join(lines) + '\n'
