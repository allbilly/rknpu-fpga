"""Separate test-only 50-cell fixture with explicit native default strength.

BaseCtx::attributesToArchInfo defaults an absent BEL_STRENGTH to USER=6;
archInfoToAttributes writes that effective value back. Declare it on the
new unused test LUT before a fresh native roundtrip. Do not change the old
failed fixture, any original 49 cells, full input, RTL or comparison gate.
"""
import probe_imported_empty_lut as original
from empty_output_candidate import FRONTEND

BASE_CTX = FRONTEND.parent.parent / 'common/kernel/basectx.cc'
BASE_TYPES = FRONTEND.parent.parent / 'common/kernel/nextpnr_base_types.h'
USER_STRENGTH = format(6, '032b')


def verify_strength_source():
    source = BASE_CTX.read_text(); types = BASE_TYPES.read_text()
    for text in ('PlaceStrength strength = PlaceStrength::STRENGTH_USER;',
                 'strength = (PlaceStrength)str->second.as_int64();',
                 'getCtx()->bindBel(b, ci, strength);',
                 'ci->attrs[id("BEL_STRENGTH")] = (int)ci->belStrength;'):
        assert source.count(text) == 1, 'Unpinned native strength default/import/export'
    assert types.count('STRENGTH_USER = 6') == 1


def fixture(design, leaf):
    verify_strength_source()
    prepared, details = original.fixture(design, leaf)
    cell = next(iter(prepared['modules'].values()))['cells'][original.NAME]
    assert 'BEL_STRENGTH' not in cell['attributes'], 'Do not overwrite an existing strength declaration'
    cell['attributes']['BEL_STRENGTH'] = USER_STRENGTH
    return prepared, details
