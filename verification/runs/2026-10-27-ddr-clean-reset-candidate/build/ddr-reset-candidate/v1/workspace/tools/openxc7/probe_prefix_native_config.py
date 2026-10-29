#!/usr/bin/env python3
"""Native FASM encoder control: four actual DSP representatives and all six BRAMs.

This test-only circuit preserves literal primitive parameters and constant
input bits, remapping variable wires explicitly. It is NOT an NPU execution
image, an alternative board demo, a full circuit equivalence proof or signoff.
Expected configuration vectors are comparison data, never execution inputs.
"""
from collections import Counter
from copy import deepcopy
import argparse
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_prefix_board import ROOT, TOP, DATABASE, CONSTIDS, digest, timestamp, packing_xdc
from place_prefix_board import verify_native_tool_transition, bind_report, verify_bindings
from audit_prefix_config_contract import dsp_contract, bram_contract, bram_half_init, FASM_SOURCE
from check_prefix_native_features import compare_dsp, compare_bram
from evidence import source_revision

PARENT = ROOT / 'build/openxc7/prefix-config-contract-1791401020849392343/report.json'
QUALIFIED = Path('/home/fedora/soDLA/build/ypcb/static-exp-qualification-1791402583316994514/qualification.json')
SELECTED = PARENT.parent / 'actual-selected-primitives.json'
CONTROL = ROOT / 'tests/cmac/test_prefix_native_config_control.py'
FEATURE_CONTROL = ROOT / 'tests/cmac/test_prefix_native_feature_controls.py'
PLACEMENT_SOURCE = FASM_SOURCE.parent / 'xilinx.cc'
XDC_SOURCE = FASM_SOURCE.parent / 'xdc.cc'
FASM_MERGE_SOURCE = Path('/home/fedora/tiny-gpu/build/ypcb/prjxray/third_party/fasm/fasm/output.py')


def representatives(selected):
    dsps = {n: c for n, c in selected.items() if c['type'] == 'DSP48E1'}
    brams = {n: c for n, c in selected.items() if c['type'] == 'RAMB36E1'}
    assert len(dsps) == 515 and len(brams) == 6
    shell = sorted(n for n in dsps if '.' not in n)
    kernels = sorted(n for n in dsps if '.' in n)
    assert len(shell) == 3 and len(kernels) == 512
    groups = Counter(n.split('.')[0] for n in kernels)
    assert len(groups) == 16 and set(groups.values()) == {32}
    for c in dsps.values(): dsp_contract(c)
    for c in brams.values(): bram_contract(c)
    return {n: selected[n] for n in [*shell, kernels[0], *sorted(brams)]}


def config_fixture(selected):
    chosen = representatives(selected)
    next_bit = 100
    def wire():
        nonlocal next_bit
        result = next_bit
        next_bit += 1
        return result
    def cell(kind, connections, directions, params=None):
        return dict(hide_name=0, type=kind, parameters=params or {}, attributes={},
                    connections=connections, port_directions=directions)
    cells = dict(
        clock_input=cell('IBUF', {'I': [2], 'O': [20]}, {'I': 'input', 'O': 'output'}),
        reset_input=cell('IBUF', {'I': [3], 'O': [21]}, {'I': 'input', 'O': 'output'}),
        clock_global=cell('BUFG', {'I': [20], 'O': [22]}, {'I': 'input', 'O': 'output'}))
    for i in range(3):
        cells[f'output_{i}'] = cell('OBUF', {'I': [24 + i], 'O': [4 + i]}, {'I': 'input', 'O': 'output'})
    ram_data, dsp_data = [], []
    origins = {}
    for source_name, original in chosen.items():
        if original['type'] != 'RAMB36E1': continue
        conns = {}
        for pin, bits in original['connections'].items():
            if original['port_directions'][pin] == 'output':
                conns[pin] = [wire() for _ in bits]
            else:
                conns[pin] = [b if type(b) is str else 22 if pin.startswith('CLK') else 21 for b in bits]
        c = cell(original['type'], conns, deepcopy(original['port_directions']), deepcopy(original['parameters']))
        name = 'bram_' + source_name
        cells[name] = c
        origins[name] = source_name
        ram_data.extend(conns['DOADO'][:8] + conns['DOPADOP'][:1])
        if int(original['parameters']['READ_WIDTH_B'], 2) == 9:
            ram_data.extend(conns['DOBDO'][:8] + conns['DOPBDOP'][:1])
    assert len(ram_data) == 72
    for index, (source_name, original) in enumerate(chosen.items()):
        if original['type'] != 'DSP48E1': continue
        conns = {}
        for pin, bits in original['connections'].items():
            if original['port_directions'][pin] == 'output':
                conns[pin] = [wire() for _ in bits]
            else:
                conns[pin] = [b if type(b) is str else ram_data[(i + index * 9) % len(ram_data)] for i, b in enumerate(bits)]
        name = 'dsp_' + source_name.replace('.', '_')
        cells[name] = cell(original['type'], conns, deepcopy(original['port_directions']), deepcopy(original['parameters']))
        origins[name] = source_name
        dsp_data.extend(conns['P'])
    assert len(dsp_data) == 192
    def reduce_xor(bits, output, prefix):
        accum = bits[0]
        for i, bit in enumerate(bits[1:]):
            result = output if i == len(bits) - 2 else wire()
            cells[f'{prefix}_{i}'] = cell('LUT2', {'I0': [accum], 'I1': [bit], 'O': [result]},
                {'I0': 'input', 'I1': 'input', 'O': 'output'}, {'INIT': '0110'})
            accum = result
    reduce_xor(dsp_data, 24, 'dsp_xor')
    reduce_xor(ram_data, 25, 'ram_xor')
    cells['input_inverse'] = cell('INV', {'I': [21], 'O': [26]}, {'I': 'input', 'O': 'output'})
    ports = dict(SYS_CLK=dict(direction='input', bits=[2]), SYS_RSTN=dict(direction='input', bits=[3]),
                 led_3bits_tri_o=dict(direction='output', bits=[4, 5, 6]))
    # The pinned XDC get_ports clock selector resolves net aliases, unlike
    # the I/O property selector. Preserve normal Yosys public-port aliases.
    netnames = {name: dict(hide_name=0, bits=list(port['bits']), attributes={})
                for name, port in ports.items()}
    design = dict(modules={TOP: dict(ports=ports, cells=cells, netnames=netnames)})
    verify_fixture(design, origins, selected)
    return design, origins


def verify_fixture(design, origins, selected):
    module = design['modules'][TOP]
    expected_ports = dict(SYS_CLK=dict(direction='input', bits=[2]), SYS_RSTN=dict(direction='input', bits=[3]),
                          led_3bits_tri_o=dict(direction='output', bits=[4, 5, 6]))
    assert module['ports'] == expected_ports, 'Changed literal public port binding'
    assert module['netnames'] == {
        name: dict(hide_name=0, bits=list(port['bits']), attributes={})
        for name, port in expected_ports.items()}, 'Missing/changed public port net alias'
    cells = module['cells']
    assert Counter(cells[n]['type'] for n in origins) == {'DSP48E1': 4, 'RAMB36E1': 6}
    assert set(origins.values()) == set(representatives(selected))
    for name, source in origins.items():
        before, after = selected[source], cells[name]
        for field in ('type', 'parameters', 'port_directions'): assert before[field] == after[field]
        assert set(before['connections']) == set(after['connections'])
        for pin, bits in before['connections'].items():
            assert len(after['connections'][pin]) == len(bits)
            if before['port_directions'][pin] == 'input':
                for original, remapped in zip(bits, after['connections'][pin]):
                    if type(original) is str:
                        assert original in ('0', '1', 'x') and remapped == original, 'Changed literal input bit'
                    else: assert type(remapped) is int and remapped >= 2


def parse_features(text):
    features = {}
    for line in text.splitlines():
        if not line or line.startswith('#'): continue
        match = re.fullmatch(r"([^\s=]+)(?: = (\d+)'b([01]+))?", line)
        assert match, 'Unparsed native FASM feature: ' + line
        name, width, bits = match.groups()
        assert name not in features, 'Duplicate native FASM feature: ' + name
        if width is not None: assert int(width) == len(bits)
        features[name] = bits if bits is not None else '1'
    return features


def parse_native_features(text):
    """Only the pinned writer's repeated I/O STEPDOWN flags are folded.

    fasm.cc writes the same pad flag before and after popping IOB_Yn.
    F4PGA output.py merge_features models repeated equal assignments as a
    set, and rejects conflicting assignments. Keep the strict parser's
    duplicate rejection for every other feature; record each folded line.
    This is syntax normalization, not configuration or electrical approval.
    """
    features, occurrences, repeated = {}, {}, {}
    for lineno, line in enumerate(text.splitlines(), 1):
        item = parse_features(line)
        if not item: continue
        name, value = next(iter(item.items()))
        occurrences.setdefault(name, []).append(lineno)
        if name in features:
            assert features[name] == value, 'Conflicting native FASM feature: ' + name
            assert value == '1' and re.fullmatch(
                r'[LR]IOB(?:18|33)_X\d+Y\d+\.IOB_Y[01]\.LVCMOS12_LVCMOS15_LVCMOS18_SSTL135_SSTL15\.STEPDOWN',
                name), 'Unsupported repeated native FASM feature: ' + name
            assert len(occurrences[name]) == 2, 'Unexpected native STEPDOWN repetition count'
            repeated[name] = occurrences[name]
        else: features[name] = value
    return features, repeated


def verify_clock_admission(log, constraints):
    assert constraints['target_period_ns'] == 20.0
    assert len(re.findall(r"applying clock period constraint on net 'SYS_CLK' \(on line \d+\)", log)) == 1, \
        'Literal 20 ns SYS_CLK clock constraint was not admitted exactly once'
    assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|target is ignored|matched nothing', log)


def native_budget(value):
    assert type(value) is int and 600 <= value <= 7200, 'Native host wall budget must be 600..7200 seconds'
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-timeout', type=int, default=3600,
                        help='Native host wall limit in seconds; no placer/FPGA timing change (600..7200)')
    args = parser.parse_args()
    native_timeout = native_budget(args.native_timeout)
    out = ROOT / f'build/openxc7/prefix-native-config-control-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(), commands=[],
        scope=__doc__, native_control_primitive_counts=dict(DSP48E1=4, RAMB36E1=6), full_target_parallel_products=512,
        full_board_native_FASM_executed=False, full_board_numerical_acceptance=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        expected_vectors_used_for_execution=False, full_circuit_identity_claimed=False, production_source_before=source_revision(),
        native_host_wall_timeout_seconds=native_timeout)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, timeout=600):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT), log=str(out / (label + '.log')),
                    timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step)
        start = time.monotonic()
        save()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as proc:
                step['pid'] = proc.pid
                save()
                try: code = proc.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text), text[-3000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()
    save()
    print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        parent = json.loads(PARENT.read_text())
        assert parent['status'] == 'AUDITED_ACTUAL_FULL_PREFIX_DSP_BRAM_CONFIGURATION_WITH_EXPLICIT_GAPS_NOT_FASM_OR_SIGNOFF'
        before = {}
        bind_report(PARENT, parent, before)
        inventory, candidate, transition = verify_native_tool_transition(QUALIFIED)
        before.update(candidate['inputs'])
        for p in (QUALIFIED, Path(__file__), CONTROL, FEATURE_CONTROL, FASM_SOURCE, PLACEMENT_SOURCE,
                  XDC_SOURCE, FASM_MERGE_SOURCE): before[str(p.resolve())] = digest(p)
        for module in list(sys.modules.values()):
            if getattr(module, '__file__', None):
                p = Path(module.__file__).resolve()
                if p.is_relative_to(ROOT / 'tools'): before[str(p)] = digest(p)
        verify_bindings(before)
        report.update(source=before, timing_inventory=inventory, native_tool_transition=transition)
        shutil.copyfile(Path(__file__), out / 'executed_source.py')
        selected = json.loads(SELECTED.read_text())
        design, origins = config_fixture(selected)
        fixture = out / 'test-only-config-input.json'
        fixture.write_text(json.dumps(design, indent=2, sort_keys=True) + '\n')
        report.update(control_origins=origins, execution_input=str(fixture.relative_to(ROOT)))
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('feature_corruption_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', FEATURE_CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        executable = candidate['executable']['path']
        report['native_version'] = run('version', [executable, '--version']).strip()
        text, constraints = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        xdc = out / 'literal.xdc'
        xdc.write_text(text)
        report['constraint_translation'] = constraints
        report['stage'] = 'native_clock_admission'
        clock_pack = out / 'clock-admitted-packed.json'
        clock_log = run('native_clock_admission', [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
            '--top', TOP, '--json', fixture, '-o', 'xdc=' + str(xdc), '--freq', '50', '--seed', '3588',
            '--Werror', '--debug', '--pack-only', '--write', clock_pack])
        verify_clock_admission(clock_log, constraints)
        report['clock_admission'] = dict(literal_SYS_CLK_alias_preserved=True, target_period_ns=20.0,
            native_parser_applied_constraint=True, clock_metadata_serialized=False, timing_signoff=False)
        routed, fasm, placement = (out / name for name in ('routed.json', 'control.fasm', 'placement.json'))
        report.update(stage='native_PNR_FASM', native_control_PNR_FASM_executed=True)
        log = run('native_PNR_FASM', [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
            '--top', TOP, '--json', fixture, '-o', 'xdc=' + str(xdc), '-o', 'fasm=' + str(fasm),
            '-o', 'placement=' + str(placement), '--placer', 'static', '--router', 'router2',
            '--freq', '50', '--seed', '3588', '--Werror', '--verbose', '--write', routed], timeout=native_timeout)
        for marker in ('Running post-placement legalisation...', 'Routing complete.', 'Program finished normally.'):
            assert marker in log
        features, repeated = parse_native_features(fasm.read_text())
        report['native_FASM_repeated_idempotent_STEPDOWN_lines'] = repeated
        placed = json.loads(placement.read_text())
        native = next(iter(json.loads(routed.read_text())['modules'].values()))
        counts = Counter(c['type'] for c in native['cells'].values())
        assert counts['DSP48E1_DSP48E1'] == 4 and counts['RAMB36E1_RAMB36E1'] == 6
        assert set(native['cells']) == set(placed) and len({p['nextpnr_bel'] for p in placed.values()}) == len(placed)
        checks = {name: compare_bram(features, placed[name], selected[source]) for name, source in origins.items()
                  if selected[source]['type'] == 'RAMB36E1'}
        dsp_checks = {name: compare_dsp(features, placed[name], selected[source], native['cells'][name])
                      for name, source in origins.items() if selected[source]['type'] == 'DSP48E1'}
        report.update(native_control_cell_counts=dict(counts), BRAM_feature_comparison=checks,
            DSP_feature_comparison=dsp_checks, native_FASM_features=len(features), DSP_feature_comparison_pending=False,
            USE_MULT_physical_default_verified=False)
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='PASS_SMALL_NATIVE_DSP_BRAM_SOURCE_DEFINED_FEATURE_CONTROL_WITH_EXPLICIT_GAPS_NOT_FULL_BOARD_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.iterdir() if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
