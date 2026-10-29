#!/usr/bin/env python3
"""Real Yosys export control on all actual kernel/shell DSP configurations only.

Extracted DSP boundaries are control fixtures, not the whole board. All
actual primitive parameters and inter-DSP connections are preserved. A
small roundtrip PASS does not validate full-board export or arithmetic.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import export_dsp_prefix_board_netlist as export
import test_dsp_prefix_primitive_models as primitive
from test_fixed_mapped_array import circuit_signature, hardware_instance_aliases

PARENT = ROOT / 'build/rknpu-dsp-prefix-board-area/1791291727991236024/report.json'


def dsp_boundary(body):
    cells = {name: deepcopy(cell) for name, cell in body['cells'].items() if cell['type'] == 'DSP48E1'}
    assert cells
    for cell in cells.values():
        params = {key: int(value, 2) if re.fullmatch('[01]+', value) else value
                  for key, value in cell['parameters'].items()}
        assert params == primitive.PARAMETERS
        assert set(cell['port_directions']) == set(cell['connections'])
        assert set(cell['port_directions'].values()) <= {'input', 'output'}
    outputs = {bit for cell in cells.values() for pin, bits in cell['connections'].items()
               if cell['port_directions'][pin] == 'output' for bit in bits if type(bit) is int}
    inputs = {bit for cell in cells.values() for pin, bits in cell['connections'].items()
              if cell['port_directions'][pin] == 'input' for bit in bits if type(bit) is int} - outputs
    assert inputs and outputs
    return dict(ports={'input_bits': dict(direction='input', bits=sorted(inputs)),
                       'output_bits': dict(direction='output', bits=sorted(outputs))},
                cells=cells, netnames={})


def main():
    parent = json.loads(PARENT.read_text())
    assert parent['status'] == 'FAIL'  # Not promoted by this isolated control.
    assert (parent['channels'], parent['kernels'], parent['parallel_products']) == (32, 16, 512)
    graph = PARENT.parent / 'mapped_hierarchy.json'
    with graph.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == parent['artifacts']['files'][str(graph.relative_to(ROOT))]
    design = json.loads(graph.read_text())
    kernel = parent['preserved_kernel']
    fixture = dict(modules={'kernel_dsp_boundary': dsp_boundary(design['modules'][kernel]),
                            'shell_dsp_boundary': dsp_boundary(design['modules']['ypcb_cmac_array_top'])})
    assert [len(fixture['modules'][name]['cells']) for name in ('kernel_dsp_boundary', 'shell_dsp_boundary')] == [32, 3]
    # The existing helper independently verifies literal restoration of the
    # entire graph. The roundtrip verifier itself remains unchanged and strict.
    aliased, aliases = hardware_instance_aliases(fixture)
    out = ROOT / f'build/rknpu-dsp-prefix-board-export-control/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    sv = out / 'actual_dsp_boundaries.v'
    sv.write_text(export.structural_board_verilog(aliased))
    generated = out / 'actual_dsp_boundaries.json'
    generated.write_text(json.dumps(fixture, indent=2) + '\n')
    alias_path = out / 'reversible_instance_aliases.json'
    alias_path.write_text(json.dumps(aliases, indent=2) + '\n')
    roundtrip = out / 'roundtrip.json'
    script = out / 'roundtrip.ys'
    script.write_text('read_verilog -sv ' + json.dumps(str(sv)) + ';\nwrite_json ' + json.dumps(str(roundtrip)) + ';\n')
    paths = {PARENT, graph, Path(__file__).resolve(), Path(export.__file__).resolve(),
             Path(export.original.__file__).resolve(), Path(primitive.__file__).resolve(),
             ROOT / 'tools/evidence.py', ROOT / 'tools/cmac/test_fixed_mapped_array.py', sv, generated, alias_path, script}
    source = fingerprint(paths)
    report = dict(status='RUNNING', source=source, started_utc=timestamp(), supervisor_pid=os.getpid(),
                  original_failed_parent=str(PARENT.relative_to(ROOT)), original_parent_unchanged_fail=True,
                  kernel_dsp_configurations=32, shell_dsp_configurations=3, commands=[],
                  full_board_export_acceptance=False, numerical_netlist_acceptance=False,
                  physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False, scope=__doc__)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label):
        log = out / (label + '.log')
        started = time.monotonic()
        with log.open('w') as stream:
            result = subprocess.run(list(map(str, argv)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        step = dict(argv=list(map(str, argv)), log=str(log.relative_to(ROOT)), returncode=result.returncode,
                    seconds=round(time.monotonic() - started, 3), status='PASS_TOOL_ONLY' if result.returncode == 0 else 'FAIL')
        report['commands'].append(step)
        save()
        text = log.read_text()
        assert result.returncode == 0 and not re.search(r'(?im)\b(?:warning|error)\s*:|sorry:', text)
        return text
    save()
    print(out / 'report.json', flush=True)
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        assert report['tool_version'] == parent['tool_version']
        run(['yosys', '-Q', '-T', '-s', script], 'roundtrip')
        assert circuit_signature(json.loads(roundtrip.read_text())) == circuit_signature(aliased)
        assert hardware_instance_aliases(fixture) == (aliased, aliases)
        assert fingerprint(paths) == source
        report.update(status='PASS_ACTUAL_32_KERNEL_3_SHELL_DSP_LITERAL_EXPORT_CONTROL_ONLY',
                      circuit_identity='PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.rglob('*') if path.is_file() and path.name != 'report.json'])
        save()


if __name__ == '__main__':
    main()
