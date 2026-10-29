#!/usr/bin/env python3
"""Elaborate the unchanged actual DSP model and audit omitted-input P dependencies.

Test-only structural evidence. No warning waiver, numerical replacement, RTL
change, full-array acceptance or physical FPGA claim is made here.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
import test_dsp_prefix_primitive_models as primitive

TOP = 'dsp_prefix_omitted_input_cone_control'
COMBINATIONAL = {'$add', '$sub', '$mul', '$mux', '$pmux', '$and', '$or', '$xor',
    '$xnor', '$not', '$eq', '$ne', '$eqx', '$nex', '$logic_not', '$logic_and',
    '$logic_or', '$reduce_and', '$reduce_or', '$reduce_xor', '$reduce_xnor',
    '$reduce_bool', '$shl', '$shr', '$sshl', '$sshr', '$shift', '$shiftx',
    '$lt', '$le', '$gt', '$ge', '$pos', '$neg', '$slice', '$concat'}


def model_ports(text):
    header = re.search(r'\bmodule DSP48E1\s*\((.*?)\);', text, re.S)
    assert header, 'Actual DSP declaration required'
    declarations = re.findall(r'\b(input|output)\s+(?:reg\s+)?(?:signed\s+)?'
        r'(?:\[(\d+):(\d+)\]\s+)?(\w+)\s*(?=,|$)', header.group(1), re.M)
    ports = {name: (direction, int(msb) - int(lsb) + 1 if msb else 1)
             for direction, msb, lsb, name in declarations}
    assert len(declarations) == len(ports) == 49, 'Unparsed or duplicate DSP ports'
    assert sum(direction == 'input' for direction, width in ports.values()) == 38
    assert ports['A'] == ('input', 30) and ports['B'] == ('input', 18) and ports['P'] == ('output', 48)
    return ports


def omitted_ports(ports):
    connected = set(primitive.CONSTANTS) | {'A', 'B', 'P'}
    assert connected <= ports.keys()
    for name, (width, value) in primitive.CONSTANTS.items():
        assert ports[name] == ('input', width)
    inputs = [name for name, (direction, width) in ports.items() if name not in connected and direction == 'input']
    outputs = [name for name, (direction, width) in ports.items() if name not in connected and direction == 'output']
    assert len(inputs) == 26 and len(outputs) == 10
    assert all(ports[name] == ('input', 1) for name in inputs)
    return inputs, outputs


def render(ports, registered_negative=False):
    inputs, _ = omitted_ports(ports)
    params = dict(primitive.PARAMETERS)
    if registered_negative:
        params.update(AREG=1, ACASCREG=1)  # Legal registered counterexample, never an actual-kernel claim.
    parameter_text = ',\n    '.join(f'.{name}("{value}")' if type(value) is str else f'.{name}({value})'
        for name, value in params.items())
    pins = {name: f"{width}'h{value:x}" for name, (width, value) in primitive.CONSTANTS.items()}
    pins.update(A='A', B='B', P='P')
    pins.update({name: f'omitted[{index}]' for index, name in enumerate(inputs)})
    pin_text = ',\n    '.join(f'.{name}({value})' for name, value in pins.items())
    return (f'module {TOP}(input [29:0] A, input [17:0] B, input [25:0] omitted, output [47:0] P);\n'
        f'  DSP48E1 #(\n    {parameter_text}\n  ) actual_dsp(\n    {pin_text}\n  );\nendmodule\n')


def output_cone(design):
    assert set(design['modules']) == {TOP}, 'Actual model must be flattened, not opaque DSP blackbox'
    module = design['modules'][TOP]
    assert not module.get('attributes', {}).get('blackbox') and not module.get('processes')
    assert set(module['ports']) == {'A', 'B', 'omitted', 'P'}
    for name, direction, width in (('A', 'input', 30), ('B', 'input', 18), ('omitted', 'input', 26), ('P', 'output', 48)):
        assert module['ports'][name]['direction'] == direction and len(module['ports'][name]['bits']) == width
    producers = {}
    for name, cell in module['cells'].items():
        assert set(cell['connections']) == set(cell['port_directions'])
        assert set(cell['port_directions'].values()) <= {'input', 'output'}
        for pin, direction in cell['port_directions'].items():
            if direction != 'output':
                continue
            for bit in cell['connections'][pin]:
                if type(bit) is not int:
                    continue
                assert bit not in producers or producers[bit] == name, 'Multiple output drivers'
                producers[bit] = name
    reached, used = set(), set()
    pending = list(module['ports']['P']['bits'])
    while pending:
        bit = pending.pop()
        if type(bit) is not int or bit in reached:
            continue
        reached.add(bit)
        name = producers.get(bit)
        if name is None or name in used:
            continue
        used.add(name)
        cell = module['cells'][name]
        pending.extend(bit for pin, bits in cell['connections'].items()
                       if cell['port_directions'][pin] == 'input' for bit in bits)
    dependencies = {name: [index for index, bit in enumerate(port['bits']) if bit in reached]
                    for name, port in module['ports'].items() if port['direction'] == 'input'}
    all_inputs = {bit for port in module['ports'].values() if port['direction'] == 'input'
                  for bit in port['bits'] if type(bit) is int}
    assert not (reached - set(producers) - all_inputs), 'Undriven signal in observed P cone'
    kinds = Counter(module['cells'][name]['type'] for name in used)
    return dict(input_dependencies=dependencies, cone_cell_types=dict(sorted(kinds.items())),
        cone_cells=len(used), cone_wire_bits=len(reached), total_cells=len(module['cells']))


def validate_positive(cone):
    deps = cone['input_dependencies']
    assert deps['omitted'] == [], 'Omitted primitive inputs reach observed P output'
    assert deps['A'] == list(range(25)) and deps['B'] == list(range(18)), 'Actual signed 25x18 operands required'
    assert set(cone['cone_cell_types']) <= COMBINATIONAL, 'Stateful or unknown cell in actual zero-register P cone'
    assert cone['cone_cell_types'].get('$mul') == 1 and cone['cone_cell_types'].get('$add', 0) > 0
    return cone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped-report', type=Path, required=True)
    args = parser.parse_args()
    parent_path = args.mapped_report.resolve()
    assert parent_path.is_relative_to(ROOT) and parent_path.is_file()
    observed = parent_path.read_bytes()
    parent = json.loads(observed)
    assert (parent['channels'], parent['kernels'], parent['parallel_products']) == (32, 16, 512)
    assert parent['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
    part, model = [parent_path.parent / name for name in ('actual_partition.json', 'xilinx_functional_models.v')]
    for path in (part, model):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == parent['source']['files'][str(path.relative_to(ROOT))]
    installed = Path(parent['installed_model']['path'])
    assert model.read_bytes() == installed.read_bytes()
    assert hashlib.sha256(model.read_bytes()).hexdigest() == parent['installed_model']['sha256']
    assert primitive.validate_configuration(json.loads(part.read_text()), primitive.BENCH.read_text()) == 32
    ports = model_ports(model.read_text())
    inputs, outputs = omitted_ports(ports)
    out = ROOT / f'build/rknpu-dsp-prefix-pin-cone/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    frozen_model = out / 'unchanged_xilinx_cells_sim.v'
    frozen_model.write_bytes(model.read_bytes())
    snapshot = out / 'observed_parent.json'
    snapshot.write_bytes(observed)
    wrappers, scripts = {}, {}
    for kind in ('positive', 'registered_negative'):
        wrappers[kind] = out / (kind + '.v')
        wrappers[kind].write_text(render(ports, kind == 'registered_negative'))
        scripts[kind] = out / (kind + '.ys')
        # YOSYS is automatically defined by read_verilog. Only simulation-only
        # checks disappear; the functional primitive model itself is unchanged.
        scripts[kind].write_text(f'read_verilog {frozen_model}\nread_verilog {wrappers[kind]}\n'
            f'hierarchy -check -top {TOP}\nproc\nopt\nflatten\nopt\ncheck -assert\n'
            f'select -module {TOP}\nwrite_json -selected {out / (kind + ".json")}\n')
    sources = [Path(__file__).resolve(), ROOT / 'tools/evidence.py',
        Path(primitive.__file__).resolve(), primitive.BENCH,
        ROOT / 'tests/cmac/test_dsp_prefix_pin_cone_control.py', part, model,
        frozen_model, snapshot, *wrappers.values(), *scripts.values()]
    before = fingerprint(sources)
    for path in sources[:5]:
        dest = out / 'snapshot' / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
    report = dict(status='RUNNING', stage='elaboration', started_utc=timestamp(), supervisor_pid=os.getpid(),
        source=before, commands=[], observed_parent_report=str(parent_path.relative_to(ROOT)),
        observed_parent_status=parent['status'], matched_actual_dsp_instances=32, control_dsp_instances=1,
        model_ports=ports, omitted_input_pins=inputs, omitted_output_pins=outputs,
        actual_parameters=primitive.PARAMETERS, actual_constant_pins=primitive.CONSTANTS,
        installed_model_sha256=parent['installed_model']['sha256'], yosys_preprocessor_macro='YOSYS',
        simulation_only_checks_removed=True, structural_cone_acceptance=False,
        compiler_diagnostics_accepted=False, numerical_acceptance=False, full_array_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='One unchanged actual Yosys DSP48E1 functional model under all 32 actual-kernel parameters/constants. '
        'All 26 omitted input pins are independently unconstrained; audit the full flattened P dependency cone. '
        'Legal AREG/ACASCREG=1 real counterexample must reach omitted controls and fail zero-register admission. '
        'Structural elaboration only: not a numerical, compiler-diagnostic, all-X, full-array or physical acceptance.')

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(argv, label):
        log = out / (label + '.log')
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str(log.relative_to(ROOT)))
        report['commands'].append(step)
        save()
        started = time.monotonic()
        try:
            with log.open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid
                    save()
                    try:
                        code = proc.wait(timeout=300)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait()
                        raise
            step['returncode'] = code
            text = log.read_text()
            assert code == 0 and not re.search(r'ERROR:|\berror:', text, re.I), text[-3000:]
            step['diagnostic_lines_recorded_not_admitted'] = [line for line in text.splitlines()
                if re.search(r'warning:|\bWarning\b', line)]
            step['status'] = 'PASS'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').splitlines()[0]
        for kind in ('registered_negative', 'positive'):
            run(['yosys', '-Q', '-T', '-s', scripts[kind]], kind)
            cone = output_cone(json.loads((out / (kind + '.json')).read_text()))
            report[kind + '_cone'] = cone
            if kind == 'registered_negative':
                assert cone['input_dependencies']['omitted'], 'Real registered negative lacks control dependency'
                assert set(cone['cone_cell_types']) - COMBINATIONAL, 'Real registered negative lacks state'
                try:
                    validate_positive(cone)
                except AssertionError as error:
                    report['registered_negative_rejected'] = str(error)
                else:
                    raise AssertionError('Registered negative unexpectedly accepted')
                report['registered_negative_control_pins'] = [inputs[index] for index in cone['input_dependencies']['omitted']]
            else:
                validate_positive(cone)
            assert fingerprint(sources) == before, 'Actual source/model/wrapper changed during audit'
        assert frozen_model.read_bytes() == installed.read_bytes() == model.read_bytes()
        assert primitive.validate_configuration(json.loads(part.read_text()), primitive.BENCH.read_text()) == 32
        report.update(status='PASS_ISOLATED_ACTUAL_DSP_OMITTED_INPUT_CONE_ONLY', stage='complete',
            structural_cone_acceptance=True)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.rglob('*') if path.is_file() and path.name != 'report.json'])
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
