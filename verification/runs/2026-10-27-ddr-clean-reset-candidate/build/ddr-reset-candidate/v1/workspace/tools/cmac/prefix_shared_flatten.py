"""Literal two-stage hierarchy expansion; no optimization or physical acceptance."""
from collections import Counter
import re

from prepare_prefix_pack_input import literal_flatten

PRIMITIVE = re.compile(r'LUT[1-6]|LUT6_2|INV|CARRY4|MUXF[78]|DSP48E1|FDCE|FDRE|FDSE|FDPE|RAMB(?:18|36)E1')


def flatten_shared(design, top, private, shared, instances):
    assert len({top, private, shared}) == 3
    assert set(design['modules']) == {top, private, shared}
    assert type(instances) is int and instances >= 2
    modules = design['modules']
    callers = {name: cell for name, cell in modules[top]['cells'].items()
               if cell['type'] == private}
    lifted = {name: cell for name, cell in modules[top]['cells'].items()
              if cell['type'] == shared}
    assert len(callers) == instances and len(lifted) == 1, 'Changed full hierarchy multiplicity'
    for module in (private, shared):
        assert all(PRIMITIVE.fullmatch(c['type']) for c in modules[module]['cells'].values())
    assert all(c['type'] in (private, shared) or PRIMITIVE.fullmatch(c['type'])
               for c in modules[top]['cells'].values()), 'Unknown shell hardware'
    expected = Counter(c['type'] for c in modules[top]['cells'].values()
                       if c['type'] not in (private, shared))
    for module, multiplicity in ((private, instances), (shared, 1)):
        for cell in modules[module]['cells'].values():
            expected[cell['type']] += multiplicity
    first_aliases, first_constants, second_aliases, second_constants = [], [], [], []
    first, retained = literal_flatten(dict(modules={top: modules[top], private: modules[private]}),
        top, private, first_aliases, first_constants)
    assert set(retained) == set(callers)
    final, shared_instances = literal_flatten(dict(modules={top: first['modules'][top],
        shared: modules[shared]}), top, shared, second_aliases, second_constants)
    assert set(shared_instances) == set(lifted)
    counts = Counter(c['type'] for c in final['modules'][top]['cells'].values())
    assert counts == expected, 'Hierarchy expansion changed physical primitive counts'
    for name in callers:
        assert Counter(c['type'] for n, c in final['modules'][top]['cells'].items()
                       if n.startswith(name + '.')) == Counter(
                           c['type'] for c in modules[private]['cells'].values())
    return final, dict(retained_private_instances=sorted(callers),
        retained_shared_instances=sorted(lifted), cells=dict(counts),
        private_output_aliases=first_aliases, private_constant_outputs=first_constants,
        shared_output_aliases=second_aliases, shared_constant_outputs=second_constants)
