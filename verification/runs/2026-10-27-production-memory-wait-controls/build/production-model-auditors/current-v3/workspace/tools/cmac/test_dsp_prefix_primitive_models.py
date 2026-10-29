#!/usr/bin/env python3
"""Actual DSP/CARRY model control, never full-array diagnostic admission."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

BENCH = ROOT / 'tests/cmac/tb_dsp_prefix_primitive_model_control.sv'
TOP = BENCH.stem
KERNEL = 'rk_cmac_fp16_cell_dsp_prefix_xc7'
PARAMETERS = {name: 0 for name in (
    'ACASCREG', 'ADREG', 'ALUMODEREG', 'AREG', 'BCASCREG', 'BREG',
    'CARRYINREG', 'CARRYINSELREG', 'CREG', 'DREG', 'INMODEREG', 'MREG', 'OPMODEREG', 'PREG')}
PARAMETERS.update(A_INPUT='DIRECT', B_INPUT='DIRECT', USE_DPORT='FALSE', USE_MULT='MULTIPLY', USE_SIMD='ONE48')
CONSTANTS = {'ACIN': (30, 0), 'BCIN': (18, 0), 'ALUMODE': (4, 0),
    'C': (48, 0x55550000), 'CARRYIN': (1, 0), 'CARRYINSEL': (3, 0),
    'D': (25, 0), 'INMODE': (5, 0), 'OPMODE': (7, 0b0110101), 'PCIN': (48, 0)}


def validate_configuration(partition, text):
    module = partition['modules'][KERNEL]
    cells = [c for c in module['cells'].values() if c['type'] == 'DSP48E1']
    assert len(cells) == 32
    for cell in cells:
        params = {k: int(v, 2) if re.fullmatch('[01]+', v) else v for k, v in cell['parameters'].items()}
        assert params == PARAMETERS, 'Control does not cover actual mapped DSP configuration'
        assert set(cell['connections']) == set(CONSTANTS) | {'A', 'B', 'P'}
        for pin, (width, value) in CONSTANTS.items():
            assert cell['connections'][pin] == list(reversed(f'{value:0{width}b}'))
        for pin, direction, width in (('A', 'input', 30), ('B', 'input', 18), ('P', 'output', 48)):
            assert cell['port_directions'][pin] == direction and len(cell['connections'][pin]) == width
    block = re.search(r'DSP48E1 #\((.*?)\) actual_dsp\(', text, re.S)
    assert block
    params = re.findall(r'\.(\w+)\((?:"([^"]+)"|(\d+))\)', block.group(1))
    assert len(params) == len(PARAMETERS)
    assert {k: word if word else int(number) for k, word, number in params} == PARAMETERS
    assert 'localparam logic [47:0] BIAS = 48\'h000055550000;' in text
    assert '.OPMODE(7\'b0110101)' in text and '.C(BIAS)' in text
    assert text.count('DSP48E1 #(') == text.count('CARRY4 actual_carry(') == 1
    return len(cells)


def expected(simulator):
    four_state = 1048576 if simulator == 'iverilog' else 0
    return ('PASS actual mapped prefix primitive model control dsp=4259904 carry_binary=1024 '
        f'carry_four_state={four_state} seed=35883216; not full-array or FPGA acceptance')


def validate_result(text, code, simulator, negative=None):
    assert not re.search(r'(?im)warning:|%Warning-|sorry:', text)
    markers = [s for s in text.splitlines() if s.startswith('PASS ')]
    if negative:
        marker = 'primitive ' + negative + ' mismatch case=0'
        assert code != 0 and marker in text and not markers
        for line in text.splitlines():
            if re.search(r'%Error|\berror:|FATAL:', line, re.I):
                assert marker in line or re.search(r'%Error:.*Verilog \$stop\s*$', line), line
    else:
        assert code == 0 and markers == [expected(simulator)]
        assert not re.search(r'FATAL:|%Error|\berror:', text, re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped-report', type=Path, required=True)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator'), required=True)
    args = parser.parse_args()
    parent_path = args.mapped_report.resolve()
    assert parent_path.is_relative_to(ROOT) and parent_path.is_file()
    parent_bytes = parent_path.read_bytes(); parent = json.loads(parent_bytes)
    assert parent['status'] in ('RUNNING', 'FAIL')
    assert (parent['channels'], parent['kernels'], parent['parallel_products']) == (32, 16, 512)
    assert parent['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
    directory = parent_path.parent
    part, model = directory / 'actual_partition.json', directory / 'xilinx_functional_models.v'
    for file in (part, model):
        assert hashlib.sha256(file.read_bytes()).hexdigest() == parent['source']['files'][str(file.relative_to(ROOT))]
    installed = Path(parent['installed_model']['path'])
    assert model.read_bytes() == installed.read_bytes()
    assert hashlib.sha256(model.read_bytes()).hexdigest() == parent['installed_model']['sha256']
    raw = json.loads(part.read_text())
    dsp_instances = validate_configuration(raw, BENCH.read_text())
    out = ROOT / f'build/rknpu-dsp-prefix-primitive-model-control/{args.simulator}-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    bench, frozen_model, snapshot = out / BENCH.name, out / 'xilinx_cells_sim.v', out / 'observed_live_parent.json'
    bench.write_bytes(BENCH.read_bytes()); frozen_model.write_bytes(model.read_bytes()); snapshot.write_bytes(parent_bytes)
    tracked = [Path(__file__).resolve(), ROOT / 'tools/evidence.py', BENCH, part, model, bench, frozen_model, snapshot]
    before = fingerprint(tracked)
    report = dict(status='RUNNING', stage='compile', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, simulator=args.simulator, commands=[],
        observed_parent_report=str(parent_path.relative_to(ROOT)), observed_parent_status=parent['status'],
        matched_actual_dsp_instances=dsp_instances, control_dsp_instances=1, control_carry_instances=1,
        dsp_comparisons=4259904, carry_binary_comparisons=1024,
        carry_four_state_comparisons=1048576 if args.simulator == 'iverilog' else 0, seed='0x35883216',
        parameters=PARAMETERS, constant_pins=CONSTANTS, installed_model_sha256=parent['installed_model']['sha256'],
        primitive_fixture_acceptance=False, compiler_diagnostics_accepted=False,
        full_array_numerical_acceptance=False, raw_board_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='One unchanged DSP48E1/CARRY4 model under exact actual-kernel parameters and bias. Exhaustive 11x11 mantissa pairs, signed boundary/random DSP checks, binary carry and Icarus-only exhaustive four-state carry truth-table control. Two real wrong-golden negatives. Does not waive any main-array diagnostic or establish full-array, raw-board, physical FPGA or RK compatibility.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(argv, label, negative=None):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (label + '.log')).relative_to(ROOT)))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            def no_core(): resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True, preexec_fn=no_core) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=1800)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            if label.endswith('_test'):
                validate_result(text, code, args.simulator, negative)
            else:
                assert code == 0 and not re.search(r'%Error|ERROR:|\berror:', text, re.I), text[-3000:]
                diagnostics = re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+: (.*)$', text, re.M)
                assert len(diagnostics) == len(re.findall(r'^%Warning-', text, re.M)), 'Unparsed primitive control diagnostic'
                step['diagnostics_recorded_not_admitted'] = [list(d) for d in diagnostics]
                assert not re.search(r'(?im)^warning:|sorry:', text), text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        if args.simulator == 'iverilog':
            report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
            report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
            binary = out / 'sim.vvp'
            run(['iverilog', '-g2012', '-s', TOP, '-o', binary, frozen_model, bench], 'compile')
            execute = ['vvp', str(binary)]
        else:
            report['tool_version'] = run(['verilator', '--version'], 'version').splitlines()[0]
            report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
            obj = out / 'obj'; binary = obj / 'sim'
            run(['verilator', '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal', '-j', '2',
                '--top-module', TOP, '--Mdir', obj, '-o', 'sim', frozen_model, bench], 'compile')
            execute = [str(binary)]
        execution = fingerprint([binary]); report['execution_inputs'] = execution
        report['stage'] = 'simulation'; save()
        for label, options, kind in (('dsp_negative_test', ['+NEG_DSP=1'], 'DSP'),
            ('carry_negative_test', ['+NEG_CARRY=1'], 'CARRY'), ('positive_test', [], None)):
            run(execute + options, label, kind)
            assert fingerprint([binary]) == execution and fingerprint(tracked) == before
        assert frozen_model.read_bytes() == installed.read_bytes() == model.read_bytes()
        assert validate_configuration(json.loads(part.read_text()), BENCH.read_text()) == 32
        report.update(status='PASS_ISOLATED_ACTUAL_DSP_CARRY_PRIMITIVE_MODEL_FIXTURES_ONLY',
            stage='complete', primitive_fixture_acceptance=True, result=expected(args.simulator))
    except BaseException as error: report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([p for p in out.rglob('*') if p.is_file() and p.name != 'report.json'])
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
