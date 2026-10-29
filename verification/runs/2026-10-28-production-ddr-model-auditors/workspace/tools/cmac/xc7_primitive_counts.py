"""Count physical XC7 cells without descending into library timing metadata."""
from collections import Counter
import re

PRIMITIVE = re.compile(r'LUT[1-6]|LUT6_2|FD[A-Z0-9]+|CARRY4|MUXF[78]|DSP48E1|INV|VCC|GND')
TIMING = {'$specify2', '$specify3', '$specrule'}

def primitive_counts(modules, top):
    def visit(name, stack):
        assert name not in stack, ('recursive hierarchy', name)
        result = Counter()
        for cell in modules[name].get('cells', {}).values():
            kind = cell['type']
            if kind == '$scopeinfo':
                continue
            if PRIMITIVE.fullmatch(kind):
                definition = modules[kind]
                assert int(definition.get('attributes', {}).get('blackbox', '0'), 2) == 1, kind
                contents = {c['type'] for c in definition.get('cells', {}).values()}
                assert contents <= TIMING, (kind, contents)
                result[kind] += 1
            else:
                assert kind in modules, ('unknown cell', kind)
                assert modules[kind].get('attributes', {}).get('hdlname') == 'rk_cmac_fp16_cell', kind
                result.update(visit(kind, stack + (name,)))
        return result
    return visit(top, ())
