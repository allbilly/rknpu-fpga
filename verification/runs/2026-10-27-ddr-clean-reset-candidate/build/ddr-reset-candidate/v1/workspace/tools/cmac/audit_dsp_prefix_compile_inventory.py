#!/usr/bin/env python3
"""Read-only completed compiler inventory and exact missing-DSP-pin provenance.

This accounts for diagnostics; it does not admit them for replay.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
import audit_dsp_prefix_pin_cone as cone


def diagnostics(text):
    assert not re.search(r'%Error|ERROR:|sorry:|\bwarning:', text, re.I)
    parsed = re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):(\d+): (.*)$', text, re.M)
    assert len(parsed) == len(re.findall(r'^%Warning-', text, re.M)), 'Unparsed compiler warning'
    return [dict(kind=kind, source=source, line=int(line), column=int(column), message=message)
            for kind, source, line, column, message in parsed]


def missing_pin_provenance(entries, source_lines, module, ports):
    omitted_inputs, omitted_outputs = cone.omitted_ports(ports)
    missing = set(omitted_inputs) | set(omitted_outputs)
    cells = {name: cell for name, cell in module['cells'].items() if cell['type'] == 'DSP48E1'}
    assert len(cells) == 32
    observed = Counter()
    sites = {}
    for entry in entries:
        assert entry['kind'] == 'PINMISSING'
        assert 1 <= entry['line'] <= len(source_lines)
        instance = re.fullmatch(r'\s*\) (\w+) \(\s*', source_lines[entry['line'] - 1])
        assert instance and instance.group(1) in cells, 'Missing pin does not identify an actual mapped DSP'
        name = instance.group(1)
        message = re.fullmatch(r"Instance has missing pin: '(\w+)'", entry['message'])
        assert message and message.group(1) in missing, 'Unexpected missing pin'
        pin = message.group(1)
        assert pin not in cells[name]['connections'], 'Diagnosed pin is actually connected'
        observed[name, pin] += 1
        sites.setdefault(name, set()).add(entry['line'])
    expected = Counter({(name, pin): 1 for name in cells for pin in missing})
    assert observed == expected, 'Missing, duplicated or additional missing-pin diagnostic'
    assert all(len(lines) == 1 for lines in sites.values()), 'Inconsistent instance declaration line'
    return dict(dsp_instances=len(cells), diagnostic_count=sum(observed.values()),
        omitted_inputs_per_instance=len(omitted_inputs), omitted_outputs_per_instance=len(omitted_outputs),
        input_diagnostics=len(cells) * len(omitted_inputs), output_diagnostics=len(cells) * len(omitted_outputs),
        instance_lines={name: next(iter(lines)) for name, lines in sorted(sites.items())},
        omitted_inputs=omitted_inputs, omitted_outputs=omitted_outputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped-report', type=Path, required=True)
    parser.add_argument('--cone-report', type=Path, required=True)
    args = parser.parse_args()
    parent_path, cone_path = [path.resolve() for path in (args.mapped_report, args.cone_report)]
    assert all(path.is_relative_to(ROOT) and path.is_file() for path in (parent_path, cone_path))
    parent, proof = [json.loads(path.read_text()) for path in (parent_path, cone_path)]
    assert parent['status'] == 'FAIL' and parent['stage'] == 'compile' and parent['finished_utc']
    assert parent['commands'][-1]['status'] == 'FAIL' and parent['commands'][-1]['returncode'] == 0
    assert parent['numerical_netlist_binary_fixture_acceptance'] is False
    assert proof['status'] == 'PASS_ISOLATED_ACTUAL_DSP_OMITTED_INPUT_CONE_ONLY'
    assert proof['stage'] == 'complete' and proof['structural_cone_acceptance'] is True
    assert proof['compiler_diagnostics_accepted'] is proof['numerical_acceptance'] is False
    for report in (parent, proof):
        for manifest in (report['source'], report['artifacts']):
            assert fingerprint([ROOT / name for name in manifest['files']]) == manifest
    directory = parent_path.parent
    part, model, netlist = [directory / name for name in ('actual_partition.json', 'xilinx_functional_models.v', 'mapped_partition.v')]
    assert proof['installed_model_sha256'] == parent['installed_model']['sha256']
    assert cone.primitive.validate_configuration(json.loads(part.read_text()), cone.primitive.BENCH.read_text()) == 32
    ports = cone.model_ports(model.read_text())
    assert proof['omitted_input_pins'] == cone.omitted_ports(ports)[0]
    actual_cone = cone.output_cone(json.loads((cone_path.parent / 'positive.json').read_text()))
    assert actual_cone == proof['positive_cone']
    cone.validate_positive(actual_cone)
    assert proof['registered_negative_control_pins'] == ['CEA2', 'CLK', 'RSTA']
    log = ROOT / parent['commands'][-1]['log']
    entries = diagnostics(log.read_text())
    permitted_sources = {netlist, model, directory / 'cell' / 'rk_cmac_fp16_cell_dsp_prefix_xc7_b.sv'}
    assert all(Path(entry['source']) in permitted_sources for entry in entries), 'Unaccounted diagnostic source'
    pins = [entry for entry in entries if entry['kind'] == 'PINMISSING']
    assert all(Path(entry['source']) == netlist for entry in pins)
    provenance = missing_pin_provenance(pins, netlist.read_text().splitlines(),
        json.loads(part.read_text())['modules'][cone.primitive.KERNEL], ports)
    out = ROOT / f'build/rknpu-dsp-prefix-compile-inventory/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    tracked = [Path(__file__).resolve(), ROOT / 'tools/evidence.py', Path(cone.__file__).resolve(),
        Path(cone.primitive.__file__).resolve(), cone.primitive.BENCH,
        ROOT / 'tests/cmac/test_dsp_prefix_compile_inventory_control.py',
        parent_path, cone_path, part, model, netlist, log]
    before = fingerprint(tracked)
    for path in tracked:
        target = out / 'snapshot' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    groups = {}
    for entry in entries:
        kind = entry['kind']
        if kind not in ('PINMISSING', 'UNDRIVEN', 'UNUSEDSIGNAL'):
            groups.setdefault(kind, []).append(entry)
    report = dict(status='READ_ONLY_COMPLETED_DSP_PREFIX_COMPILER_INVENTORY_ONLY', finished_utc=timestamp(),
        source=before, completed_compile_report=str(parent_path.relative_to(ROOT)),
        cone_report=str(cone_path.relative_to(ROOT)), diagnostics=dict(sorted(Counter(entry['kind'] for entry in entries).items())),
        total_diagnostics=len(entries), exact_missing_pin_provenance=provenance,
        source_site_inventory_recorded_not_admitted=groups,
        compiler_diagnostics_accepted=False, full_array_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Exact completed compiler warning inventory; all 1152 missing-pin notices bijectively identify '
        '32 actual mapped DSPs and their 26 omitted inputs/10 omitted outputs. The source-bound actual model '
        'cone proves omitted inputs cannot reach P for this zero-register configuration. Remaining classes '
        'are retained, not waived. No main diagnostic or numerical/physical acceptance.')
    assert fingerprint(tracked) == before
    report['artifacts'] = fingerprint([path for path in out.rglob('*') if path.is_file()])
    (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(out / 'report.json')


if __name__ == '__main__':
    main()
