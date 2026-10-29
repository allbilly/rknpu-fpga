"""Explicit, unmodified UNISIM model inventory for the C32/K16 DSP board.

This separate simulation profile never broadens the original non-DSP
inventory, substitutes RTL, supplies missing pins or edits vendor models.
"""
import hashlib
import re
import unisim_board_models as original
import test_dsp_prefix_primitive_models as primitive
from check_dsp_prefix_unisim_models import DSP_SHA

CACHE, COMMIT = original.CACHE, original.COMMIT


def selected_models(kinds):
    kinds = set(kinds)
    assert 'DSP48E1' in kinds, 'DSP-prefix board profile requires actual DSP hardware'
    result = original.selected_models(kinds - {'DSP48E1'})
    result[CACHE / 'verilog/src/unisims/DSP48E1.v'] = DSP_SHA
    return result


def freeze_models(destination, kinds):
    assert destination.resolve().is_relative_to(original.ROOT)
    source = selected_models(kinds)
    destination.mkdir(parents=True, exist_ok=False)
    frozen = []
    for path, expected in source.items():
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, ('Changed pinned board model', path)
        target = destination / path.name
        target.write_bytes(data)
        assert target.read_bytes() == data
        frozen.append(target)
    return source, frozen


def verify_configurations(implementation, top, kernel):
    assert set(implementation['modules']) == {top, kernel}
    # The unchanged checker verifies every kernel input, constant and bias,
    # not simply its DSP count or declared precision.
    primitive.validate_configuration({'modules': {
        primitive.KERNEL: implementation['modules'][kernel]}}, primitive.BENCH.read_text())
    counts = {}
    for name, body in implementation['modules'].items():
        cells = [cell for cell in body['cells'].values() if cell['type'] == 'DSP48E1']
        for cell in cells:
            params = {key: int(value, 2) if re.fullmatch('[01]+', value) else value
                      for key, value in cell['parameters'].items()}
            assert params == primitive.PARAMETERS, 'Untested DSP parameter configuration'
        counts[name] = len(cells)
    assert counts == {top: 3, kernel: 32}, 'Incomplete actual kernel/shell DSP boundaries'
    assert sum(cell['type'] == kernel for cell in implementation['modules'][top]['cells'].values()) == 16
    return dict(kernel_dsp_configurations=32, shell_dsp_configurations=3,
                physical_cmac_dsps=512, total_physical_dsps=515)
